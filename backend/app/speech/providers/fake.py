"""An offline synthesis provider for tests and local development.

Like the transcription fake, this is scripted rather than always-yes: every
failure the Timbre adapter can produce is reachable deterministically, because
an error-mapping layer is only as trustworthy as the failures it has been
driven through.

It returns a **real, valid WAV** built with the standard library, not a
placeholder byte string. That matters: the result model reports sample rate,
channels and duration measured from the audio, and a fake that returned
`b"audio"` would leave those measurements untested and let a broken header
reach Phase 6 unnoticed.

Kept out of production by the same two guards as the transcription fake: its
own registry name, and a refusal to be selected when `APP_ENV=production`.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.speech.base import SynthesisCapabilities, VoiceDescriptor
from app.speech.errors import (
    InvalidTextError,
    MalformedSpeechResponseError,
    SpeechAuthenticationError,
    SpeechError,
    SpeechProviderUnavailableError,
    SpeechRateLimitError,
    SpeechTimeoutError,
)
from app.speech.models import AudioContainer, AudioEncodingName, SpeechRequest, SpeechResult

PROVIDER_NAME = "fake"

FAKE_VOICES: tuple[VoiceDescriptor, ...] = (
    VoiceDescriptor(name="Testa", gender="female", character="Offline test voice"),
    VoiceDescriptor(name="Testo", gender="male", character="Offline test voice"),
)

CONTENT_TYPES: dict[AudioContainer, str] = {
    AudioContainer.WAV: "audio/wav",
    AudioContainer.MP3: "audio/mpeg",
    AudioContainer.OGG: "audio/ogg",
    AudioContainer.RAW: "application/octet-stream",
    AudioContainer.MULAW: "audio/basic",
    AudioContainer.ALAW: "audio/basic",
}

G711_SAMPLE_RATE = 8000


def build_wav(*, sample_rate: int = 8000, channels: int = 1, seconds: float = 0.5) -> bytes:
    """Build a real WAV of a quiet tone, so header parsing is exercised."""
    total = int(sample_rate * seconds)
    peak = int(0.2 * 32767)
    samples = [
        int(peak * math.sin(2 * math.pi * 440.0 * n / sample_rate))
        for n in range(total)
        for _ in range(channels)
    ]
    frames = struct.pack(f"<{len(samples)}h", *samples)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return buffer.getvalue()


@dataclass(slots=True)
class FakeSpeechScript:
    """What the fake should do, and in what order."""

    failures: Sequence[SpeechError | None] = ()
    """Consumed one entry per call; `None` means "succeed this time"."""
    audio: bytes | None = None
    """Override the generated audio, to simulate an unmeasurable payload."""
    empty_response: bool = False
    """Raise as the adapter does for a 200 with no body."""
    seconds: float = 0.5
    latency_ms: float = 7.0
    """Fixed so assertions are exact rather than timing-dependent."""
    honour_sample_rate: bool = True
    """When false, return audio at a rate other than the one requested - the
    case that makes `rate_was_honoured` worth having."""
    calls: list[str] = field(default_factory=list)
    requests: list[SpeechRequest] = field(default_factory=list)
    """Every request received, so a test can assert what the service passed."""

    def next_failure(self) -> SpeechError | None:
        """Pop the next scripted failure, or `None` to succeed."""
        if not self.failures:
            return None
        head, *tail = self.failures
        self.failures = tail
        return head


class FakeSynthesisProvider:
    """A `SynthesisProvider` that never touches the network."""

    def __init__(
        self,
        script: FakeSpeechScript | None = None,
        *,
        languages: Iterable[str] | None = None,
    ) -> None:
        from app.core.languages import SUPPORTED_CODES

        self.script = script or FakeSpeechScript()
        self._languages = (
            frozenset(languages) if languages is not None else frozenset(SUPPORTED_CODES)
        )
        self._closed = False

    @property
    def capabilities(self) -> SynthesisCapabilities:
        return SynthesisCapabilities(
            name=PROVIDER_NAME,
            display_name="Offline fake",
            languages=self._languages,
            extra_language_values=frozenset({"auto"}),
            voices=FAKE_VOICES,
            voices_are_exhaustive=True,
            models=frozenset({"fake-tts-v1"}),
            default_model="fake-tts-v1",
            containers=frozenset(AudioContainer),
            encodings=frozenset(AudioEncodingName),
            sample_rates=frozenset({8000, 16000, 22050, 24000, 44100, 48000}),
            speed_range=(0.5, 2.0),
            speed_aliases=frozenset({"slow", "medium", "fast"}),
            audio_tags=(),
            supports_audio_tags=False,
            supports_streaming=False,
            max_text_chars=5000,
            requires_credentials=False,
            serialises_requests=False,
            notes=(
                "Offline test double. Audio is a synthesised tone, not speech. "
                "Never selectable when APP_ENV=production.",
            ),
        )

    @property
    def closed(self) -> bool:
        """Whether `close` has been called, so cleanup can be asserted."""
        return self._closed

    async def synthesise(self, request: SpeechRequest) -> SpeechResult:
        """Return scripted audio, or raise the next scripted failure."""
        self.script.calls.append("synthesise")
        self.script.requests.append(request)

        failure = self.script.next_failure()
        if failure is not None:
            raise failure
        if not request.text.strip():
            raise InvalidTextError("the text to synthesise is empty", provider=PROVIDER_NAME)
        if self.script.empty_response:
            raise MalformedSpeechResponseError(
                "the fake provider was scripted to return an empty body",
                provider=PROVIDER_NAME,
            )

        requested_rate = request.audio.sample_rate_hz
        actual_rate = requested_rate if self.script.honour_sample_rate else 16000
        container = request.audio.container

        payload, rate, channels, duration = self._render(request, container, actual_rate)

        return SpeechResult(
            audio=payload,
            container=container,
            content_type=CONTENT_TYPES[container],
            provider=PROVIDER_NAME,
            model=request.model or "fake-tts-v1",
            voice=request.voice or FAKE_VOICES[0].name,
            language=request.language,
            requested_language=request.language,
            speed=request.speed,
            latency_ms=self.script.latency_ms,
            size_bytes=len(payload),
            sample_rate_hz=rate,
            channels=channels,
            duration_seconds=duration,
            requested_sample_rate_hz=requested_rate,
        )

    def _render(
        self, request: SpeechRequest, container: AudioContainer, actual_rate: int
    ) -> tuple[bytes, int | None, int | None, float | None]:
        """Produce the payload and whatever can honestly be measured from it.

        Mirrors the real adapter's measurement rules rather than reporting
        everything: an MP3's rate is not knowable without a decoder here
        either, so it stays unset.
        """
        if self.script.audio is not None:
            return self.script.audio, None, None, None

        if container is AudioContainer.WAV:
            payload = build_wav(
                sample_rate=actual_rate,
                channels=request.audio.channels,
                seconds=self.script.seconds,
            )
            return payload, actual_rate, request.audio.channels, self.script.seconds

        if container in {AudioContainer.MULAW, AudioContainer.ALAW}:
            payload = b"\x00" * int(G711_SAMPLE_RATE * self.script.seconds)
            return payload, G711_SAMPLE_RATE, 1, len(payload) / G711_SAMPLE_RATE

        # raw / mp3 / ogg: opaque, exactly as the real adapter treats them.
        return b"\x00" * int(actual_rate * self.script.seconds), None, None, None

    async def close(self) -> None:
        self._closed = True


# -- Prebuilt failures, so tests read as intent -----------------------------


def auth_failure(status: int = 401) -> SpeechAuthenticationError:
    """A permanent credential failure (401/402/403); never retried."""
    return SpeechAuthenticationError(
        "the fake provider rejected the credentials",
        provider=PROVIDER_NAME,
        status_code=status,
    )


def rate_limit_failure(retry_after: float | None = None) -> SpeechRateLimitError:
    """A transient 429, optionally carrying the provider's own guidance."""
    return SpeechRateLimitError(
        "the fake provider is rate limiting",
        provider=PROVIDER_NAME,
        status_code=429,
        retry_after=retry_after,
    )


def unavailable_failure() -> SpeechProviderUnavailableError:
    """A transient network or 5xx failure."""
    return SpeechProviderUnavailableError(
        "the fake provider is unreachable", provider=PROVIDER_NAME
    )


def timeout_failure() -> SpeechTimeoutError:
    """A transient timeout."""
    return SpeechTimeoutError("the fake provider timed out", provider=PROVIDER_NAME)


__all__ = [
    "CONTENT_TYPES",
    "FAKE_VOICES",
    "G711_SAMPLE_RATE",
    "PROVIDER_NAME",
    "FakeSpeechScript",
    "FakeSynthesisProvider",
    "auth_failure",
    "build_wav",
    "rate_limit_failure",
    "timeout_failure",
    "unavailable_failure",
]
