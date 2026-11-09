"""Provider-independent speech-synthesis domain models.

The mirror of `app.transcription.models`, and the same rule applies: nothing
outside `app.speech.providers` may see a vendor's request or response shape.
Phase 6's caller agent will build a `SpeechRequest` and read a `SpeechResult`,
and will not know Timbre exists.

**What is measured is reported; what is not is `None`.** `sample_rate_hz`,
`channels` and `duration_seconds` are only set when they can actually be
established - read out of a WAV header, or derived from a known encoding and
byte count. For an MP3 they stay unset rather than being filled in from the
value that was *requested*, because "what we asked for" and "what came back"
are different claims and only one of them is evidence.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AudioContainer(StrEnum):
    """Container the synthesised audio is wrapped in.

    These are BhashaBench's names for the containers Timbre documents; the
    adapter maps them to whatever its provider calls them.
    """

    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"
    RAW = "raw"
    MULAW = "mulaw"
    """8 kHz G.711 µ-law - the telephony codec, not a general container."""
    ALAW = "alaw"
    """8 kHz G.711 A-law."""


class AudioEncodingName(StrEnum):
    """Sample encoding inside the container."""

    LINEAR_PCM = "linear_pcm"
    PCM_S16LE = "pcm_s16le"
    PCM_MULAW = "pcm_mulaw"
    PCM_ALAW = "pcm_alaw"
    OGG_OPUS = "oggopus"


class SpeechSpeed(StrEnum):
    """Documented string shortcuts for speaking rate.

    Kept separate from the numeric range so a caller can use either without
    the API having to accept a union of float and free-form string.
    """

    SLOW = "slow"
    MEDIUM = "medium"
    FAST = "fast"


class AudioConfig(BaseModel):
    """How the audio should be rendered.

    Defaults chosen for this project rather than copied from the vendor: 8 kHz
    mono, because an Indian phone call is 8 kHz mono and Phase 9 will put this
    audio down a telephone line. The vendor's own default is 48 kHz, which
    would have to be downsampled - and resampling the signal under test is
    exactly what Phase 7 exists to control.
    """

    model_config = ConfigDict(frozen=True)

    container: AudioContainer = Field(
        default=AudioContainer.WAV, description="Container for the returned audio."
    )
    encoding: AudioEncodingName = Field(
        default=AudioEncodingName.LINEAR_PCM, description="Sample encoding."
    )
    sample_rate_hz: int = Field(default=8000, gt=0, description="Requested sample rate in hertz.")
    channels: int = Field(default=1, gt=0, description="Channel count.")
    sample_width_bytes: int = Field(default=2, gt=0, description="Bytes per sample.")
    bitrate: str | None = Field(
        default=None, description="MP3 bitrate, e.g. `128k`. Ignored for other containers."
    )


class SpeechRequest(BaseModel):
    """A request to synthesise one piece of text."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(description="The text to speak.")
    language: str = Field(
        description="BhashaBench language tag, or a provider-level value like `auto`."
    )
    voice: str | None = Field(
        default=None, description="Voice identifier; the provider default applies when unset."
    )
    model: str | None = Field(
        default=None, description="Provider model identifier; the configured default when unset."
    )
    speed: float | SpeechSpeed | None = Field(
        default=None, description="Speaking rate, numeric or a documented shortcut."
    )
    audio: AudioConfig = Field(default_factory=AudioConfig, description="Output audio settings.")
    correlation_id: str | None = Field(
        default=None, description="Caller-supplied identifier, echoed into logs."
    )


class SpeechResult(BaseModel):
    """Synthesised audio plus what could be established about it."""

    model_config = ConfigDict(frozen=True)

    audio: bytes = Field(description="The audio payload.")
    container: AudioContainer = Field(description="Container the audio is in.")
    content_type: str = Field(description="Media type appropriate for this container.")
    provider: str = Field(description="Registry name of the provider that produced this.")
    model: str = Field(description="Provider model identifier used.")
    voice: str | None = Field(default=None, description="Voice identifier used.")
    language: str = Field(description="Language value sent to the provider.")
    requested_language: str = Field(description="Language the caller asked for.")
    speed: float | SpeechSpeed | None = Field(default=None, description="Speed applied.")
    latency_ms: float = Field(
        ge=0, description="Wall-clock milliseconds measured by BhashaBench, including retries."
    )
    size_bytes: int = Field(ge=0, description="Length of the audio payload.")
    sample_rate_hz: int | None = Field(
        default=None,
        description="Verified from the returned audio, not merely requested. "
        "Unset when the container carries no readable header.",
    )
    channels: int | None = Field(
        default=None, description="Verified from the returned audio. Unset when unknown."
    )
    duration_seconds: float | None = Field(
        default=None,
        description="Measured from the returned audio. Unset when it cannot be "
        "derived without decoding.",
    )
    requested_sample_rate_hz: int = Field(
        description="What was asked for. Kept alongside the verified value so a "
        "provider that ignores the request is visible rather than assumed away."
    )
    attempts: int = Field(default=1, ge=1, description="Provider calls made, including retries.")
    provider_request_id: str | None = Field(
        default=None, description="Provider request identifier, when one is supplied."
    )

    @property
    def rate_was_honoured(self) -> bool | None:
        """Whether the returned rate matches the requested one.

        `None` when the returned rate could not be established - which is not
        the same as a mismatch, and must not be reported as one.
        """
        if self.sample_rate_hz is None:
            return None
        return self.sample_rate_hz == self.requested_sample_rate_hz


__all__ = [
    "AudioConfig",
    "AudioContainer",
    "AudioEncodingName",
    "SpeechRequest",
    "SpeechResult",
    "SpeechSpeed",
]
