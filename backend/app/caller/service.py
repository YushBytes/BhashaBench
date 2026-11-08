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
import re
from dataclasses import dataclass

from app.caller.errors import InvalidCallerDecisionError
from app.caller.protocol import CallerCapabilities, CallerProvider
from app.caller.schemas import CallerContext, CallerDecision
from app.caller.state import can_transition, is_terminal
from app.core.config import Settings
from app.speech.errors import SpeechError
from app.speech.models import AudioConfig, SpeechResult
from app.speech.service import SpeechService
from app.transcription.redaction import redact
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.caller")

# Phrases that would mean the caller is reciting its own instructions rather
# than speaking as the persona. §9 forbids revealing the system prompt or the
# evaluation criteria, and a rule engine cannot do it - but a future model
# provider can and will, so the check lives here where both pass through.
_LEAK_PATTERNS = (
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"\byou are an? (?:ai|assistant|caller|simulated)\b", re.IGNORECASE),
    re.compile(r"\bexpected[_ ]outcomes?\b", re.IGNORECASE),
    re.compile(r"\bevaluation criteria\b", re.IGNORECASE),
    re.compile(r"\bknown[_ ]facts\b", re.IGNORECASE),
    re.compile(r"\bscenario (?:id|name|spec|yaml)\b", re.IGNORECASE),
    re.compile(r"\bas an ai\b", re.IGNORECASE),
    re.compile(r"\bmy instructions\b", re.IGNORECASE),
    re.compile(r"\bignore (?:all |the )?(?:previous|above) instructions\b", re.IGNORECASE),
)

# Digit runs of this length or more are treated as identifier-shaped: "2019"
# passes, "0471883" must be traceable to a known fact.
#
# Five, not four, and the boundary is the whole decision. A four-digit run is
# almost always a year in this domain - a crop year, a policy year, the year a
# holding was registered - and a caller that could not say "I registered in
# 2019" would have valid turns rejected for speaking normally. The cost is that
# a four-digit invented PIN would pass this check; that is the smaller harm,
# and the §9 guarantee that matters - a fabricated *reference number* spoken to
# a real bot - concerns runs far longer than this.
_IDENTIFIER_DIGIT_LENGTH = 5
_DIGIT_RUN = re.compile(r"\d[\d\s\-]*\d|\d")


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

        Collects every violation rather than failing on the first, because a
        provider that produced one bad field has usually produced several and a
        single-violation message makes that a sequence of round trips to
        diagnose.

        Raises:
            InvalidCallerDecisionError: one or more checks failed.
        """
        violations: list[str] = []

        text = decision.message.strip()
        if not text:
            violations.append("message is empty or whitespace only")
        if len(decision.message) > self._settings.caller_max_message_chars:
            violations.append(
                f"message is {len(decision.message)} characters, over the "
                f"{self._settings.caller_max_message_chars} limit"
            )

        if not can_transition(context.state, decision.next_state):
            violations.append(
                f"{context.state} -> {decision.next_state} is not a permitted state transition"
            )

        if is_terminal(decision.next_state) and not decision.should_terminate:
            violations.append(
                f"next_state {decision.next_state} is terminal but should_terminate is False"
            )

        for pattern in _LEAK_PATTERNS:
            if pattern.search(decision.message):
                violations.append(
                    f"message appears to reveal hidden instructions (matched {pattern.pattern!r})"
                )
                break

        violations.extend(self._unsourced_identifiers(decision, context))

        for key in decision.facts_used:
            if key not in context.known_facts:
                violations.append(f"facts_used names '{key}', absent from known_facts")

        if violations:
            raise InvalidCallerDecisionError(
                f"the caller decision was rejected: {'; '.join(violations)}",
                violations=tuple(violations),
                provider=self.capabilities.name,
            )

    def _unsourced_identifiers(self, decision: CallerDecision, context: CallerContext) -> list[str]:
        """Find identifier-shaped numbers that no known fact accounts for.

        This is §9's "do not invent account numbers" enforced rather than
        trusted. The rule engine structurally cannot fabricate one, but a model
        provider absolutely will, and a plausible invented claim reference
        spoken to a real bot is the single most damaging thing this system
        could do - it would look like a successful conversation.

        A number is accepted when its digits appear in some known fact, so a
        caller reading "0471883" is fine and one reading "9988776655" is not.
        """
        known_digits = {re.sub(r"\D", "", value) for value in context.known_facts.values()}
        known_digits.discard("")

        problems: list[str] = []
        for match in _DIGIT_RUN.finditer(decision.message):
            compact = re.sub(r"\D", "", match.group())
            if len(compact) < _IDENTIFIER_DIGIT_LENGTH:
                continue
            if not any(compact in known or known in compact for known in known_digits):
                problems.append(
                    f"message contains '{match.group().strip()}', which is "
                    "identifier-shaped and matches no known fact"
                )
        return problems

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
