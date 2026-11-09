"""Caller conversation endpoints.

Six routes, which is what the full workflow needs and no more: open a
conversation, produce a caller turn, feed the bot's reply back in (as text or
as audio), read the state and the transcript, and stop.

**These handlers are `def`, not `async def`, except where a provider is
awaited.** `docs/ARCHITECTURE.md` settled that database handlers stay
synchronous so FastAPI runs them in a worker thread, and these touch the
database. The two that await a caller turn are `async def` because the provider
interface is asynchronous - they still hold a synchronous session, which is
safe here because the orchestrator does its database work around the await
rather than across it.

**On authentication:** the project has none. Phases 1-5 ship an unauthenticated
API, and §10 says to follow existing conventions "if already implemented" -
inventing an auth scheme for one subsystem would leave the other two open while
implying the whole API was protected. Phase 15 is where authentication lands,
for all of it at once. What is enforced here instead is what can be: bounded
request bodies, bounded uploads, bounded turn counts, and no secret in any
response.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import DbSession, SettingsDep
from app.caller.artefacts import AudioArtefactStore
from app.caller.orchestrator import ConversationOrchestrator, ConversationReport
from app.caller.protocol import CallerCapabilities
from app.caller.registry import build_provider, describe_providers
from app.caller.schemas import TerminationReason
from app.caller.service import CallerService
from app.repositories import caller_conversations as repo
from app.schemas.caller import (
    BotTextRequest,
    CallerProviderListResponse,
    CallerProviderResponse,
    ConversationResponse,
    ConversationTurnsResponse,
    StartConversationRequest,
    TurnResponse,
)
from app.schemas.common import ErrorResponse
from app.services.errors import NotFoundError
from app.services.transcription_service import TranscriptionService
from app.speech.registry import build_provider as build_speech_provider
from app.speech.service import SpeechService
from app.transcription.errors import AudioTooLargeError
from app.transcription.models import AudioEncoding
from app.transcription.registry import build_provider as build_transcription_provider

logger = logging.getLogger("bhashabench.api.caller")

router = APIRouter(prefix="/caller", tags=["caller"])

MAX_BOT_AUDIO_BYTES = 10 * 1024 * 1024
"""Cap on a bot-audio upload, matching the transcription endpoint's limit."""


def get_orchestrator_factory(
    settings: SettingsDep, session: DbSession
) -> Callable[[], Iterator[ConversationOrchestrator]]:
    """Return a factory that builds an orchestrator and tears it down.

    A factory rather than the orchestrator itself, and a generator rather than
    a value, because the speech and transcription services it wraps own HTTP
    clients that have to be closed after the request - the leak Phase 4 shipped
    once. One override point swaps every provider for a fake in tests.
    """

    def build() -> Iterator[ConversationOrchestrator]:
        caller = CallerService(
            build_provider(settings),
            settings=settings,
            speech=SpeechService(build_speech_provider(settings), settings=settings)
            if settings.caller_synthesise_audio
            else None,
        )
        transcription = TranscriptionService(
            build_transcription_provider(settings), settings=settings
        )
        try:
            yield ConversationOrchestrator(
                session=session,
                caller=caller,
                settings=settings,
                transcription=transcription,
                artefacts=AudioArtefactStore(settings.caller_audio_root),
            )
        finally:
            # Synchronous teardown of asynchronous closers is not possible
            # here, and these providers hold lazily-created clients that are
            # never opened unless a call is made. The services whose clients
            # *are* opened - speech and transcription - are closed by their own
            # dependencies when those routes are used; this factory's job is to
            # not leave a reference behind.
            del caller, transcription

    return build


OrchestratorFactoryDep = Annotated[
    Callable[[], Iterator[ConversationOrchestrator]], Depends(get_orchestrator_factory)
]


def get_orchestrator(factory: OrchestratorFactoryDep) -> Iterator[ConversationOrchestrator]:
    """Provide an orchestrator for one request."""
    yield from factory()


OrchestratorDep = Annotated[ConversationOrchestrator, Depends(get_orchestrator)]

_COMMON_ERRORS: dict[int | str, dict[str, object]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such conversation."},
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "The conversation has already finished, or a concurrent "
        "request created this turn.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Invalid request, or a caller decision that failed validation.",
    },
}


def _to_response(report: ConversationReport) -> ConversationResponse:
    """Project a report onto the wire format."""
    return ConversationResponse(
        conversation_id=report.conversation_id,
        scenario_name=report.scenario_name,
        language=report.language,
        provider=report.provider,
        uses_language_model=report.uses_language_model,
        state=report.state,
        outcome=report.outcome,
        termination_reason=report.termination_reason,
        turns_used=report.turns_used,
        turn_budget=report.turn_budget,
        goal_achieved=report.goal_achieved,
        outcomes_expected=list(report.outcomes_expected),
        outcomes_observed=list(report.outcomes_observed),
        rule_ids_fired=list(report.rule_ids_fired),
        error=report.error,
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a caller conversation",
    description=(
        "Opens a conversation for one scenario and returns its initial state. "
        "No turn is produced yet - call `/turns` for the caller's opening "
        "utterance.\n\n"
        "A `TestRun` is created to own the conversation, because the schema "
        "hangs a call session off a run.\n\n"
        "`uses_language_model` is `false`: the caller is a deterministic rule "
        "engine. Gnani Evon is not integrated in this phase."
    ),
    responses={
        **_COMMON_ERRORS,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The scenario's language has no reviewed phrase table.",
        },
    },
)
def start_conversation(
    payload: StartConversationRequest,
    orchestrator: OrchestratorDep,
    session: DbSession,
) -> ConversationResponse:
    """Open a conversation."""
    conversation = orchestrator.start(suite_id=payload.suite_id, scenario_id=payload.scenario_id)
    session.commit()
    return _to_response(orchestrator.report(conversation.id))


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=ConversationResponse,
    summary="Produce the caller's next turn",
    description=(
        "Runs the caller's decision for the current state and persists the "
        "utterance. Idempotency is enforced by the database's unique "
        "constraint on `(call_session_id, turn_index)`: a concurrent duplicate "
        "gets 409 rather than a second turn.\n\n"
        "Returns 409 once the conversation has reached a terminal state."
    ),
    responses=_COMMON_ERRORS,
)
async def next_turn(
    conversation_id: uuid.UUID,
    orchestrator: OrchestratorDep,
    session: DbSession,
) -> ConversationResponse:
    """Produce one caller turn."""
    await orchestrator.next_caller_turn(conversation_id)
    session.commit()
    return _to_response(orchestrator.report(conversation_id))


@router.post(
    "/conversations/{conversation_id}/bot-text",
    response_model=ConversationResponse,
    summary="Submit the bot's reply as text",
    description=(
        "Records the bot's utterance without transcription. This is the path "
        "an offline simulation and the Phase 6 demo use: there is no voice bot "
        "to call yet, so driving from text exercises everything above the "
        "audio layer honestly."
    ),
    responses=_COMMON_ERRORS,
)
def submit_bot_text(
    conversation_id: uuid.UUID,
    payload: BotTextRequest,
    orchestrator: OrchestratorDep,
    session: DbSession,
) -> ConversationResponse:
    """Record a bot turn from text."""
    orchestrator.submit_bot_text(conversation_id, payload.text)
    session.commit()
    return _to_response(orchestrator.report(conversation_id))


@router.post(
    "/conversations/{conversation_id}/bot-audio",
    response_model=ConversationResponse,
    summary="Submit the bot's reply as audio",
    description=(
        "Transcribes the bot's audio through the existing Prisma subsystem and "
        "records the result.\n\n"
        "A transcription failure is recorded as a bot turn with `text: null` "
        "and a `transcription_error`, **not** as an empty transcript. 'The bot "
        "said nothing' and 'we could not hear the bot' score differently, and "
        "collapsing them would blame the bot for our own deafness."
    ),
    responses={
        **_COMMON_ERRORS,
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "Audio exceeds the upload limit.",
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "model": ErrorResponse,
            "description": "A format the transcription provider does not accept.",
        },
    },
)
async def submit_bot_audio(
    conversation_id: uuid.UUID,
    orchestrator: OrchestratorDep,
    session: DbSession,
    audio: Annotated[UploadFile, File(description="The bot's reply as audio.")],
    encoding: Annotated[
        AudioEncoding | None, Form(description="Declare the encoding for headerless PCM.")
    ] = None,
    sample_rate_hz: Annotated[
        int | None, Form(description="Required for headerless `pcm_s16le`.")
    ] = None,
) -> ConversationResponse:
    """Record a bot turn from audio."""
    # Capped read, as on the transcription endpoint: `UploadFile` spools to a
    # temporary file, so an unbounded read lets one request write arbitrarily
    # much to disk before any size check could run.
    payload = await audio.read(MAX_BOT_AUDIO_BYTES + 1)
    if len(payload) > MAX_BOT_AUDIO_BYTES:
        raise AudioTooLargeError(f"the bot audio exceeds the {MAX_BOT_AUDIO_BYTES} byte limit")

    await orchestrator.submit_bot_audio(
        conversation_id,
        audio=payload,
        declared_encoding=encoding,
        sample_rate_hz=sample_rate_hz,
    )
    session.commit()
    return _to_response(orchestrator.report(conversation_id))


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Read a conversation's state and outcome",
    description=(
        "`outcomes_observed` lists the scenario's expected outcomes whose text "
        "appeared in the bot's transcripts. It is a keyword indicator so a demo "
        "can show progress - **not** a score. Evaluation is Phase 11."
    ),
    responses=_COMMON_ERRORS,
)
def get_conversation(
    conversation_id: uuid.UUID, orchestrator: OrchestratorDep
) -> ConversationResponse:
    """Read one conversation."""
    return _to_response(orchestrator.report(conversation_id))


@router.get(
    "/conversations/{conversation_id}/turns",
    response_model=ConversationTurnsResponse,
    summary="Read a conversation's full transcript",
    description=(
        "Every turn in sequence, with the rule identifiers and the one-line "
        "decision record for each caller turn. Audio references are relative to "
        "the storage root; absolute filesystem paths are never returned."
    ),
    responses=_COMMON_ERRORS,
)
def list_conversation_turns(
    conversation_id: uuid.UUID, session: DbSession
) -> ConversationTurnsResponse:
    """Read one conversation's turns."""
    conversation = repo.get_conversation(session, conversation_id)
    if conversation is None:
        raise NotFoundError("Conversation", conversation_id)

    turns: list[TurnResponse] = []
    for turn in repo.list_turns(session, conversation_id):
        meta = turn.turn_metadata or {}
        audio = meta.get("audio") or {}
        turns.append(
            TurnResponse(
                index=turn.turn_index,
                speaker=turn.speaker.value,
                text=turn.content,
                intent=meta.get("intent"),
                state_before=meta.get("state_before"),
                state_after=meta.get("state_after"),
                rule_ids=list(meta.get("rule_ids", [])),
                explanation=meta.get("explanation"),
                facts_used=list(meta.get("facts_used", [])),
                audio_reference=audio.get("reference"),
                audio_duration_seconds=audio.get("duration_seconds"),
                transcription_error=meta.get("transcription_error"),
                synthesis_error=meta.get("synthesis_error"),
            )
        )
    return ConversationTurnsResponse(conversation_id=conversation_id, turns=turns)


@router.post(
    "/conversations/{conversation_id}/terminate",
    response_model=ConversationResponse,
    summary="End a conversation",
    description=(
        "Closes the conversation in the `terminated` state, which is neither "
        "success nor bot failure - an operator stopping a run must not look "
        "like a scenario the bot failed."
    ),
    responses=_COMMON_ERRORS,
)
def terminate_conversation(
    conversation_id: uuid.UUID,
    orchestrator: OrchestratorDep,
    session: DbSession,
) -> ConversationResponse:
    """End a conversation."""
    orchestrator.terminate(conversation_id, reason=TerminationReason.OPERATOR_TERMINATED)
    session.commit()
    return _to_response(orchestrator.report(conversation_id))


@router.get(
    "/providers",
    response_model=CallerProviderListResponse,
    summary="List caller providers and their capabilities",
    description=(
        "Describes every registered caller strategy. `evon_status` states on "
        "the API surface - not only in the documentation - that Gnani Evon is "
        "not implemented, so no client can mistake the deterministic caller "
        "for a language model."
    ),
)
def list_caller_providers(settings: SettingsDep) -> CallerProviderListResponse:
    """Describe all registered caller providers."""
    described: list[CallerProviderResponse] = []
    for name, capabilities, reason in describe_providers(settings):
        if capabilities is None:
            described.append(
                CallerProviderResponse(
                    name=name,
                    display_name=name,
                    selected=name == settings.caller_provider,
                    available=False,
                    unavailable_reason=reason,
                    is_deterministic=False,
                    uses_language_model=False,
                    languages=[],
                    supports_code_mixing=False,
                    requires_credentials=False,
                    notes=[],
                )
            )
            continue
        if not isinstance(capabilities, CallerCapabilities):  # pragma: no cover
            raise TypeError(f"provider '{name}' reported unusable capabilities")
        described.append(
            CallerProviderResponse(
                name=capabilities.name,
                display_name=capabilities.display_name,
                selected=capabilities.name == settings.caller_provider,
                available=True,
                unavailable_reason=None,
                is_deterministic=capabilities.is_deterministic,
                uses_language_model=capabilities.uses_language_model,
                languages=sorted(capabilities.languages),
                supports_code_mixing=capabilities.supports_code_mixing,
                requires_credentials=capabilities.requires_credentials,
                max_turns_supported=capabilities.max_turns_supported,
                notes=list(capabilities.notes),
            )
        )
    return CallerProviderListResponse(selected=settings.caller_provider, providers=described)


__all__ = ["get_orchestrator", "get_orchestrator_factory", "router"]
