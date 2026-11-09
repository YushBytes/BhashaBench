"""Transcription business rules.

Sits between the API and the provider. Everything here is expressed in
`app.transcription.models` terms - there is no Prisma field name, no HTTP
status and no `HTTPException` in this module, in line with the layering rule
in `CLAUDE.md`.

What it owns:

* checking the language against both the BhashaBench catalogue *and* the
  selected provider's capabilities, which are different questions;
* refusing a request the provider cannot serve, before any audio is sent;
* applying the retry policy to batch calls, and deliberately not to streams;
* measuring end-to-end latency, including retries, so the number reported is
  what a caller actually waited.

**No persistence.** Phase 4 stores nothing. The foundational `TestRun`,
`CallSession` and `ConversationTurn` tables exist, but deciding which turn a
transcript belongs to is conversation orchestration - Phase 10 - and a table
written by nothing would be schema guesswork. Transcription is a pure function
of its input here, which also means these endpoints work with the database
down.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.core import languages
from app.core.config import Settings
from app.transcription import audio as audio_tools
from app.transcription.base import ProviderCapabilities, TranscriptionProvider
from app.transcription.errors import (
    TranscriptionError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.transcription.models import (
    AudioEncoding,
    StreamEvent,
    TranscriptionMode,
    TranscriptionRequest,
    TranscriptionResult,
)
from app.transcription.retry import RetryPolicy, call_with_retry
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.transcription")


def retry_policy_from(settings: Settings) -> RetryPolicy:
    """Build the retry policy the configuration asks for."""
    return RetryPolicy(
        max_attempts=settings.transcription_max_attempts,
        initial_backoff_seconds=settings.transcription_initial_backoff_seconds,
        max_backoff_seconds=settings.transcription_max_backoff_seconds,
    )


class TranscriptionService:
    """Transcribe audio through whichever provider is configured."""

    def __init__(
        self,
        provider: TranscriptionProvider,
        *,
        settings: Settings,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._policy = policy or retry_policy_from(settings)

    @property
    def capabilities(self) -> ProviderCapabilities:
        """The selected provider's capabilities."""
        return self._provider.capabilities

    # -- Validation ---------------------------------------------------------

    def _check_language(self, language: str) -> str:
        """Validate a language tag against the catalogue, then the provider.

        Two distinct failures, reported distinctly:

        * not a BhashaBench language at all - a typo or an unsupported locale.
          `languages.validate_tag` already distinguishes malformed from
          unknown, so that message is reused rather than rewritten.
        * a real BhashaBench language with no speech model behind it. Urdu,
          Odia and Assamese are in the catalogue and Prisma does not
          transcribe them. Telling the caller "unsupported language" without
          saying *by the provider* would send them looking for a typo that is
          not there.
        """
        tag = languages.validate_tag(language)

        capabilities = self.capabilities
        if not capabilities.supports_language(tag):
            raise UnsupportedLanguageError(
                f"'{tag}' is a supported BhashaBench language, but the "
                f"'{capabilities.name}' provider does not transcribe it. "
                f"Languages this provider supports: {sorted(capabilities.languages)}.",
                language=tag,
                supported=tuple(sorted(capabilities.languages)),
                provider=capabilities.name,
            )
        return tag

    def _check_mode(self, mode: TranscriptionMode | None) -> TranscriptionMode | None:
        """Reject an output mode the provider does not implement."""
        if mode is None:
            return None
        capabilities = self.capabilities
        if mode not in capabilities.modes:
            raise UnsupportedFormatError(
                f"output mode '{mode.value}' is not supported by the "
                f"'{capabilities.name}' provider; supported modes are "
                f"{sorted(m.value for m in capabilities.modes)}",
                provider=capabilities.name,
            )
        return mode

    # -- Batch --------------------------------------------------------------

    async def transcribe_batch(
        self,
        audio: bytes,
        *,
        language: str,
        mode: TranscriptionMode | None = None,
        declared_encoding: AudioEncoding | None = None,
        sample_rate_hz: int | None = None,
        correlation_id: str | None = None,
        filename: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe one complete piece of audio.

        Validation order is cheapest-first and intentional: language and mode
        are dictionary lookups, size is a length check, and content sniffing
        comes last. A request for Odia never has its audio inspected.

        Raises:
            app.core.languages.UnsupportedLanguageError: not a BhashaBench tag.
            TranscriptionError: any provider or validation failure, normalised.
        """
        capabilities = self.capabilities
        if not capabilities.supports_batch:
            raise UnsupportedFormatError(
                f"the '{capabilities.name}' provider does not support batch transcription",
                provider=capabilities.name,
            )

        tag = self._check_language(language)
        checked_mode = self._check_mode(mode)

        metadata = audio_tools.validate(
            audio,
            accepted=capabilities.batch_encodings,
            max_bytes=self._effective_max_bytes(capabilities),
            declared=declared_encoding,
            sample_rate_hz=sample_rate_hz,
            max_duration_seconds=capabilities.max_batch_duration_seconds,
        )

        request = TranscriptionRequest(
            audio=audio,
            language=tag,
            encoding=metadata.encoding,
            mode=checked_mode,
            sample_rate_hz=sample_rate_hz or metadata.sample_rate_hz,
            correlation_id=correlation_id,
            # The provider forwards this as the multipart filename. It is
            # already reduced to a safe basename by `audio_tools.safe_filename`
            # inside the adapter; passing the raw value keeps the sanitising in
            # one place rather than two.
            metadata={"filename": filename} if filename else {},
        )

        started = monotonic_seconds()
        result, attempts = await call_with_retry(
            lambda: self._provider.transcribe_batch(request),
            policy=self._policy,
            provider=capabilities.name,
            operation_name="batch",
            correlation_id=correlation_id,
        )
        elapsed_ms = round((monotonic_seconds() - started) * 1000, 3)

        logger.info(
            "transcription.completed",
            extra={
                "provider": capabilities.name,
                "operation": "batch",
                "language": tag,
                "mode": checked_mode.value if checked_mode else None,
                "correlation_id": correlation_id,
                "attempts": attempts,
                "latency_ms": elapsed_ms,
                "audio_bytes": metadata.size_bytes,
                "audio_duration_seconds": metadata.duration_seconds,
                "encoding": metadata.encoding.value,
                # Length, never content: a transcript can carry whatever the
                # caller said, including things that do not belong in a log.
                "transcript_chars": len(result.text),
                "empty_transcript": result.is_empty,
                "outcome": "empty" if result.is_empty else "success",
            },
        )

        # Replace the adapter's single-call latency with the service's
        # end-to-end measurement, and record how many attempts it took. A
        # result that took three tries and nine seconds must not report the
        # 600 ms the last attempt happened to take.
        return result.model_copy(
            update={
                "latency_ms": elapsed_ms,
                "attempts": attempts,
                "audio_duration_seconds": (
                    result.audio_duration_seconds or metadata.duration_seconds
                ),
            }
        )

    def _effective_max_bytes(self, capabilities: ProviderCapabilities) -> int:
        """The smaller of our configured limit and the provider's own."""
        configured = self._settings.transcription_max_upload_bytes
        if capabilities.max_batch_bytes is None:
            return configured
        return min(configured, capabilities.max_batch_bytes)

    # -- Streaming ----------------------------------------------------------

    def transcribe_stream(
        self,
        audio: AsyncIterator[bytes],
        *,
        language: str,
        sample_rate_hz: int,
        mode: TranscriptionMode | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Transcribe streaming audio, yielding provider-independent events.

        Not retried. The audio has already been consumed from a one-shot
        iterator by the time a failure is known, so a retry would transcribe
        whatever is left and present it as the whole utterance. The terminal
        `TranscriptionFailed` event carries `retryable`, and the decision
        belongs to the caller that still holds the audio source.

        Validation happens eagerly, before the returned generator is iterated,
        so a bad language or sample rate raises at the call site rather than
        surfacing as a failure event three frames in.
        """
        capabilities = self.capabilities
        if not capabilities.supports_streaming:
            raise UnsupportedFormatError(
                f"the '{capabilities.name}' provider does not support streaming transcription",
                provider=capabilities.name,
            )

        tag = self._check_language(language)
        checked_mode = self._check_mode(mode)

        if (
            capabilities.streaming_sample_rates
            and sample_rate_hz not in capabilities.streaming_sample_rates
        ):
            raise UnsupportedFormatError(
                f"the '{capabilities.name}' provider does not accept "
                f"{sample_rate_hz} Hz streaming audio; accepted rates are "
                f"{sorted(capabilities.streaming_sample_rates)} Hz",
                provider=capabilities.name,
            )

        logger.info(
            "transcription.stream_opened",
            extra={
                "provider": capabilities.name,
                "operation": "stream",
                "language": tag,
                "sample_rate_hz": sample_rate_hz,
                "correlation_id": correlation_id,
            },
        )

        return self._provider.transcribe_stream(
            audio,
            language=tag,
            sample_rate_hz=sample_rate_hz,
            mode=checked_mode,
            correlation_id=correlation_id,
        )

    async def close(self) -> None:
        """Release the provider's connections."""
        await self._provider.close()


def classify(error: TranscriptionError) -> str:
    """A stable, machine-readable category for an error.

    `AuthenticationError` -> `authentication_error`. Used by the API's error
    envelope and by the streaming failure event, so a client can branch on the
    category without parsing prose.
    """
    name = type(error).__name__
    if name.endswith("Error"):
        name = name[: -len("Error")]
    snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
    return f"{snake}_error"


__all__ = ["TranscriptionService", "classify", "retry_policy_from"]
