"""Structured transcription failures.

These are provider-independent on purpose. A caller handles
`AuthenticationError` without knowing whether the provider signalled it with
HTTP 401, a WebSocket close code or a vendor-specific error body - that
translation is the adapter's job.

Each error carries a `retryable` flag rather than leaving the retry decision to
a list of exception types scattered through the client. Getting that wrong is
expensive in both directions: retrying invalid credentials burns the rate
limit, and *not* retrying a reset connection fails a run for no reason.

`TranscriptionError` is a `DomainError` so the existing exception handlers in
`app.main` can map it to HTTP in one place, the same way `NotFoundError` is
handled - a service never raises `HTTPException`.
"""

from __future__ import annotations

from app.services.errors import DomainError


class TranscriptionError(DomainError):
    """Base class for every transcription failure.

    Attributes:
        message: Safe, human-readable explanation. Must never embed a
            credential; adapters pass provider text through `redact` first.
        provider: Registry name of the provider that failed, e.g. `prisma`.
        retryable: Whether retrying the identical request could plausibly
            succeed. Permanent client mistakes are false.
        status_code: Provider HTTP status, when the failure came from one.
        request_id: Provider-assigned request identifier, when known. The
            single most useful field when asking a vendor what happened.
    """

    retryable: bool = False
    """Class-level default so subclasses declare intent once."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.request_id = request_id
        if retryable is not None:
            self.retryable = retryable

    def __str__(self) -> str:
        return self.message


# -- Permanent failures: retrying the same request cannot help ---------------


class AuthenticationError(TranscriptionError):
    """The API key is missing, malformed, revoked or lacks the needed scope.

    Not retryable. A 401 that is retried three times is three times the log
    noise and no closer to working.
    """


class InvalidAudioError(TranscriptionError):
    """The audio is empty, truncated, or not decodable as the declared format."""


class UnsupportedFormatError(TranscriptionError):
    """The container or encoding is not one the provider accepts."""


class UnsupportedLanguageError(TranscriptionError):
    """The provider does not transcribe the requested language.

    Deliberately distinct from `app.core.languages.UnsupportedLanguageError`,
    which means "not in the BhashaBench catalogue". A language can be perfectly
    valid to author a scenario in and still have no speech model behind it -
    conflating the two would let a scenario silently transcribe as the wrong
    language.
    """

    def __init__(
        self,
        message: str,
        *,
        language: str | None = None,
        supported: tuple[str, ...] = (),
        **kwargs: object,
    ) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.language = language
        self.supported = supported


class AudioTooLargeError(TranscriptionError):
    """The audio exceeds the configured or documented size limit."""


class MalformedProviderResponseError(TranscriptionError):
    """The provider replied with something the adapter cannot interpret.

    Not retryable: a response that does not match the documented schema is a
    contract problem, and hammering the endpoint will not change the schema.
    Surfaced as its own type so a provider-side contract change is immediately
    distinguishable from a network fault.
    """


class ConfigurationError(TranscriptionError):
    """The provider cannot be constructed from the current settings.

    Raised at provider initialisation - an unknown provider name, or a missing
    API key for a provider that needs one - so a misconfiguration surfaces
    before any audio is read.
    """


# -- Transient failures: a retry may succeed --------------------------------


class ProviderUnavailableError(TranscriptionError):
    """The provider is unreachable or returned a 5xx."""

    retryable = True


class RateLimitError(TranscriptionError):
    """The provider rejected the request for rate or quota reasons.

    `retry_after` carries the provider's own guidance when it sends any, so the
    backoff can respect it instead of guessing.
    """

    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: object) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after


class TranscriptionTimeoutError(TranscriptionError):
    """The provider did not respond inside the configured timeout.

    Named with the `Transcription` prefix so it cannot be confused with the
    built-in `TimeoutError` in an `except` clause.
    """

    retryable = True


class StreamClosedError(TranscriptionError):
    """The provider closed the stream before the transcript was complete.

    Retryable as a *classification*, but the streaming path does not replay
    consumed audio - see `app.transcription.retry` for why that distinction
    matters.
    """

    retryable = True


class TranscriptionCancelledError(TranscriptionError):
    """The caller cancelled the operation.

    Not an error condition of the provider, but it travels the same channel, so
    consumers get one place to notice that no transcript is coming.
    """


__all__ = [
    "AudioTooLargeError",
    "AuthenticationError",
    "ConfigurationError",
    "InvalidAudioError",
    "MalformedProviderResponseError",
    "ProviderUnavailableError",
    "RateLimitError",
    "StreamClosedError",
    "TranscriptionCancelledError",
    "TranscriptionError",
    "TranscriptionTimeoutError",
    "UnsupportedFormatError",
    "UnsupportedLanguageError",
]
