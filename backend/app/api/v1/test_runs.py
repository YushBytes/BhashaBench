"""HTTP surface for the end-to-end voice testing pipeline.

Thin, as every route module here is: build the engine from the request's
dependencies, call one method, shape the response. No `select()`, no business
rules, and no `HTTPException` - the handlers in `app/main.py` remain the single
place a domain failure becomes a status code.

**There is no authentication**, because Phases 1-6 ship none and authentication
lands in Phase 15. Do not expose this service publicly before then: these
endpoints write files to disk and, with a provider configured, spend money.

**Artefacts are served, carefully.** An earlier revision of this module listed
artefacts and refused to stream them, on the grounds that who may hear a
recorded conversation is an authorisation decision and there is no identity to
make it against. The reasoning still holds; what changed is that the inspector
this API exists to feed cannot work without playback, and refusing the route
did not create an authorisation model - it only moved the recording out of
reach of the one operator entitled to it.

So `GET /{run_id}/artifacts/{turn_index}/audio` streams a stored file under
three constraints, and all three are load-bearing:

- **No client string reaches the filesystem.** The artefact is addressed by
  run, turn index and variant; the stored reference is looked up in the run's
  own record, and `AudioArtefactStore` refuses anything resolving outside its
  root besides.
- **The route is off where it would be reachable.** Staging and production
  refuse unless `PIPELINE_SERVE_ARTEFACTS` is set, because this payload is a
  recording rather than a status field.
- **It claims no authorisation.** A run id is an identifier, not a credential,
  and this route is exactly as open as every other one here. Real access
  control arrives with authentication in Phase 15.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, Path, Query, UploadFile, status
from fastapi.responses import Response

from app.api.deps import DbSession, PaginationParams, SettingsDep
from app.caller.artefacts import AudioArtefactStore
from app.caller.errors import CallerError
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.registry import build_provider as build_caller_provider
from app.caller.schemas import Speaker
from app.caller.service import CallerService
from app.core.config import AppEnv
from app.models.test_run import RunStatus, TestRun
from app.pipeline.bots.registry import (
    SCRIPTED_ADAPTER,
    available_adapters,
    build_adapter,
    describe_adapters,
    fixture_replies_from_path,
)
from app.pipeline.concurrency import get_run_slots
from app.pipeline.degradation import NoiseProfile
from app.pipeline.engine import (
    MAX_BOT_AUDIO_BYTES,
    ArtefactRecord,
    RunConfig,
    RunEngine,
    RunReport,
)
from app.pipeline.errors import ArtefactAccessDisabledError, PipelineConfigurationError
from app.pipeline.modes import (
    IMPLEMENTED_MODES,
    ExecutionMode,
    PipelineStatus,
    RunOutcome,
)
from app.repositories import caller_conversations as caller_repo
from app.repositories import pipeline_runs as pipeline_repo
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
    RunSummary,
    RunTurnResponse,
    RunTurnsResponse,
    StageEventResponse,
)
from app.schemas.suite import Page
from app.services.errors import NotFoundError
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
        # A scripted run started through the API used to have no replies at
        # all, so it failed on turn 0 and `audio_fixture_test` was unusable
        # outside the tests, which inject their own adapter. An operator
        # supplies the fixture through `PIPELINE_FIXTURE_AUDIO_PATH`; unset,
        # this resolves to `None` and the previous behaviour is unchanged.
        #
        # Only the scripted adapter is offered replies: the manual adapter
        # refuses them, correctly, because its audio arrives later.
        resolved_adapter = (adapter_name or settings.pipeline_bot_adapter or "").strip().casefold()
        replies: tuple[bytes, ...] | None = None
        if resolved_adapter == SCRIPTED_ADAPTER and settings.pipeline_fixture_audio_path:
            replies = fixture_replies_from_path(
                settings.pipeline_fixture_audio_path,
                count=settings.caller_max_turns,
            )
        adapter = build_adapter(resolved_adapter or settings.pipeline_bot_adapter, replies=replies)
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


def _recorded_adapter(session: DbSession, run_id: uuid.UUID) -> str | None:
    """The bot adapter this run recorded when it was created, if any.

    `None` for an unknown run: the route then raises its usual 404 from the
    engine, so this lookup never invents a status of its own.
    """
    run = pipeline_repo.get_run(session, run_id)
    if run is None:
        return None
    name = pipeline_repo.pipeline_metadata_of(run).get("bot_adapter")
    return str(name) if name else None


def get_engine(
    run_id: uuid.UUID, factory: EngineFactoryDep, session: DbSession
) -> Iterator[RunEngine]:
    """Provide an engine built with the adapter the run recorded at creation.

    For the routes that exchange audio with the bot (`/start`, `/bot-audio`).
    This used to build the *settings default* for every run, so a run created
    with `bot_adapter: "manual"` was executed by the scripted adapter and
    failed with its error - the API accepted, stored and reported a choice it
    then ignored. A recorded name that is no longer registered is refused
    with a message naming it, never silently swapped for the default.
    """
    recorded = _recorded_adapter(session, run_id)
    built = factory(recorded)
    # Only construction is wrapped. Exceptions from the route body are thrown
    # back into this generator at the `yield`, and an unrelated configuration
    # error there ("not waiting for audio") must not be relabelled as an
    # adapter failure.
    try:
        engine = next(built)
    except PipelineConfigurationError as exc:
        if recorded is None:
            raise
        raise PipelineConfigurationError(
            f"run {run_id} recorded the bot adapter '{recorded}', which cannot be built: {exc}"
        ) from exc
    try:
        yield engine
    finally:
        built.close()


def get_reading_engine(
    run_id: uuid.UUID, factory: EngineFactoryDep, session: DbSession
) -> Iterator[RunEngine]:
    """An engine for routes that never call the bot adapter.

    Reads and `/cancel` use the run's recorded adapter when it is still
    registered and the default otherwise: the adapter is never invoked on these
    paths, and a run whose adapter has since been removed must stay readable
    and cancellable rather than locking its own evidence away.
    """
    recorded = _recorded_adapter(session, run_id)
    usable = recorded if recorded in available_adapters() else None
    yield from factory(usable)


EngineDep = Annotated[RunEngine, Depends(get_engine)]
ReadingEngineDep = Annotated[RunEngine, Depends(get_reading_engine)]

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


_RANGE_PREFIX = "bytes="


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single byte range, or return None to send the whole file.

    Deliberately narrow: one range, `bytes=` only. Multipart ranges exist in
    the spec and no audio element asks for them, so supporting them would be
    untested code on a hot path. Anything unparseable is treated as "no range"
    rather than an error, which is what the RFC asks of a server that cannot
    honour a range unit.

    Returns:
        An inclusive `(start, end)` pair, or None for the whole file.

    Raises:
        ValueError: the range parsed but lies outside the file, which is a
            416 rather than a silent full-body response.
    """
    if not header or not header.startswith(_RANGE_PREFIX) or size <= 0:
        return None

    spec = header[len(_RANGE_PREFIX) :].strip()
    if "," in spec:
        return None

    first, _, last = spec.partition("-")
    try:
        if not first:
            # A suffix range: the final N bytes.
            length = int(last)
            if length <= 0:
                return None
            return max(0, size - length), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None

    if start > end or start >= size:
        raise ValueError("range outside the artefact")
    return start, min(end, size - 1)


def _audio_response(payload: bytes, content_type: str, range_header: str | None) -> Response:
    """Return the audio whole, or the one range the client asked for."""
    size = len(payload)
    common = {
        "Accept-Ranges": "bytes",
        # A stored artefact never changes: the reference is derived from the
        # conversation, turn and variant, and the engine writes it once.
        "Cache-Control": "private, max-age=3600",
    }

    try:
        window = _parse_range(range_header, size)
    except ValueError:
        return Response(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            headers={**common, "Content-Range": f"bytes */{size}"},
        )

    if window is None:
        return Response(content=payload, media_type=content_type, headers=common)

    start, end = window
    return Response(
        content=payload[start : end + 1],
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=content_type,
        headers={**common, "Content-Range": f"bytes {start}-{end}/{size}"},
    )


def _artefact(record: ArtefactRecord) -> ArtefactResponse:
    return ArtefactResponse(**record.as_dict())


def _summary(run: TestRun, turn_counts: dict[str, int]) -> RunSummary:
    """Build a listing row from the run and its stored pipeline metadata.

    Reads only what was persisted. Where metadata is absent the field stays
    null rather than acquiring a default that would read as a measurement -
    a run with no recorded mode is not an `offline_simulation`, it is a run
    whose mode we did not store.
    """
    meta = pipeline_repo.pipeline_metadata_of(run)

    duration: float | None = None
    if run.started_at is not None and run.finished_at is not None:
        duration = (run.finished_at - run.started_at).total_seconds()

    outcome = meta.get("outcome")
    return RunSummary(
        run_id=run.id,
        suite_id=run.suite_id,
        scenario_name=str(meta.get("scenario_name") or ""),
        language=str(meta.get("language") or ""),
        mode=ExecutionMode(meta.get("mode", ExecutionMode.OFFLINE_SIMULATION.value)),
        status=PipelineStatus(meta.get("status", PipelineStatus.CREATED.value)),
        outcome=RunOutcome(outcome) if outcome else None,
        noise_profile=meta.get("noise_profile"),
        bot_adapter=meta.get("bot_adapter"),
        bot_audio_externally_received=bool(meta.get("bot_audio_externally_received", False)),
        uses_language_model=bool(meta.get("uses_language_model", False)),
        caller_turns=turn_counts.get(Speaker.CALLER.value, 0),
        bot_turns=turn_counts.get(Speaker.BOT.value, 0),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=duration,
        error=run.error_message,
    )


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


@router.get(
    "",
    response_model=Page[RunSummary],
    summary="List test runs",
    description=(
        "Newest first. Every field is read from the run row or the pipeline "
        "metadata it stored; nothing is derived to fill a column.\n\n"
        "**Only runs the pipeline created are listed.** A `TestRun` is also "
        "the parent of a Phase 6 caller conversation, and those record no "
        "pipeline metadata - listing them would produce rows whose detail "
        "view is empty. They remain addressable through the caller API.\n\n"
        "`duration_seconds` is null until a run has both a start and a finish: "
        "an elapsed-so-far figure in a duration column would be read as one."
    ),
)
def list_runs(
    session: DbSession,
    page: PaginationParams,
    suite_id: Annotated[uuid.UUID | None, Query(description="Only runs in this suite.")] = None,
    status_filter: Annotated[
        RunStatus | None,
        Query(alias="status", description="Persisted run status."),
    ] = None,
    mode: Annotated[ExecutionMode | None, Query(description="Execution mode.")] = None,
    language: Annotated[
        str | None, Query(max_length=35, description="BhashaBench language tag.")
    ] = None,
    outcome: Annotated[RunOutcome | None, Query(description="Recorded outcome.")] = None,
    scenario: Annotated[
        str | None,
        Query(max_length=200, description="Case-insensitive match on the scenario name."),
    ] = None,
) -> Page[RunSummary]:
    """A filtered page of runs, with the totals a pager needs."""
    filters = {
        "suite_id": suite_id,
        "status": status_filter,
        "mode": None if mode is None else mode.value,
        "language": language,
        "outcome": None if outcome is None else outcome.value,
        "scenario_contains": scenario,
    }
    runs = pipeline_repo.search_runs(session, limit=page.limit, offset=page.offset, **filters)
    counts = pipeline_repo.turn_counts_for_runs(session, [run.id for run in runs])
    return Page[RunSummary](
        items=[_summary(run, counts.get(run.id, {})) for run in runs],
        total=pipeline_repo.count_runs(session, **filters),
        limit=page.limit,
        offset=page.offset,
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
def cancel_run(run_id: uuid.UUID, engine: ReadingEngineDep, session: DbSession) -> RunResponse:
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
def read_run(run_id: uuid.UUID, engine: ReadingEngineDep) -> RunResponse:
    """A run's current state and, once finished, its outcome."""
    return _run(engine.report(run_id))


@router.get(
    "/{run_id}/turns",
    response_model=RunTurnsResponse,
    summary="Read a run's conversation",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}},
)
def read_turns(run_id: uuid.UUID, engine: ReadingEngineDep, session: DbSession) -> RunTurnsResponse:
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
        "References and measured metadata. The bytes themselves come from "
        "`GET /{run_id}/artifacts/{turn_index}/audio`, which addresses an "
        "artefact by turn and variant rather than by the reference printed "
        "here.\n\n"
        "A degraded artefact names the original it came from, so the pair can "
        "be compared after the fact."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}},
)
def read_artefacts(run_id: uuid.UUID, engine: ReadingEngineDep) -> RunArtefactsResponse:
    """Every audio artefact the run produced."""
    report = engine.report(run_id)
    return RunArtefactsResponse(
        run_id=run_id,
        artefacts=[_artefact(record) for record in report.artefacts],
        total_audio_seconds=report.total_audio_seconds,
    )


@router.get(
    "/{run_id}/artifacts/{turn_index}/audio",
    summary="Stream one stored audio artefact",
    description=(
        "Returns the **binary audio** of a single artefact, so a conversation "
        "can be listened to rather than only read about.\n\n"
        "**The reference never comes from the client.** The artefact is "
        "addressed by run, turn index and variant; the server looks the "
        "stored reference up in the run's own record and resolves it under "
        "the storage root. There is no request field a path could travel in, "
        "and the store refuses anything resolving outside its root regardless."
        "\n\n"
        "**Access model: there is none beyond knowing the run id.** This "
        "application has no authentication, so this route is exactly as open "
        "as every other one, and a run id is an identifier rather than a "
        "credential. Because the payload here is a recording of a "
        "conversation, the route is switched off in staging and production "
        "unless `PIPELINE_SERVE_ARTEFACTS` is explicitly set; development "
        "serves it, where the operator is the only listener.\n\n"
        "Supports a single `Range` header so a player can seek."
    ),
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": "The stored audio.",
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        },
        status.HTTP_206_PARTIAL_CONTENT: {"description": "The requested byte range."},
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "This environment does not serve stored audio.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No such run, or no artefact for that turn and variant.",
        },
        status.HTTP_416_RANGE_NOT_SATISFIABLE: {
            "description": "The requested range lies outside the file."
        },
    },
)
def read_artefact_audio(
    run_id: uuid.UUID,
    turn_index: Annotated[int, Path(ge=0, description="Turn the audio belongs to.")],
    engine: ReadingEngineDep,
    settings: SettingsDep,
    variant: Annotated[
        Literal["original", "degraded"] | None,
        Query(
            description=(
                "Which version of a degraded turn's audio. Omit for a turn stored without variants."
            )
        ),
    ] = None,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    """Stream one artefact's bytes, resolved from the run's own record."""
    if settings.app_env in (AppEnv.STAGING, AppEnv.PRODUCTION) and not (
        settings.pipeline_serve_artefacts
    ):
        raise ArtefactAccessDisabledError(
            "this environment does not stream stored conversation audio; "
            "the application has no authentication, so the route is off "
            "unless PIPELINE_SERVE_ARTEFACTS is set",
            run_id=str(run_id),
            stage="artefact_access",
        )

    report = engine.report(run_id)
    record = next(
        (
            candidate
            for candidate in report.artefacts
            if candidate.turn_index == turn_index and candidate.variant == variant
        ),
        None,
    )
    if record is None:
        named = "no variant" if variant is None else f"the '{variant}' variant"
        raise NotFoundError(f"stored audio for turn {turn_index} with {named} of run", run_id)

    try:
        payload = engine.artefact_store.read(record.reference)
    except CallerError as exc:
        # The run recorded an artefact the store cannot produce: the file was
        # removed, or the configured root moved. 404 rather than 500 - the
        # server is fine, the recording is not there.
        raise NotFoundError(f"a readable recording for turn {turn_index} of run", run_id) from exc

    return _audio_response(payload, record.content_type, range_header)


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
def read_report(run_id: uuid.UUID, engine: ReadingEngineDep) -> RunReportResponse:
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


__all__ = ["get_engine", "get_engine_factory", "get_reading_engine", "router"]
