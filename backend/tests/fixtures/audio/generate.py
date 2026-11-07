"""Regenerate the audio fixtures in this directory.

Run from the repository root:

    python backend/tests/fixtures/audio/generate.py

The output is deterministic - no RNG, no timestamps - so a regeneration that
changes a byte means a code change, and `tests/test_audio_fixtures.py` fails if
the committed files do not match what this script produces.

**These fixtures contain no speech.** They are synthesised tones, silence and
deliberately malformed files. That is a limitation, recorded honestly rather
than papered over: no licensed Indian-language speech recordings have been
supplied to this repository, and inventing an "expected transcript" for audio
nobody has listened to would put fabricated ground truth into the test suite.

What they are sufficient for: exercising container detection, header parsing,
size and duration limits, the multipart upload path, the streaming frame
pipeline, and every error branch. What they cannot do: verify recognition
accuracy. That needs real speech and a real provider, and is gated behind
`TRANSCRIPTION_LIVE_TESTS` - see `docs/PROVIDERS.md`.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent

SAMPLE_RATE_TELEPHONY = 8000
"""8 kHz: what an Indian phone call actually arrives at, and the rate Prisma
documents for telephony audio. The default fixture rate for that reason."""

SAMPLE_RATE_WIDEBAND = 16000
"""Prisma's documented streaming default."""


def _tone(
    *,
    frequency_hz: float,
    duration_seconds: float,
    sample_rate: int,
    amplitude: float = 0.3,
) -> bytes:
    """Signed 16-bit little-endian mono PCM of a pure sine tone."""
    total = int(duration_seconds * sample_rate)
    peak = int(amplitude * 32767)
    samples = (
        int(peak * math.sin(2 * math.pi * frequency_hz * n / sample_rate)) for n in range(total)
    )
    return struct.pack(f"<{total}h", *samples)


def _silence(*, duration_seconds: float, sample_rate: int) -> bytes:
    """Digital silence, for asserting that an empty transcript is not an error."""
    return b"\x00\x00" * int(duration_seconds * sample_rate)


def _write_wav(path: Path, pcm: bytes, *, sample_rate: int, channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def generate() -> list[Path]:
    """Write every fixture, returning the paths in a stable order."""
    written: list[Path] = []

    # A short telephony-rate tone: the ordinary happy path.
    _write_wav(
        HERE / "tone_8k_mono.wav",
        _tone(frequency_hz=440.0, duration_seconds=1.0, sample_rate=SAMPLE_RATE_TELEPHONY),
        sample_rate=SAMPLE_RATE_TELEPHONY,
    )
    written.append(HERE / "tone_8k_mono.wav")

    # Wideband, matching Prisma's streaming default.
    _write_wav(
        HERE / "tone_16k_mono.wav",
        _tone(frequency_hz=440.0, duration_seconds=1.0, sample_rate=SAMPLE_RATE_WIDEBAND),
        sample_rate=SAMPLE_RATE_WIDEBAND,
    )
    written.append(HERE / "tone_16k_mono.wav")

    # Silence: a successful transcription with nothing recognised.
    _write_wav(
        HERE / "silence_8k_mono.wav",
        _silence(duration_seconds=0.5, sample_rate=SAMPLE_RATE_TELEPHONY),
        sample_rate=SAMPLE_RATE_TELEPHONY,
    )
    written.append(HERE / "silence_8k_mono.wav")

    # Stereo: must be rejected rather than silently downmixed, because
    # downmixing would change the signal under test.
    stereo = _tone(frequency_hz=440.0, duration_seconds=0.25, sample_rate=SAMPLE_RATE_TELEPHONY)
    interleaved = b"".join(stereo[i : i + 2] * 2 for i in range(0, len(stereo), 2))
    _write_wav(
        HERE / "tone_8k_stereo.wav",
        interleaved,
        sample_rate=SAMPLE_RATE_TELEPHONY,
        channels=2,
    )
    written.append(HERE / "tone_8k_stereo.wav")

    # A RIFF/WAVE header with a truncated body: `wave` can open it but the
    # frame count disagrees with the data present. Exercises the corrupt-file
    # branch rather than the unrecognised-format branch.
    full = (HERE / "tone_8k_mono.wav").read_bytes()
    (HERE / "truncated.wav").write_bytes(full[: len(full) // 3])
    written.append(HERE / "truncated.wav")

    # An HTML error page saved with a .wav name. The reason content sniffing
    # exists: the extension says audio, the bytes say otherwise.
    (HERE / "not_audio.wav").write_bytes(
        b"<!doctype html>\n<html><body><h1>502 Bad Gateway</h1></body></html>\n"
    )
    written.append(HERE / "not_audio.wav")

    # Headerless PCM, for the streaming path, which has no container at all.
    (HERE / "raw_8k_mono.pcm").write_bytes(
        _tone(frequency_hz=440.0, duration_seconds=0.5, sample_rate=SAMPLE_RATE_TELEPHONY)
    )
    written.append(HERE / "raw_8k_mono.pcm")

    return written


if __name__ == "__main__":
    for path in generate():
        print(f"{path.name:<24} {path.stat().st_size:>8} bytes")
