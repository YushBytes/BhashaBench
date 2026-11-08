"""Structured caller failures.

Same shape as the transcription and speech families: `DomainError` at the base
so `app.main` maps them to HTTP in one place, and a `retryable` flag on the
error rather than a status-code list in a retry loop.
"""

from __future__ import annotations

from app.services.errors import DomainError


class CallerError(DomainError):
    """Base class for every caller failure."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool | None = None,
        conversation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.conversation_id = conversation_id
        if retryable is not None:
            self.retryable = retryable

    def __str__(self) -> str:
        return self.message


class CallerConfigurationError(CallerError):
    """The caller provider cannot be constructed from the current settings."""


class ScenarioNotUsableError(CallerError):
    """The scenario cannot drive a caller conversation.

    Distinct from "scenario not found", which is `NotFoundError`. This is a
    scenario that exists and is valid YAML but whose language no configured
    speech provider supports, or whose objective leaves the caller nothing to
    ask for.
    """


class InvalidCallerDecisionError(CallerError):
    """A provider returned a decision that failed validation.

    The important case for §7: a decision is rejected *before* its text can
    reach speech synthesis. Never retryable - a provider that produced an
    invalid decision once will produce it again from the same context, and the
    orchestrator's controlled recovery path is the answer, not a retry.
    """

    def __init__(self, message: str, *, violations: tuple[str, ...] = (), **kwargs: object) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.violations = violations


class ConversationNotActiveError(CallerError):
    """A turn was requested on a conversation that has already finished.

    Returned rather than silently ignored: a caller loop that keeps asking a
    finished conversation for turns is a bug, and answering it would hide the
    bug and inflate the turn count.
    """


class TurnBudgetExhaustedError(CallerError):
    """The scenario's `max_turns` has been reached."""


class DuplicateTurnError(CallerError):
    """A turn index already exists for this conversation.

    The database's unique constraint on `(call_session_id, turn_index)` is the
    real guard; this is how that constraint is reported as a domain failure
    rather than an opaque integrity error.
    """


__all__ = [
    "CallerConfigurationError",
    "CallerError",
    "ConversationNotActiveError",
    "DuplicateTurnError",
    "InvalidCallerDecisionError",
    "ScenarioNotUsableError",
    "TurnBudgetExhaustedError",
]
