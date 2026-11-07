"""The transcription provider interface.

A `Protocol` rather than an abstract base class: adapters are constructed from
settings and never share implementation, so inheritance would buy nothing and
would force every fake in a test to call a base `__init__`. Structural typing
also means a test double satisfies the interface without importing it.

`ProviderCapabilities` is the part that keeps this project honest. Every
limitation a provider has - which languages it transcribes, whether it streams
interim results, whether it reports confidence - is declared data rather than
discovered at runtime from a failed request. The service layer can then refuse
an impossible request with a precise message instead of forwarding it and
translating a vendor error.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.transcription.models import (
    AudioEncoding,
    StreamEvent,
    TranscriptionMode,
    TranscriptionRequest,
    TranscriptionResult,
)


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can actually do.

    Reported through `GET /api/v1/transcription/providers`, so the limitation
    a developer hits is one they could have read first.
    """

    name: str
    """Registry name, e.g. `prisma`."""
    display_name: str
    """Human-readable name for documentation and UI."""
    languages: frozenset[str]
    """BhashaBench language tags this provider transcribes.

    A subset of the catalogue, not the catalogue. Prisma documents ten of the
    thirteen languages BhashaBench can author scenarios in; a scenario in one
    of the other three is valid to write and cannot currently be transcribed.
    """
    batch_encodings: frozenset[AudioEncoding]
    """Containers accepted on the batch path."""
    streaming_encodings: frozenset[AudioEncoding] = frozenset()
    """Encodings accepted on the streaming path; empty when streaming is absent."""
    modes: frozenset[TranscriptionMode] = frozenset()
    """Output modes the provider implements."""
    supports_batch: bool = True
    supports_streaming: bool = False
    supports_partial_results: bool = False
    """Whether streaming emits interim hypotheses before a segment settles.

    False for Prisma: its documented protocol emits a transcript event only
    after voice-activity detection reports end-of-speech, with no interim
    indicator. A consumer that wants live captions needs to know this rather
    than wait for partials that never arrive.
    """
    supports_confidence: bool = False
    """Whether results carry a confidence score. False for Prisma."""
    supports_word_timestamps: bool = False
    """Whether results carry per-word timings. False for Prisma."""
    supports_diarisation: bool = False
    """Whether results carry speaker labels."""
    streaming_sample_rates: frozenset[int] = frozenset()
    """Sample rates the streaming path accepts."""
    streaming_frame_bytes: int | None = None
    """Exact frame size the provider requires, when it requires one.

    Prisma's streaming protocol documents frames of exactly 1024 bytes and
    warns that bursting degrades its voice-activity detection, so this is a
    protocol requirement rather than a tuning parameter.
    """
    max_batch_bytes: int | None = None
    """Largest batch payload, when the provider or configuration bounds it."""
    max_batch_duration_seconds: float | None = None
    """Longest batch audio, when documented."""
    requires_credentials: bool = True
    """False only for the offline fake, which is what makes CI credential-free."""
    notes: tuple[str, ...] = field(default_factory=tuple)
    """Verified limitations and documentation gaps, surfaced to clients.

    Written for a developer reading the API, not for internal bookkeeping: if
    the vendor's documentation contradicts itself, that belongs here.
    """

    def supports_language(self, language: str) -> bool:
        """Whether this provider transcribes `language`."""
        return language in self.languages


@runtime_checkable
class TranscriptionProvider(Protocol):
    """Speech-to-text for one provider.

    Both methods are `async`: transcription is network-bound, and the
    streaming path has to interleave sending audio with receiving events,
    which a synchronous interface cannot express. This is a departure from the
    synchronous database sessions described in `docs/ARCHITECTURE.md`, and a
    deliberate one - these calls touch no database, so they are not subject to
    the reasoning that made sessions synchronous.
    """

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What this provider supports. Must be cheap and side-effect free."""
        ...

    async def transcribe_batch(self, request: TranscriptionRequest) -> TranscriptionResult:
        """Transcribe one complete piece of audio.

        Raises:
            TranscriptionError: any failure, in its normalised form. An
                adapter must not let a vendor library's exception escape.
        """
        ...

    def transcribe_stream(
        self,
        audio: AsyncIterator[bytes],
        *,
        language: str,
        sample_rate_hz: int,
        mode: TranscriptionMode | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Transcribe audio as it arrives, yielding events as they occur.

        Not `async def`: it returns an async generator, so the call itself does
        not need awaiting and the connection opens on first iteration. That
        keeps cancellation simple - abandoning the iterator closes the
        provider connection through the generator's own cleanup.

        Implementations must emit exactly one terminal event, either
        `TranscriptionCompleted` or `TranscriptionFailed`, so a consumer always
        learns how the stream ended.

        Args:
            audio: Chunks of raw audio in a `streaming_encodings` encoding.
                Consumed lazily; the provider applies its own backpressure by
                not pulling faster than it can send.
            language: BhashaBench language tag.
            sample_rate_hz: Sample rate of `audio`. Required because raw PCM
                carries no header.
            mode: Requested output mode, if the provider supports choosing.
            correlation_id: Echoed into logs and the `started` event.
        """
        ...

    async def close(self) -> None:
        """Release pooled connections. Idempotent."""
        ...


__all__ = ["ProviderCapabilities", "TranscriptionProvider"]
