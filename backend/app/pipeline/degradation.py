"""Controlled audio degradation.

A real Indian phone call is not a studio recording, and a bench that only ever
feeds a bot clean 16 kHz speech measures something nobody experiences. This
module applies a declared, reproducible set of transformations to 16-bit PCM
WAV and records exactly what it did.

**Why there is no numpy.** The repository has no numeric or audio dependency -
no numpy, scipy, soundfile or pydub - and `audioop`, which would have supplied
`ratecv`, `tomono` and `lin2lin`, was removed from the standard library in
Python 3.13. The choice was to add a scientific stack or to write the hundred
or so lines of integer arithmetic these transformations actually need. One
utterance is a few seconds of 8 kHz mono - tens of thousands of samples - so
pure Python is comfortably fast enough, and a dependency carried for that would
be the overengineering this phase was told to avoid. If a later phase needs
spectral work (a real reverb, a measured room impulse), that is the point to
reconsider; it is not needed to make speech sound like a phone call.

**Every transformation is a documented approximation, not a measurement.**
These are simulated conditions. `LIGHT_BACKGROUND_NOISE` is shaped white noise
at a stated SNR, not a recording of a market in Coimbatore, and nothing in this
repository claims otherwise. See `docs/PIPELINE.md`.

**Reproducibility is the property that matters.** A degraded artefact is only
evidence if the same input, profile and seed produce the same bytes. The seed
is required for anything stochastic, it is recorded in the artefact's metadata,
and a test asserts byte-identical output across runs.
"""

from __future__ import annotations

import array
import io
import math
import random
import wave
from dataclasses import dataclass, field, replace
from enum import StrEnum

from app.pipeline.errors import DegradationError

_INT16_MIN = -32768
_INT16_MAX = 32767

MAX_INPUT_BYTES = 25 * 1024 * 1024
"""Refuse to process anything larger, matching the artefact store's limit.

Degradation allocates several Python lists the length of the sample count, so
an unbounded input is a memory exposure as well as a slow one.
"""


class Transformation(StrEnum):
    """One degradation step. The value is what lands in the metadata."""

    TO_MONO = "to_mono"
    RESAMPLE = "resample"
    BANDPASS = "bandpass"
    ADD_NOISE = "add_noise"
    CLIP = "clip"
    REDUCE_AMPLITUDE = "reduce_amplitude"
    CODEC = "codec"
    PACKET_LOSS = "packet_loss"
    JITTER = "jitter"
    DROPOUT = "dropout"
    TRUNCATE = "truncate"
    PAD_SILENCE = "pad_silence"


class NoiseProfile(StrEnum):
    """A named, reviewed combination of transformations.

    Named profiles rather than free-form parameters on the API, so that two
    runs described as `MODERATE_BACKGROUND_NOISE` are actually comparable.
    A scenario's own `audio.noise_profile` maps onto these.
    """

    CLEAN = "clean"
    LIGHT_BACKGROUND_NOISE = "light_background_noise"
    MODERATE_BACKGROUND_NOISE = "moderate_background_noise"
    HEAVY_BACKGROUND_NOISE = "heavy_background_noise"
    TELEPHONY_BANDWIDTH = "telephony_bandwidth"


@dataclass(frozen=True, slots=True)
class DegradationConfig:
    """What to do to the audio.

    Every field is independently settable, so a test can exercise one
    transformation in isolation; the profiles below are just preset instances.
    `seed` is not optional for anything stochastic - see `validate`.
    """

    profile: NoiseProfile = NoiseProfile.CLEAN
    target_sample_rate_hz: int | None = None
    """Resample to this rate. `None` leaves the rate alone."""
    force_mono: bool = False
    bandpass_low_hz: float | None = None
    bandpass_high_hz: float | None = None
    snr_db: float | None = None
    """Signal-to-noise ratio for added noise. `None` adds no noise."""
    clip_threshold: float | None = None
    """Hard-clip at this fraction of full scale, in (0, 1]."""
    amplitude_scale: float | None = None
    """Multiply samples by this, in (0, 1]. Quiet speech, not silence."""
    codec: str | None = None
    """`g711_ulaw` or `g711_alaw`: encode and decode through the telephone
    codec's companding (ITU-T G.711), at 8 kHz. Exact, not approximated."""
    packet_loss_percent: float = 0.0
    packet_duration_ms: float = 20.0
    """Length of one simulated packet. 20 ms is the common RTP payload size."""
    jitter_ms: float = 0.0
    """Largest extra network delay a packet may suffer, drawn uniformly per
    packet. Where a packet's delay exceeds `jitter_buffer_ms` the receiver
    under-runs and the shortfall is inserted as silence before it."""
    jitter_buffer_ms: float = 40.0
    dropout_count: int = 0
    """Number of silent gaps of `dropout_ms` placed at seeded positions - a
    signal fade or a dead spot, longer than one packet."""
    dropout_ms: float = 200.0
    truncate_after_seconds: float | None = None
    """Cut the audio here, as a call that drops mid-sentence does."""
    leading_silence_ms: float = 0.0
    trailing_silence_ms: float = 0.0
    seed: int | None = None

    def validate(self) -> None:
        """Reject a configuration that cannot be honoured.

        Raises:
            DegradationError: a parameter is outside its documented range, or
                a stochastic transformation was requested without a seed.
        """
        problems: list[str] = []

        if self.target_sample_rate_hz is not None and not (
            4000 <= self.target_sample_rate_hz <= 48000
        ):
            problems.append(
                f"target_sample_rate_hz must be between 4000 and 48000, "
                f"got {self.target_sample_rate_hz}"
            )
        if self.bandpass_low_hz is not None and self.bandpass_low_hz < 0:
            problems.append(f"bandpass_low_hz must not be negative, got {self.bandpass_low_hz}")
        if self.bandpass_high_hz is not None and self.bandpass_high_hz <= 0:
            problems.append(f"bandpass_high_hz must be positive, got {self.bandpass_high_hz}")
        if (
            self.bandpass_low_hz is not None
            and self.bandpass_high_hz is not None
            and self.bandpass_low_hz >= self.bandpass_high_hz
        ):
            problems.append(
                f"bandpass_low_hz ({self.bandpass_low_hz}) must be below "
                f"bandpass_high_hz ({self.bandpass_high_hz})"
            )
        if self.clip_threshold is not None and not (0 < self.clip_threshold <= 1):
            problems.append(f"clip_threshold must be in (0, 1], got {self.clip_threshold}")
        if self.amplitude_scale is not None and not (0 < self.amplitude_scale <= 1):
            problems.append(f"amplitude_scale must be in (0, 1], got {self.amplitude_scale}")
        if not (0 <= self.packet_loss_percent <= 100):
            problems.append(
                f"packet_loss_percent must be in [0, 100], got {self.packet_loss_percent}"
            )
        if self.packet_duration_ms <= 0:
            problems.append(f"packet_duration_ms must be positive, got {self.packet_duration_ms}")
        if self.codec is not None and self.codec not in CODECS:
            problems.append(f"codec must be one of {sorted(CODECS)}, got {self.codec!r}")
        if not (0 <= self.jitter_ms <= 500):
            problems.append(f"jitter_ms must be in [0, 500], got {self.jitter_ms}")
        if not (0 <= self.jitter_buffer_ms <= 500):
            problems.append(f"jitter_buffer_ms must be in [0, 500], got {self.jitter_buffer_ms}")
        if not (0 <= self.dropout_count <= 50):
            problems.append(f"dropout_count must be in [0, 50], got {self.dropout_count}")
        if not (0 < self.dropout_ms <= 5000):
            problems.append(f"dropout_ms must be in (0, 5000], got {self.dropout_ms}")
        if self.truncate_after_seconds is not None and not (0 < self.truncate_after_seconds <= 600):
            problems.append(
                f"truncate_after_seconds must be in (0, 600], got {self.truncate_after_seconds}"
            )
        for name in ("leading_silence_ms", "trailing_silence_ms"):
            value = getattr(self, name)
            if not (0 <= value <= 10000):
                problems.append(f"{name} must be in [0, 10000], got {value}")

        # The reproducibility rule, enforced rather than documented: noise and
        # packet loss both draw from an RNG, and an unseeded run produces an
        # artefact nobody can reproduce - which is not evidence.
        stochastic = (
            self.snr_db is not None
            or self.packet_loss_percent > 0
            or self.jitter_ms > 0
            or self.dropout_count > 0
        )
        if stochastic and self.seed is None:
            problems.append(
                "a seed is required when adding noise or simulating packet loss, jitter "
                "or dropouts, because an artefact that cannot be reproduced is not evidence"
            )

        if problems:
            raise DegradationError(
                "the degradation configuration is invalid: " + "; ".join(problems),
                stage="degradation",
            )

    @property
    def is_noop(self) -> bool:
        """Whether this configuration would leave the audio untouched."""
        return not self.planned_transformations()

    def planned_transformations(self) -> tuple[Transformation, ...]:
        """The steps this configuration will apply, in execution order.

        Order is fixed and not configurable: channel reduction, then rate
        conversion, then filtering, then noise, then level, then loss. It
        mirrors a real path - a codec band-limits before the line adds noise,
        and loss happens last because it happens on the wire.
        """
        steps: list[Transformation] = []
        if self.force_mono:
            steps.append(Transformation.TO_MONO)
        if self.target_sample_rate_hz is not None:
            steps.append(Transformation.RESAMPLE)
        if self.bandpass_low_hz is not None or self.bandpass_high_hz is not None:
            steps.append(Transformation.BANDPASS)
        if self.snr_db is not None:
            steps.append(Transformation.ADD_NOISE)
        if self.amplitude_scale is not None:
            steps.append(Transformation.REDUCE_AMPLITUDE)
        if self.clip_threshold is not None:
            steps.append(Transformation.CLIP)
        if self.codec is not None:
            steps.append(Transformation.CODEC)
        if self.packet_loss_percent > 0:
            steps.append(Transformation.PACKET_LOSS)
        if self.jitter_ms > 0:
            steps.append(Transformation.JITTER)
        if self.dropout_count > 0:
            steps.append(Transformation.DROPOUT)
        if self.truncate_after_seconds is not None:
            steps.append(Transformation.TRUNCATE)
        if self.leading_silence_ms > 0 or self.trailing_silence_ms > 0:
            steps.append(Transformation.PAD_SILENCE)
        return tuple(steps)


def with_conditions(
    config: DegradationConfig, conditions: dict[str, float | int | None]
) -> DegradationConfig:
    """Apply declared channel conditions on top of a profile's configuration.

    Keys are `AudioConditions` field names; a missing or `None` key leaves the
    configuration alone. The mapping, in one place:

    - `gain_db` -> `amplitude_scale = 10 ** (gain_db / 20)`
    - `sample_rate_hz` -> `target_sample_rate_hz`, with `force_mono`, because
      resampling is mono-only and a profile that resamples also forces mono
    - `dropout_ms` without `dropout_count` changes nothing
    - everything else maps to the field of the same name
    """
    updates: dict[str, object] = {}
    gain = conditions.get("gain_db")
    if gain is not None:
        updates["amplitude_scale"] = 10 ** (float(gain) / 20)
    if conditions.get("clip_threshold") is not None:
        updates["clip_threshold"] = float(conditions["clip_threshold"])  # type: ignore[arg-type]
    if conditions.get("sample_rate_hz") is not None:
        updates["target_sample_rate_hz"] = int(conditions["sample_rate_hz"])  # type: ignore[arg-type]
        updates["force_mono"] = True
    for name in ("jitter_ms", "leading_silence_ms", "trailing_silence_ms", "dropout_ms"):
        if conditions.get(name) is not None:
            updates[name] = float(conditions[name])  # type: ignore[arg-type]
    if conditions.get("dropout_count") is not None:
        updates["dropout_count"] = int(conditions["dropout_count"])  # type: ignore[arg-type]
    if conditions.get("codec") is not None:
        updates["codec"] = str(conditions["codec"])
        # G.711 is 8 kHz mono; reaching it from any other rate is a conversion.
        updates.setdefault("target_sample_rate_hz", 8000)
        updates["force_mono"] = True
    if conditions.get("truncate_after_seconds") is not None:
        updates["truncate_after_seconds"] = float(conditions["truncate_after_seconds"])  # type: ignore[arg-type]
    if (updates.get("jitter_ms") or updates.get("dropout_count")) and not (
        config.force_mono or updates.get("force_mono")
    ):
        # Jitter and dropouts are mono-only, like resampling.
        updates["force_mono"] = True
    return replace(config, **updates) if updates else config


def profile_config(profile: NoiseProfile, *, seed: int | None = None) -> DegradationConfig:
    """The reviewed configuration for a named profile.

    The SNR figures are chosen to be audibly distinct and to bracket the range
    where speech recognition typically starts to struggle. They are not
    measurements of any particular network.
    """
    if profile is NoiseProfile.CLEAN:
        return DegradationConfig(profile=profile, seed=seed)

    if profile is NoiseProfile.TELEPHONY_BANDWIDTH:
        # 300-3400 Hz at 8 kHz is the classic narrowband telephone channel:
        # what a PSTN call does to speech before anything else happens to it.
        return DegradationConfig(
            profile=profile,
            target_sample_rate_hz=8000,
            force_mono=True,
            bandpass_low_hz=300.0,
            bandpass_high_hz=3400.0,
            seed=seed,
        )

    # The three noise profiles all sit on the telephony channel, because noise
    # on a wideband studio recording is not the condition being simulated.
    snr = {
        NoiseProfile.LIGHT_BACKGROUND_NOISE: 25.0,
        NoiseProfile.MODERATE_BACKGROUND_NOISE: 15.0,
        NoiseProfile.HEAVY_BACKGROUND_NOISE: 7.0,
    }[profile]
    return DegradationConfig(
        profile=profile,
        target_sample_rate_hz=8000,
        force_mono=True,
        bandpass_low_hz=300.0,
        bandpass_high_hz=3400.0,
        snr_db=snr,
        seed=seed,
    )


@dataclass(frozen=True, slots=True)
class DegradationResult:
    """Processed audio and the complete record of how it was produced.

    Everything needed to reproduce the artefact, because §8 requires it: the
    transformation list, the parameters, the seed, and both formats.
    """

    audio: bytes
    profile: NoiseProfile
    transformations: tuple[Transformation, ...]
    parameters: dict[str, float | int | bool | str | None]
    seed: int | None
    input_sample_rate_hz: int
    output_sample_rate_hz: int
    input_channels: int
    output_channels: int
    input_duration_seconds: float
    output_duration_seconds: float
    input_size_bytes: int
    output_size_bytes: int
    peak_amplitude: float
    """Highest absolute sample in the output, as a fraction of full scale."""
    clipped_sample_count: int
    """Samples sitting exactly at full scale after processing.

    Reported so an unintended clip is visible rather than inferred. Only
    meaningful against the configured `clip_threshold`: a run with no clipping
    configured and a non-zero count here has a level problem.
    """
    applied: bool = True
    parameter_notes: tuple[str, ...] = field(default=())
    """Where a request could not be honoured exactly, said plainly.

    A bandpass whose high edge exceeds Nyquist is clamped, for instance, and a
    report that silently kept the requested figure would be describing audio
    that was never produced.
    """


# ---------------------------------------------------------------------------
# WAV decoding and encoding
# ---------------------------------------------------------------------------


def _decode(audio: bytes) -> tuple[array.array, int, int]:
    """Decode 16-bit PCM WAV into samples, rate and channel count.

    Only 16-bit PCM is accepted. Both Timbre and the offline fake produce it,
    and guessing at other widths without a decoder is how a bench starts
    reporting on audio it did not understand.

    Raises:
        DegradationError: not WAV, not 16-bit, or unreadable.
    """
    if not audio:
        raise DegradationError("refusing to degrade an empty audio payload", stage="degradation")
    if len(audio) > MAX_INPUT_BYTES:
        raise DegradationError(
            f"the audio is {len(audio)} bytes, over the {MAX_INPUT_BYTES} byte "
            "limit for degradation",
            stage="degradation",
        )

    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            width = handle.getsampwidth()
            channels = handle.getnchannels()
            rate = handle.getframerate()
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError, OSError) as exc:
        raise DegradationError(
            f"the audio could not be read as a WAV file: {exc}", stage="degradation"
        ) from exc

    if width != 2:
        raise DegradationError(
            f"only 16-bit PCM is supported for degradation, but this audio is "
            f"{width * 8}-bit; no decoder is available to convert it",
            stage="degradation",
        )
    if channels < 1:
        raise DegradationError(f"the WAV header declares {channels} channels", stage="degradation")
    if rate <= 0:
        raise DegradationError(
            f"the WAV header declares a sample rate of {rate} Hz", stage="degradation"
        )
    if not frames:
        raise DegradationError(
            "the WAV file contains a header but no audio frames", stage="degradation"
        )

    samples = array.array("h")
    # `readframes` can return a partial final frame on a damaged file; trim to
    # whole samples rather than letting `frombytes` raise an opaque error.
    usable = len(frames) - (len(frames) % 2)
    samples.frombytes(frames[:usable])
    # WAV is little-endian; `array` uses native order, so swap on big-endian
    # hosts. Untested here because CI is little-endian, but wrong without it.
    if array.array("h", b"\x01\x00")[0] != 1:  # pragma: no cover - endianness
        samples.byteswap()
    return samples, rate, channels


def _encode(samples: array.array, *, rate: int, channels: int) -> bytes:
    """Encode samples back into a WAV file."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        payload = array.array("h", samples)
        if array.array("h", b"\x01\x00")[0] != 1:  # pragma: no cover - endianness
            payload.byteswap()
        handle.writeframes(payload.tobytes())
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------


def _to_mono(samples: array.array, channels: int) -> array.array:
    """Average interleaved channels down to one."""
    if channels == 1:
        return samples
    frames = len(samples) // channels
    out = array.array("h", bytes(frames * 2))
    for index in range(frames):
        base = index * channels
        total = 0
        for offset in range(channels):
            total += samples[base + offset]
        out[index] = _clamp(total // channels)
    return out


def _resample(samples: array.array, *, source_rate: int, target_rate: int) -> array.array:
    """Linear interpolation resampler.

    Linear, not sinc: for speech being deliberately degraded, the interpolation
    artefacts are far below the noise and band-limiting applied around them,
    and a windowed-sinc kernel would be a lot of arithmetic to improve
    something this phase is actively ruining. Downsampling relies on the
    bandpass that the telephony profiles apply first to limit aliasing; a
    profile that downsamples without filtering would alias, which is why the
    presets always pair them.
    """
    if source_rate == target_rate or not samples:
        return samples
    ratio = target_rate / source_rate
    out_length = max(int(len(samples) * ratio), 1)
    out = array.array("h", bytes(out_length * 2))
    last = len(samples) - 1
    for index in range(out_length):
        position = index / ratio
        left = int(position)
        if left >= last:
            out[index] = samples[last]
            continue
        fraction = position - left
        value = samples[left] * (1.0 - fraction) + samples[left + 1] * fraction
        out[index] = _clamp(round(value))
    return out


def _bandpass(
    samples: array.array, *, rate: int, low_hz: float | None, high_hz: float | None
) -> tuple[array.array, list[str]]:
    """One-pole high-pass and low-pass in cascade.

    A single pole per edge is a gentle 6 dB/octave roll-off rather than a brick
    wall. That is the honest shape for simulating a telephone channel, which is
    not a brick wall either, and it avoids the ringing a naive high-order IIR
    would add if its coefficients were slightly wrong.
    """
    notes: list[str] = []
    if not samples:
        return samples, notes

    nyquist = rate / 2.0
    effective_high = high_hz
    if effective_high is not None and effective_high >= nyquist:
        notes.append(
            f"bandpass_high_hz {high_hz} is at or above the {nyquist} Hz Nyquist "
            f"limit for {rate} Hz audio, so no low-pass was applied"
        )
        effective_high = None

    working = samples

    if effective_high is not None:
        # y[n] = y[n-1] + a * (x[n] - y[n-1])
        alpha = 1.0 - math.exp(-2.0 * math.pi * effective_high / rate)
        out = array.array("h", bytes(len(working) * 2))
        state = 0.0
        for index, value in enumerate(working):
            state += alpha * (value - state)
            out[index] = _clamp(round(state))
        working = out

    if low_hz is not None and low_hz > 0:
        # High-pass as the input minus its own low-pass.
        alpha = 1.0 - math.exp(-2.0 * math.pi * low_hz / rate)
        out = array.array("h", bytes(len(working) * 2))
        state = 0.0
        for index, value in enumerate(working):
            state += alpha * (value - state)
            out[index] = _clamp(round(value - state))
        working = out

    return working, notes


def _rms(samples: array.array) -> float:
    """Root mean square amplitude."""
    if not samples:
        return 0.0
    total = 0
    for value in samples:
        total += value * value
    return math.sqrt(total / len(samples))


def _add_noise(
    samples: array.array, *, snr_db: float, rng: random.Random
) -> tuple[array.array, float, list[str]]:
    """Mix in white noise scaled to hit a target signal-to-noise ratio.

    The noise amplitude is derived from the signal's own RMS, so the stated SNR
    holds for this particular utterance rather than being a fixed noise level
    that happens to be mild on loud speech and overwhelming on quiet speech.
    """
    notes: list[str] = []
    signal_rms = _rms(samples)
    if signal_rms <= 0:
        notes.append("the audio is silent, so no noise was added at any ratio")
        return samples, 0.0, notes

    noise_rms = signal_rms / (10.0 ** (snr_db / 20.0))
    # Uniform noise on [-1, 1] has RMS 1/sqrt(3); scale so the result has the
    # RMS the target ratio calls for.
    amplitude = noise_rms * math.sqrt(3.0)

    out = array.array("h", bytes(len(samples) * 2))
    for index, value in enumerate(samples):
        out[index] = _clamp(round(value + rng.uniform(-amplitude, amplitude)))
    return out, noise_rms, notes


def _achieved_snr_db(clean: array.array, noisy: array.array) -> float | None:
    """The signal-to-noise ratio actually present, in dB, rounded to 0.01.

    `None` when either side is silent, because a ratio with a zero term is not
    a measurement.
    """
    if len(clean) != len(noisy) or not clean:
        return None
    signal_rms = _rms(clean)
    noise_power = sum((n - c) ** 2 for c, n in zip(clean, noisy, strict=True)) / len(clean)
    if signal_rms <= 0 or noise_power <= 0:
        return None
    return round(20.0 * math.log10(signal_rms / math.sqrt(noise_power)), 2)


def _reduce_amplitude(samples: array.array, scale: float) -> array.array:
    """Scale every sample."""
    out = array.array("h", bytes(len(samples) * 2))
    for index, value in enumerate(samples):
        out[index] = _clamp(round(value * scale))
    return out


def _clip(samples: array.array, threshold: float) -> tuple[array.array, int]:
    """Hard-clip at a fraction of full scale, returning the count clipped."""
    ceiling = max(int(_INT16_MAX * threshold), 1)
    floor = -ceiling
    clipped = 0
    out = array.array("h", bytes(len(samples) * 2))
    for index, value in enumerate(samples):
        if value > ceiling:
            out[index] = ceiling
            clipped += 1
        elif value < floor:
            out[index] = floor
            clipped += 1
        else:
            out[index] = value
    return out, clipped


def _packet_loss(
    samples: array.array,
    *,
    rate: int,
    loss_percent: float,
    packet_duration_ms: float,
    rng: random.Random,
) -> tuple[array.array, int, int]:
    """Drop whole packets of samples, returning (audio, dropped, total).

    Packets, not individual samples: loss on a real network discards a datagram
    carrying 20 ms of audio, and dropping scattered samples would be a
    different artefact entirely - it would sound like crackle rather than like
    a gap. Lost packets are filled with silence, which is what a receiver with
    no concealment produces.
    """
    packet_samples = max(int(rate * packet_duration_ms / 1000.0), 1)
    total_packets = max(math.ceil(len(samples) / packet_samples), 1)
    out = array.array("h", samples)
    dropped = 0
    for packet in range(total_packets):
        if rng.uniform(0.0, 100.0) >= loss_percent:
            continue
        start = packet * packet_samples
        end = min(start + packet_samples, len(out))
        for index in range(start, end):
            out[index] = 0
        dropped += 1
    return out, dropped, total_packets


CODECS = frozenset({"g711_ulaw", "g711_alaw"})
_ULAW_BIAS = 0x84
_ULAW_CLIP = 32635


def _ulaw_encode(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), _ULAW_CLIP) + _ULAW_BIAS
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not magnitude & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def _ulaw_decode(code: int) -> int:
    code = ~code & 0xFF
    sign, exponent, mantissa = code & 0x80, (code >> 4) & 0x07, code & 0x0F
    magnitude = (((mantissa << 3) + _ULAW_BIAS) << exponent) - _ULAW_BIAS
    return -magnitude if sign else magnitude


def _alaw_encode(sample: int) -> int:
    # As the ITU reference: a 13-bit value, negatives folded to -x - 1.
    pcm = sample >> 3
    if pcm >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        pcm = -pcm - 1
    if pcm < 32:
        code = pcm >> 1
    else:
        exponent = pcm.bit_length() - 5
        code = (exponent << 4) | ((pcm >> exponent) & 0x0F)
    return code ^ mask


def _alaw_decode(code: int) -> int:
    code ^= 0x55
    sign, exponent, mantissa = code & 0x80, (code >> 4) & 0x07, code & 0x0F
    magnitude = (mantissa << 4) + (8 if exponent == 0 else 0x108)
    if exponent > 1:
        magnitude <<= exponent - 1
    return magnitude if sign else -magnitude


def _codec(samples: array.array, codec: str) -> tuple[array.array, float | None]:
    """Round-trip through G.711, returning the audio and the measured
    signal-to-quantisation-noise ratio in dB (`None` for silence)."""
    encode, decode = (
        (_ulaw_encode, _ulaw_decode) if codec == "g711_ulaw" else (_alaw_encode, _alaw_decode)
    )
    out = array.array("h", (_clamp(decode(encode(value))) for value in samples))
    signal = sum(v * v for v in samples)
    noise = sum((a - b) * (a - b) for a, b in zip(samples, out, strict=True))
    if not signal:
        return out, None
    if not noise:
        return out, math.inf
    return out, round(10 * math.log10(signal / noise), 3)


def _jitter(
    samples: array.array,
    *,
    rate: int,
    jitter_ms: float,
    buffer_ms: float,
    packet_duration_ms: float,
    rng: random.Random,
) -> tuple[array.array, int, float]:
    """Insert under-run silence where a packet's delay exceeds the buffer.

    Returns (audio, gaps inserted, total silence inserted in ms). An
    approximation of a receiver with a fixed jitter buffer and no
    concealment: real receivers adapt their buffer and conceal, so this is
    the harsh end of what jitter does, and it is reported as such.
    """
    packet_samples = max(int(rate * packet_duration_ms / 1000.0), 1)
    out = array.array("h")
    gaps = 0
    inserted = 0
    for start in range(0, len(samples), packet_samples):
        late_ms = rng.uniform(0.0, jitter_ms) - buffer_ms
        if late_ms > 0:
            count = int(rate * late_ms / 1000.0)
            if count:
                out.extend(array.array("h", bytes(count * 2)))
                gaps += 1
                inserted += count
        out.extend(samples[start : start + packet_samples])
    return out, gaps, round(1000.0 * inserted / rate, 3)


def _dropouts(
    samples: array.array, *, rate: int, count: int, dropout_ms: float, rng: random.Random
) -> tuple[array.array, float]:
    """Silence `count` gaps of `dropout_ms` at seeded positions.

    Returns the audio and the silenced duration actually achieved, in ms: gaps
    can overlap, and a gap cannot be longer than the audio, so the achieved
    figure is measured over the union rather than multiplied out.
    """
    width = min(max(int(rate * dropout_ms / 1000.0), 1), len(samples))
    out = array.array("h", samples)
    silenced = bytearray(len(samples))
    for _ in range(count):
        if not len(samples):
            break
        start = rng.randrange(0, max(len(samples) - width, 0) + 1)
        for index in range(start, start + width):
            out[index] = 0
            silenced[index] = 1
    return out, round(1000.0 * sum(silenced) / rate, 3)


def _clamp(value: int) -> int:
    """Hold a sample inside the 16-bit range."""
    if value > _INT16_MAX:
        return _INT16_MAX
    if value < _INT16_MIN:
        return _INT16_MIN
    return value


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


def degrade(audio: bytes, config: DegradationConfig) -> DegradationResult:
    """Apply `config` to `audio` and report exactly what happened.

    The input bytes are never modified, and the caller is expected to keep
    them: §8 requires the original artefact to survive, and this function
    returning new bytes rather than writing anything is how that holds
    structurally.

    Raises:
        DegradationError: invalid configuration, or audio that is not
            readable 16-bit PCM WAV.
    """
    config.validate()
    samples, source_rate, source_channels = _decode(audio)

    input_frames = len(samples) // source_channels
    input_duration = input_frames / source_rate

    if config.is_noop:
        # Returning the input unchanged rather than re-encoding it: a
        # round-trip through the WAV writer would produce different bytes for
        # the same audio, which makes "CLEAN is the original" harder to verify
        # than it should be.
        peak = max((abs(value) for value in samples), default=0) / _INT16_MAX
        return DegradationResult(
            audio=audio,
            profile=config.profile,
            transformations=(),
            parameters={},
            seed=config.seed,
            input_sample_rate_hz=source_rate,
            output_sample_rate_hz=source_rate,
            input_channels=source_channels,
            output_channels=source_channels,
            input_duration_seconds=input_duration,
            output_duration_seconds=input_duration,
            input_size_bytes=len(audio),
            output_size_bytes=len(audio),
            peak_amplitude=peak,
            clipped_sample_count=sum(1 for value in samples if abs(value) >= _INT16_MAX),
            applied=False,
        )

    rng = random.Random(config.seed)
    parameters: dict[str, float | int | bool | str | None] = {}
    notes: list[str] = []
    applied: list[Transformation] = []
    channels = source_channels
    rate = source_rate
    clipped = 0

    if config.force_mono:
        samples = _to_mono(samples, channels)
        parameters["from_channels"] = channels
        channels = 1
        applied.append(Transformation.TO_MONO)

    if config.target_sample_rate_hz is not None:
        if channels != 1:
            # Interleaved multi-channel resampling would need per-channel
            # handling; refusing is better than silently mangling the
            # interleaving. Every profile that resamples also forces mono.
            raise DegradationError(
                "resampling is only supported for mono audio; set force_mono "
                f"as well, or supply mono input (this audio has {channels} channels)",
                stage="degradation",
            )
        samples = _resample(samples, source_rate=rate, target_rate=config.target_sample_rate_hz)
        parameters["from_sample_rate_hz"] = rate
        parameters["to_sample_rate_hz"] = config.target_sample_rate_hz
        rate = config.target_sample_rate_hz
        applied.append(Transformation.RESAMPLE)

    if config.bandpass_low_hz is not None or config.bandpass_high_hz is not None:
        samples, band_notes = _bandpass(
            samples, rate=rate, low_hz=config.bandpass_low_hz, high_hz=config.bandpass_high_hz
        )
        notes.extend(band_notes)
        parameters["bandpass_low_hz"] = config.bandpass_low_hz
        parameters["bandpass_high_hz"] = config.bandpass_high_hz
        applied.append(Transformation.BANDPASS)

    if config.snr_db is not None:
        clean = samples
        samples, noise_rms, noise_notes = _add_noise(samples, snr_db=config.snr_db, rng=rng)
        notes.extend(noise_notes)
        parameters["snr_db"] = config.snr_db
        parameters["noise_rms"] = round(noise_rms, 4)
        # Measured from the bytes, not restated from the request: the noise
        # actually added is the difference between the output and its input,
        # clamping included, so a ratio the int16 range could not honour shows.
        achieved = _achieved_snr_db(clean, samples)
        if achieved is not None:
            parameters["snr_db_achieved"] = achieved
        applied.append(Transformation.ADD_NOISE)

    if config.amplitude_scale is not None:
        before = _rms(samples)
        samples = _reduce_amplitude(samples, config.amplitude_scale)
        parameters["amplitude_scale"] = config.amplitude_scale
        after = _rms(samples)
        # Measured, so rounding at very low levels shows rather than hides.
        if before > 0 and after > 0:
            parameters["gain_db_achieved"] = round(20 * math.log10(after / before), 3)
        applied.append(Transformation.REDUCE_AMPLITUDE)

    if config.clip_threshold is not None:
        samples, clipped = _clip(samples, config.clip_threshold)
        parameters["clip_threshold"] = config.clip_threshold
        parameters["clipped_samples"] = clipped
        applied.append(Transformation.CLIP)

    if config.codec is not None:
        if rate != 8000 or channels != 1:
            raise DegradationError(
                f"G.711 is an 8 kHz mono codec; this audio is {rate} Hz with "
                f"{channels} channel(s) at the codec stage. Declare sample_rate_hz 8000",
                stage="degradation",
            )
        samples, sqnr = _codec(samples, config.codec)
        parameters["codec"] = config.codec
        if sqnr is not None and math.isfinite(sqnr):
            parameters["codec_sqnr_db_achieved"] = sqnr
        applied.append(Transformation.CODEC)

    if config.packet_loss_percent > 0:
        samples, dropped, total = _packet_loss(
            samples,
            rate=rate,
            loss_percent=config.packet_loss_percent,
            packet_duration_ms=config.packet_duration_ms,
            rng=rng,
        )
        parameters["packet_loss_percent"] = config.packet_loss_percent
        parameters["packet_duration_ms"] = config.packet_duration_ms
        parameters["packets_total"] = total
        parameters["packets_dropped"] = dropped
        # The realised rate, not just the requested one: with few packets the
        # two differ a lot, and reporting only the request would overstate what
        # the audio actually suffered.
        parameters["packet_loss_realised_percent"] = round(100.0 * dropped / total, 2)
        applied.append(Transformation.PACKET_LOSS)

    if config.jitter_ms > 0:
        if channels != 1:
            raise DegradationError(
                "jitter is only supported for mono audio; set force_mono as well",
                stage="degradation",
            )
        samples, gaps, inserted_ms = _jitter(
            samples,
            rate=rate,
            jitter_ms=config.jitter_ms,
            buffer_ms=config.jitter_buffer_ms,
            packet_duration_ms=config.packet_duration_ms,
            rng=rng,
        )
        parameters["jitter_ms"] = config.jitter_ms
        parameters["jitter_buffer_ms"] = config.jitter_buffer_ms
        parameters["jitter_gaps_inserted"] = gaps
        parameters["jitter_silence_inserted_ms"] = inserted_ms
        if config.jitter_ms <= config.jitter_buffer_ms:
            notes.append(
                f"jitter of up to {config.jitter_ms:g} ms never exceeds the "
                f"{config.jitter_buffer_ms:g} ms buffer, so no gap could be inserted"
            )
        applied.append(Transformation.JITTER)

    if config.dropout_count > 0:
        if channels != 1:
            raise DegradationError(
                "dropouts are only supported for mono audio; set force_mono as well",
                stage="degradation",
            )
        samples, silenced_ms = _dropouts(
            samples, rate=rate, count=config.dropout_count, dropout_ms=config.dropout_ms, rng=rng
        )
        parameters["dropout_count"] = config.dropout_count
        parameters["dropout_ms"] = config.dropout_ms
        parameters["dropout_silenced_ms_achieved"] = silenced_ms
        requested_ms = config.dropout_count * config.dropout_ms
        if silenced_ms < requested_ms:
            notes.append(
                f"{config.dropout_count} dropouts of {config.dropout_ms:g} ms silenced "
                f"{silenced_ms:g} ms, not {requested_ms:g} ms: gaps overlapped or the "
                "audio was shorter than requested"
            )
        applied.append(Transformation.DROPOUT)

    if config.truncate_after_seconds is not None:
        keep = int(config.truncate_after_seconds * rate) * channels
        removed_frames = max(len(samples) - keep, 0) // channels
        if removed_frames:
            samples = samples[:keep]
        else:
            notes.append(
                f"the audio was already shorter than {config.truncate_after_seconds:g} s, "
                "so nothing was truncated"
            )
        parameters["truncate_after_seconds"] = config.truncate_after_seconds
        parameters["truncated_seconds"] = round(removed_frames / rate, 3)
        applied.append(Transformation.TRUNCATE)

    if config.leading_silence_ms > 0 or config.trailing_silence_ms > 0:
        lead = int(rate * config.leading_silence_ms / 1000.0) * channels
        trail = int(rate * config.trailing_silence_ms / 1000.0) * channels
        samples = array.array("h", bytes(lead * 2)) + samples + array.array("h", bytes(trail * 2))
        parameters["leading_silence_ms"] = config.leading_silence_ms
        parameters["trailing_silence_ms"] = config.trailing_silence_ms
        applied.append(Transformation.PAD_SILENCE)

    output = _encode(samples, rate=rate, channels=channels)
    frames = len(samples) // channels
    peak = max((abs(value) for value in samples), default=0) / _INT16_MAX
    at_full_scale = sum(1 for value in samples if abs(value) >= _INT16_MAX)

    return DegradationResult(
        audio=output,
        profile=config.profile,
        transformations=tuple(applied),
        parameters=parameters,
        seed=config.seed,
        input_sample_rate_hz=source_rate,
        output_sample_rate_hz=rate,
        input_channels=source_channels,
        output_channels=channels,
        input_duration_seconds=input_duration,
        output_duration_seconds=frames / rate,
        input_size_bytes=len(audio),
        output_size_bytes=len(output),
        peak_amplitude=peak,
        clipped_sample_count=clipped or at_full_scale,
        parameter_notes=tuple(notes),
    )


__all__ = [
    "MAX_INPUT_BYTES",
    "DegradationConfig",
    "DegradationResult",
    "NoiseProfile",
    "Transformation",
    "degrade",
    "profile_config",
    "with_conditions",
]
