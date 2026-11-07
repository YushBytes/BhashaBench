"""HTTP request and response models for the transcription endpoints.

Separate from `app.transcription.models` on purpose. Those are domain objects
shared with the CLI and the phases to come; these are the wire format, and the
two are allowed to diverge. In particular a response here never carries the
audio back, and never carries a provider's raw payload.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.transcription.models import (
    AudioEncoding,
    TranscriptionMode,
    TranscriptionResult,
    TranscriptionSegment,
)


class TranscriptionSegmentResponse(BaseModel):
    """One segment of a transcript."""

    text: str = Field(description="Transcribed text of this segment.")
    start_seconds: float | None = Field(
        default=None, description="Offset of the segment start, null when the provider omits it."
    )
    end_seconds: float | None = Field(
        default=None, description="Offset of the segment end, null when the provider omits it."
    )
    speaker: str | None = Field(
        default=None, description="Speaker label, null unless the provider diarises."
    )
    confidence: float | None = Field(
        default=None, description="Confidence, null unless the provider reports one."
    )

    @classmethod
    def of(cls, segment: TranscriptionSegment) -> TranscriptionSegmentResponse:
        return cls(
            text=segment.text,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            speaker=segment.speaker,
            confidence=segment.confidence,
        )


class TranscriptionResponse(BaseModel):
    """A completed transcription.

    `confidence` and `segments` are `null` when the provider does not report
    them rather than being filled with a plausible value. A client that needs
    confidence should read `GET /api/v1/transcription/providers` and find out
    whether any is available before designing around it.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "namaste, main aapki kya madad kar sakta hoon",
                "language": "hi-IN",
                "requested_language": "hi-IN",
                "provider": "prisma",
                "model": "prisma-v3.0",
                "request_id": "3f6c1e8a-2b7d-4a19-9c21-5f0d8e6b4a73",
                "correlation_id": "run-42-turn-3",
                "mode": "transcribe",
                "latency_ms": 663.0,
                "provider_processing_ms": 580.0,
                "audio_duration_seconds": 2.34,
                "confidence": None,
                "segments": None,
                "attempts": 1,
                "empty": False,
            }
        }
    )

    text: str = Field(description="The transcript. Empty when no speech was recognised.")
    language: str = Field(description="Language of the transcript, as a BhashaBench tag.")
    requested_language: str = Field(description="Language the request asked for.")
    provider: str = Field(description="Provider that produced this transcript.")
    model: str | None = Field(default=None, description="Provider model identifier.")
    request_id: str | None = Field(
        default=None, description="Provider request identifier, for vendor support queries."
    )
    correlation_id: str | None = Field(default=None, description="The caller's identifier.")
    mode: TranscriptionMode | None = Field(default=None, description="Output mode applied.")
    latency_ms: float = Field(
        description="End-to-end milliseconds measured by BhashaBench, including any retries."
    )
    provider_processing_ms: float | None = Field(
        default=None, description="The provider's own processing time, when reported."
    )
    audio_duration_seconds: float | None = Field(
        default=None, description="Duration of the submitted audio, when derivable."
    )
    confidence: float | None = Field(
        default=None, description="Null unless the provider reports confidence."
    )
    segments: list[TranscriptionSegmentResponse] | None = Field(
        default=None, description="Null unless the provider segments the transcript."
    )
    attempts: int = Field(description="Provider calls made, including retries.")
    empty: bool = Field(
        description="True when the provider succeeded but recognised no speech - "
        "a legitimate outcome, distinct from an error."
    )

    @classmethod
    def of(cls, result: TranscriptionResult) -> TranscriptionResponse:
        """Project a domain result onto the wire format."""
        return cls(
            text=result.text,
            language=result.language,
            requested_language=result.requested_language,
            provider=result.provider,
            model=result.model,
            request_id=result.request_id,
            correlation_id=result.correlation_id,
            mode=result.mode,
            latency_ms=result.latency_ms,
            provider_processing_ms=result.provider_processing_ms,
            audio_duration_seconds=result.audio_duration_seconds,
            confidence=result.confidence,
            segments=(
                [TranscriptionSegmentResponse.of(s) for s in result.segments]
                if result.segments is not None
                else None
            ),
            attempts=result.attempts,
            empty=result.is_empty,
        )


class ProviderCapabilitiesResponse(BaseModel):
    """What one provider can do.

    Published so a client can discover a limitation by reading rather than by
    hitting it. `notes` carries the vendor documentation gaps verbatim.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "prisma",
                "display_name": "Gnani Prisma",
                "selected": True,
                "available": True,
                "unavailable_reason": None,
                "languages": ["bn-IN", "en-IN", "gu-IN", "hi-IN"],
                "unsupported_catalogue_languages": ["as-IN", "or-IN", "ur-IN"],
                "batch_encodings": ["aac", "flac", "m4a", "mp3", "ogg", "wav"],
                "streaming_encodings": ["pcm_s16le"],
                "modes": ["transcribe"],
                "supports_batch": True,
                "supports_streaming": True,
                "supports_partial_results": False,
                "supports_confidence": False,
                "supports_word_timestamps": False,
                "supports_diarisation": False,
                "streaming_sample_rates": [8000, 16000, 44100, 48000],
                "streaming_frame_bytes": 1024,
                "max_batch_bytes": 10485760,
                "max_batch_duration_seconds": None,
                "requires_credentials": True,
                "notes": ["..."],
            }
        }
    )

    name: str = Field(description="Registry name, used in TRANSCRIPTION_PROVIDER.")
    display_name: str = Field(description="Human-readable provider name.")
    selected: bool = Field(description="Whether this is the configured provider.")
    available: bool = Field(
        description="Whether this provider can currently be constructed - "
        "false when a credential is missing."
    )
    unavailable_reason: str | None = Field(
        default=None,
        description="Why the provider is unavailable. Names the missing setting, never its value.",
    )
    languages: list[str] = Field(description="BhashaBench tags this provider transcribes.")
    unsupported_catalogue_languages: list[str] = Field(
        description="Catalogue languages this provider cannot transcribe. "
        "A scenario may be authored in them; no transcript can be produced."
    )
    batch_encodings: list[AudioEncoding] = Field(description="Accepted batch encodings.")
    streaming_encodings: list[AudioEncoding] = Field(description="Accepted streaming encodings.")
    modes: list[TranscriptionMode] = Field(description="Supported output modes.")
    supports_batch: bool
    supports_streaming: bool
    supports_partial_results: bool = Field(
        description="Whether streaming emits interim hypotheses before a segment settles."
    )
    supports_confidence: bool
    supports_word_timestamps: bool
    supports_diarisation: bool
    streaming_sample_rates: list[int] = Field(description="Accepted streaming sample rates in Hz.")
    streaming_frame_bytes: int | None = Field(
        default=None, description="Exact frame size required, when the protocol requires one."
    )
    max_batch_bytes: int | None = Field(default=None, description="Effective batch size limit.")
    max_batch_duration_seconds: float | None = Field(
        default=None, description="Batch duration limit, when the provider documents one."
    )
    requires_credentials: bool
    notes: list[str] = Field(description="Verified limitations and vendor documentation gaps.")


class ProviderListResponse(BaseModel):
    """Every registered provider, with the selected one flagged."""

    selected: str = Field(description="The configured provider name.")
    providers: list[ProviderCapabilitiesResponse] = Field(description="All registered providers.")


# -- Streaming envelope -----------------------------------------------------


class StreamMessage(BaseModel):
    """One message on the transcription WebSocket.

    A single envelope for every event, rather than a bare union, so a client
    can switch on `type` without inspecting which fields happen to be present.
    Unset fields are omitted from the JSON by the route, keeping frames small.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "final_transcript",
                "text": "haan, order number do teen char hai",
                "segment_index": 0,
                "segment_id": "seg_7f3a92",
                "at": "2026-11-07T10:30:05.987000Z",
            }
        }
    )

    type: str = Field(
        description="Event type: started, partial_transcript, "
        "final_transcript, completed or failed."
    )
    at: datetime = Field(description="UTC time the event was produced.")

    # started
    provider: str | None = None
    language: str | None = None
    sample_rate_hz: int | None = None
    correlation_id: str | None = None

    # partial_transcript / final_transcript
    text: str | None = None
    segment_index: int | None = None
    segment_id: str | None = None
    audio_duration_ms: float | None = None
    latency_ms: float | None = None

    # completed
    result: TranscriptionResponse | None = None

    # failed
    error_type: str | None = None
    message: str | None = None
    retryable: bool | None = None
    request_id: str | None = None


__all__ = [
    "ProviderCapabilitiesResponse",
    "ProviderListResponse",
    "StreamMessage",
    "TranscriptionResponse",
    "TranscriptionSegmentResponse",
]
