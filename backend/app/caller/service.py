"""One caller turn: decide what to say, validate it, optionally speak it.

Sits between the orchestrator and the provider. Knows nothing about the
database or HTTP, so a turn can be exercised in a unit test with three lines
and no fixtures.

Two responsibilities worth separating from the provider itself.

**Validation of the decision.** §7 requires rejecting an invalid decision
before its text reaches synthesis, and the checks belong here rather than in
the provider for the obvious reason: a provider cannot be trusted to police
itself, and a future Evon provider returning model-generated JSON will need
exactly these checks applied to it. They are the reason
`InvalidCallerDecisionError` exists.

**Synthesis.** The decision's text goes to the existing `app/speech/` service
unchanged - there is no second Timbre adapter here, only a call into the one
Phase 5 built.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.caller.protocol import CallerCapabilities, CallerProvider
from app.caller.schemas import CallerContext, CallerDecision
from app.caller.validation import validate_decision
from app.core.config import Settings
from app.speech.errors import SpeechError
from app.speech.models import AudioConfig, SpeechResult
from app.speech.service import SpeechService
from app.transcription.redaction import redact
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.caller")


@dataclass(frozen=True, slots=True)
class CallerTurn:
    """One produced caller turn: the decision plus any audio for it."""

    decision: CallerDecision
    audio: SpeechResult | None
    """`None` when synthesis is disabled or unavailable.

    Deliberately nullable rather than defaulted to silence: §7 says generated
    audio must not be treated as proof a voice conversation happened, and a
    `None` here is the honest record that this turn is text only.
    """
    decide_latency_ms: float
    synthesis_latency_ms: float | None
    synthesis_error: str | None = None
    """Why synthesis failed, when it did and the turn continued anyway."""


class CallerService:
    """Produces one validated caller turn, with optional speech."""

    def __init__(
        self,
        provider: CallerProvider,
        *,
        settings: Settings,
        speech: SpeechService | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._speech = speech

    @property
    def capabilities(self) -> CallerCapabilities:
        """The selected provider's capabilities."""
        return self._provider.capabilities

    # -- Validation ---------------------------------------------------------

    def validate(self, decision: CallerDecision, context: CallerContext) -> None:
        """Reject a decision that must not be spoken.

        The checks themselves live in `app.caller.validation`, so a
        model-backed provider can apply the identical gate to its own draft
        before returning it. This call is still made on every decision,
        whatever the provider did first.

        Raises:
            InvalidCallerDecisionError: one or more checks failed.
        """
        validate_decision(
            decision,
            context,
            max_message_chars=self._settings.caller_max_message_chars,
            provider=self.capabilities.name,
        )

    # -- Turn production ----------------------------------------------------

    async def produce_turn(self, context: CallerContext) -> CallerTurn:
        """Decide the next utterance, validate it, and synthesise if enabled.

        Raises:
            InvalidCallerDecisionError: the provider's decision was unusable.
            CallerError: the provider failed.
        """
        started = monotonic_seconds()
        decision = await self._provider.decide(context)
        decide_ms = round((monotonic_seconds() - started) * 1000, 3)

        # Before synthesis, always. A rejected decision must not become audio.
        self.validate(decision, context)

        audio: SpeechResult | None = None
        synthesis_ms: float | None = None
        synthesis_error: str | None = None

        if self._settings.caller_synthesise_audio and self._speech is not None:
            audio, synthesis_ms, synthesis_error = await self._synthesise(decision, context)

        logger.info(
            "caller.turn_produced",
            extra={
                "provider": self.capabilities.name,
                "uses_language_model": self.capabilities.uses_language_model,
                "scenario": context.scenario_name,
                "language": context.persona.language,
                "turn_index": context.turn_index,
                "state_before": context.state.value,
                "state_after": decision.next_state.value,
                "intent": decision.intent.value,
                "rule_ids": list(decision.rule_ids),
                "goal_achieved": decision.goal_achieved,
                "terminating": decision.should_terminate,
                "decide_latency_ms": decide_ms,
                "synthesis_latency_ms": synthesis_ms,
                # Length, never content: a caller utterance quotes scenario
                # facts, which may include an account number.
                "message_chars": len(decision.message),
                "facts_used": list(decision.facts_used),
            },
        )

        return CallerTurn(
            decision=decision,
            audio=audio,
            decide_latency_ms=decide_ms,
            synthesis_latency_ms=synthesis_ms,
            synthesis_error=synthesis_error,
        )

    async def _synthesise(
        self, decision: CallerDecision, context: CallerContext
    ) -> tuple[SpeechResult | None, float | None, str | None]:
        """Turn the caller's text into audio via the Phase 5 speech service.

        A synthesis failure does **not** fail the turn. The conversation's
        subject is the bot, and the decision text is already valid and
        persisted; losing the audio for one turn is a recorded gap, while
        aborting the conversation would throw away the transcript too. The
        error is returned so it lands in `turn_metadata` rather than vanishing.
        """
        started = monotonic_seconds()
        try:
            result = await self._speech.synthesise(  # type: ignore[union-attr]
                decision.message,
                language=context.persona.language,
                audio=AudioConfig(),
                correlation_id=f"caller-{context.scenario_name}-{context.turn_index}",
            )
        except SpeechError as exc:
            elapsed = round((monotonic_seconds() - started) * 1000, 3)
            logger.warning(
                "caller.synthesis_failed",
                extra={
                    "scenario": context.scenario_name,
                    "turn_index": context.turn_index,
                    "error_type": type(exc).__name__,
                    "retryable": exc.retryable,
                },
            )
            # `str(exc)` only: the speech layer has already redacted it, and a
            # traceback has no business in a conversation record.
            # Redacted: this string is persisted in `turn_metadata` and
            # returned on the API surface, and provider error text has
            # carried an Authorization header before now.
            return None, elapsed, f"{type(exc).__name__}: {redact(exc)}"

        return result, round((monotonic_seconds() - started) * 1000, 3), None

    async def close(self) -> None:
        """Release the provider. The speech service is owned by its caller."""
        await self._provider.close()


__all__ = ["CallerService", "CallerTurn"]
