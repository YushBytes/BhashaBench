"""An offline transcription provider for tests and local development.

This is what makes the default test suite runnable with no credentials and no
network, which in turn is what makes CI able to reject a broken transcription
path on a pull request from a fork.

It is a *scripted* fake, not a stub that always succeeds. Every failure the
real adapter can produce - 401, 429, timeout, reset connection, malformed
body, mid-stream disconnect - is reachable here deterministically, because a
retry policy and an error-mapping layer are only as trustworthy as the failures
they have actually been driven through.

Two guards keep it out of production:

* it is registered under its own name, `fake`, never as a fallback for a
  misconfigured `prisma`; and
* `app.transcription.registry.build_provider` refuses to select it when
  `APP_ENV=production`, so a stray `TRANSCRIPTION_PROVIDER=fake` in a
  production environment fails at startup instead of silently returning
  fabricated transcripts.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field

from app.transcription import audio as audio_tools
from app.transcription.base import ProviderCapabilities
from app.transcription.errors import (
    AuthenticationError,
    MalformedProviderResponseError,
    ProviderUnavailableError,
    RateLimitError,
    StreamClosedError,
    TranscriptionError,
    TranscriptionTimeoutError,
)
from app.transcription.models import (
    AudioEncoding,
    FinalTranscript,
    PartialTranscript,
    StreamEvent,
    TranscriptionCompleted,
    TranscriptionFailed,
    TranscriptionMode,
    TranscriptionRequest,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionStarted,
)
from app.transcription.redaction import redact
from app.utils.timing import utc_now

PROVIDER_NAME = "fake"

DEFAULT_TRANSCRIPT = "namaste, main aapki kya madad kar sakta hoon"
"""A plausible Hinglish greeting from a support bot - the kind of utterance
this project exists to measure. Deliberately not `"test"`: a fixture that
looks like real traffic catches normalisation bugs that `"test"` cannot."""


@dataclass(slots=True)
class FakeScript:
    """What the fake should do, and in what order.

    `failures` is consumed one entry per call. A `None` entry means "succeed
    this time", so a script of `[RateLimitError(...), None]` drives the exact
    path a retry policy must handle: fail once, then succeed.
    """

    transcript: str = DEFAULT_TRANSCRIPT
    segments: Sequence[str] = ()
    """Texts to emit as streaming segments. Falls back to `transcript`."""
    partials: Sequence[str] = ()
    """Interim hypotheses to emit before each final segment.

    The fake declares `supports_partial_results=True` so the consuming side of
    partial handling is exercised somewhere. Prisma does not emit them; the
    interface still has to work for a provider that does.
    """
    failures: Sequence[TranscriptionError | None] = ()
    confidence: float | None = None
    provider_processing_ms: float | None = 42.0
    latency_ms: float = 12.0
    """Fixed so assertions on a result are exact rather than timing-dependent."""
    fail_mid_stream_after: int | None = None
    """Emit this many final segments, then raise `StreamClosedError`."""
    malformed_response: bool = False
    """Raise `MalformedProviderResponseError` as a real adapter would on a
    response it cannot interpret."""
    stream_delay_seconds: float = 0.0
    """Pause before each segment, for exercising cancellation and backpressure."""
    calls: list[str] = field(default_factory=list)
    """Appended to on every call, so a test can assert attempt counts."""
    frames_received: list[int] = field(default_factory=list)
    """Byte length of each audio chunk the stream consumed, so a test can show
    that audio was pulled lazily rather than drained up front."""

    def next_failure(self) -> TranscriptionError | None:
        """Pop the next scripted failure, or `None` to succeed."""
        if not self.failures:
            return None
        head, *tail = self.failures
        self.failures = tail
        return head


class FakeTranscriptionProvider:
    """A `TranscriptionProvider` that never touches the network."""

    def __init__(
        self,
        script: FakeScript | None = None,
        *,
        languages: Iterable[str] | None = None,
    ) -> None:
        self.script = script or FakeScript()
        # Defaults to the whole BhashaBench catalogue so a test can transcribe
        # any language without caring about provider coverage; a test that
        # cares passes an explicit subset.
        from app.core.languages import SUPPORTED_CODES

        self._languages = (
            frozenset(languages) if languages is not None else frozenset(SUPPORTED_CODES)
        )
        self._closed = False

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name=PROVIDER_NAME,
            display_name="Offline fake",
            languages=self._languages,
            batch_encodings=audio_tools.CONTAINER_ENCODINGS,
            streaming_encodings=frozenset({AudioEncoding.PCM_S16LE}),
            modes=frozenset(TranscriptionMode),
            supports_batch=True,
            supports_streaming=True,
            # True here on purpose: the one provider that exercises the
            # partial-result path, so the interface is not untested.
            supports_partial_results=True,
            supports_confidence=True,
            supports_word_timestamps=False,
            supports_diarisation=False,
            streaming_sample_rates=frozenset({8000, 16000, 44100, 48000}),
            streaming_frame_bytes=None,
            max_batch_bytes=None,
            requires_credentials=False,
            notes=(
                "Offline test double. Transcripts are scripted, not recognised. "
                "Never selectable when APP_ENV=production.",
            ),
        )

    @property
    def closed(self) -> bool:
        """Whether `close` has been called, so cleanup can be asserted."""
        return self._closed

    async def transcribe_batch(self, request: TranscriptionRequest) -> TranscriptionResult:
        """Return a scripted result, or raise the next scripted failure."""
        self.script.calls.append("batch")

        failure = self.script.next_failure()
        if failure is not None:
            raise failure
        if self.script.malformed_response:
            raise MalformedProviderResponseError(
                "the fake provider was scripted to return an uninterpretable response",
                provider=PROVIDER_NAME,
            )

        metadata = audio_tools.inspect(
            request.audio,
            declared=request.encoding if request.encoding is AudioEncoding.PCM_S16LE else None,
            sample_rate_hz=request.sample_rate_hz,
        )

        return TranscriptionResult(
            text=self.script.transcript,
            language=request.language,
            requested_language=request.language,
            provider=PROVIDER_NAME,
            model="fake-v1",
            request_id="fake-request-id",
            correlation_id=request.correlation_id,
            mode=request.mode,
            latency_ms=self.script.latency_ms,
            provider_processing_ms=self.script.provider_processing_ms,
            audio_duration_seconds=metadata.duration_seconds,
            confidence=self.script.confidence,
            segments=None,
        )

    async def transcribe_stream(
        self,
        audio: AsyncIterator[bytes],
        *,
        language: str,
        sample_rate_hz: int = 16000,
        mode: TranscriptionMode | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Emit a scripted event sequence.

        Audio is consumed before transcripts are emitted but recorded chunk by
        chunk in `frames_received`, so a test can assert the stream really
        pulled from the caller's iterator rather than ignoring it.
        """
        self.script.calls.append("stream")

        try:
            failure = self.script.next_failure()
            if failure is not None:
                raise failure

            yield TranscriptionStarted(
                provider=PROVIDER_NAME,
                language=language,
                sample_rate_hz=sample_rate_hz,
                correlation_id=correlation_id,
                at=utc_now(),
            )

            async for chunk in audio:
                self.script.frames_received.append(len(chunk))

            texts = list(self.script.segments) or [self.script.transcript]
            segments: list[TranscriptionSegment] = []
            emitted: list[str] = []

            for index, text in enumerate(texts):
                if self.script.stream_delay_seconds:
                    # A real await point, so a cancelling consumer has
                    # somewhere to interrupt.
                    await asyncio.sleep(self.script.stream_delay_seconds)

                if (
                    self.script.fail_mid_stream_after is not None
                    and index >= self.script.fail_mid_stream_after
                ):
                    raise StreamClosedError(
                        "the fake provider was scripted to drop the stream",
                        provider=PROVIDER_NAME,
                    )

                for hypothesis in self.script.partials:
                    yield PartialTranscript(text=hypothesis, segment_index=index, at=utc_now())

                segments.append(TranscriptionSegment(text=text, confidence=self.script.confidence))
                if text:
                    emitted.append(text)

                yield FinalTranscript(
                    text=text,
                    segment_index=index,
                    segment_id=f"fake-seg-{index}",
                    audio_duration_ms=1000.0,
                    latency_ms=self.script.latency_ms,
                    at=utc_now(),
                )

            yield TranscriptionCompleted(
                result=TranscriptionResult(
                    text=" ".join(emitted).strip(),
                    language=language,
                    requested_language=language,
                    provider=PROVIDER_NAME,
                    model="fake-v1",
                    correlation_id=correlation_id,
                    mode=mode,
                    latency_ms=self.script.latency_ms,
                    confidence=self.script.confidence,
                    segments=segments or None,
                ),
                at=utc_now(),
            )
        except TranscriptionError as exc:
            yield TranscriptionFailed(
                error_type=type(exc).__name__,
                message=redact(exc),
                retryable=exc.retryable,
                request_id=exc.request_id,
                at=utc_now(),
            )

    async def close(self) -> None:
        self._closed = True


# -- Prebuilt failures, so tests read as intent rather than construction ----


def auth_failure() -> AuthenticationError:
    """A permanent 401, which must never be retried."""
    return AuthenticationError(
        "the fake provider rejected the credentials",
        provider=PROVIDER_NAME,
        status_code=401,
    )


def rate_limit_failure(retry_after: float | None = None) -> RateLimitError:
    """A transient 429, optionally carrying the provider's own guidance."""
    return RateLimitError(
        "the fake provider is rate limiting",
        provider=PROVIDER_NAME,
        status_code=429,
        retry_after=retry_after,
    )


def unavailable_failure() -> ProviderUnavailableError:
    """A transient network or 5xx failure."""
    return ProviderUnavailableError("the fake provider is unreachable", provider=PROVIDER_NAME)


def timeout_failure() -> TranscriptionTimeoutError:
    """A transient timeout."""
    return TranscriptionTimeoutError("the fake provider timed out", provider=PROVIDER_NAME)


__all__ = [
    "DEFAULT_TRANSCRIPT",
    "PROVIDER_NAME",
    "FakeScript",
    "FakeTranscriptionProvider",
    "auth_failure",
    "rate_limit_failure",
    "timeout_failure",
    "unavailable_failure",
]
