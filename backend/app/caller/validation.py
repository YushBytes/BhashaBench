"""The caller validation gate: what a decision must satisfy before it is spoken.

A module of its own, not a method on `CallerService`, because two things have
to apply exactly the same checks. The service applies them to every decision
before synthesis - that is the gate, and it is unconditional. A model-backed
provider applies them earlier, to its own draft, so that a rejected draft can
be replaced by the deterministic caller instead of killing the conversation.
One implementation means the provider cannot pass a decision the gate would
refuse, and cannot be stricter or laxer than it either.

The rule engine structurally cannot fail most of these. They exist for a
language model, which can and will.
"""

from __future__ import annotations

import re

from app.caller.errors import InvalidCallerDecisionError
from app.caller.schemas import CallerContext, CallerDecision
from app.caller.state import can_transition, is_terminal

# Phrases that would mean the caller is reciting its own instructions rather
# than speaking as the persona. §9 forbids revealing the system prompt or the
# evaluation criteria, and a rule engine cannot do it - but a model provider
# can and will, so the check lives where both pass through.
LEAK_PATTERNS = (
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
IDENTIFIER_DIGIT_LENGTH = 5
_DIGIT_RUN = re.compile(r"\d[\d\s\-]*\d|\d")


def unsourced_identifiers(decision: CallerDecision, context: CallerContext) -> list[str]:
    """Find identifier-shaped numbers that no known fact accounts for.

    This is §9's "do not invent account numbers" enforced rather than trusted.
    The rule engine structurally cannot fabricate one, but a model provider
    absolutely will, and a plausible invented claim reference spoken to a real
    bot is the single most damaging thing this system could do - it would look
    like a successful conversation.

    A number is accepted when its digits appear in some known fact, so a
    caller reading "0471883" is fine and one reading "9988776655" is not.
    """
    known_digits = {re.sub(r"\D", "", value) for value in context.known_facts.values()}
    known_digits.discard("")

    problems: list[str] = []
    for match in _DIGIT_RUN.finditer(decision.message):
        compact = re.sub(r"\D", "", match.group())
        if len(compact) < IDENTIFIER_DIGIT_LENGTH:
            continue
        if not any(compact in known or known in compact for known in known_digits):
            problems.append(
                f"message contains '{match.group().strip()}', which is "
                "identifier-shaped and matches no known fact"
            )
    return problems


def violations_of(
    decision: CallerDecision, context: CallerContext, *, max_message_chars: int
) -> tuple[str, ...]:
    """Every reason `decision` must not be spoken; empty when it may be.

    Collects every violation rather than stopping at the first, because a
    provider that produced one bad field has usually produced several and a
    single-violation message makes that a sequence of round trips to diagnose.
    """
    violations: list[str] = []

    if not decision.message.strip():
        violations.append("message is empty or whitespace only")
    if len(decision.message) > max_message_chars:
        violations.append(
            f"message is {len(decision.message)} characters, over the {max_message_chars} limit"
        )

    if not can_transition(context.state, decision.next_state):
        violations.append(
            f"{context.state} -> {decision.next_state} is not a permitted state transition"
        )

    if is_terminal(decision.next_state) and not decision.should_terminate:
        violations.append(
            f"next_state {decision.next_state} is terminal but should_terminate is False"
        )

    for pattern in LEAK_PATTERNS:
        if pattern.search(decision.message):
            violations.append(
                f"message appears to reveal hidden instructions (matched {pattern.pattern!r})"
            )
            break

    violations.extend(unsourced_identifiers(decision, context))

    for key in decision.facts_used:
        if key not in context.known_facts:
            violations.append(f"facts_used names '{key}', absent from known_facts")

    return tuple(violations)


def validate_decision(
    decision: CallerDecision,
    context: CallerContext,
    *,
    max_message_chars: int,
    provider: str,
) -> None:
    """Reject a decision that must not be spoken.

    Raises:
        InvalidCallerDecisionError: one or more checks failed.
    """
    violations = violations_of(decision, context, max_message_chars=max_message_chars)
    if violations:
        raise InvalidCallerDecisionError(
            f"the caller decision was rejected: {'; '.join(violations)}",
            violations=violations,
            provider=provider,
        )


__all__ = [
    "IDENTIFIER_DIGIT_LENGTH",
    "LEAK_PATTERNS",
    "unsourced_identifiers",
    "validate_decision",
    "violations_of",
]
