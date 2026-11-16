"""The Phase 7 audio conditions: jitter, dropouts, truncation, silence and gain.

Each is tested alone and in combination, against a generated sine so every
expectation can be computed rather than eyeballed. The rule throughout: an
achieved value is measured from the output bytes, and where it differs from
the request the result says so in `parameter_notes`.
"""

from __future__ import annotations

import array
import io
import math
import wave
from dataclasses import replace

import pytest

from app.pipeline.degradation import DegradationConfig, Transformation, degrade
from app.pipeline.errors import DegradationError

RATE = 8000


def _sine(seconds: float = 1.0, *, rate: int = RATE, amplitude: float = 0.5) -> bytes:
    frames = int(seconds * rate)
    samples = array.array(
        "h",
        (int(32767 * amplitude * math.sin(2 * math.pi * 440 * i / rate)) for i in range(frames)),
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())
    return buffer.getvalue()


def _pcm(audio: bytes) -> array.array:
    with wave.open(io.BytesIO(audio), "rb") as reader:
        return array.array("h", reader.readframes(reader.getnframes()))


SINE = _sine()


class TestJitter:
    def test_gaps_are_inserted_when_delay_exceeds_the_buffer(self) -> None:
        result = degrade(SINE, DegradationConfig(jitter_ms=120, jitter_buffer_ms=20, seed=7))
        assert Transformation.JITTER in result.transformations
        gaps = result.parameters["jitter_gaps_inserted"]
        inserted = result.parameters["jitter_silence_inserted_ms"]
        assert isinstance(gaps, int) and gaps > 0
        # The output is longer by exactly the silence inserted.
        assert result.output_duration_seconds == pytest.approx(
            result.input_duration_seconds + float(inserted) / 1000, abs=1 / RATE
        )

    def test_no_gap_when_jitter_fits_the_buffer_and_the_result_says_so(self) -> None:
        result = degrade(SINE, DegradationConfig(jitter_ms=30, jitter_buffer_ms=40, seed=7))
        assert result.parameters["jitter_gaps_inserted"] == 0
        assert any("never exceeds" in note for note in result.parameter_notes)
        assert result.output_duration_seconds == pytest.approx(result.input_duration_seconds)

    def test_jitter_is_reproducible_and_seed_dependent(self) -> None:
        config = DegradationConfig(jitter_ms=120, jitter_buffer_ms=20, seed=7)
        assert degrade(SINE, config).audio == degrade(SINE, config).audio
        assert degrade(SINE, config).audio != degrade(SINE, replace(config, seed=8)).audio

    def test_jitter_without_a_seed_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="seed"):
            degrade(SINE, DegradationConfig(jitter_ms=50))


class TestDropouts:
    def test_one_dropout_silences_exactly_its_duration(self) -> None:
        result = degrade(SINE, DegradationConfig(dropout_count=1, dropout_ms=100, seed=3))
        assert result.parameters["dropout_silenced_ms_achieved"] == pytest.approx(100.0)
        samples = _pcm(result.audio)
        # A contiguous run of 800 zeros exists (100 ms at 8 kHz). The sine
        # itself crosses zero only on isolated samples.
        longest = run = 0
        for value in samples:
            run = run + 1 if value == 0 else 0
            longest = max(longest, run)
        assert longest >= 800
        assert result.output_duration_seconds == pytest.approx(result.input_duration_seconds)

    def test_overlapping_dropouts_report_the_union_and_say_why(self) -> None:
        short = _sine(0.3)
        result = degrade(short, DegradationConfig(dropout_count=10, dropout_ms=200, seed=3))
        achieved = float(result.parameters["dropout_silenced_ms_achieved"])
        assert achieved <= 300.0 + 1e-6
        assert achieved < 10 * 200
        assert any("not 2000" in note for note in result.parameter_notes)

    def test_dropouts_are_reproducible(self) -> None:
        config = DegradationConfig(dropout_count=3, dropout_ms=50, seed=11)
        assert degrade(SINE, config).audio == degrade(SINE, config).audio

    def test_dropouts_without_a_seed_are_refused(self) -> None:
        with pytest.raises(DegradationError, match="seed"):
            degrade(SINE, DegradationConfig(dropout_count=1))


class TestTruncation:
    def test_audio_is_cut_at_the_requested_time(self) -> None:
        result = degrade(SINE, DegradationConfig(truncate_after_seconds=0.25))
        assert result.output_duration_seconds == pytest.approx(0.25)
        assert result.parameters["truncated_seconds"] == pytest.approx(0.75)

    def test_shorter_audio_is_left_alone_and_the_result_says_so(self) -> None:
        result = degrade(SINE, DegradationConfig(truncate_after_seconds=5))
        assert result.parameters["truncated_seconds"] == 0
        assert any("already shorter" in note for note in result.parameter_notes)


class TestSilencePadding:
    def test_leading_and_trailing_silence_add_exactly(self) -> None:
        result = degrade(SINE, DegradationConfig(leading_silence_ms=250, trailing_silence_ms=500))
        assert result.output_duration_seconds == pytest.approx(1.75)
        samples = _pcm(result.audio)
        assert not any(samples[: int(0.25 * RATE)])
        assert not any(samples[-int(0.5 * RATE) :])
        assert any(samples[int(0.25 * RATE) : int(0.25 * RATE) + 100])


class TestGain:
    @pytest.mark.parametrize("gain_db", [-3.0, -12.0, -24.0])
    def test_the_achieved_gain_is_measured(self, gain_db: float) -> None:
        scale = 10 ** (gain_db / 20)
        result = degrade(SINE, DegradationConfig(amplitude_scale=scale))
        assert result.parameters["gain_db_achieved"] == pytest.approx(gain_db, abs=0.1)


class TestValidation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("jitter_ms", 501),
            ("jitter_ms", -1),
            ("jitter_buffer_ms", 501),
            ("dropout_count", 51),
            ("dropout_ms", 0),
            ("truncate_after_seconds", 0),
            ("leading_silence_ms", 10001),
            ("trailing_silence_ms", -5),
        ],
    )
    def test_out_of_range_values_are_refused(self, field: str, value: float) -> None:
        with pytest.raises(DegradationError, match=field):
            degrade(SINE, replace(DegradationConfig(seed=1), **{field: value}))


class TestCombined:
    CONFIG = DegradationConfig(
        snr_db=15,
        amplitude_scale=0.5,
        clip_threshold=0.3,
        packet_loss_percent=5,
        jitter_ms=100,
        jitter_buffer_ms=40,
        dropout_count=2,
        dropout_ms=80,
        truncate_after_seconds=0.9,
        leading_silence_ms=100,
        trailing_silence_ms=100,
        seed=99,
    )

    def test_every_condition_is_applied_in_the_documented_order(self) -> None:
        result = degrade(SINE, self.CONFIG)
        assert result.transformations == (
            Transformation.ADD_NOISE,
            Transformation.REDUCE_AMPLITUDE,
            Transformation.CLIP,
            Transformation.PACKET_LOSS,
            Transformation.JITTER,
            Transformation.DROPOUT,
            Transformation.TRUNCATE,
            Transformation.PAD_SILENCE,
        )
        assert result.transformations == self.CONFIG.planned_transformations()

    def test_the_combination_is_byte_reproducible(self) -> None:
        assert degrade(SINE, self.CONFIG).audio == degrade(SINE, self.CONFIG).audio

    def test_the_original_is_never_modified(self) -> None:
        before = bytes(SINE)
        degrade(SINE, self.CONFIG)
        assert before == SINE

    def test_truncation_then_padding_fixes_the_final_length(self) -> None:
        result = degrade(SINE, self.CONFIG)
        assert result.output_duration_seconds == pytest.approx(0.9 + 0.2, abs=1 / RATE)


class TestCodec:
    """G.711 is implemented exactly, so it is tested against its code table."""

    def test_every_ulaw_code_round_trips(self) -> None:
        from app.pipeline.degradation import _ulaw_decode, _ulaw_encode

        # 0x7F is mu-law's negative zero; it decodes to 0, which encodes as 0xFF.
        assert all(_ulaw_encode(_ulaw_decode(c)) == c for c in range(256) if c != 0x7F)
        assert (_ulaw_encode(0), _ulaw_decode(0x80), _ulaw_decode(0x00)) == (0xFF, 32124, -32124)

    def test_every_alaw_code_round_trips(self) -> None:
        from app.pipeline.degradation import _alaw_decode, _alaw_encode

        assert all(_alaw_encode(_alaw_decode(c)) == c for c in range(256))
        assert (_alaw_encode(0), _alaw_decode(0xAA), _alaw_decode(0x2A)) == (0xD5, 32256, -32256)

    @pytest.mark.parametrize("codec", ["g711_ulaw", "g711_alaw"])
    def test_the_quantisation_snr_is_measured_and_plausible(self, codec: str) -> None:
        result = degrade(SINE, DegradationConfig(codec=codec))
        assert Transformation.CODEC in result.transformations
        assert 30.0 < float(result.parameters["codec_sqnr_db_achieved"]) < 45.0
        assert result.audio != SINE

    def test_a_non_8khz_input_is_refused_rather_than_misrepresented(self) -> None:
        with pytest.raises(DegradationError, match="8 kHz"):
            degrade(_sine(rate=16000), DegradationConfig(codec="g711_ulaw"))

    def test_an_unknown_codec_is_refused(self) -> None:
        with pytest.raises(DegradationError, match="codec"):
            degrade(SINE, DegradationConfig(codec="opus"))

    def test_with_conditions_converts_to_8khz_for_the_codec(self) -> None:
        from app.pipeline.degradation import with_conditions

        config = with_conditions(DegradationConfig(), {"codec": "g711_alaw"})
        assert (config.codec, config.target_sample_rate_hz, config.force_mono) == (
            "g711_alaw",
            8000,
            True,
        )
        result = degrade(_sine(rate=16000), config)
        assert result.output_sample_rate_hz == 8000
