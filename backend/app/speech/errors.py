"""Structured speech-synthesis failures.

Deliberately a separate hierarchy from `app.transcription.errors` rather than
a shared one. The two subsystems fail for different reasons - a transcription
cannot have an "unsupported voice" and a synthesis cannot have "invalid audio"
on the way in - and a single flattened hierarchy would mean every handler
checking which half of it it was looking at.

What they *do* share is the shape: a `retryable` flag on the error rather than
a list of status codes in the retry loop, and `DomainError` as the base so the
handlers in `app.main` map them to HTTP in one place. That is what lets both
subsystems use one `call_with_retry`.
"""

from __future__ import annotations

from app.services.errors import DomainError


class SpeechError(DomainError):
    """Base class for every speech-synthesis failure.

    Attributes:
        message: Safe explanation. Never embeds a credential - adapters pass
            provider text through `redact` first.
        provider: Registry name of the provider that failed, e.g. `timbre`.
        retryable: Whether retrying the identical request could plausibly
            succeed.
        status_code: Provider HTTP status, when the failure came from one.
        error_code: Provider's own error code, when it sends one. Timbre's
            401/403/429 bodies carry one; its 400/500 bodies do not.
    """

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retryable: bool | None = None,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.error_code = error_code
        if retryable is not None:
            self.retryable = retryable

    def __str__(self) -> str:
        return self.message


# -- Permanent failures -----------------------------------------------------


class SpeechAuthenticationError(SpeechError):
    """The API key is missing, invalid, out of credit, or lacks the TTS scope.

    Covers 401, 402 and 403. Not retryable: none of the three changes because
    you asked again, and 402 in particular would keep failing while burning
    the rate limit.
    """


class InvalidTextError(SpeechError):
    """The text is empty, whitespace-only, or longer than the configured bound."""


class UnsupportedVoiceError(SpeechError):
    """The requested voice is not one the model documents."""

    def __init__(
        self,
        message: str,
        *,
        voice: str | None = None,
        supported: tuple[str, ...] = (),
        **kw: object,
    ) -> None:
        super().__init__(message, **kw)  # type: ignore[arg-type]
        self.voice = voice
        self.supported = supported


class UnsupportedSpeechLanguageError(SpeechError):
    """The provider does not synthesise the requested language.

    Distinct from `app.core.languages.UnsupportedLanguageError`, which means
    "not in the BhashaBench catalogue", and from the transcription error of the
    same role. A language can be authorable, recognisable and *not* speakable.
    """

    def __init__(
        self,
        message: str,
        *,
        language: str | None = None,
        supported: tuple[str, ...] = (),
        **kw: object,
    ) -> None:
        super().__init__(message, **kw)  # type: ignore[arg-type]
        self.language = language
        self.supported = supported


class UnsupportedAudioConfigError(SpeechError):
    """A container, encoding, sample rate, bitrate or speed the provider rejects."""


class MalformedSpeechResponseError(SpeechError):
    """The provider replied with something that is not usable audio.

    The important case for a TTS endpoint: a response that is syntactically
    fine but contains zero bytes, or JSON where audio was expected. Not
    retryable - repeating the request will not change the contract.
    """


class SpeechConfigurationError(SpeechError):
    """The provider cannot be constructed from the current settings."""


# -- Transient failures -----------------------------------------------------


class SpeechProviderUnavailableError(SpeechError):
    """The provider is unreachable or returned 500/503."""

    retryable = True


class SpeechRateLimitError(SpeechError):
    """The provider rejected the request for rate or quota reasons (429)."""

    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: object) -> None:
        super().__init__(message, **kw)  # type: ignore[arg-type]
        self.retry_after = retry_after


class SpeechTimeoutError(SpeechError):
    """The provider did not respond inside the configured timeout."""

    retryable = True


__all__ = [
    "InvalidTextError",
    "MalformedSpeechResponseError",
    "SpeechAuthenticationError",
    "SpeechConfigurationError",
    "SpeechError",
    "SpeechProviderUnavailableError",
    "SpeechRateLimitError",
    "SpeechTimeoutError",
    "UnsupportedAudioConfigError",
    "UnsupportedSpeechLanguageError",
    "UnsupportedVoiceError",
]
