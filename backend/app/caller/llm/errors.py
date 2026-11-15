"""Normalised language-model failures.

Each carries a stable `code`, which is what lands in a turn's evidence as the
reason an attempt failed or a fallback happened. The class decides
`retryable`, as everywhere else in this codebase: a retry loop asks the error,
it does not keep its own list of status codes.

Two of these are refusals made *before* any request is sent -
`LiveCallsDisabledError` and `BudgetExceededError`. They are errors rather
than silent no-ops so that a caller which expected a model turn learns it did
not get one.
"""

from __future__ import annotations

from app.caller.errors import CallerError


class LlmError(CallerError):
    """Base class for every language-model failure."""

    code: str = "llm_error"
    request_sent: bool = True
    """Whether a request left the process before this was raised. The budget
    ledger charges the worst case for anything that did."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        provider_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message, provider=provider, retryable=retryable)
        self.status_code = status_code
        self.provider_code = provider_code
        self.request_id = request_id


class LiveCallsDisabledError(LlmError):
    """A live provider was asked to send a request while live calls are off."""

    code = "live_calls_disabled"
    request_sent = False


class BudgetExceededError(LlmError):
    """The request's worst-case cost does not fit a spending limit."""

    code = "budget_exceeded"
    request_sent = False


class PricingUnknownError(LlmError):
    """No price is configured for the model, so its cost cannot be bounded.

    Refused rather than treated as free: an unknown price is not a price of
    zero.
    """

    code = "pricing_unknown"
    request_sent = False


class LlmRequestTooLargeError(LlmError):
    """The prompt or the requested output is over a configured token limit."""

    code = "request_over_limit"
    request_sent = False


class LlmAuthenticationError(LlmError):
    """The provider rejected the credential."""

    code = "authentication_failed"


class LlmQuotaExhaustedError(LlmError):
    """The account has no credit left. Not retryable: waiting will not help."""

    code = "quota_exhausted"


class LlmRateLimitError(LlmError):
    """The provider is throttling. Retryable, honouring `retry_after`."""

    code = "rate_limited"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: object) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after


class LlmTimeoutError(LlmError):
    """No response within the timeout. Retryable, and possibly billed."""

    code = "timeout"
    retryable = True


class LlmUnavailableError(LlmError):
    """A server-side or transport failure. Retryable."""

    code = "provider_unavailable"
    retryable = True


class LlmBadRequestError(LlmError):
    """The provider refused the request as malformed. Never retryable."""

    code = "bad_request"


class LlmInvalidResponseError(LlmError):
    """The provider answered, but not with something usable.

    Covers a response that is not the documented shape, text that is not the
    requested JSON, and JSON that does not describe a legal caller turn.
    Retryable: a model asked again may well produce a usable answer, and the
    attempt limit bounds what that can cost.
    """

    code = "invalid_output"
    retryable = True


__all__ = [
    "BudgetExceededError",
    "LiveCallsDisabledError",
    "LlmAuthenticationError",
    "LlmBadRequestError",
    "LlmError",
    "LlmInvalidResponseError",
    "LlmQuotaExhaustedError",
    "LlmRateLimitError",
    "LlmRequestTooLargeError",
    "LlmTimeoutError",
    "LlmUnavailableError",
    "PricingUnknownError",
]
