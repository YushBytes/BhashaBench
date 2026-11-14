"""Provider-independent transcription domain models.

Nothing outside `app.transcription.providers` is allowed to see a vendor's
response shape. These models are the contract everything else codes against,
so swapping Prisma for another engine in Phase 11 changes one adapter rather
than the evaluation layer.

**Optional means optional.** `confidence`, `segments` and word timings are
`None` unless the provider genuinely returned them. Gnani Prisma's documented
STT response carries no confidence score and no word timings, so a Prisma
result leaves them unset. Defaulting them to `1.0` or `[]` would read as "the
model was certain" rather than "the provider does not report this", and every
downstream metric built on it would be quietly fictional.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AudioEncoding(StrEnum):
    """Container or encoding of a piece of audio.

    Only what a provider in this project actually accepts. `PCM_S16LE` is raw
    headerless audio, used by the streaming path; the rest are containers used
    by the batch path.
    """

    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"
    FLAC = "flac"
    AAC = "aac"
    M4A = "m4a"
    PCM_S16LE = "pcm_s16le"


class TranscriptionMode(StrEnum):
    """How the transcript should be written out.

    These are BhashaBench's names for the four output modes Prisma v3.0
    documents. They are part of our own vocabulary: an adapter maps them to
    whatever its provider calls them, and a provider that supports only one
    mode declares that in its capabilities.

    `CODE_MIX` matters to this project specifically - Phase 3 added
    code-mixing annotations to the scenario schema, and a Hinglish utterance
    transcribed into pure Devanagari would score as a failure that never
    happened.
    """

    VERBATIM = "verbatim"
    """Word for word as spoken, fillers and repetitions kept."""
    TRANSCRIBE = "transcribe"
    """Clean readable text in the native script, numbers as digits."""
    CODE_MIX = "code_mix"
    """Each word in the script of the language it was spoken in."""
    TRANSLITERATE = "transliterate"
    """Every word in Latin script."""


class AudioMetadata(BaseModel):
    """What inspection could establish about a piece of audio.

    Every field except `encoding` is optional because the depth of inspection
    varies by container: a WAV header gives sample rate, channels and duration
    exactly, while an MP3's duration cannot be read without decoding, which
    this phase deliberately does not do.
    """

    model_config = ConfigDict(frozen=True)

    encoding: AudioEncoding = Field(description="Detected container or encoding.")
    size_bytes: int = Field(ge=0, description="Size of the audio payload in bytes.")
    sample_rate_hz: int | None = Field(
        default=None, gt=0, description="Sample rate, when the header declares one."
    )
    channels: int | None = Field(
        default=None, gt=0, description="Channel count, when the header declares one."
    )
    bit_depth: int | None = Field(
        default=None, gt=0, description="Bits per sample, for PCM-style encodings."
    )
    duration_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Duration, only when derivable without decoding the audio.",
    )


class TranscriptionRequest(BaseModel):
    """A request to transcribe one piece of audio.

    Carries the audio by value. That is a deliberate limit of this phase: the
    batch path handles short utterances, and keeping bytes in memory avoids
    writing caller-supplied data to disk at all. Long-file handling belongs
    with Prisma's asynchronous job API, which Phase 4 does not implement.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    audio: bytes = Field(description="The audio payload.")
    language: str = Field(description="BhashaBench language tag, e.g. `hi-IN`.")
    encoding: AudioEncoding = Field(description="Container or encoding of `audio`.")
    mode: TranscriptionMode | None = Field(
        default=None,
        description="Requested output mode; the provider default applies when unset.",
    )
    sample_rate_hz: int | None = Field(
        default=None,
        gt=0,
        description="Required for headerless encodings, where it cannot be inferred.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Caller-supplied identifier, echoed into logs to tie a "
        "transcription to the run that asked for it.",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Free-form caller annotations. Never sent to the provider.",
    )


class TranscriptionSegment(BaseModel):
    """One contiguous piece of a transcript.

    `start_seconds` and `end_seconds` are optional because not every provider
    timestamps segments. Prisma's streaming events carry a segment duration but
    no absolute offsets, so the adapter derives offsets from the accumulated
    stream position and leaves them unset on the batch path.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(description="Transcribed text of this segment.")
    start_seconds: float | None = Field(
        default=None, ge=0, description="Offset of the segment start, when known."
    )
    end_seconds: float | None = Field(
        default=None, ge=0, description="Offset of the segment end, when known."
    )
    speaker: str | None = Field(
        default=None, description="Speaker label, only when the provider diarises."
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Provider confidence, only when the provider reports one.",
    )


class TranscriptionResult(BaseModel):
    """A completed transcription, normalised across providers."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(description="The transcript. Empty when nothing was recognised.")
    language: str = Field(description="Language the transcript is in, as a BhashaBench tag.")
    requested_language: str = Field(description="Language the caller asked for.")
    provider: str = Field(description="Registry name of the provider that produced this.")
    model: str | None = Field(default=None, description="Provider model identifier, when reported.")
    request_id: str | None = Field(
        default=None, description="Provider-assigned request identifier, when reported."
    )
    correlation_id: str | None = Field(
        default=None, description="The caller's identifier, echoed back."
    )
    mode: TranscriptionMode | None = Field(
        default=None, description="Output mode actually applied, when known."
    )
    latency_ms: float = Field(
        ge=0,
        description="Wall-clock milliseconds measured by BhashaBench around the "
        "provider call, including retries.",
    )
    provider_processing_ms: float | None = Field(
        default=None,
        ge=0,
        description="Provider's own processing time, when it reports one.",
    )
    audio_duration_seconds: float | None = Field(
        default=None, ge=0, description="Duration of the audio, when known."
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Overall confidence. Unset for providers that do not report it.",
    )
    segments: list[TranscriptionSegment] | None = Field(
        default=None,
        description="Segment breakdown. Unset for providers that do not segment.",
    )
    attempts: int = Field(
        default=1, ge=1, description="How many provider calls were made, including retries."
    )

    @property
    def is_empty(self) -> bool:
        """True when the provider succeeded but recognised no speech.

        A distinct condition from failure: silence, or audio with no speech in
        it, is a legitimate result that a voice-bot test may well assert on.
        """
        return not self.text.strip()


# -- Streaming events -------------------------------------------------------
#
# A discriminated union rather than a bag of optional fields, so a consumer
# that handles `event.type == "final_transcript"` cannot accidentally read a
# field that only exists on another event.


class StreamEventType(StrEnum):
    """Kinds of event a streaming transcription emits."""

    STARTED = "started"
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    COMPLETED = "completed"
    FAILED = "failed"


class TranscriptionStarted(BaseModel):
    """The provider accepted the stream and is ready for audio."""

    model_config = ConfigDict(frozen=True)

    type: Literal[StreamEventType.STARTED] = StreamEventType.STARTED
    provider: str
    language: str
    sample_rate_hz: int | None = None
    correlation_id: str | None = None
    at: datetime


class PartialTranscript(BaseModel):
    """An interim hypothesis that the provider may still revise.

    Part of the interface because providers that stream interim results exist
    and this project will meet one. Gnani Prisma is not one of them: its
    documented streaming protocol emits a `transcript` event only after
    end-of-speech is detected, with no interim indicator. The Prisma adapter
    therefore never emits this event, and says so through
    `ProviderCapabilities.supports_partial_results`.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal[StreamEventType.PARTIAL_TRANSCRIPT] = StreamEventType.PARTIAL_TRANSCRIPT
    text: str
    segment_index: int | None = None
    at: datetime


class FinalTranscript(BaseModel):
    """A settled segment the provider will not revise."""

    model_config = ConfigDict(frozen=True)

    type: Literal[StreamEventType.FINAL_TRANSCRIPT] = StreamEventType.FINAL_TRANSCRIPT
    text: str
    segment_index: int | None = None
    segment_id: str | None = None
    audio_duration_ms: float | None = None
    latency_ms: float | None = None
    at: datetime


class TranscriptionCompleted(BaseModel):
    """The stream ended normally; `result` aggregates every final segment."""

    model_config = ConfigDict(frozen=True)

    type: Literal[StreamEventType.COMPLETED] = StreamEventType.COMPLETED
    result: TranscriptionResult
    at: datetime


class TranscriptionFailed(BaseModel):
    """The stream ended abnormally.

    Carries the error *category* and a redacted message rather than an
    exception, so the event can be serialised to a WebSocket client without
    leaking a stack trace or a credential.
    """

    model_config = ConfigDict(frozen=True)

    type: Literal[StreamEventType.FAILED] = StreamEventType.FAILED
    error_type: str
    message: str
    retryable: bool
    request_id: str | None = None
    at: datetime


StreamEvent = (
    TranscriptionStarted
    | PartialTranscript
    | FinalTranscript
    | TranscriptionCompleted
    | TranscriptionFailed
)
"""Everything a streaming transcription can emit."""


__all__ = [
    "AudioEncoding",
    "AudioMetadata",
    "FinalTranscript",
    "PartialTranscript",
    "StreamEvent",
    "StreamEventType",
    "TranscriptionCompleted",
    "TranscriptionFailed",
    "TranscriptionMode",
    "TranscriptionRequest",
    "TranscriptionResult",
    "TranscriptionSegment",
    "TranscriptionStarted",
]
