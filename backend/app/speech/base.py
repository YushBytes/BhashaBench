"""The speech-synthesis provider interface.

A `Protocol`, for the same reasons as `TranscriptionProvider`: adapters are
built from settings, share no implementation, and a test double should satisfy
the interface without importing it.

`SynthesisCapabilities` is again declared data rather than discovered
behaviour. A voice that does not exist, a language the provider cannot speak,
or a container it does not render are all refused with a precise message
before any request is sent - and published through
`GET /api/v1/speech/providers` so a scenario author can read the limits
instead of discovering them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.speech.models import AudioContainer, AudioEncodingName, SpeechRequest, SpeechResult


@dataclass(frozen=True, slots=True)
class VoiceDescriptor:
    """One voice a provider offers."""

    name: str
    gender: str | None = None
    character: str | None = None
    """The provider's description of its intended use, when it publishes one.

    Carried because picking a voice for a scenario persona from a bare list of
    names is guesswork, and the vendor already wrote the useful part.
    """
    languages: frozenset[str] = field(default_factory=frozenset)
    """Languages this voice speaks. Empty means "every language the provider
    supports" - true of all Timbre v3.0 voices."""


@dataclass(frozen=True, slots=True)
class SynthesisCapabilities:
    """What a synthesis provider can actually do."""

    name: str
    display_name: str
    languages: frozenset[str]
    """BhashaBench language tags this provider speaks - a subset of the
    catalogue, not the catalogue."""
    extra_language_values: frozenset[str] = frozenset()
    """Provider-level language values that are not BhashaBench tags, such as
    `auto` and `hi-en`. Separated so the catalogue gap stays computable."""
    voices: tuple[VoiceDescriptor, ...] = ()
    """Voices whose identifiers are known. May be empty when a provider has
    voices but does not publish a complete roster."""
    voices_are_exhaustive: bool = True
    """False when the provider has more voices than are documented.

    This is what stops the adapter rejecting a real-but-unlisted voice: with an
    incomplete roster the only honest behaviour is to forward the name and let
    the provider decide.
    """
    models: frozenset[str] = frozenset()
    default_model: str = ""
    containers: frozenset[AudioContainer] = frozenset()
    encodings: frozenset[AudioEncodingName] = frozenset()
    sample_rates: frozenset[int] = frozenset()
    speed_range: tuple[float, float] | None = None
    speed_aliases: frozenset[str] = frozenset()
    audio_tags: tuple[str, ...] = ()
    """Inline expression tags, when the provider supports them."""
    supports_audio_tags: bool = False
    supports_streaming: bool = False
    """False for this phase. Timbre documents SSE and WebSocket streaming;
    neither is implemented, because nothing consumes a stream until Phase 9."""
    max_text_chars: int | None = None
    requires_credentials: bool = True
    serialises_requests: bool = False
    """Whether the adapter deliberately allows only one in-flight call."""
    notes: tuple[str, ...] = field(default_factory=tuple)
    """Verified limitations and documentation gaps, surfaced to clients."""

    def supports_language(self, language: str) -> bool:
        """Whether this provider can speak `language`."""
        return language in self.languages or language in self.extra_language_values

    def knows_voice(self, voice: str) -> bool:
        """Whether `voice` is a documented identifier, case-insensitively."""
        folded = voice.strip().casefold()
        return any(v.name.casefold() == folded for v in self.voices)


@runtime_checkable
class SynthesisProvider(Protocol):
    """Text to speech for one provider.

    `synthesise` is `async` because it is network-bound. There is no streaming
    method in this phase: Timbre documents SSE and WebSocket transports, but
    adding an interface nothing consumes would be speculative - the caller
    agent (Phase 6) and the orchestrator (Phase 9) are what will decide the
    shape a stream needs to take.
    """

    @property
    def capabilities(self) -> SynthesisCapabilities:
        """What this provider supports. Cheap and side-effect free."""
        ...

    async def synthesise(self, request: SpeechRequest) -> SpeechResult:
        """Render `request.text` as audio.

        Raises:
            SpeechError: any failure, normalised. An adapter must not let a
                vendor library's exception escape.
        """
        ...

    async def close(self) -> None:
        """Release pooled connections. Idempotent."""
        ...


__all__ = ["SynthesisCapabilities", "SynthesisProvider", "VoiceDescriptor"]
