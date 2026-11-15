"""Turn a model's reply into a `CallerDecision`, or say exactly why not.

A provider's schema enforcement is not relied on. Structured output may be
unsupported, best-effort or simply off, so every reply is parsed and checked
here as though it were free text - and the checks are the same ones the
schema describes.

What is derived rather than asked for: `should_terminate` and `goal_achieved`
follow from `next_state`, so a model cannot return a decision that
contradicts itself on them. What is *not* repaired: a missing reason for a
failure, an illegal state, an unknown fact key. Those are rejected; guessing
what the model meant would put words in the record that no one produced.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.caller.llm.errors import LlmInvalidResponseError
from app.caller.llm.prompt import allowed_next_states, allowed_termination_reasons
from app.caller.schemas import CallerContext, CallerDecision, CallerIntent, TerminationReason
from app.caller.state import CallerState, is_terminal

LLM_RULE_ID = "llm.generated"
"""Recorded in `rule_ids` for a model-generated turn, so a report that counts
rules can tell it from every rule the deterministic engine fires."""

_MAX_EXPLANATION_CHARS = 200


def _strip_code_fence(text: str) -> str:
    """Remove a Markdown fence a model wrapped its JSON in.

    Only the wrapper is removed. Prose before or after the JSON is left in
    place and fails to parse, because a reply with commentary around it is not
    the reply that was asked for.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _reject(reason: str, *, provider: str) -> LlmInvalidResponseError:
    return LlmInvalidResponseError(f"the model's reply was unusable: {reason}", provider=provider)


def parse_decision(text: str, context: CallerContext, *, provider: str) -> CallerDecision:
    """Build a `CallerDecision` from a model's reply.

    Raises:
        LlmInvalidResponseError: the reply is empty, is not a JSON object, or
            does not describe a turn the caller may take from this context.
    """
    if not text or not text.strip():
        raise _reject("it was empty", provider=provider)

    try:
        payload: Any = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        raise _reject(f"it was not valid JSON ({exc.msg})", provider=provider) from exc
    if not isinstance(payload, dict):
        raise _reject("it was JSON but not an object", provider=provider)

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise _reject("'message' is missing or empty", provider=provider)

    try:
        intent = CallerIntent(payload.get("intent"))
    except ValueError as exc:
        raise _reject(
            f"'intent' is not a known intent: {payload.get('intent')!r}", provider=provider
        ) from exc

    try:
        next_state = CallerState(payload.get("next_state"))
    except ValueError as exc:
        raise _reject(
            f"'next_state' is not a known state: {payload.get('next_state')!r}", provider=provider
        ) from exc
    permitted = allowed_next_states(context)
    if next_state not in permitted:
        raise _reject(
            f"'next_state' is {next_state.value}, but from {context.state.value} with "
            f"{context.turns_remaining} turn(s) left only "
            f"{[state.value for state in permitted]} are allowed",
            provider=provider,
        )

    raw_reason = payload.get("termination_reason")
    reason: TerminationReason | None = None
    if next_state is CallerState.GOAL_ACHIEVED:
        # The only reason a successful call can end for. Derived, not asked.
        reason = TerminationReason.GOAL_ACHIEVED
    elif next_state is CallerState.FAILED:
        try:
            reason = TerminationReason(raw_reason)
        except ValueError as exc:
            raise _reject(
                f"next_state is failed but 'termination_reason' is {raw_reason!r}",
                provider=provider,
            ) from exc
        if reason not in allowed_termination_reasons():
            raise _reject(
                f"'termination_reason' {reason.value} is not one a caller may give",
                provider=provider,
            )
    elif raw_reason is not None:
        raise _reject(
            f"'termination_reason' is {raw_reason!r} but the call is continuing", provider=provider
        )

    facts_used = payload.get("facts_used", [])
    if not isinstance(facts_used, list) or not all(isinstance(key, str) for key in facts_used):
        raise _reject("'facts_used' is not a list of strings", provider=provider)

    explanation = payload.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = "generated by the language model"

    try:
        return CallerDecision(
            message=message.strip(),
            intent=intent,
            next_state=next_state,
            goal_achieved=next_state is CallerState.GOAL_ACHIEVED,
            should_terminate=is_terminal(next_state),
            termination_reason=reason,
            explanation=explanation.strip()[:_MAX_EXPLANATION_CHARS],
            rule_ids=(LLM_RULE_ID,),
            facts_used=tuple(dict.fromkeys(facts_used)),
        )
    except ValidationError as exc:
        raise _reject(
            f"it did not form a consistent decision ({exc.error_count()} error(s))",
            provider=provider,
        ) from exc


__all__ = ["LLM_RULE_ID", "parse_decision"]
