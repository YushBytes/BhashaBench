"""The conversation lifecycle.

Deliberately free of FastAPI, so §9's "must be testable directly" holds: the
multi-turn simulation test drives this class with a session and three fakes,
no HTTP client involved.

It owns four things the service below it does not:

* **The turn budget**, taken as the lower of the scenario's `goal.max_turns`
  and `CALLER_MAX_TURNS`. Two limits rather than one because a scenario author
  should be able to ask for a long negotiation, and an operator should still be
  able to cap the whole deployment.
* **Persistence**, through `app/repositories/caller_conversations.py`. It owns
  the transaction boundary, as services do everywhere else here.
* **Bot audio**, handed to the existing `app/transcription/` service. A
  transcription failure is recorded as a failure, never as an empty success -
  §8's requirement, and the difference between "the bot said nothing" and "we
  could not hear the bot", which score differently.
* **Outcome assessment** against `expected_outcomes`, which the caller never
  sees. That separation is what stops the caller reciting the marking scheme.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.caller.analysis import mentions_value, normalise
from app.caller.artefacts import AudioArtefactStore
from app.caller.errors import (
    ConversationNotActiveError,
    DuplicateTurnError,
    ScenarioNotUsableError,
)
from app.caller.schemas import (
    CallerContext,
    CallerIntent,
    CallerPersona,
    ConversationTurnView,
    Speaker,
    TerminationReason,
)
from app.caller.service import CallerService
from app.caller.state import CallerState, is_terminal, outcome_of
from app.core.config import Settings
from app.models.call_session import CallSession, CallStatus
from app.models.conversation_turn import Speaker as DbSpeaker
from app.repositories import caller_conversations as repo
from app.schemas.scenario_spec import ScenarioSpec
from app.services.errors import NotFoundError
from app.services.transcription_service import TranscriptionService
from app.transcription.errors import (
    AudioTooLargeError,
    InvalidAudioError,
    TranscriptionError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.transcription.models import AudioEncoding
from app.transcription.redaction import redact

logger = logging.getLogger("bhashabench.caller.orchestrator")

# Transcription failures that mean the *request* was wrong, not that the
# speech provider let us down. These are re-raised so the API answers 4xx;
# everything else is recorded as a failed bot turn and the conversation goes
# on, because a provider outage mid-call should not throw away a transcript.
#
# The line between the two is who can fix it: a caller who sent a text file
# or an unsupported container fixes it by sending different bytes, and a
# silent 200 would tell them nothing was wrong.
_REQUEST_DEFECTS = (
    InvalidAudioError,
    UnsupportedFormatError,
    AudioTooLargeError,
    UnsupportedLanguageError,
)


@dataclass(frozen=True, slots=True)
class ConversationReport:
    """The structured result of a conversation."""

    conversation_id: uuid.UUID
    scenario_name: str
    language: str
    provider: str
    uses_language_model: bool
    """Carried into the report on purpose. Any claim built on this run has to
    be able to say whether a model generated the caller's words. In Phase 6 it
    is always False."""
    state: CallerState
    outcome: str
    """`success`, `failure` or `aborted` - see `state.outcome_of`."""
    termination_reason: TerminationReason | None
    turns_used: int
    turn_budget: int
    goal_achieved: bool
    outcomes_expected: tuple[str, ...]
    outcomes_observed: tuple[str, ...]
    """Expected outcomes whose text was found in the bot's transcripts.

    A keyword match, not a judgement. Phase 10 is the evaluation engine; this
    is a cheap indicator so a demo can show progress, and the report says which
    it is rather than implying a score.
    """
    rule_ids_fired: tuple[str, ...]
    error: str | None = None


class ConversationOrchestrator:
    """Runs a caller conversation from start to terminal state."""

    def __init__(
        self,
        *,
        session: Session,
        caller: CallerService,
        settings: Settings,
        transcription: TranscriptionService | None = None,
        artefacts: AudioArtefactStore | None = None,
    ) -> None:
        self._session = session
        self._caller = caller
        self._settings = settings
        self._transcription = transcription
        self._artefacts = artefacts

    # -- Scenario projection ------------------------------------------------

    def _spec_of(self, conversation: CallSession) -> ScenarioSpec:
        """Parse the stored scenario document.

        Validated on the way out of the database as well as on the way in: a
        row could predate a spec change, and a caller driven by a document that
        no longer validates would fail in confusing ways much later.
        """
        return ScenarioSpec.model_validate(conversation.scenario.spec)

    def _persona_of(self, spec: ScenarioSpec) -> CallerPersona:
        """Project the scenario's persona for the provider."""
        mixing = spec.code_mixing
        return CallerPersona(
            identity=spec.persona.identity,
            speaking_style=str(spec.persona.speaking_style),
            traits=tuple(spec.persona.traits),
            language=spec.language,
            secondary_language=(mixing.secondary[0] if mixing and mixing.secondary else None),
            code_mixing_expected=bool(mixing and mixing.expected),
            switch_triggers=tuple(str(t) for t in (mixing.switch_triggers if mixing else ())),
        )

    def _budget(self, spec: ScenarioSpec) -> int:
        """The effective turn budget: the lower of the two limits."""
        return min(spec.goal.max_turns, self._settings.caller_max_turns)

    # -- Lifecycle ----------------------------------------------------------

    def start(self, *, suite_id: uuid.UUID, scenario_id: uuid.UUID) -> CallSession:
        """Open a conversation for one scenario.

        Raises:
            NotFoundError: no such scenario.
            ScenarioNotUsableError: the caller provider cannot speak the
                scenario's language.
        """
        scenario = repo.get_scenario(self._session, scenario_id)
        if scenario is None:
            raise NotFoundError("Scenario", scenario_id)

        spec = ScenarioSpec.model_validate(scenario.spec)
        capabilities = self._caller.capabilities

        if not capabilities.supports_language(spec.language):
            # Refused rather than silently answered in English: a Kannada
            # scenario answered in English would look like a language test that
            # passed, which is exactly the dishonesty to avoid. The phrase
            # tables' English fallback is for composing an utterance, not for
            # pretending to cover a language.
            raise ScenarioNotUsableError(
                f"scenario '{spec.name}' is in {spec.language}, which the "
                f"'{capabilities.name}' caller provider has no reviewed phrase "
                f"table for; it covers {sorted(capabilities.languages)}",
                provider=capabilities.name,
            )

        run = repo.create_run(
            self._session,
            suite_id=suite_id,
            metadata={
                "origin": "caller.phase6",
                "provider": capabilities.name,
                "uses_language_model": capabilities.uses_language_model,
            },
        )
        conversation = repo.create_conversation(
            self._session,
            test_run_id=run.id,
            scenario_id=scenario_id,
            caller_metadata={
                "state": CallerState.INITIAL.value,
                "provider": capabilities.name,
                "uses_language_model": capabilities.uses_language_model,
                "turn_budget": self._budget(spec),
                "goal_achieved": False,
                "termination_reason": None,
                "rule_ids": [],
            },
        )
        logger.info(
            "caller.conversation_started",
            extra={
                "conversation_id": str(conversation.id),
                "scenario": spec.name,
                "language": spec.language,
                "provider": capabilities.name,
                "turn_budget": self._budget(spec),
            },
        )
        return conversation

    def _load_active(self, conversation_id: uuid.UUID) -> CallSession:
        """Fetch a conversation and insist it is still running."""
        conversation = repo.get_conversation(self._session, conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation", conversation_id)

        state = CallerState(
            repo.caller_metadata_of(conversation).get("state", CallerState.INITIAL.value)
        )
        if is_terminal(state):
            raise ConversationNotActiveError(
                f"conversation {conversation_id} has already finished in state "
                f"'{state.value}'; no further turns can be produced",
                conversation_id=str(conversation_id),
            )
        return conversation

    def _history(self, conversation: CallSession) -> tuple[ConversationTurnView, ...]:
        """The conversation so far, as a provider sees it."""
        views: list[ConversationTurnView] = []
        for turn in repo.list_turns(self._session, conversation.id):
            intent_value = (turn.turn_metadata or {}).get("intent")
            views.append(
                ConversationTurnView(
                    index=turn.turn_index,
                    speaker=Speaker(turn.speaker.value),
                    text=turn.content or "",
                    intent=CallerIntent(intent_value) if intent_value else None,
                )
            )
        return tuple(views)

    async def next_caller_turn(self, conversation_id: uuid.UUID) -> CallSession:
        """Produce and persist the caller's next utterance.

        Raises:
            NotFoundError, ConversationNotActiveError, DuplicateTurnError,
            InvalidCallerDecisionError, CallerError.
        """
        conversation = self._load_active(conversation_id)
        spec = self._spec_of(conversation)
        meta = repo.caller_metadata_of(conversation)
        state = CallerState(meta.get("state", CallerState.INITIAL.value))
        budget = int(meta.get("turn_budget", self._budget(spec)))

        history = self._history(conversation)
        turn_index = repo.next_turn_index(self._session, conversation.id)
        caller_turns_used = sum(1 for view in history if view.speaker is Speaker.CALLER)

        last_bot = next(
            (view.text for view in reversed(history) if view.speaker is Speaker.BOT), None
        )

        context = CallerContext(
            scenario_id=str(conversation.scenario_id),
            scenario_name=spec.name,
            objective=spec.goal.objective,
            persona=self._persona_of(spec),
            known_facts=dict(spec.known_facts),
            history=history,
            bot_transcript=last_bot,
            state=state,
            turn_index=turn_index,
            turns_remaining=max(budget - caller_turns_used, 0),
        )

        turn = await self._caller.produce_turn(context)
        decision = turn.decision

        audio_reference: str | None = None
        if turn.audio is not None and self._artefacts is not None:
            stored = self._artefacts.write(
                turn.audio.audio,
                conversation_id=conversation.id,
                turn_index=turn_index,
                speaker=Speaker.CALLER,
                container=turn.audio.container.value,
                content_type=turn.audio.content_type,
            )
            audio_reference = stored.reference

        metadata: dict[str, Any] = {
            "intent": decision.intent.value,
            "state_before": state.value,
            "state_after": decision.next_state.value,
            "rule_ids": list(decision.rule_ids),
            "explanation": decision.explanation,
            "facts_used": list(decision.facts_used),
            "provider": self._caller.capabilities.name,
            "uses_language_model": self._caller.capabilities.uses_language_model,
            "decide_latency_ms": turn.decide_latency_ms,
        }
        if audio_reference is not None and turn.audio is not None:
            metadata["audio"] = {
                "reference": audio_reference,
                "container": turn.audio.container.value,
                "content_type": turn.audio.content_type,
                "size_bytes": turn.audio.size_bytes,
                # Only what the speech layer actually verified. An unmeasurable
                # rate stays absent rather than being echoed from the request.
                "sample_rate_hz": turn.audio.sample_rate_hz,
                "duration_seconds": turn.audio.duration_seconds,
                "synthesis_latency_ms": turn.synthesis_latency_ms,
            }
        if turn.synthesis_error is not None:
            metadata["synthesis_error"] = turn.synthesis_error

        try:
            repo.add_turn(
                self._session,
                conversation_id=conversation.id,
                turn_index=turn_index,
                speaker=DbSpeaker.CALLER,
                content=decision.message,
                metadata=metadata,
            )
        except IntegrityError as exc:
            # The unique constraint fired: another request created this index
            # first. Reported rather than retried - a duplicate turn means two
            # loops are driving one conversation, which is the bug.
            raise DuplicateTurnError(
                f"turn {turn_index} already exists for conversation "
                f"{conversation.id}; a concurrent request created it",
                conversation_id=str(conversation.id),
            ) from exc

        meta.update(
            {
                "state": decision.next_state.value,
                "goal_achieved": decision.goal_achieved,
                "termination_reason": (
                    decision.termination_reason.value if decision.termination_reason else None
                ),
                "rule_ids": [*meta.get("rule_ids", []), *decision.rule_ids],
            }
        )

        if decision.should_terminate:
            self._close(conversation, meta, decision.next_state)
        else:
            repo.update_caller_metadata(self._session, conversation, meta)

        return conversation

    async def submit_bot_audio(
        self,
        conversation_id: uuid.UUID,
        *,
        audio: bytes,
        declared_encoding: AudioEncoding | None = None,
        sample_rate_hz: int | None = None,
    ) -> CallSession:
        """Transcribe the bot's reply and record it as a turn.

        A transcription failure is persisted as a failed bot turn with a null
        `content`, not as an empty transcript. §8 requires that distinction and
        the reason is scoring: "the bot was silent" is a bot defect, while "we
        could not transcribe the bot" is ours, and a pipeline that collapsed
        them would blame the bot for its own deafness.
        """
        conversation = self._load_active(conversation_id)
        if self._transcription is None:
            raise ScenarioNotUsableError(
                "no transcription service is configured, so bot audio cannot be "
                "accepted; submit the bot's text instead",
                conversation_id=str(conversation_id),
            )

        spec = self._spec_of(conversation)
        turn_index = repo.next_turn_index(self._session, conversation.id)

        metadata: dict[str, Any] = {"source": "bot_audio"}
        failure: TranscriptionError | None = None
        result = None

        # Transcribe before writing anything. A request rejected below must
        # leave no artefact on disk and no turn in the conversation.
        try:
            result = await self._transcription.transcribe_batch(
                audio,
                language=spec.language,
                declared_encoding=declared_encoding,
                sample_rate_hz=sample_rate_hz,
                correlation_id=f"caller-bot-{conversation.id}-{turn_index}",
            )
        except _REQUEST_DEFECTS:
            # The submitted bytes are not usable audio. That is the API
            # caller's mistake, not a transcription outage, and the two must
            # not be confused: recording a silent turn here would answer 200
            # OK to a .txt upload and leave a null turn in the transcript
            # looking exactly like a bot that said nothing.
            raise
        except TranscriptionError as exc:
            failure = exc

        if self._artefacts is not None:
            stored = self._artefacts.write(
                audio,
                conversation_id=conversation.id,
                turn_index=turn_index,
                speaker=Speaker.BOT,
                container="wav",
                content_type="audio/wav",
            )
            metadata["audio"] = {"reference": stored.reference, "size_bytes": len(audio)}

        if failure is not None:
            # Redacted for the same reason as the synthesis error: this
            # lands in `turn_metadata` and on the API surface.
            metadata["transcription_error"] = f"{type(failure).__name__}: {redact(failure)}"
            repo.add_turn(
                self._session,
                conversation_id=conversation.id,
                turn_index=turn_index,
                speaker=DbSpeaker.BOT,
                # Null, not "": the schema's own comment says a turn can exist
                # with audio captured and transcription incomplete.
                content=None,
                metadata=metadata,
            )
            logger.warning(
                "caller.bot_transcription_failed",
                extra={
                    "conversation_id": str(conversation.id),
                    "turn_index": turn_index,
                    "error_type": type(failure).__name__,
                },
            )
            return conversation

        metadata.update(
            {
                "transcription_provider": result.provider,
                "transcription_model": result.model,
                "transcription_latency_ms": result.latency_ms,
                "empty_transcript": result.is_empty,
            }
        )
        repo.add_turn(
            self._session,
            conversation_id=conversation.id,
            turn_index=turn_index,
            speaker=DbSpeaker.BOT,
            content=result.text,
            metadata=metadata,
        )
        return conversation

    def submit_bot_text(self, conversation_id: uuid.UUID, text: str) -> CallSession:
        """Record the bot's reply as text, skipping transcription.

        The path the offline simulation and the competition demo use: there is
        no voice bot to call yet, so driving the conversation from text is the
        honest way to exercise everything above the audio layer.
        """
        conversation = self._load_active(conversation_id)
        turn_index = repo.next_turn_index(self._session, conversation.id)
        repo.add_turn(
            self._session,
            conversation_id=conversation.id,
            turn_index=turn_index,
            speaker=DbSpeaker.BOT,
            content=text,
            metadata={"source": "bot_text"},
        )
        return conversation

    def terminate(
        self,
        conversation_id: uuid.UUID,
        *,
        reason: TerminationReason = TerminationReason.OPERATOR_TERMINATED,
    ) -> CallSession:
        """End a conversation from outside."""
        conversation = self._load_active(conversation_id)
        meta = repo.caller_metadata_of(conversation)
        meta.update({"state": CallerState.TERMINATED.value, "termination_reason": reason.value})
        self._close(conversation, meta, CallerState.TERMINATED)
        return conversation

    def _close(self, conversation: CallSession, meta: dict[str, Any], state: CallerState) -> None:
        """Mark a conversation finished in the database."""
        status = CallStatus.COMPLETED if state is CallerState.GOAL_ACHIEVED else CallStatus.FAILED
        meta["state"] = state.value
        repo.finish_conversation(self._session, conversation, status=status, caller_metadata=meta)
        logger.info(
            "caller.conversation_finished",
            extra={
                "conversation_id": str(conversation.id),
                "state": state.value,
                "outcome": outcome_of(state),
                "termination_reason": meta.get("termination_reason"),
            },
        )

    # -- Reporting ----------------------------------------------------------

    def report(self, conversation_id: uuid.UUID) -> ConversationReport:
        """Assemble the structured result of a conversation.

        Outcome matching happens here, against the bot's transcripts, because
        this is the one place that may see `expected_outcomes` - the caller
        never does.
        """
        conversation = repo.get_conversation(self._session, conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation", conversation_id)

        spec = self._spec_of(conversation)
        meta = repo.caller_metadata_of(conversation)
        turns = repo.list_turns(self._session, conversation.id)
        state = CallerState(meta.get("state", CallerState.INITIAL.value))

        bot_text = " ".join(
            normalise(turn.content or "") for turn in turns if turn.speaker is DbSpeaker.BOT
        )
        observed = tuple(
            outcome for outcome in spec.expected_outcomes if mentions_value(bot_text, outcome)
        )

        reason = meta.get("termination_reason")
        return ConversationReport(
            conversation_id=conversation.id,
            scenario_name=spec.name,
            language=spec.language,
            provider=str(meta.get("provider", "unknown")),
            uses_language_model=bool(meta.get("uses_language_model", False)),
            state=state,
            outcome=outcome_of(state) if is_terminal(state) else "in_progress",
            termination_reason=TerminationReason(reason) if reason else None,
            turns_used=sum(1 for t in turns if t.speaker is DbSpeaker.CALLER),
            turn_budget=int(meta.get("turn_budget", self._budget(spec))),
            goal_achieved=bool(meta.get("goal_achieved", False)),
            outcomes_expected=tuple(spec.expected_outcomes),
            outcomes_observed=observed,
            rule_ids_fired=tuple(meta.get("rule_ids", [])),
            error=conversation.error_message,
        )

    # -- Offline simulation -------------------------------------------------

    async def simulate(
        self,
        *,
        suite_id: uuid.UUID,
        scenario_id: uuid.UUID,
        bot_replies: list[str],
    ) -> ConversationReport:
        """Run a whole conversation against a scripted bot, offline.

        The §17 acceptance requirement, and the demo path: `bot_replies` stands
        in for the voice bot, so a full multi-turn conversation can be driven
        with no provider, no credential and no telephony. The caller's side is
        the real implementation - the same rules, the same state machine, the
        same persistence.

        Stops when the caller reaches a terminal state or the replies run out.
        Cannot loop forever: every turn either terminates or consumes one of a
        finite list, and the budget rule terminates independently.
        """
        conversation = self.start(suite_id=suite_id, scenario_id=scenario_id)
        await self.next_caller_turn(conversation.id)

        for reply in bot_replies:
            state = CallerState(
                repo.caller_metadata_of(
                    repo.get_conversation(self._session, conversation.id)  # type: ignore[arg-type]
                ).get("state", CallerState.INITIAL.value)
            )
            if is_terminal(state):
                break
            self.submit_bot_text(conversation.id, reply)
            await self.next_caller_turn(conversation.id)

        # Replies exhausted with the caller still going: close it rather than
        # leaving a conversation open forever in the database.
        current = repo.get_conversation(self._session, conversation.id)
        if current is not None:
            meta = repo.caller_metadata_of(current)
            if not is_terminal(CallerState(meta.get("state", CallerState.INITIAL.value))):
                meta["termination_reason"] = TerminationReason.NO_PROGRESS.value
                self._close(current, meta, CallerState.FAILED)

        return self.report(conversation.id)


__all__ = ["ConversationOrchestrator", "ConversationReport"]
