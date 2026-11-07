"""Audio validation, domain models, the retry policy and the registry.

No network and no database: everything here is pure logic or the offline fake.

Async code is driven with `asyncio.run` rather than `pytest-asyncio`. That
avoids a plugin whose configuration would have to be duplicated into both
`pyproject.toml` and `backend/pytest.ini` - and `tests/test_tooling.py`
requires those two to stay in lockstep.
"""

from __future__ import annotations

import asyncio
import wave
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path

import pytest

from app.core.config import AppEnv, Settings
from app.core.languages import SUPPORTED_CODES
from app.transcription import audio as audio_tools
from app.transcription.errors import (
    AudioTooLargeError,
    AuthenticationError,
    ConfigurationError,
    InvalidAudioError,
    ProviderUnavailableError,
    RateLimitError,
    TranscriptionError,
    TranscriptionTimeoutError,
    UnsupportedFormatError,
)
from app.transcription.models import (
    AudioEncoding,
    TranscriptionMode,
    TranscriptionResult,
)
from app.transcription.providers import prisma_contract as contract
from app.transcription.providers.fake import (
    FakeScript,
    FakeTranscriptionProvider,
    auth_failure,
    rate_limit_failure,
    unavailable_failure,
)
from app.transcription.providers.prisma import PROVIDER_NAME as PRISMA_NAME
from app.transcription.registry import (
    available_providers,
    build_provider,
    describe_providers,
)
from app.transcription.retry import RetryPolicy, call_with_retry


def _wav(*, sample_rate: int = 8000, channels: int = 1, frames: int = 800) -> bytes:
    """Build a tiny WAV in memory, for cases a committed fixture does not cover."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames * channels)
    return buffer.getvalue()


def _streaming_wav(
    *,
    frames: int,
    sample_rate: int = 8000,
    channels: int = 1,
    width: int = 2,
    data_size: int = 0xFFFFFFFF,
) -> bytes:
    """Build a WAV whose size fields say "length unknown".

    Written by hand rather than with the stdlib `wave` writer, because that
    writer always back-fills the real length - which is precisely why this
    header shape never showed up in an offline fixture.
    """
    import struct

    samples = bytes([0x00, 0x01]) * frames * channels
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack(
            "<IHHIIHH",
            16,
            1,
            channels,
            sample_rate,
            sample_rate * channels * width,
            channels * width,
            width * 8,
        )
        + b"data"
        + struct.pack("<I", data_size)
        + samples
    )
    # A sentinel data size goes with a sentinel RIFF size; a zero data size
    # does not, or `wave` cannot find the WAVE chunk at all.
    riff_size = 0xFFFFFFFF if data_size == 0xFFFFFFFF else len(body)
    return b"RIFF" + struct.pack("<I", riff_size) + body


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


class TestFormatDetection:
    """Content decides the format. A declaration is a hint, never evidence."""

    def test_detects_wav_from_riff_header(self, wav_8k: bytes) -> None:
        assert audio_tools.detect_encoding(wav_8k) is AudioEncoding.WAV

    @pytest.mark.parametrize(
        ("signature", "expected"),
        [
            (b"fLaC\x00\x00\x00\x22", AudioEncoding.FLAC),
            (b"OggS\x00\x02\x00\x00", AudioEncoding.OGG),
            (b"\x00\x00\x00\x20ftypM4A ", AudioEncoding.M4A),
            (b"ID3\x04\x00\x00\x00\x00", AudioEncoding.MP3),
            (b"\xff\xfb\x90\x00", AudioEncoding.MP3),
            (b"\xff\xf1\x50\x80", AudioEncoding.AAC),
        ],
    )
    def test_detects_each_container(self, signature: bytes, expected: AudioEncoding) -> None:
        assert audio_tools.detect_encoding(signature) is expected

    def test_html_masquerading_as_wav_is_not_detected_as_audio(self, audio_fixtures: Path) -> None:
        """The attack this check exists for: a `.wav` name on an error page."""
        payload = (audio_fixtures / "not_audio.wav").read_bytes()
        assert audio_tools.detect_encoding(payload) is None

    def test_too_short_to_identify_returns_none(self) -> None:
        assert audio_tools.detect_encoding(b"\xff") is None

    def test_raw_pcm_cannot_be_detected_only_declared(self, raw_pcm_8k: bytes) -> None:
        """Headerless audio has nothing to sniff, by definition."""
        assert audio_tools.detect_encoding(raw_pcm_8k) is None


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


class TestInspection:
    def test_reads_wav_header_fields(self, wav_8k: bytes) -> None:
        metadata = audio_tools.inspect(wav_8k)
        assert metadata.encoding is AudioEncoding.WAV
        assert metadata.sample_rate_hz == 8000
        assert metadata.channels == 1
        assert metadata.bit_depth == 16
        assert metadata.duration_seconds == pytest.approx(1.0)

    def test_rejects_empty_payload(self) -> None:
        with pytest.raises(InvalidAudioError, match="empty"):
            audio_tools.inspect(b"")

    def test_rejects_unidentifiable_content(self, audio_fixtures: Path) -> None:
        payload = (audio_fixtures / "not_audio.wav").read_bytes()
        with pytest.raises(UnsupportedFormatError, match="could not be identified"):
            audio_tools.inspect(payload)

    def test_reports_a_truncated_wav_as_invalid_not_unsupported(self, audio_fixtures: Path) -> None:
        """A damaged file of a supported format is a different mistake."""
        payload = (audio_fixtures / "truncated.wav").read_bytes()
        with pytest.raises(InvalidAudioError):
            audio_tools.inspect(payload)

    def test_a_declaration_contradicting_the_content_is_rejected(self, wav_8k: bytes) -> None:
        with pytest.raises(UnsupportedFormatError, match="not trusted over the content"):
            audio_tools.inspect(wav_8k, declared=AudioEncoding.MP3)

    def test_raw_pcm_requires_a_declared_sample_rate(self, raw_pcm_8k: bytes) -> None:
        with pytest.raises(InvalidAudioError, match="sample_rate_hz must be supplied"):
            audio_tools.inspect(raw_pcm_8k, declared=AudioEncoding.PCM_S16LE)

    def test_raw_pcm_duration_comes_from_the_declared_rate(self, raw_pcm_8k: bytes) -> None:
        metadata = audio_tools.inspect(
            raw_pcm_8k, declared=AudioEncoding.PCM_S16LE, sample_rate_hz=8000
        )
        assert metadata.duration_seconds == pytest.approx(0.5)
        assert metadata.channels == 1
        assert metadata.bit_depth == 16

    def test_odd_length_raw_pcm_is_rejected(self) -> None:
        """16-bit samples cannot be half present."""
        with pytest.raises(InvalidAudioError, match="odd length"):
            audio_tools.inspect(
                b"\x00\x00\x00", declared=AudioEncoding.PCM_S16LE, sample_rate_hz=8000
            )

    def test_a_streaming_wav_header_is_accepted_and_measured_from_its_bytes(self) -> None:
        """A writer that does not know the final length puts `0xFFFFFFFF` in the
        RIFF and `data` size fields. That is ordinary, valid WAV - and the
        truncation check above used to reject it.

        Found by the first live Gnani Timbre call, not by any mock: a fixture
        built with the stdlib `wave` writer always knows its own length, so no
        amount of offline testing produces this header.
        """
        metadata = audio_tools.inspect(_streaming_wav(frames=35200, sample_rate=8000))
        assert metadata.encoding is AudioEncoding.WAV
        assert metadata.sample_rate_hz == 8000
        assert metadata.channels == 1
        assert metadata.bit_depth == 16
        # Measured from the bytes present, not from the sentinel.
        assert metadata.duration_seconds == pytest.approx(4.4)

    @pytest.mark.parametrize(
        ("sample_rate", "channels", "frames"),
        [(8000, 1, 8000), (16000, 1, 1600), (48000, 2, 4800), (22050, 1, 2205)],
    )
    def test_a_streaming_header_is_measured_at_any_rate_or_channel_count(
        self, sample_rate: int, channels: int, frames: int
    ) -> None:
        """The sentinel check works in bytes, so it must not depend on the
        block alignment."""
        metadata = audio_tools.inspect(
            _streaming_wav(frames=frames, sample_rate=sample_rate, channels=channels)
        )
        assert metadata.sample_rate_hz == sample_rate
        assert metadata.channels == channels
        assert metadata.duration_seconds == pytest.approx(frames / sample_rate)

    def test_a_zero_length_data_chunk_is_accepted_without_a_duration(self) -> None:
        """The other streaming convention. Rate and channels are readable; the
        length is not, so none is claimed rather than one being invented."""
        metadata = audio_tools.inspect(_streaming_wav(frames=4000, data_size=0))
        assert metadata.sample_rate_hz == 8000
        assert metadata.channels == 1
        assert metadata.duration_seconds is None

    def test_a_truncated_file_is_still_rejected_despite_the_sentinel_allowance(
        self, audio_fixtures: Path
    ) -> None:
        """The allowance must not have reopened the hole it sits next to: a
        *plausible* declared length with bytes missing is still a damaged file.
        """
        payload = (audio_fixtures / "truncated.wav").read_bytes()
        with pytest.raises(InvalidAudioError, match="truncated"):
            audio_tools.inspect(payload)

    def test_compressed_containers_report_size_but_not_duration(self) -> None:
        """Duration would need decoding, which this phase deliberately avoids."""
        metadata = audio_tools.inspect(b"ID3\x04\x00\x00\x00\x00" + b"\x00" * 64)
        assert metadata.encoding is AudioEncoding.MP3
        assert metadata.duration_seconds is None
        assert metadata.sample_rate_hz is None


# ---------------------------------------------------------------------------
# Validation limits
# ---------------------------------------------------------------------------


class TestValidation:
    def test_accepts_audio_within_every_limit(self, wav_8k: bytes) -> None:
        metadata = audio_tools.validate(
            wav_8k,
            accepted=contract.BATCH_ENCODINGS,
            max_bytes=1_000_000,
            accepted_sample_rates=frozenset({8000, 16000}),
            max_channels=1,
        )
        assert metadata.encoding is AudioEncoding.WAV

    def test_rejects_oversized_audio_before_inspecting_it(self, wav_8k: bytes) -> None:
        """Size is the cheapest check and bounds the cost of the rest."""
        with pytest.raises(AudioTooLargeError, match="exceeds"):
            audio_tools.validate(wav_8k, accepted=contract.BATCH_ENCODINGS, max_bytes=10)

    def test_rejects_an_encoding_the_provider_does_not_accept(self, raw_pcm_8k: bytes) -> None:
        with pytest.raises(UnsupportedFormatError, match="not accepted"):
            audio_tools.validate(
                raw_pcm_8k,
                accepted=contract.BATCH_ENCODINGS,
                max_bytes=1_000_000,
                declared=AudioEncoding.PCM_S16LE,
                sample_rate_hz=8000,
            )

    def test_rejects_an_unaccepted_sample_rate(self) -> None:
        with pytest.raises(UnsupportedFormatError, match="sample rate"):
            audio_tools.validate(
                _wav(sample_rate=22050),
                accepted=contract.BATCH_ENCODINGS,
                max_bytes=1_000_000,
                accepted_sample_rates=frozenset({8000, 16000}),
            )

    def test_rejects_stereo_rather_than_downmixing_it(self, audio_fixtures: Path) -> None:
        """Downmixing would change the signal under test; that is Phase 7's job."""
        payload = (audio_fixtures / "tone_8k_stereo.wav").read_bytes()
        with pytest.raises(UnsupportedFormatError, match="channels"):
            audio_tools.validate(
                payload,
                accepted=contract.BATCH_ENCODINGS,
                max_bytes=1_000_000,
                max_channels=1,
            )

    def test_rejects_audio_longer_than_the_duration_limit(self, wav_8k: bytes) -> None:
        with pytest.raises(AudioTooLargeError, match="long"):
            audio_tools.validate(
                wav_8k,
                accepted=contract.BATCH_ENCODINGS,
                max_bytes=1_000_000,
                max_duration_seconds=0.5,
            )

    def test_a_duration_limit_is_not_enforced_when_duration_is_unknown(self) -> None:
        """An MP3's length is not readable without decoding, so it passes."""
        metadata = audio_tools.validate(
            b"ID3\x04\x00\x00\x00\x00" + b"\x00" * 64,
            accepted=contract.BATCH_ENCODINGS,
            max_bytes=1_000_000,
            max_duration_seconds=0.001,
        )
        assert metadata.duration_seconds is None


# ---------------------------------------------------------------------------
# Filename safety
# ---------------------------------------------------------------------------


class TestSafeFilename:
    """An upload's filename is attacker-controlled and reaches logs."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam",
            "/etc/shadow",
            "C:\\Windows\\win.ini",
            "....//....//etc/passwd",
        ],
    )
    def test_strips_every_path_component(self, hostile: str) -> None:
        safe = audio_tools.safe_filename(hostile, encoding=AudioEncoding.WAV)
        assert "/" not in safe
        assert "\\" not in safe
        assert not safe.startswith("..")

    def test_strips_control_characters_that_could_forge_a_log_line(self) -> None:
        safe = audio_tools.safe_filename(
            "call\n2026-01-01 CRITICAL fake log entry.wav", encoding=AudioEncoding.WAV
        )
        assert "\n" not in safe

    def test_strips_a_nul_byte(self) -> None:
        safe = audio_tools.safe_filename("evil\x00.wav", encoding=AudioEncoding.WAV)
        assert "\x00" not in safe

    @pytest.mark.parametrize("empty", [None, "", "   ", ".", "..", "..."])
    def test_falls_back_to_a_generated_name(self, empty: str | None) -> None:
        assert audio_tools.safe_filename(empty, encoding=AudioEncoding.WAV) == "audio.wav"

    def test_caps_the_length(self) -> None:
        safe = audio_tools.safe_filename("a" * 500 + ".wav", encoding=AudioEncoding.WAV)
        assert len(safe) <= 128

    def test_keeps_an_ordinary_name(self) -> None:
        assert (
            audio_tools.safe_filename("hindi_greeting.wav", encoding=AudioEncoding.WAV)
            == "hindi_greeting.wav"
        )


# ---------------------------------------------------------------------------
# Result model honesty
# ---------------------------------------------------------------------------


class TestResultModel:
    def test_unreported_fields_stay_none(self) -> None:
        """A provider that does not report confidence must not appear certain."""
        result = TranscriptionResult(
            text="haan",
            language="hi-IN",
            requested_language="hi-IN",
            provider="prisma",
            latency_ms=10.0,
        )
        assert result.confidence is None
        assert result.segments is None

    @pytest.mark.parametrize("text", ["", "   ", "\n\t"])
    def test_blank_text_reads_as_empty(self, text: str) -> None:
        result = TranscriptionResult(
            text=text,
            language="hi-IN",
            requested_language="hi-IN",
            provider="fake",
            latency_ms=1.0,
        )
        assert result.is_empty

    def test_real_text_is_not_empty(self) -> None:
        result = TranscriptionResult(
            text="namaste",
            language="hi-IN",
            requested_language="hi-IN",
            provider="fake",
            latency_ms=1.0,
        )
        assert not result.is_empty

    def test_confidence_outside_zero_to_one_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="less than or equal to 1"):
            TranscriptionResult(
                text="x",
                language="hi-IN",
                requested_language="hi-IN",
                provider="fake",
                latency_ms=1.0,
                confidence=1.5,
            )


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


class TestRetryPolicyArithmetic:
    def test_backoff_grows_exponentially_without_jitter(self) -> None:
        policy = RetryPolicy(
            max_attempts=5, initial_backoff_seconds=1.0, max_backoff_seconds=100.0, jitter=False
        )
        assert [policy.backoff_for(n) for n in (1, 2, 3, 4)] == [1.0, 2.0, 4.0, 8.0]

    def test_backoff_is_capped(self) -> None:
        policy = RetryPolicy(
            max_attempts=9, initial_backoff_seconds=1.0, max_backoff_seconds=5.0, jitter=False
        )
        assert policy.backoff_for(8) == 5.0

    def test_jitter_scales_the_delay_by_the_random_value(self) -> None:
        policy = RetryPolicy(initial_backoff_seconds=4.0, max_backoff_seconds=100.0, jitter=True)
        assert policy.backoff_for(1, rand=lambda: 0.5) == 2.0
        assert policy.backoff_for(1, rand=lambda: 0.0) == 0.0

    def test_provider_retry_after_overrides_our_arithmetic(self) -> None:
        policy = RetryPolicy(initial_backoff_seconds=1.0, max_backoff_seconds=30.0, jitter=False)
        assert policy.backoff_for(1, retry_after=7.5) == 7.5

    def test_provider_retry_after_is_still_capped(self) -> None:
        """A provider must not be able to make us appear to hang."""
        policy = RetryPolicy(max_backoff_seconds=8.0, jitter=False)
        assert policy.backoff_for(1, retry_after=3600.0) == 8.0

    def test_negative_retry_after_is_clamped_to_zero(self) -> None:
        policy = RetryPolicy(max_backoff_seconds=8.0, jitter=False)
        assert policy.backoff_for(1, retry_after=-5.0) == 0.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_attempts": 0},
            {"initial_backoff_seconds": -1.0},
            {"initial_backoff_seconds": 10.0, "max_backoff_seconds": 1.0},
            {"multiplier": 0.5},
        ],
    )
    def test_an_incoherent_policy_is_rejected_at_construction(
        self, kwargs: dict[str, float]
    ) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(**kwargs)  # type: ignore[arg-type]


class TestRetryBehaviour:
    """What gets retried, what does not, and how many times."""

    @staticmethod
    def _run(
        operation: Callable[[], Awaitable[object]],
        policy: RetryPolicy,
        delays: list[float],
    ) -> tuple[object, int]:
        async def sleep(seconds: float) -> None:
            delays.append(seconds)

        return asyncio.run(
            call_with_retry(
                operation,
                policy=policy,
                provider="fake",
                operation_name="batch",
                sleep=sleep,
                rand=lambda: 1.0,
            )
        )

    def test_a_successful_call_is_not_retried(self) -> None:
        calls: list[int] = []

        async def operation() -> str:
            calls.append(1)
            return "ok"

        delays: list[float] = []
        result, attempts = self._run(operation, RetryPolicy(max_attempts=3), delays)
        assert (result, attempts, len(calls), delays) == ("ok", 1, 1, [])

    def test_a_transient_failure_is_retried_then_succeeds(self) -> None:
        state = {"n": 0}

        async def operation() -> str:
            state["n"] += 1
            if state["n"] == 1:
                raise unavailable_failure()
            return "recovered"

        delays: list[float] = []
        result, attempts = self._run(
            operation,
            RetryPolicy(max_attempts=3, initial_backoff_seconds=1.0, jitter=False),
            delays,
        )
        assert (result, attempts) == ("recovered", 2)
        assert delays == [1.0]

    def test_a_permanent_failure_is_not_retried_at_all(self) -> None:
        """Retrying a 401 cannot succeed; it only burns the rate limit."""
        calls: list[int] = []

        async def operation() -> str:
            calls.append(1)
            raise auth_failure()

        delays: list[float] = []
        with pytest.raises(AuthenticationError):
            self._run(operation, RetryPolicy(max_attempts=5), delays)
        assert len(calls) == 1
        assert delays == []

    @pytest.mark.parametrize(
        "error",
        [
            InvalidAudioError("bad audio"),
            UnsupportedFormatError("bad format"),
            ConfigurationError("misconfigured"),
        ],
    )
    def test_no_input_mistake_is_retried(self, error: TranscriptionError) -> None:
        calls: list[int] = []

        async def operation() -> str:
            calls.append(1)
            raise error

        with pytest.raises(type(error)):
            self._run(operation, RetryPolicy(max_attempts=4), [])
        assert len(calls) == 1

    def test_retries_are_exhausted_and_the_last_error_is_raised(self) -> None:
        calls: list[int] = []

        async def operation() -> str:
            calls.append(1)
            raise unavailable_failure()

        delays: list[float] = []
        with pytest.raises(ProviderUnavailableError):
            self._run(
                operation,
                RetryPolicy(max_attempts=3, initial_backoff_seconds=1.0, jitter=False),
                delays,
            )
        assert len(calls) == 3
        # Two sleeps for three attempts: no pointless wait after the last one.
        assert delays == [1.0, 2.0]

    def test_max_attempts_of_one_disables_retrying(self) -> None:
        calls: list[int] = []

        async def operation() -> str:
            calls.append(1)
            raise unavailable_failure()

        with pytest.raises(ProviderUnavailableError):
            self._run(operation, RetryPolicy(max_attempts=1), [])
        assert len(calls) == 1

    def test_a_rate_limit_respects_the_providers_retry_after(self) -> None:
        state = {"n": 0}

        async def operation() -> str:
            state["n"] += 1
            if state["n"] == 1:
                raise rate_limit_failure(retry_after=2.5)
            return "ok"

        delays: list[float] = []
        self._run(
            operation,
            RetryPolicy(max_attempts=2, initial_backoff_seconds=30.0, max_backoff_seconds=60.0),
            delays,
        )
        assert delays == [2.5]

    def test_cancellation_is_propagated_and_never_retried(self) -> None:
        """Swallowing cancellation would let cancelled work run to completion."""
        calls: list[int] = []

        async def operation() -> str:
            calls.append(1)
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            self._run(operation, RetryPolicy(max_attempts=3), [])
        assert len(calls) == 1

    def test_a_timeout_is_treated_as_transient(self) -> None:
        assert TranscriptionTimeoutError("t").retryable is True
        assert RateLimitError("r").retryable is True
        assert ProviderUnavailableError("u").retryable is True
        assert AuthenticationError("a").retryable is False
        assert InvalidAudioError("i").retryable is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "secret_key": "test-secret-key-not-used-for-anything",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestRegistry:
    def test_both_providers_are_registered(self) -> None:
        assert available_providers() == ("fake", "prisma")

    def test_the_configured_provider_is_built(self) -> None:
        provider = build_provider(_settings(transcription_provider="fake"))
        assert provider.capabilities.name == "fake"

    def test_an_unknown_provider_name_lists_the_known_ones(self) -> None:
        with pytest.raises(ConfigurationError, match="available providers"):
            build_provider(_settings(transcription_provider="whisper"))

    @pytest.mark.parametrize("spelling", ["PRISMA", "  prisma  ", "Prisma"])
    def test_the_provider_name_is_case_and_whitespace_insensitive(self, spelling: str) -> None:
        provider = build_provider(
            _settings(transcription_provider=spelling, gnani_api_key="k" * 24)
        )
        assert provider.capabilities.name == PRISMA_NAME

    def test_prisma_without_a_key_names_the_variable_to_set(self) -> None:
        with pytest.raises(ConfigurationError, match="GNANI_API_KEY"):
            build_provider(_settings(transcription_provider="prisma", gnani_api_key=""))

    def test_the_missing_key_error_suggests_the_offline_fake(self) -> None:
        """A developer with no credentials still needs a way to run the code."""
        with pytest.raises(ConfigurationError, match="TRANSCRIPTION_PROVIDER=fake"):
            build_provider(_settings(transcription_provider="prisma", gnani_api_key=""))

    def test_the_fake_is_refused_in_production(self) -> None:
        """It returns scripted text; publishing that as a measurement is the
        exact dishonesty this project's first rule forbids."""
        with pytest.raises(ConfigurationError, match="APP_ENV=production"):
            build_provider(
                _settings(
                    app_env=AppEnv.PRODUCTION,
                    secret_key="a-real-production-secret-value",
                    transcription_provider="fake",
                )
            )

    def test_the_fake_is_allowed_outside_production(self) -> None:
        for env in (AppEnv.DEVELOPMENT, AppEnv.STAGING, AppEnv.TEST):
            settings = _settings(
                app_env=env,
                secret_key="a-real-non-development-secret",
                transcription_provider="fake",
            )
            assert build_provider(settings).capabilities.name == "fake"

    def test_describe_lists_an_unconfigured_provider_with_its_reason(self) -> None:
        """Omitting it would be indistinguishable from it not existing."""
        described = {
            name: (caps, reason)
            for name, caps, reason in describe_providers(
                _settings(transcription_provider="fake", gnani_api_key="")
            )
        }
        assert set(described) == {"fake", "prisma"}

        fake_caps, fake_reason = described["fake"]
        assert fake_caps is not None and fake_reason is None

        prisma_caps, prisma_reason = described["prisma"]
        assert prisma_caps is None
        assert prisma_reason is not None and "GNANI_API_KEY" in prisma_reason

    def test_describe_never_includes_the_credential(self) -> None:
        secret = "super-secret-gnani-key-value-0123456789"
        rendered = repr(
            describe_providers(_settings(transcription_provider="prisma", gnani_api_key=secret))
        )
        assert secret not in rendered


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class TestFakeProvider:
    """The fake must behave like a provider, not like an always-yes stub."""

    def test_it_declares_that_it_needs_no_credentials(self) -> None:
        """This is what makes the default suite runnable in CI.""" ""
        assert FakeTranscriptionProvider().capabilities.requires_credentials is False

    def test_it_satisfies_the_same_interface_as_prisma(self) -> None:
        from app.transcription.base import TranscriptionProvider

        assert isinstance(FakeTranscriptionProvider(), TranscriptionProvider)

    def test_it_covers_the_whole_catalogue_by_default(self) -> None:
        assert FakeTranscriptionProvider().capabilities.languages == frozenset(SUPPORTED_CODES)

    def test_it_can_be_narrowed_to_a_language_subset(self) -> None:
        provider = FakeTranscriptionProvider(languages=["hi-IN"])
        assert provider.capabilities.supports_language("hi-IN")
        assert not provider.capabilities.supports_language("ta-IN")

    def test_close_is_observable(self) -> None:
        provider = FakeTranscriptionProvider()
        asyncio.run(provider.close())
        assert provider.closed

    def test_it_exercises_partial_results_which_prisma_cannot(self) -> None:
        """Somebody has to test the interim-hypothesis path."""
        assert FakeTranscriptionProvider().capabilities.supports_partial_results is True
        from app.transcription.providers.prisma import GnaniPrismaProvider

        prisma = GnaniPrismaProvider(api_key="k" * 24)
        assert prisma.capabilities.supports_partial_results is False

    def test_a_scripted_failure_sequence_is_consumed_in_order(self) -> None:
        script = FakeScript(failures=[unavailable_failure(), None])
        assert script.next_failure() is not None
        assert script.next_failure() is None

    def test_it_makes_no_network_call(self, wav_8k: bytes, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Guard the property CI depends on, rather than assuming it."""
        import httpx2

        def explode(*_: object, **__: object) -> None:
            raise AssertionError("the fake provider must not open a connection")

        monkeypatch.setattr(httpx2.AsyncClient, "request", explode)
        monkeypatch.setattr(httpx2.AsyncClient, "post", explode)

        from app.transcription.models import TranscriptionRequest

        provider = FakeTranscriptionProvider()
        result = asyncio.run(
            provider.transcribe_batch(
                TranscriptionRequest(audio=wav_8k, language="hi-IN", encoding=AudioEncoding.WAV)
            )
        )
        assert result.text


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestTranscriptionConfiguration:
    def test_the_default_provider_is_the_offline_fake(self) -> None:
        """A fresh checkout with no credentials must still start and test."""
        assert _settings().transcription_provider == "fake"

    def test_no_credential_is_configured_by_default(self) -> None:
        assert _settings().gnani_api_key == ""

    def test_live_tests_are_off_by_default(self) -> None:
        """CI must never be able to spend money by accident."""
        assert _settings().transcription_live_tests is False

    def test_the_config_defaults_match_the_verified_contract(self) -> None:
        """`app.core` must not import a vendor module, so these are duplicated.

        This test is the thing that stops the duplication drifting.
        """
        from app.core.config import PRISMA_DEFAULT_BASE_URL, PRISMA_DEFAULT_MODEL

        assert PRISMA_DEFAULT_BASE_URL == contract.DEFAULT_BASE_URL
        assert PRISMA_DEFAULT_MODEL == contract.DEFAULT_MODEL

    @pytest.mark.parametrize("bad", ["api.vachana.ai", "ftp://api.vachana.ai", "wss://x.y"])
    def test_a_base_url_without_an_http_scheme_is_rejected(self, bad: str) -> None:
        """The adapter derives its WebSocket URL by swapping the scheme."""
        with pytest.raises(ValueError, match="http"):
            _settings(gnani_api_base_url=bad)

    def test_a_trailing_slash_is_normalised_away(self) -> None:
        assert (
            _settings(gnani_api_base_url="https://api.vachana.ai/").gnani_api_base_url
            == "https://api.vachana.ai"
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("transcription_timeout_seconds", 0),
            ("transcription_timeout_seconds", 10_000),
            ("transcription_max_attempts", 0),
            ("transcription_max_attempts", 99),
            ("transcription_max_upload_bytes", 0),
        ],
    )
    def test_out_of_range_settings_are_rejected(self, field: str, value: float) -> None:
        with pytest.raises(ValueError):
            _settings(**{field: value})


class TestModeMapping:
    def test_only_modes_with_a_documented_wire_value_are_supported(self) -> None:
        """Guessing `code-mix` versus `code_mix` would be inventing the API."""
        assert frozenset({TranscriptionMode.TRANSCRIBE}) == contract.SUPPORTED_MODES

    def test_every_supported_mode_has_a_mapping(self) -> None:
        for mode in contract.SUPPORTED_MODES:
            assert contract.MODE_MAP[mode]

    def test_the_four_modes_exist_in_our_vocabulary_even_if_unsupported(self) -> None:
        """The product concept is real; only the wire values are unconfirmed."""
        assert {m.value for m in TranscriptionMode} == {
            "verbatim",
            "transcribe",
            "code_mix",
            "transliterate",
        }
