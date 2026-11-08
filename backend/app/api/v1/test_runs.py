"""HTTP surface for the end-to-end voice testing pipeline.

Thin, as every route module here is: build the engine from the request's
dependencies, call one method, shape the response. No `select()`, no business
rules, and no `HTTPException` - the handlers in `app/main.py` remain the single
place a domain failure becomes a status code.

**There is no authentication**, because Phases 1-6 ship none and authentication
lands in Phase 15. Do not expose this service publicly before then: these
endpoints write files to disk and, with a provider configured, spend money.

**Artefacts are listed, not served.** A route that streamed a stored file by
reference would be the obvious convenience and the wrong thing to add here: it
is an authorisation decision - who may hear a recording of a conversation -
and there is no identity to make it against yet. So the API reports what was
recorded and where it sits under the storage root, and reading it is an
operator's job until Phase 15.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import DbSession, SettingsDep
from app.caller.artefacts import AudioArtefactStore
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.registry import build_provider as build_caller_provider
from app.caller.service import CallerService
from app.pipeline.bots.registry import build_adapter, describe_adapters
from app.pipeline.concurrency import get_run_slots
from app.pipeline.degradation import NoiseProfile
from app.pipeline.engine import (
    MAX_BOT_AUDIO_BYTES,
    ArtefactRecord,
    RunConfig,
    RunEngine,
    RunReport,
)
from app.pipeline.modes import IMPLEMENTED_MODES
from app.repositories import caller_conversations as caller_repo
from app.schemas.common import ErrorResponse
from app.schemas.pipeline import (
    ArtefactResponse,
    BotAdapterListResponse,
    BotAdapterResponse,
    BotAudioResponse,
    CreateRunRequest,
    RunArtefactsResponse,
    RunReportResponse,
    RunResponse,
    RunTurnResponse,
    RunTurnsResponse,
    StageEventResponse,
)
from app.services.transcription_service import TranscriptionService
from app.speech.registry import build_provider as build_speech_provider
from app.speech.service import SpeechService
from app.transcription.errors import AudioTooLargeError
from app.transcription.registry import build_provider as build_transcription_provider

router = APIRouter(prefix="/test-runs", tags=["test-runs"])


def get_engine_factory(
    settings: SettingsDep, session: DbSession
) -> Callable[[str | None], Iterator[RunEngine]]:
    """Return a factory that builds a run engine and tears it down.

    A factory taking the adapter name, because which bot adapter a run uses is
    chosen per request while everything else comes from settings. A generator,
    because the speech and transcription services own HTTP clients that have to
    be closed - the leak Phase 4 shipped once.
    """

    def build(adapter_name: str | None) -> Iterator[RunEngine]:
        speech_provider = build_speech_provider(settings)
        transcription_provider = build_transcription_provider(settings)
        speech = SpeechService(speech_provider, settings=settings)
        transcription = TranscriptionService(transcription_provider, settings=settings)
        # Synthesis is forced on for the pipeline regardless of
        # `CALLER_SYNTHESISE_AUDIO`: a run that moves audio has nothing to send
        # without it, and the setting exists to stop Phase 6's *text*
        # conversations billing a provider per turn.
        caller = CallerService(
            build_caller_provider(settings),
            settings=settings.model_copy(update={"caller_synthesise_audio": True}),
            speech=speech,
        )
        artefacts = AudioArtefactStore(settings.caller_audio_root)
        adapter = build_adapter(adapter_name or settings.pipeline_bot_adapter)
        orchestrator = ConversationOrchestrator(
            session=session,
            caller=caller,
            settings=settings,
            transcription=transcription,
            artefacts=artefacts,
        )
        try:
            yield RunEngine(
                session=session,
                orchestrator=orchestrator,
                settings=settings,
                bot_adapter=adapter,
                artefacts=artefacts,
                stt_provider=transcription_provider.capabilities.name,
                tts_provider=speech_provider.capabilities.name,
                # The process-wide limiter, not a per-request one. A limiter
                # built per request would count to one and enforce nothing,
                # which is exactly how PIPELINE_MAX_CONCURRENT_RUNS came to be
                # a documented number with no consumer.
                slots=get_run_slots(settings),
            )
        finally:
            # Synchronous teardown cannot await an async close, and these
            # providers hold lazily-created clients that are never opened
            # unless a call is made. Dropping the references is this factory's
            # job; the speech and transcription routes close their own.
            del caller, speech, transcription, adapter

    return build


EngineFactoryDep = Annotated[
    Callable[[str | None], Iterator[RunEngine]], Depends(get_engine_factory)
]


def get_engine(factory: EngineFactoryDep) -> Iterator[RunEngine]:
    """Provide an engine using the configured default adapter."""
    yield from factory(None)


EngineDep = Annotated[RunEngine, Depends(get_engine)]

_CAPACITY_ERROR: dict[int | str, dict[str, object]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Every concurrent-run slot is in use. The run was not "
        "started and keeps its current state, so retry it when a slot frees up.",
    },
}

_COMMON_ERRORS: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."},
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "The run has already finished.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Invalid request, or a configuration the engine cannot honour.",
    },
}


def _artefact(record: ArtefactRecord) -> ArtefactResponse:
    return ArtefactResponse(**record.as_dict())


def _run(report: RunReport) -> RunResponse:
    return RunResponse(
        run_id=report.run_id,
        conversation_id=report.conversation_id,
        scenario_name=report.scenario_name,
        language=report.language,
        mode=report.mode,
        status=report.status,
        outcome=report.outcome,
        caller_provider=report.caller_provider,
        uses_language_model=report.uses_language_model,
        stt_provider=report.stt_provider,
        tts_provider=report.tts_provider,
        bot_adapter=report.bot_adapter,
        bot_audio_externally_received=report.bot_audio_externally_received,
        noise_profile=report.noise_profile,
        scenario_noise_profile=report.scenario_noise_profile,
        degradation_seed=report.degradation_seed,
        caller_turns=report.caller_turns,
        bot_turns=report.bot_turns,
        bot_transcripts_succeeded=report.bot_transcripts_succeeded,
        bot_transcripts_failed=report.bot_transcripts_failed,
        turn_budget=report.turn_budget,
        caller_state=report.caller_state,
        termination_reason=report.termination_reason,
        goal_achieved=report.goal_achieved,
        total_audio_seconds=report.total_audio_seconds,
        awaiting_bot_audio_for_turn=report.awaiting_bot_audio_for_turn,
        started_at=report.started_at,
        finished_at=report.finished_at,
        error=report.error,
    )


@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a test run",
    description=(
        "Opens a run and its conversation without executing anything. The run "
        "is `created`; POST to `/start` to execute it.\n\n"
        "`mode` is the honesty control: `offline_simulation` moves no audio, "
        "`audio_fixture_test` runs every stage with the bot's replies read from "
        "fixtures, and `external_bot_test` waits for an operator to supply the "
        "bot's audio. `telephony_test` is refused - no telephony exists."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No such scenario.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "An unimplemented mode, an unknown adapter, or a "
            "scenario in a language the caller has no phrase table for.",
        },
    },
)
def create_run(
    payload: CreateRunRequest,
    factory: EngineFactoryDep,
    session: DbSession,
) -> RunResponse:
    """Open a run for one scenario."""
    engine_iter = factory(payload.bot_adapter)
    engine = next(engine_iter)
    try:
        run = engine.create(
            suite_id=payload.suite_id,
            scenario_id=payload.scenario_id,
            config=RunConfig(
                mode=payload.mode,
                noise_profile=payload.noise_profile or NoiseProfile.CLEAN,
                seed=payload.seed,
                bot_adapter=payload.bot_adapter or "scripted",
                max_turns=payload.max_turns,
                degrade_caller_audio=payload.degrade_caller_audio,
            ),
        )
        session.commit()
        return _run(engine.report(run.id))
    finally:
        # Drain the generator so its `finally` runs, as a `yield` dependency's
        # teardown would.
        for _ in engine_iter:  # pragma: no cover - single-yield generator
            pass


@router.post(
    "/{run_id}/start",
    response_model=RunResponse,
    summary="Execute a run",
    description=(
        "Runs turns until the run reaches a terminal state, or until it needs "
        "audio that has to come from outside. A run left `running` with "
        "`awaiting_bot_audio_for_turn` set is healthy and waiting, not failed: "
        "submit the bot's reply to `/bot-audio` to continue it.\n\n"
        "At most `PIPELINE_MAX_CONCURRENT_RUNS` runs execute at once. Beyond "
        "that this answers **503** immediately rather than queueing: a request "
        "waiting behind an unbounded line has no bound on its own latency, and "
        "the client cannot tell a slow run from a stuck one. The run is "
        "untouched - not started, not failed - so retrying is safe."
    ),
    responses=_COMMON_ERRORS | _CAPACITY_ERROR,
)
async def start_run(run_id: uuid.UUID, engine: EngineDep, session: DbSession) -> RunResponse:
    """Execute a run to its terminal state, or to its next wait."""
    report = await engine.run_to_completion(run_id)
    session.commit()
    return _run(report)


@router.post(
    "/{run_id}/bot-audio",
    response_model=BotAudioResponse,
    summary="Supply the bot's reply as audio",
    description=(
        "The external-bot path. The run stored the caller's audio and paused; "
        "play that artefact to the bot under test, record the answer and post "
        "it here. The audio is validated, transcribed through the configured "
        "provider, and the run continues.\n\n"
        "Audio supplied here is recorded as externally obtained, because "
        "posting it asserts that it came from the bot under test. The pipeline "
        "cannot verify that claim and does not pretend to."
    ),
    responses=_COMMON_ERRORS
    | {
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "The audio exceeds the upload limit.",
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "model": ErrorResponse,
            "description": "The audio is in a container that cannot be decoded.",
        },
    },
)
async def submit_bot_audio(
    run_id: uuid.UUID,
    engine: EngineDep,
    session: DbSession,
    audio: Annotated[UploadFile, File(description="The bot's reply as audio.")],
) -> BotAudioResponse:
    """Accept the bot's reply and carry the run on."""
    # Capped read: `UploadFile` spools to a temporary file, so an unbounded
    # read lets one request write arbitrarily much to disk before any size
    # check could run.
    payload = await audio.read(MAX_BOT_AUDIO_BYTES + 1)
    if len(payload) > MAX_BOT_AUDIO_BYTES:
        raise AudioTooLargeError(f"the bot audio exceeds the {MAX_BOT_AUDIO_BYTES} byte limit")

    before = engine.report(run_id)
    awaiting = before.awaiting_bot_audio_for_turn
    report = await engine.supply_bot_audio(
        run_id, audio=payload, content_type=audio.content_type or "audio/wav"
    )
    session.commit()
    return BotAudioResponse(
        run=_run(report),
        accepted_bytes=len(payload),
        turn_index=awaiting if awaiting is not None else 0,
    )


@router.post(
    "/{run_id}/cancel",
    response_model=RunResponse,
    summary="Cancel a run",
    description=(
        "Records the outcome as `cancelled`, never `failed`: an operator "
        "stopping a run is not a finding about the bot, and scoring it as one "
        "would punish the bot for the operator's decision."
    ),
    responses=_COMMON_ERRORS,
)
def cancel_run(run_id: uuid.UUID, engine: EngineDep, session: DbSession) -> RunResponse:
    """Stop a run from outside."""
    engine.cancel(run_id)
    session.commit()
    return _run(engine.report(run_id))


@router.get(
    "/{run_id}",
    response_model=RunResponse,
    summary="Read a run's state",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}},
)
def read_run(run_id: uuid.UUID, engine: EngineDep) -> RunResponse:
    """A run's current state and, once finished, its outcome."""
    return _run(engine.report(run_id))


@router.get(
    "/{run_id}/turns",
    response_model=RunTurnsResponse,
    summary="Read a run's conversation",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}},
)
def read_turns(run_id: uuid.UUID, engine: EngineDep, session: DbSession) -> RunTurnsResponse:
    """Every utterance of the run's conversation, in order."""
    report = engine.report(run_id)
    turns: list[RunTurnResponse] = []
    if report.conversation_id is not None:
        for turn in caller_repo.list_turns(session, report.conversation_id):
            metadata = turn.turn_metadata or {}
            audio = metadata.get("audio") or {}
            turns.append(
                RunTurnResponse(
                    index=turn.turn_index,
                    speaker=turn.speaker.value,
                    text=turn.content,
                    intent=metadata.get("intent"),
                    state_before=metadata.get("state_before"),
                    state_after=metadata.get("state_after"),
                    rule_ids=list(metadata.get("rule_ids", [])),
                    audio_reference=audio.get("reference"),
                    transcription_error=metadata.get("transcription_error"),
                    synthesis_error=metadata.get("synthesis_error"),
                )
            )
    return RunTurnsResponse(run_id=run_id, turns=turns)


@router.get(
    "/{run_id}/artifacts",
    response_model=RunArtefactsResponse,
    summary="List a run's audio artefacts",
    description=(
        "References and measured metadata, not the audio itself. Serving a "
        "recording is an authorisation decision - who may hear a conversation "
        "- and there is no identity to make it against until Phase 15.\n\n"
        "A degraded artefact names the original it came from, so the pair can "
        "be compared after the fact."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}},
)
def read_artefacts(run_id: uuid.UUID, engine: EngineDep) -> RunArtefactsResponse:
    """Every audio artefact the run produced."""
    report = engine.report(run_id)
    return RunArtefactsResponse(
        run_id=run_id,
        artefacts=[_artefact(record) for record in report.artefacts],
        total_audio_seconds=report.total_audio_seconds,
    )


@router.get(
    "/{run_id}/report",
    response_model=RunReportResponse,
    summary="Read a run's full evidence",
    description=(
        "State, artefacts, caller state transitions and every stage that ran, "
        "with its measured duration.\n\n"
        "**Measurements, not judgements.** There is no accuracy score, no word "
        "error rate and no semantic verdict here: none is possible without a "
        "reviewed reference transcript, and evaluation is a later phase."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}},
)
def read_report(run_id: uuid.UUID, engine: EngineDep) -> RunReportResponse:
    """The run's complete evidence."""
    report = engine.report(run_id)
    return RunReportResponse(
        run=_run(report),
        state_transitions=[dict(transition) for transition in report.state_transitions],
        artefacts=[_artefact(record) for record in report.artefacts],
        events=[
            StageEventResponse(
                turn_index=event.turn_index,
                stage=event.stage,
                status=event.status,
                duration_ms=event.duration_ms,
                detail=event.detail,
            )
            for event in report.events
        ],
    )


@router.get(
    "/bot-adapters/available",
    response_model=BotAdapterListResponse,
    summary="List the bot adapters",
    description=(
        "Every registered adapter with its capabilities. "
        "`contacts_external_system` is `false` for all of them: nothing in "
        "this phase sends audio anywhere by itself, which is why the default "
        "configuration is safe."
    ),
)
def list_adapters(settings: SettingsDep) -> BotAdapterListResponse:
    """What bot adapters exist, and which modes a run may use."""
    selected = settings.pipeline_bot_adapter
    return BotAdapterListResponse(
        selected=selected,
        adapters=[
            BotAdapterResponse(
                name=capabilities.name,
                display_name=capabilities.display_name,
                selected=capabilities.name == selected,
                contacts_external_system=capabilities.contacts_external_system,
                supports_sessions=capabilities.supports_sessions,
                requires_credentials=capabilities.requires_credentials,
                accepts_containers=sorted(capabilities.accepts_containers),
                notes=list(capabilities.notes),
            )
            for capabilities in describe_adapters()
        ],
        execution_modes=sorted(mode.value for mode in IMPLEMENTED_MODES),
    )


__all__ = ["get_engine", "get_engine_factory", "router"]
