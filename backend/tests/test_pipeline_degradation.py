"""The audio degradation engine: the DSP, the profiles and the record it keeps.

Pure functions over real WAV bytes. No database and no providers, so these are
fast and they are where the arithmetic is actually pinned down - including the
one quantitative claim the engine makes, that a requested signal-to-noise ratio
is the ratio actually delivered.
"""

from __future__ import annotations

import array
import io
import math
import wave

import pytest

from app.pipeline.degradation import (
    MAX_INPUT_BYTES,
    DegradationConfig,
    NoiseProfile,
    Transformation,
    degrade,
    profile_config,
)
from app.pipeline.errors import DegradationError

_INT16_MAX = 32767


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tone(
    *,
    seconds: float = 0.5,
    rate: int = 16000,
    channels: int = 1,
    hz: float = 440.0,
    amplitude: float = 0.3,
) -> bytes:
    """A sine tone as 16-bit PCM WAV.

    Generated rather than loaded from a fixture so a test can ask for any rate
    or channel count. Contains no speech, which is why nothing here claims
    anything about recognition.
    """
    frames = int(rate * seconds)
    samples = array.array("h")
    for index in range(frames):
        value = int(amplitude * _INT16_MAX * math.sin(2 * math.pi * hz * index / rate))
        for _ in range(channels):
            samples.append(value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


def _read(audio: bytes) -> tuple[array.array, int, int]:
    with wave.open(io.BytesIO(audio), "rb") as handle:
        samples = array.array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
        return samples, handle.getframerate(), handle.getnchannels()


def _rms(samples: array.array) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(value * value for value in samples) / len(samples))


# ---------------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_a_default_configuration_is_valid(self) -> None:
        DegradationConfig().validate()

    def test_noise_without_a_seed_is_refused(self) -> None:
        """The reproducibility rule, enforced rather than documented: an
        artefact nobody can reproduce is not evidence."""
        with pytest.raises(DegradationError, match="a seed is required"):
            DegradationConfig(snr_db=15.0).validate()

    def test_packet_loss_without_a_seed_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="a seed is required"):
            DegradationConfig(packet_loss_percent=5.0).validate()

    def test_a_seeded_stochastic_configuration_is_accepted(self) -> None:
        DegradationConfig(snr_db=15.0, packet_loss_percent=5.0, seed=1).validate()

    @pytest.mark.parametrize("rate", [100, 3999, 48001, 96000])
    def test_an_implausible_sample_rate_is_refused(self, rate: int) -> None:
        with pytest.raises(DegradationError, match="target_sample_rate_hz"):
            DegradationConfig(target_sample_rate_hz=rate).validate()

    @pytest.mark.parametrize("threshold", [0.0, -0.5, 1.5])
    def test_an_out_of_range_clip_threshold_is_refused(self, threshold: float) -> None:
        with pytest.raises(DegradationError, match="clip_threshold"):
            DegradationConfig(clip_threshold=threshold).validate()

    @pytest.mark.parametrize("scale", [0.0, -1.0, 2.0])
    def test_an_out_of_range_amplitude_is_refused(self, scale: float) -> None:
        with pytest.raises(DegradationError, match="amplitude_scale"):
            DegradationConfig(amplitude_scale=scale).validate()

    @pytest.mark.parametrize("percent", [-1.0, 101.0])
    def test_an_out_of_range_loss_percentage_is_refused(self, percent: float) -> None:
        with pytest.raises(DegradationError, match="packet_loss_percent"):
            DegradationConfig(packet_loss_percent=percent, seed=1).validate()

    def test_an_inverted_bandpass_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="must be below"):
            DegradationConfig(bandpass_low_hz=3000.0, bandpass_high_hz=300.0).validate()

    def test_every_violation_is_reported_at_once(self) -> None:
        with pytest.raises(DegradationError) as caught:
            DegradationConfig(clip_threshold=5.0, amplitude_scale=-1.0, snr_db=10.0).validate()
        message = str(caught.value)
        assert "clip_threshold" in message
        assert "amplitude_scale" in message
        assert "seed is required" in message

    def test_the_transformation_order_is_fixed(self) -> None:
        """Channel reduction, rate, filter, noise, level, clip, loss - the
        order a real path would apply them in."""
        config = DegradationConfig(
            force_mono=True,
            target_sample_rate_hz=8000,
            bandpass_low_hz=300.0,
            bandpass_high_hz=3400.0,
            snr_db=20.0,
            amplitude_scale=0.8,
            clip_threshold=0.9,
            packet_loss_percent=1.0,
            seed=1,
        )
        assert config.planned_transformations() == (
            Transformation.TO_MONO,
            Transformation.RESAMPLE,
            Transformation.BANDPASS,
            Transformation.ADD_NOISE,
            Transformation.REDUCE_AMPLITUDE,
            Transformation.CLIP,
            Transformation.PACKET_LOSS,
        )

    def test_an_empty_configuration_is_a_noop(self) -> None:
        assert DegradationConfig().is_noop


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------


class TestInputHandling:
    def test_empty_audio_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="empty audio payload"):
            degrade(b"", DegradationConfig(force_mono=True))

    def test_audio_that_is_not_wav_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="could not be read as a WAV"):
            degrade(b"this is not audio at all", DegradationConfig(force_mono=True))

    def test_a_truncated_wav_is_refused(self) -> None:
        with pytest.raises(DegradationError):
            degrade(_tone()[:20], DegradationConfig(force_mono=True))

    def test_a_header_with_no_frames_is_refused(self) -> None:
        """A valid header over nothing is not usable audio."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"")
        with pytest.raises(DegradationError, match="no audio frames"):
            degrade(buffer.getvalue(), DegradationConfig(force_mono=True))

    def test_eight_bit_audio_is_refused_rather_than_guessed_at(self) -> None:
        """No decoder is available to convert it, and processing it as 16-bit
        would silently produce noise."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(1)
            handle.setframerate(8000)
            handle.writeframes(bytes(800))
        with pytest.raises(DegradationError, match="only 16-bit PCM"):
            degrade(buffer.getvalue(), DegradationConfig(force_mono=True))

    def test_an_oversized_payload_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="limit for degradation"):
            degrade(b"RIFF" + bytes(MAX_INPUT_BYTES), DegradationConfig(force_mono=True))

    def test_a_noop_returns_the_input_bytes_unchanged(self) -> None:
        """Not a re-encode: a round trip through the WAV writer would produce
        different bytes for the same audio, which makes "CLEAN is the original"
        harder to verify than it should be."""
        source = _tone()
        result = degrade(source, DegradationConfig())
        assert result.audio == source
        assert result.applied is False
        assert result.transformations == ()


# ---------------------------------------------------------------------------
# Individual transformations
# ---------------------------------------------------------------------------


class TestResampling:
    def test_downsampling_halves_the_frame_count(self) -> None:
        source = _tone(seconds=1.0, rate=16000)
        result = degrade(source, DegradationConfig(target_sample_rate_hz=8000))
        samples, rate, channels = _read(result.audio)
        assert rate == 8000
        assert channels == 1
        assert len(samples) == pytest.approx(8000, abs=2)

    def test_upsampling_doubles_the_frame_count(self) -> None:
        result = degrade(
            _tone(seconds=0.5, rate=8000), DegradationConfig(target_sample_rate_hz=16000)
        )
        samples, rate, _ = _read(result.audio)
        assert rate == 16000
        assert len(samples) == pytest.approx(8000, abs=2)

    def test_the_duration_is_preserved(self) -> None:
        """Resampling changes the rate, not how long the speech lasts."""
        result = degrade(
            _tone(seconds=1.0, rate=16000), DegradationConfig(target_sample_rate_hz=8000)
        )
        assert result.input_duration_seconds == pytest.approx(1.0, abs=0.01)
        assert result.output_duration_seconds == pytest.approx(1.0, abs=0.01)

    def test_resampling_to_the_same_rate_changes_nothing(self) -> None:
        source = _tone(rate=8000)
        result = degrade(source, DegradationConfig(target_sample_rate_hz=8000))
        assert _read(result.audio)[0] == _read(source)[0]

    def test_the_rates_are_recorded(self) -> None:
        result = degrade(_tone(rate=16000), DegradationConfig(target_sample_rate_hz=8000))
        assert result.input_sample_rate_hz == 16000
        assert result.output_sample_rate_hz == 8000
        assert result.parameters["from_sample_rate_hz"] == 16000
        assert result.parameters["to_sample_rate_hz"] == 8000

    def test_resampling_stereo_without_mono_conversion_is_refused(self) -> None:
        """Rather than mangling the interleaving silently. Every profile that
        resamples also forces mono."""
        with pytest.raises(DegradationError, match="only supported for mono"):
            degrade(_tone(channels=2), DegradationConfig(target_sample_rate_hz=8000))


class TestChannelConversion:
    def test_stereo_becomes_mono(self) -> None:
        result = degrade(_tone(channels=2, seconds=0.5), DegradationConfig(force_mono=True))
        samples, _, channels = _read(result.audio)
        assert channels == 1
        assert result.input_channels == 2
        assert result.output_channels == 1
        assert len(samples) == pytest.approx(8000, abs=2)

    def test_mono_stays_mono(self) -> None:
        result = degrade(_tone(channels=1), DegradationConfig(force_mono=True))
        assert _read(result.audio)[2] == 1


class TestBandpass:
    def test_a_low_tone_survives_a_high_pass_above_it_poorly(self) -> None:
        """A 100 Hz tone through a 1000 Hz high-pass should lose most of its
        energy - which is what makes the filter a filter."""
        source = _tone(hz=100.0, rate=16000, seconds=0.5)
        result = degrade(source, DegradationConfig(bandpass_low_hz=1000.0))
        assert _rms(_read(result.audio)[0]) < _rms(_read(source)[0]) * 0.5

    def test_a_tone_inside_the_band_largely_survives(self) -> None:
        source = _tone(hz=1000.0, rate=16000, seconds=0.5)
        result = degrade(source, DegradationConfig(bandpass_low_hz=300.0, bandpass_high_hz=3400.0))
        assert _rms(_read(result.audio)[0]) > _rms(_read(source)[0]) * 0.4

    def test_a_high_tone_is_attenuated_by_a_low_pass_below_it(self) -> None:
        source = _tone(hz=6000.0, rate=16000, seconds=0.5)
        result = degrade(source, DegradationConfig(bandpass_high_hz=1000.0))
        assert _rms(_read(result.audio)[0]) < _rms(_read(source)[0]) * 0.5

    def test_a_band_edge_above_nyquist_is_reported_not_silently_kept(self) -> None:
        """A report that kept the requested figure would be describing audio
        that was never produced."""
        result = degrade(_tone(rate=8000), DegradationConfig(bandpass_high_hz=9000.0))
        assert result.parameter_notes
        assert "Nyquist" in result.parameter_notes[0]

    def test_the_band_edges_are_recorded(self) -> None:
        result = degrade(
            _tone(rate=16000),
            DegradationConfig(bandpass_low_hz=300.0, bandpass_high_hz=3400.0),
        )
        assert result.parameters["bandpass_low_hz"] == 300.0
        assert result.parameters["bandpass_high_hz"] == 3400.0


class TestNoise:
    @pytest.mark.parametrize("target", [30.0, 25.0, 20.0, 15.0, 10.0, 7.0, 5.0])
    def test_the_requested_snr_is_the_snr_delivered(self, target: float) -> None:
        """The engine's one quantitative claim, measured rather than asserted.

        The noise is isolated by subtracting the clean signal from the noisy
        one, so this is the real achieved ratio and not a restatement of the
        parameter.
        """
        source = _tone(seconds=1.0, rate=8000)
        result = degrade(source, DegradationConfig(snr_db=target, seed=42))
        clean, _, _ = _read(source)
        noisy, _, _ = _read(result.audio)
        noise = array.array("h", [n - c for c, n in zip(clean, noisy, strict=True)])
        achieved = 20 * math.log10(_rms(clean) / _rms(noise))
        assert achieved == pytest.approx(target, abs=0.5)

    def test_noise_raises_the_signal_rms(self) -> None:
        source = _tone(seconds=0.5, rate=8000)
        result = degrade(source, DegradationConfig(snr_db=5.0, seed=1))
        assert _rms(_read(result.audio)[0]) > _rms(_read(source)[0])

    def test_the_noise_level_is_recorded(self) -> None:
        result = degrade(_tone(rate=8000), DegradationConfig(snr_db=20.0, seed=1))
        assert result.parameters["snr_db"] == 20.0
        assert result.parameters["noise_rms"] > 0

    def test_silent_audio_gets_no_noise_and_says_so(self) -> None:
        """The SNR is undefined against silence, so the honest answer is to
        add nothing and record why rather than divide by zero."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(bytes(1600))
        result = degrade(buffer.getvalue(), DegradationConfig(snr_db=10.0, seed=1))
        assert any("silent" in note for note in result.parameter_notes)


class TestAmplitudeAndClipping:
    def test_amplitude_reduction_scales_the_signal(self) -> None:
        source = _tone(seconds=0.5, rate=8000)
        result = degrade(source, DegradationConfig(amplitude_scale=0.5))
        assert _rms(_read(result.audio)[0]) == pytest.approx(_rms(_read(source)[0]) * 0.5, rel=0.02)

    def test_clipping_caps_the_peak(self) -> None:
        result = degrade(_tone(amplitude=0.9, rate=8000), DegradationConfig(clip_threshold=0.2))
        assert result.peak_amplitude == pytest.approx(0.2, abs=0.01)

    def test_clipping_counts_the_samples_it_clipped(self) -> None:
        result = degrade(
            _tone(amplitude=0.9, rate=8000, seconds=0.5),
            DegradationConfig(clip_threshold=0.2),
        )
        assert result.clipped_sample_count > 0
        assert result.parameters["clipped_samples"] == result.clipped_sample_count

    def test_clipping_above_the_signal_peak_clips_nothing(self) -> None:
        result = degrade(_tone(amplitude=0.1, rate=8000), DegradationConfig(clip_threshold=0.9))
        assert result.clipped_sample_count == 0

    def test_unintended_clipping_is_visible_without_being_configured(self) -> None:
        """A level problem should be legible in the record rather than
        inferred by listening."""
        result = degrade(_tone(amplitude=0.1, rate=8000), DegradationConfig(force_mono=True))
        assert result.peak_amplitude == pytest.approx(0.1, abs=0.01)
        assert result.clipped_sample_count == 0


class TestPacketLoss:
    def test_total_loss_silences_the_audio(self) -> None:
        result = degrade(
            _tone(seconds=0.5, rate=8000),
            DegradationConfig(packet_loss_percent=100.0, seed=1),
        )
        assert _rms(_read(result.audio)[0]) == 0.0

    def test_no_loss_leaves_the_audio_alone(self) -> None:
        source = _tone(seconds=0.5, rate=8000)
        result = degrade(source, DegradationConfig(packet_loss_percent=0.0, seed=1))
        assert result.transformations == ()

    def test_partial_loss_removes_some_energy(self) -> None:
        source = _tone(seconds=2.0, rate=8000)
        result = degrade(source, DegradationConfig(packet_loss_percent=50.0, seed=7))
        assert 0 < _rms(_read(result.audio)[0]) < _rms(_read(source)[0])

    def test_whole_packets_are_dropped_not_scattered_samples(self) -> None:
        """Loss on a real network discards a datagram carrying 20 ms of audio;
        scattered samples would sound like crackle, not like a gap."""
        result = degrade(
            _tone(seconds=1.0, rate=8000),
            DegradationConfig(packet_loss_percent=50.0, packet_duration_ms=20.0, seed=3),
        )
        samples, _, _ = _read(result.audio)
        # A 20 ms packet at 8 kHz is 160 samples; find the longest zero run.
        longest = current = 0
        for value in samples:
            current = current + 1 if value == 0 else 0
            longest = max(longest, current)
        assert longest >= 160

    def test_the_realised_loss_rate_is_recorded_alongside_the_requested_one(
        self,
    ) -> None:
        """With few packets the two differ a lot, and reporting only the
        request would overstate what the audio actually suffered."""
        result = degrade(
            _tone(seconds=1.0, rate=8000),
            DegradationConfig(packet_loss_percent=30.0, seed=5),
        )
        assert result.parameters["packet_loss_percent"] == 30.0
        assert "packet_loss_realised_percent" in result.parameters
        assert result.parameters["packets_total"] > 0


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    @pytest.mark.parametrize("profile", list(NoiseProfile))
    def test_the_same_seed_gives_byte_identical_output(self, profile: NoiseProfile) -> None:
        source = _tone(seconds=0.5, rate=16000)
        first = degrade(source, profile_config(profile, seed=1234))
        second = degrade(source, profile_config(profile, seed=1234))
        assert first.audio == second.audio

    def test_a_different_seed_gives_different_output(self) -> None:
        source = _tone(seconds=0.5, rate=16000)
        first = degrade(source, profile_config(NoiseProfile.HEAVY_BACKGROUND_NOISE, seed=1))
        second = degrade(source, profile_config(NoiseProfile.HEAVY_BACKGROUND_NOISE, seed=2))
        assert first.audio != second.audio

    def test_the_seed_is_recorded_with_the_result(self) -> None:
        result = degrade(
            _tone(rate=8000), profile_config(NoiseProfile.MODERATE_BACKGROUND_NOISE, seed=77)
        )
        assert result.seed == 77

    def test_the_input_is_never_modified(self) -> None:
        """§8 requires the original artefact to survive, and this function
        returning new bytes rather than writing anything is how that holds."""
        source = _tone(seconds=0.5, rate=16000)
        before = bytes(source)
        degrade(source, profile_config(NoiseProfile.HEAVY_BACKGROUND_NOISE, seed=1))
        assert source == before


# ---------------------------------------------------------------------------
# Named profiles
# ---------------------------------------------------------------------------


class TestProfiles:
    def test_clean_applies_nothing(self) -> None:
        config = profile_config(NoiseProfile.CLEAN)
        assert config.is_noop
        assert config.snr_db is None

    def test_telephony_band_limits_without_adding_noise(self) -> None:
        config = profile_config(NoiseProfile.TELEPHONY_BANDWIDTH)
        assert config.target_sample_rate_hz == 8000
        assert config.bandpass_low_hz == 300.0
        assert config.bandpass_high_hz == 3400.0
        assert config.snr_db is None

    @pytest.mark.parametrize(
        ("profile", "snr"),
        [
            (NoiseProfile.LIGHT_BACKGROUND_NOISE, 25.0),
            (NoiseProfile.MODERATE_BACKGROUND_NOISE, 15.0),
            (NoiseProfile.HEAVY_BACKGROUND_NOISE, 7.0),
        ],
    )
    def test_each_noise_profile_has_its_documented_ratio(
        self, profile: NoiseProfile, snr: float
    ) -> None:
        assert profile_config(profile, seed=1).snr_db == snr

    def test_the_noise_profiles_sit_on_the_telephony_channel(self) -> None:
        """Noise on a wideband studio recording is not the condition being
        simulated."""
        for profile in (
            NoiseProfile.LIGHT_BACKGROUND_NOISE,
            NoiseProfile.MODERATE_BACKGROUND_NOISE,
            NoiseProfile.HEAVY_BACKGROUND_NOISE,
        ):
            config = profile_config(profile, seed=1)
            assert config.target_sample_rate_hz == 8000
            assert config.force_mono
            assert config.bandpass_low_hz == 300.0

    def test_the_profiles_are_ordered_by_severity(self) -> None:
        """Heavier profiles must actually degrade more, or the names lie."""
        source = _tone(seconds=1.0, rate=16000)
        ratios = []
        for profile in (
            NoiseProfile.LIGHT_BACKGROUND_NOISE,
            NoiseProfile.MODERATE_BACKGROUND_NOISE,
            NoiseProfile.HEAVY_BACKGROUND_NOISE,
        ):
            result = degrade(source, profile_config(profile, seed=11))
            ratios.append(result.parameters["noise_rms"])
        assert ratios == sorted(ratios), ratios

    @pytest.mark.parametrize("profile", list(NoiseProfile))
    def test_every_profile_produces_readable_wav(self, profile: NoiseProfile) -> None:
        result = degrade(_tone(seconds=0.5, rate=16000), profile_config(profile, seed=9))
        samples, rate, channels = _read(result.audio)
        assert samples
        assert rate > 0
        assert channels == 1

    @pytest.mark.parametrize("profile", list(NoiseProfile))
    def test_every_profile_records_what_it_did(self, profile: NoiseProfile) -> None:
        result = degrade(_tone(seconds=0.5, rate=16000), profile_config(profile, seed=9))
        assert result.profile is profile
        assert result.output_size_bytes > 0
        assert result.input_size_bytes > 0
        assert result.output_duration_seconds > 0
        if profile is not NoiseProfile.CLEAN:
            assert result.transformations
            assert result.parameters

    def test_no_profile_silences_the_audio(self) -> None:
        """Degradation is meant to make recognition harder, not impossible;
        a profile that produced silence would be measuring nothing."""
        source = _tone(seconds=1.0, rate=16000)
        for profile in NoiseProfile:
            result = degrade(source, profile_config(profile, seed=3))
            assert _rms(_read(result.audio)[0]) > 0, profile

    def test_no_profile_simulates_packet_loss(self) -> None:
        """Documented rather than assumed: loss is configurable but no named
        profile applies it, so a profile name never implies a lossy network."""
        for profile in NoiseProfile:
            assert profile_config(profile, seed=1).packet_loss_percent == 0.0
