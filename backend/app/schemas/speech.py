"""HTTP request and response models for the speech endpoints.

The synthesis response is **binary audio**, not JSON, so unlike the
transcription endpoints there is no response model for the success path -
`Response` carries the bytes and the content type. What is modelled here is
the request, the provider capability listing, and the metadata that travels
alongside the audio in headers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.speech.models import AudioContainer, AudioEncodingName, SpeechSpeed

MAX_TEXT_CHARS = 5000
"""Schema-level ceiling, matching the `SPEECH_MAX_TEXT_CHARS` default.

Declared here as well as in settings so an over-long body is rejected by
request validation - before a handler runs and before any provider is built.
A lower configured value still applies on top, in the service.
"""


class SpeechGenerateRequest(BaseModel):
    """A request to synthesise one utterance."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "नमस्ते, मैं आपकी पॉलिसी की स्थिति जाँच रहा हूँ।",
                "language": "hi-IN",
                "voice": "Kalpana",
                "speed": 1.0,
                "container": "wav",
                "sample_rate_hz": 8000,
            }
        }
    )

    text: str = Field(
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description="The text to speak. Expression tags such as `<laugh>` are "
        "accepted inline only by models that document them.",
    )
    language: str = Field(
        description="A BhashaBench language tag such as `hi-IN`, or a "
        "provider-level value: `auto` (recommended for mixed-script text) or "
        "`hi-en` for Hinglish.",
    )
    voice: str | None = Field(
        default=None,
        description="Voice identifier. The configured default applies when omitted; "
        "`GET /api/v1/speech/providers` lists what is available.",
    )
    model: str | None = Field(
        default=None, description="Provider model identifier. The configured default when omitted."
    )
    speed: float | SpeechSpeed | None = Field(
        default=None,
        description="Speaking rate: a number inside the provider's documented "
        "range, or one of `slow`, `medium`, `fast`.",
    )
    container: AudioContainer = Field(
        default=AudioContainer.WAV, description="Container for the returned audio."
    )
    encoding: AudioEncodingName = Field(
        default=AudioEncodingName.LINEAR_PCM, description="Sample encoding."
    )
    sample_rate_hz: int = Field(
        default=8000,
        gt=0,
        description="Requested sample rate. Defaults to 8000 Hz, the rate an "
        "Indian phone call runs at; the provider's own default is 48000.",
    )
    channels: int = Field(default=1, gt=0, le=2, description="Channel count.")
    sample_width_bytes: int = Field(default=2, gt=0, le=4, description="Bytes per sample.")
    bitrate: str | None = Field(
        default=None, description="MP3 bitrate, e.g. `128k`. Rejected for other containers."
    )
    correlation_id: str | None = Field(
        default=None, description="Your identifier, echoed into the response headers and logs."
    )


class VoiceResponse(BaseModel):
    """One voice a provider offers."""

    name: str = Field(description="Exact value to send as `voice`.")
    gender: str | None = Field(default=None, description="As catalogued by the provider.")
    character: str | None = Field(
        default=None,
        description="The provider's description of the voice's intended use, "
        "which is what makes it possible to match a voice to a scenario persona.",
    )


class SpeechProviderResponse(BaseModel):
    """What one synthesis provider can do."""

    name: str = Field(description="Registry name, used in SPEECH_PROVIDER.")
    display_name: str
    selected: bool = Field(description="Whether this is the configured provider.")
    available: bool = Field(
        description="Whether this provider can currently be constructed - "
        "false when a credential is missing."
    )
    unavailable_reason: str | None = Field(
        default=None,
        description="Why it is unavailable. Names the missing setting, never its value.",
    )
    languages: list[str] = Field(description="BhashaBench tags this provider can speak.")
    extra_language_values: list[str] = Field(
        description="Provider-level language values that are not BhashaBench "
        "tags, such as `auto` and `hi-en`."
    )
    unsupported_catalogue_languages: list[str] = Field(
        description="Catalogue languages this provider cannot speak. A scenario "
        "may be authored in them; no caller audio can be synthesised."
    )
    voices: list[VoiceResponse] = Field(description="Voices whose identifiers are documented.")
    voices_are_exhaustive: bool = Field(
        description="False when the provider has more voices than are "
        "documented. A voice name is then forwarded unvalidated rather than "
        "rejected for being absent from an incomplete list."
    )
    models: list[str]
    default_model: str
    containers: list[AudioContainer]
    encodings: list[AudioEncodingName]
    sample_rates: list[int]
    speed_min: float | None = Field(default=None)
    speed_max: float | None = Field(default=None)
    speed_aliases: list[str]
    audio_tags: list[str] = Field(
        description="Inline expression tags, empty when the model does not support them."
    )
    supports_audio_tags: bool
    supports_streaming: bool = Field(
        description="False throughout Phase 5. Timbre documents SSE and "
        "WebSocket streaming; neither is implemented."
    )
    max_text_chars: int | None
    requires_credentials: bool
    serialises_requests: bool = Field(
        description="Whether the adapter deliberately allows only one in-flight call."
    )
    notes: list[str] = Field(description="Verified limitations and documentation gaps.")


class SpeechProviderListResponse(BaseModel):
    """Every registered synthesis provider, with the selected one flagged."""

    selected: str = Field(description="The configured provider name.")
    providers: list[SpeechProviderResponse]


__all__ = [
    "MAX_TEXT_CHARS",
    "SpeechGenerateRequest",
    "SpeechProviderListResponse",
    "SpeechProviderResponse",
    "VoiceResponse",
]
