"""Audio inspection and validation.

Two deliberate limits on scope.

**No decoding.** Validation reads container headers only. Establishing that an
MP3's payload decodes cleanly means decoding it, which needs a codec library
and costs CPU proportional to the audio - and the provider is going to decode
it anyway and tell us if it cannot. What we *can* do cheaply is reject the
mistakes that are actually common: an empty file, an HTML error page saved as
`.wav`, a 40 MB upload, a WAV whose header says eight channels.

**No conversion.** Resampling or transcoding belongs to the audio degradation
pipeline in Phase 7, and doing it here would silently change the signal under
test. A format the provider does not accept is rejected with an explanation,
not quietly converted.

The content sniffing is also a security control. A client-declared MIME type
or a filename extension is a hint from an untrusted source; the first bytes of
the payload are evidence. Where they disagree, the bytes win.
"""

from __future__ import annotations

import io
import wave
from pathlib import PurePosixPath, PureWindowsPath

from app.transcription.errors import (
    AudioTooLargeError,
    InvalidAudioError,
    UnsupportedFormatError,
)
from app.transcription.models import AudioEncoding, AudioMetadata

# Bytes per sample for 16-bit PCM, used to turn a raw byte count into seconds.
_PCM_S16_BYTES_PER_SAMPLE = 2

# Enough to carry every signature below plus the WAV `fmt ` chunk.
_SNIFF_BYTES = 64

# The value a WAV writer puts in the RIFF and `data` size fields when it does
# not yet know how long the stream will be. Gnani Timbre uses it for every
# synthesised utterance.
_WAV_UNKNOWN_SIZE = 0xFFFFFFFF

MIME_TYPES: dict[AudioEncoding, str] = {
    AudioEncoding.WAV: "audio/wav",
    AudioEncoding.MP3: "audio/mpeg",
    AudioEncoding.OGG: "audio/ogg",
    AudioEncoding.FLAC: "audio/flac",
    AudioEncoding.AAC: "audio/aac",
    AudioEncoding.M4A: "audio/mp4",
    AudioEncoding.PCM_S16LE: "audio/L16",
}
"""Canonical media type per encoding, for building outbound multipart parts."""

EXTENSIONS: dict[AudioEncoding, str] = {
    AudioEncoding.WAV: ".wav",
    AudioEncoding.MP3: ".mp3",
    AudioEncoding.OGG: ".ogg",
    AudioEncoding.FLAC: ".flac",
    AudioEncoding.AAC: ".aac",
    AudioEncoding.M4A: ".m4a",
    AudioEncoding.PCM_S16LE: ".raw",
}


def detect_encoding(audio: bytes) -> AudioEncoding | None:
    """Identify a container from its leading bytes.

    Returns `None` for anything unrecognised, including raw PCM - which has no
    header by definition and therefore cannot be detected, only declared.
    """
    if len(audio) < 4:
        return None

    # RIFF....WAVE
    if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return AudioEncoding.WAV
    if audio[:4] == b"fLaC":
        return AudioEncoding.FLAC
    if audio[:4] == b"OggS":
        return AudioEncoding.OGG
    # ISO base media file format: a `ftyp` box at offset 4. M4A and AAC-in-MP4
    # share it; the brand distinguishes them in principle, but both go to the
    # provider as MP4-contained audio, so M4A is the honest label.
    if audio[4:8] == b"ftyp":
        return AudioEncoding.M4A
    # ADTS AAC: 12 sync bits (0xFFF) then a 0 for MPEG-4/2 AAC.
    if audio[0] == 0xFF and (audio[1] & 0xF6) == 0xF0:
        return AudioEncoding.AAC
    # MP3 with an ID3v2 tag, or a bare MPEG audio frame header.
    if audio[:3] == b"ID3":
        return AudioEncoding.MP3
    if audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0:
        return AudioEncoding.MP3

    return None


def _inspect_wav(audio: bytes) -> tuple[int | None, int | None, int | None, float | None]:
    """Read sample rate, channels, bit depth and duration from a WAV header.

    Uses the standard library's `wave` module, which parses the RIFF chunks
    without decoding the samples. A header that does not parse is a corrupt
    file, not an unsupported one.

    `wave` reports the frame count the *header declares* and never checks that
    the data chunk actually contains it, so a file cut short mid-stream opens
    cleanly and reports its original duration. That matters twice over: a
    truncated upload would sail past a duration limit, and the duration we
    record against a transcript would be fiction. So the declared count is
    verified against the bytes really present, which is what `readframes`
    returns - bounded, because the payload is already in memory under the
    caller's size cap.

    **Two different reasons the declared count can exceed the real one**, and
    only one of them is a damaged file:

    * The writer knew the length and the bytes are missing - a truncated
      upload. Rejected.
    * The writer did *not* know the length when it wrote the header, so it
      filled the RIFF and `data` size fields with the `0xFFFFFFFF` sentinel.
      This is the ordinary convention for streamed or generated WAV and the
      file is perfectly good; the real length is simply the bytes present.
      Accepted, and measured from those bytes.

    Gnani Timbre does exactly the second thing. Treating it as truncation
    rejected every synthesised utterance - found by the first live call, not
    by any amount of mocking, because a fixture built with the stdlib `wave`
    writer always knows its own length.
    """
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            declared_frames = handle.getnframes()
            actual_frames = len(handle.readframes(declared_frames)) // (channels * sample_width)
    except (wave.Error, EOFError) as exc:
        raise InvalidAudioError(
            f"the WAV header could not be parsed ({exc}); the file is truncated or corrupt"
        ) from exc
    except ZeroDivisionError as exc:
        # A header claiming zero channels or a zero sample width.
        raise InvalidAudioError(
            "the WAV header declares zero channels or a zero sample width"
        ) from exc

    block_align = channels * sample_width
    # The `0xFFFFFFFF` sentinel, expressed as a frame count. `wave` divides the
    # declared byte size by the block alignment, so the comparison is made back
    # in bytes to stay independent of channels and sample width.
    #
    # The other streaming convention - a `data` size of zero - needs no branch
    # here: it yields `declared_frames == 0`, the truncation comparison cannot
    # fire, and the file is accepted with its rate and channels read but no
    # duration. "Accepted, length unknown" is the honest outcome, and claiming
    # a duration would mean reading past the chunk `wave` was told about.
    length_is_unknown = declared_frames * block_align >= _WAV_UNKNOWN_SIZE - block_align

    if length_is_unknown:
        frames = actual_frames
    elif actual_frames < declared_frames:
        raise InvalidAudioError(
            f"the WAV header declares {declared_frames} frames but only "
            f"{actual_frames} are present; the file is truncated"
        )
    else:
        frames = declared_frames

    duration = frames / sample_rate if sample_rate and frames else None
    return sample_rate, channels, sample_width * 8, duration


def inspect(
    audio: bytes,
    *,
    declared: AudioEncoding | None = None,
    sample_rate_hz: int | None = None,
) -> AudioMetadata:
    """Describe `audio`, trusting its bytes over any declaration.

    `declared` is used only for raw PCM, which carries no header to sniff. For
    everything else a mismatch between declaration and content is reported as
    an error rather than resolved in the declaration's favour - that is the
    path by which a `.wav`-named HTML error page reaches a provider.

    Raises:
        InvalidAudioError: empty payload, or a header that does not parse.
        UnsupportedFormatError: unrecognised content, or content that
            contradicts `declared`.
    """
    if not audio:
        raise InvalidAudioError("the audio payload is empty")

    detected = detect_encoding(audio)

    if declared is AudioEncoding.PCM_S16LE:
        # Headerless: nothing to sniff, so the declaration is all there is.
        if sample_rate_hz is None:
            raise InvalidAudioError(
                "raw pcm_s16le audio carries no header, so sample_rate_hz must be supplied"
            )
        if len(audio) % _PCM_S16_BYTES_PER_SAMPLE:
            raise InvalidAudioError(
                f"raw pcm_s16le audio must contain whole 16-bit samples, "
                f"but {len(audio)} bytes is an odd length"
            )
        samples = len(audio) // _PCM_S16_BYTES_PER_SAMPLE
        return AudioMetadata(
            encoding=AudioEncoding.PCM_S16LE,
            size_bytes=len(audio),
            sample_rate_hz=sample_rate_hz,
            channels=1,
            bit_depth=16,
            duration_seconds=samples / sample_rate_hz,
        )

    if detected is None:
        raise UnsupportedFormatError(
            "the audio format could not be identified from its content; "
            f"supported containers are {sorted(e.value for e in CONTAINER_ENCODINGS)}"
        )

    if declared is not None and declared is not detected:
        raise UnsupportedFormatError(
            f"the payload is {detected.value} audio but was declared as "
            f"{declared.value}; the declared format is not trusted over the content"
        )

    if detected is AudioEncoding.WAV:
        rate, channels, depth, duration = _inspect_wav(audio)
        return AudioMetadata(
            encoding=detected,
            size_bytes=len(audio),
            sample_rate_hz=rate,
            channels=channels,
            bit_depth=depth,
            duration_seconds=duration,
        )

    # Compressed containers: size and identity are all that is available
    # without decoding, and that is enough to decide whether to send it.
    return AudioMetadata(encoding=detected, size_bytes=len(audio))


CONTAINER_ENCODINGS: frozenset[AudioEncoding] = frozenset(
    {
        AudioEncoding.WAV,
        AudioEncoding.MP3,
        AudioEncoding.OGG,
        AudioEncoding.FLAC,
        AudioEncoding.AAC,
        AudioEncoding.M4A,
    }
)
"""Encodings that carry their own header, i.e. everything except raw PCM."""


def validate(
    audio: bytes,
    *,
    accepted: frozenset[AudioEncoding],
    max_bytes: int,
    declared: AudioEncoding | None = None,
    sample_rate_hz: int | None = None,
    accepted_sample_rates: frozenset[int] | None = None,
    max_channels: int | None = None,
    max_duration_seconds: float | None = None,
) -> AudioMetadata:
    """Inspect `audio` and enforce the caller's limits.

    Size is checked first and before inspection: it is the cheapest check and
    the one that bounds the cost of everything after it.

    Raises:
        AudioTooLargeError: over `max_bytes`, or longer than
            `max_duration_seconds` when the duration is knowable.
        InvalidAudioError: empty or corrupt.
        UnsupportedFormatError: a format, sample rate or channel count the
            provider does not accept.
    """
    if len(audio) > max_bytes:
        raise AudioTooLargeError(
            f"the audio is {len(audio)} bytes, which exceeds the {max_bytes} byte limit"
        )

    metadata = inspect(audio, declared=declared, sample_rate_hz=sample_rate_hz)

    if metadata.encoding not in accepted:
        raise UnsupportedFormatError(
            f"{metadata.encoding.value} audio is not accepted by this provider; "
            f"accepted encodings are {sorted(e.value for e in accepted)}"
        )

    if (
        accepted_sample_rates is not None
        and metadata.sample_rate_hz is not None
        and metadata.sample_rate_hz not in accepted_sample_rates
    ):
        raise UnsupportedFormatError(
            f"a sample rate of {metadata.sample_rate_hz} Hz is not accepted; "
            f"accepted rates are {sorted(accepted_sample_rates)} Hz"
        )

    if (
        max_channels is not None
        and metadata.channels is not None
        and metadata.channels > max_channels
    ):
        raise UnsupportedFormatError(
            f"the audio has {metadata.channels} channels but at most "
            f"{max_channels} is accepted; downmix it before transcribing"
        )

    if (
        max_duration_seconds is not None
        and metadata.duration_seconds is not None
        and metadata.duration_seconds > max_duration_seconds
    ):
        raise AudioTooLargeError(
            f"the audio is {metadata.duration_seconds:.1f}s long, which exceeds the "
            f"{max_duration_seconds:g}s limit for a single request"
        )

    return metadata


def safe_filename(name: str | None, *, encoding: AudioEncoding) -> str:
    """Reduce a client-supplied filename to a safe basename.

    An upload's filename is attacker-controlled. It is never used to open a
    path in this project - audio stays in memory - but it *is* forwarded in the
    outbound multipart body, and it reaches logs. A name like
    `../../etc/passwd` or one carrying a NUL or a newline has no business in
    either place.

    Both path flavours are stripped, not just the platform's own: a POSIX
    server must still neutralise `..\\..\\windows` arriving from a Windows
    client.
    """
    fallback = f"audio{EXTENSIONS[encoding]}"
    if not name:
        return fallback

    # Take the basename under both conventions, so neither separator survives.
    base = PureWindowsPath(PurePosixPath(name).name).name

    # Control characters, including the NUL byte that can truncate a filename
    # inside a C library, and the newlines that let a name forge a log line.
    base = "".join(character for character in base if character.isprintable())
    base = base.strip().strip(".")

    if not base or base in {".", ".."}:
        return fallback
    return base[:128]


__all__ = [
    "CONTAINER_ENCODINGS",
    "EXTENSIONS",
    "MIME_TYPES",
    "detect_encoding",
    "inspect",
    "safe_filename",
    "validate",
]
