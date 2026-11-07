"""The Timbre contract, the domain models, the registry and the service layer.

No network and no credentials: everything here is pure logic or the offline
fake. Async code is driven with `asyncio.run` for the same reason as the
transcription tests - no plugin whose configuration would have to be mirrored
into both pytest config files.
"""

from __future__ import annotations

import asyncio
import wave
from io import BytesIO

import pytest

from app.core.config import AppEnv, Settings
from app.core.languages import SUPPORTED_CODES
from app.core.languages import UnsupportedLanguageError as CatalogueLanguageError
from app.speech.base import SynthesisCapabilities
from app.speech.errors import (
    InvalidTextError,
    MalformedSpeechResponseError,
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechError,
    SpeechProviderUnavailableError,
    SpeechRateLimitError,
    SpeechTimeoutError,
    UnsupportedAudioConfigError,
    UnsupportedSpeechLanguageError,
    UnsupportedVoiceError,
)
from app.speech.models import (
    AudioConfig,
    AudioContainer,
    AudioEncodingName,
    SpeechResult,
    SpeechSpeed,
)
from app.speech.providers import timbre_contract as contract
from app.speech.providers.fake import (
    FakeSpeechScript,
    FakeSynthesisProvider,
    auth_failure,
    build_wav,
    rate_limit_failure,
    unavailable_failure,
)
from app.speech.registry import available_providers, build_provider, describe_providers
from app.speech.service import SpeechService

TAMIL_LINE = "வணக்கம், உங்கள் பயிர் காப்பீட்டு விண்ணப்பத்தின் நிலையைச் சரிபார்க்கிறேன்."
"""A real Tamil support-call line. Used because an ASCII placeholder would not
exercise the UTF-8 path that every Indian-language utterance takes."""


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "secret_key": "test-secret-key-not-used-for-anything",
        "speech_max_attempts": 3,
        "speech_initial_backoff_seconds": 0.0,
        "speech_max_backoff_seconds": 0.0,
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _service(provider: FakeSynthesisProvider | None = None, **overrides: object) -> SpeechService:
    return SpeechService(provider or FakeSynthesisProvider(), settings=_settings(**overrides))


# ---------------------------------------------------------------------------
# The published contract
# ---------------------------------------------------------------------------


class TestContractConstants:
    """Asserted against the documentation, so a careless edit is caught."""

    def test_endpoint_and_transport(self) -> None:
        assert contract.DEFAULT_BASE_URL == "https://api.vachana.ai"
        assert contract.INFERENCE_PATH == "/api/v1/tts/inference"

    def test_the_api_key_header_is_not_a_bearer_scheme(self) -> None:
        assert contract.API_KEY_HEADER == "X-API-Key-ID"
        assert "bearer" not in contract.API_KEY_HEADER.lower()

    def test_it_shares_the_key_header_with_prisma(self) -> None:
        """One Gnani platform key, one header - which is why there is no
        second credential setting."""
        from app.transcription.providers import prisma_contract as stt

        assert contract.API_KEY_HEADER == stt.API_KEY_HEADER
        assert contract.DEFAULT_BASE_URL == stt.DEFAULT_BASE_URL

    def test_request_field_names(self) -> None:
        assert contract.FIELD_TEXT == "text"
        assert contract.FIELD_MODEL == "model"
        assert contract.FIELD_VOICE == "voice"
        assert contract.FIELD_LANGUAGE == "language"
        assert contract.FIELD_SPEED == "speed"
        assert contract.FIELD_AUDIO_CONFIG == "audio_config"

    def test_audio_config_field_names(self) -> None:
        assert contract.CONFIG_SAMPLE_RATE == "sample_rate"
        assert contract.CONFIG_NUM_CHANNELS == "num_channels"
        assert contract.CONFIG_SAMPLE_WIDTH == "sample_width"
        assert contract.CONFIG_ENCODING == "encoding"
        assert contract.CONFIG_CONTAINER == "container"
        assert contract.CONFIG_BITRATE == "bitrate"

    def test_required_fields_are_the_documented_three(self) -> None:
        assert frozenset({"text", "model", "audio_config"}) == contract.REQUIRED_FIELDS

    def test_documented_models(self) -> None:
        assert frozenset({"timbre-v3.0", "timbre-v2.5"}) == contract.SUPPORTED_MODELS
        assert contract.DEFAULT_MODEL == "timbre-v3.0"

    def test_documented_speed_range(self) -> None:
        assert (contract.SPEED_MIN, contract.SPEED_MAX) == (0.85, 1.15)

    def test_documented_speed_aliases(self) -> None:
        assert set(contract.SPEED_ALIASES) == {"slow", "medium", "fast"}

    def test_documented_sample_rates(self) -> None:
        assert frozenset({8000, 16000, 22050, 24000, 44100, 48000}) == contract.SAMPLE_RATES
        assert contract.DEFAULT_SAMPLE_RATE == 48000

    def test_documented_containers(self) -> None:
        assert frozenset({"wav", "raw", "mp3", "ogg", "mulaw", "alaw"}) == contract.CONTAINERS

    def test_documented_encodings(self) -> None:
        assert (
            frozenset({"linear_pcm", "pcm_s16le", "pcm_mulaw", "pcm_alaw", "oggopus"})
            == contract.ENCODINGS
        )

    def test_documented_bitrates(self) -> None:
        assert frozenset({"32k", "64k", "96k", "128k", "192k"}) == contract.BITRATES

    def test_g711_containers_are_8khz(self) -> None:
        assert contract.MULAW_ALAW_SAMPLE_RATE == 8000

    def test_documented_error_statuses(self) -> None:
        assert contract.STATUS_BAD_REQUEST == 400
        assert contract.STATUS_UNAUTHORIZED == 401
        assert contract.STATUS_PAYMENT_REQUIRED == 402
        assert contract.STATUS_FORBIDDEN == 403
        assert contract.STATUS_RATE_LIMITED == 429
        assert contract.STATUS_SERVER_ERROR == 500
        assert contract.STATUS_UNAVAILABLE == 503

    def test_documentation_gaps_are_recorded_rather_than_guessed(self) -> None:
        assert len(contract.DOCUMENTATION_GAPS) >= 6
        joined = " ".join(contract.DOCUMENTATION_GAPS).lower()
        # The three that changed implementation decisions.
        assert "v2.5 voice roster" in joined
        assert "twelve audio tags" in joined
        assert "one-active-request" in joined


class TestVoiceCatalogue:
    def test_thirteen_v3_voices_are_documented(self) -> None:
        assert len(contract.V3_VOICES) == 13
        assert len(contract.V3_VOICE_NAMES) == 13

    def test_every_voice_has_a_gender_and_a_character(self) -> None:
        """The character is what makes a voice choosable for a persona."""
        for voice in contract.V3_VOICES:
            assert voice.gender in {"female", "male"}
            assert voice.character.strip()

    def test_the_documented_capitalisation_is_preserved(self) -> None:
        """Case sensitivity is undocumented, so the published spelling is what
        gets sent - a lower-cased roster would be a guess."""
        assert "Kalpana" in contract.V3_VOICE_NAMES
        assert "kalpana" not in contract.V3_VOICE_NAMES

    @pytest.mark.parametrize("spelling", ["Kalpana", "kalpana", "KALPANA", "  Kalpana  "])
    def test_voice_lookup_is_case_and_whitespace_insensitive(self, spelling: str) -> None:
        found = contract.voice_for(spelling)
        assert found is not None
        assert found.name == "Kalpana"

    def test_an_unknown_voice_is_not_found(self) -> None:
        assert contract.voice_for("Siri") is None

    def test_the_default_voice_is_a_documented_one(self) -> None:
        assert contract.DEFAULT_VOICE in contract.V3_VOICE_NAMES

    def test_the_v25_roster_is_marked_as_examples_only(self) -> None:
        """42 voices exist and nine are quoted, so this must never be treated
        as a complete list to validate against."""
        assert len(contract.V25_VOICE_EXAMPLES) < 42


class TestLanguageCoverage:
    def test_timbre_documents_ten_languages(self) -> None:
        assert len(contract.PROVIDER_LANGUAGE_CODES) == 10

    def test_every_timbre_language_is_in_the_bhashabench_catalogue(self) -> None:
        assert set(contract.PROVIDER_LANGUAGE_CODES) <= set(SUPPORTED_CODES)

    def test_three_catalogue_languages_cannot_be_spoken(self) -> None:
        missing = set(SUPPORTED_CODES) - set(contract.PROVIDER_LANGUAGE_CODES)
        assert missing == {"ur-IN", "or-IN", "as-IN"}
        assert set(contract.UNSUPPORTED_BHASHABENCH_LANGUAGES) == missing

    def test_the_mapping_is_explicit_even_though_it_is_the_identity(self) -> None:
        assert {c: c for c in contract.PROVIDER_LANGUAGE_CODES} == contract.LANGUAGE_MAP

    def test_auto_and_hinglish_are_accepted_values(self) -> None:
        assert contract.AUTO_LANGUAGE_CODE in contract.SUPPORTED_LANGUAGE_VALUES
        assert contract.HINGLISH_LANGUAGE_CODE in contract.SUPPORTED_LANGUAGE_VALUES

    def test_hinglish_is_not_added_to_the_catalogue(self) -> None:
        assert contract.HINGLISH_LANGUAGE_CODE not in SUPPORTED_CODES

    def test_there_is_no_tanglish_code(self) -> None:
        """`hi-en` is the only documented code-mixed value. A Tamil-English
        line has to use `auto` or `ta-IN`, and pretending otherwise would
        invent a contract."""
        # A code-mixed value pairs two lowercase language subtags (`hi-en`);
        # an ordinary tag has an uppercase region (`ta-IN`).
        mixed = {
            v for v in contract.SUPPORTED_LANGUAGE_VALUES if "-" in v and v.split("-")[1].islower()
        }
        assert mixed == {"hi-en"}
        assert "ta-en" not in contract.SUPPORTED_LANGUAGE_VALUES

    def test_timbre_and_prisma_cover_the_same_ten(self) -> None:
        """Not relied upon anywhere, but worth knowing: a scenario that can be
        spoken can also be transcribed."""
        from app.transcription.providers import prisma_contract as stt

        assert set(contract.PROVIDER_LANGUAGE_CODES) == set(stt.PROVIDER_LANGUAGE_CODES)


class TestAudioTags:
    def test_eleven_tags_are_enumerated(self) -> None:
        assert len(contract.AUDIO_TAGS) == 11

    def test_every_tag_is_angle_bracketed(self) -> None:
        for tag in contract.AUDIO_TAGS:
            assert tag.startswith("<") and tag.endswith(">")

    def test_the_count_discrepancy_is_recorded(self) -> None:
        """The product page says twelve; the reference enumerates eleven."""
        joined = " ".join(contract.DOCUMENTATION_GAPS)
        assert "twelve" in joined.lower()


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class TestAudioConfigDefaults:
    def test_it_defaults_to_telephony_audio(self) -> None:
        """8 kHz mono, because that is what a phone call is - not the
        vendor's 48 kHz default, which would need downsampling."""
        config = AudioConfig()
        assert config.sample_rate_hz == 8000
        assert config.channels == 1
        assert config.container is AudioContainer.WAV
        assert config.encoding is AudioEncodingName.LINEAR_PCM

    def test_the_vendor_default_differs_and_that_is_deliberate(self) -> None:
        assert AudioConfig().sample_rate_hz != contract.DEFAULT_SAMPLE_RATE


class TestResultModel:
    def _result(self, **overrides: object) -> SpeechResult:
        base: dict[str, object] = {
            "audio": b"\x00\x01",
            "container": AudioContainer.WAV,
            "content_type": "audio/wav",
            "provider": "timbre",
            "model": "timbre-v3.0",
            "language": "ta-IN",
            "requested_language": "ta-IN",
            "latency_ms": 10.0,
            "size_bytes": 2,
            "requested_sample_rate_hz": 8000,
        }
        base.update(overrides)
        return SpeechResult(**base)  # type: ignore[arg-type]

    def test_unmeasurable_fields_stay_none(self) -> None:
        """An MP3's rate is not knowable without decoding, so it must not be
        echoed back from the request and presented as fact."""
        result = self._result(container=AudioContainer.MP3, content_type="audio/mpeg")
        assert result.sample_rate_hz is None
        assert result.duration_seconds is None
        assert result.channels is None

    def test_rate_honoured_is_none_when_the_rate_is_unknown(self) -> None:
        """Unknown is not the same as mismatched, and must not read as one."""
        assert self._result().rate_was_honoured is None

    def test_rate_honoured_is_true_on_a_match(self) -> None:
        assert self._result(sample_rate_hz=8000).rate_was_honoured is True

    def test_rate_honoured_is_false_on_a_mismatch(self) -> None:
        """The case this field exists for: a provider that ignored us."""
        assert self._result(sample_rate_hz=48000).rate_was_honoured is False

    def test_the_requested_rate_is_always_retained(self) -> None:
        assert self._result(sample_rate_hz=48000).requested_sample_rate_hz == 8000


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_both_providers_are_registered(self) -> None:
        assert available_providers() == ("fake", "timbre")

    def test_the_configured_provider_is_built(self) -> None:
        assert build_provider(_settings(speech_provider="fake")).capabilities.name == "fake"

    def test_an_unknown_provider_lists_the_known_ones(self) -> None:
        with pytest.raises(SpeechConfigurationError, match="available providers"):
            build_provider(_settings(speech_provider="elevenlabs"))

    @pytest.mark.parametrize("spelling", ["TIMBRE", "  timbre  ", "Timbre"])
    def test_the_provider_name_is_case_and_whitespace_insensitive(self, spelling: str) -> None:
        provider = build_provider(_settings(speech_provider=spelling, gnani_api_key="k" * 30))
        assert provider.capabilities.name == "timbre"

    def test_timbre_without_a_key_names_the_variable(self) -> None:
        with pytest.raises(SpeechConfigurationError, match="GNANI_API_KEY"):
            build_provider(_settings(speech_provider="timbre", gnani_api_key=""))

    def test_the_missing_key_error_says_it_is_shared_with_prisma(self) -> None:
        """A developer who already configured STT should not go looking for a
        second credential that does not exist."""
        with pytest.raises(SpeechConfigurationError, match="same key Prisma"):
            build_provider(_settings(speech_provider="timbre", gnani_api_key=""))

    def test_the_missing_key_error_suggests_the_offline_fake(self) -> None:
        with pytest.raises(SpeechConfigurationError, match="SPEECH_PROVIDER=fake"):
            build_provider(_settings(speech_provider="timbre", gnani_api_key=""))

    def test_the_fake_is_refused_in_production(self) -> None:
        """It returns a tone. Playing that at a bot and scoring the result is
        the same dishonesty as a fabricated transcript."""
        with pytest.raises(SpeechConfigurationError, match="APP_ENV=production"):
            build_provider(
                _settings(
                    app_env=AppEnv.PRODUCTION,
                    secret_key="a-real-production-secret-value",
                    speech_provider="fake",
                )
            )

    def test_the_fake_is_allowed_outside_production(self) -> None:
        for env in (AppEnv.DEVELOPMENT, AppEnv.STAGING, AppEnv.TEST):
            settings = _settings(
                app_env=env,
                secret_key="a-real-non-development-secret",
                speech_provider="fake",
            )
            assert build_provider(settings).capabilities.name == "fake"

    def test_describe_lists_an_unconfigured_provider_with_its_reason(self) -> None:
        described = {
            name: (caps, reason)
            for name, caps, reason in describe_providers(
                _settings(speech_provider="fake", gnani_api_key="")
            )
        }
        assert set(described) == {"fake", "timbre"}
        assert described["fake"][0] is not None
        assert described["timbre"][0] is None
        assert "GNANI_API_KEY" in described["timbre"][1]  # type: ignore[operator]

    def test_describe_never_includes_the_credential(self) -> None:
        secret = "timbre-secret-key-value-0123456789abcd"
        rendered = repr(
            describe_providers(_settings(speech_provider="timbre", gnani_api_key=secret))
        )
        assert secret not in rendered


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestSpeechConfiguration:
    def test_the_default_provider_is_the_offline_fake(self) -> None:
        assert Settings(_env_file=None).speech_provider == "fake"

    def test_live_tests_are_off_by_default(self) -> None:
        assert Settings(_env_file=None).speech_live_tests is False

    def test_the_live_flags_are_independent(self) -> None:
        """Enabling transcription live tests must not enable billable TTS."""
        settings = Settings(transcription_live_tests=True, _env_file=None)
        assert settings.speech_live_tests is False

    def test_no_second_credential_setting_exists(self) -> None:
        """The vendor documents one key; a TTS-specific one would be a
        variable nobody could fill in."""
        fields = set(Settings.model_fields)
        assert "gnani_api_key" in fields
        assert not {f for f in fields if "tts" in f and "key" in f}

    def test_the_config_defaults_match_the_verified_contract(self) -> None:
        """`app.core` must not import a vendor module, so these are duplicated.
        This test is what stops the duplication drifting."""
        from app.core.config import TIMBRE_DEFAULT_MODEL, TIMBRE_DEFAULT_VOICE

        assert TIMBRE_DEFAULT_MODEL == contract.DEFAULT_MODEL
        assert TIMBRE_DEFAULT_VOICE == contract.DEFAULT_VOICE

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("speech_timeout_seconds", 0),
            ("speech_timeout_seconds", 10_000),
            ("speech_max_attempts", 0),
            ("speech_max_attempts", 99),
            ("speech_max_text_chars", 0),
        ],
    )
    def test_out_of_range_settings_are_rejected(self, field: str, value: float) -> None:
        with pytest.raises(ValueError):
            _settings(**{field: value})


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class TestFakeProvider:
    def test_it_satisfies_the_synthesis_interface(self) -> None:
        from app.speech.base import SynthesisProvider

        assert isinstance(FakeSynthesisProvider(), SynthesisProvider)

    def test_it_declares_that_it_needs_no_credentials(self) -> None:
        assert FakeSynthesisProvider().capabilities.requires_credentials is False

    def test_it_returns_a_real_parsable_wav(self) -> None:
        """A placeholder byte string would leave every measurement untested."""
        result = asyncio.run(_service().synthesise(TAMIL_LINE, language="ta-IN"))
        with wave.open(BytesIO(result.audio), "rb") as handle:
            assert handle.getframerate() == 8000
            assert handle.getnchannels() == 1
            assert handle.getnframes() > 0

    def test_build_wav_honours_its_arguments(self) -> None:
        payload = build_wav(sample_rate=16000, channels=2, seconds=0.25)
        with wave.open(BytesIO(payload), "rb") as handle:
            assert handle.getframerate() == 16000
            assert handle.getnchannels() == 2

    def test_close_is_observable(self) -> None:
        provider = FakeSynthesisProvider()
        asyncio.run(provider.close())
        assert provider.closed

    def test_it_records_every_request_for_inspection(self) -> None:
        provider = FakeSynthesisProvider()
        asyncio.run(_service(provider).synthesise("hello", language="en-IN"))
        assert len(provider.script.requests) == 1
        assert provider.script.requests[0].language == "en-IN"

    def test_it_makes_no_network_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guard the property CI depends on rather than assuming it."""
        import httpx2

        def explode(*_: object, **__: object) -> None:
            raise AssertionError("the fake provider must not open a connection")

        monkeypatch.setattr(httpx2.AsyncClient, "post", explode)
        monkeypatch.setattr(httpx2.AsyncClient, "request", explode)
        result = asyncio.run(_service().synthesise("hello", language="en-IN"))
        assert result.size_bytes > 0

    def test_it_can_simulate_a_provider_ignoring_the_sample_rate(self) -> None:
        provider = FakeSynthesisProvider(FakeSpeechScript(honour_sample_rate=False))
        result = asyncio.run(
            _service(provider).synthesise(
                "hello", language="en-IN", audio=AudioConfig(sample_rate_hz=8000)
            )
        )
        assert result.rate_was_honoured is False

    def test_a_scripted_failure_sequence_is_consumed_in_order(self) -> None:
        script = FakeSpeechScript(failures=[unavailable_failure(), None])
        assert script.next_failure() is not None
        assert script.next_failure() is None


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


class TestServiceValidation:
    def test_empty_text_is_rejected(self) -> None:
        with pytest.raises(InvalidTextError, match="empty"):
            asyncio.run(_service().synthesise("   ", language="en-IN"))

    def test_over_long_text_is_rejected_with_the_limit_named(self) -> None:
        with pytest.raises(InvalidTextError, match="SPEECH_MAX_TEXT_CHARS"):
            asyncio.run(_service(speech_max_text_chars=10).synthesise("x" * 11, language="en-IN"))

    def test_the_effective_limit_is_the_lower_of_the_two(self) -> None:
        """The provider declares 5000; a stricter local setting wins."""
        with pytest.raises(InvalidTextError):
            asyncio.run(_service(speech_max_text_chars=5).synthesise("x" * 6, language="en-IN"))

    def test_a_malformed_tag_is_a_catalogue_error(self) -> None:
        with pytest.raises(CatalogueLanguageError, match="well-formed"):
            asyncio.run(_service().synthesise("hi", language="ta_IN"))

    def test_a_language_outside_the_catalogue_is_rejected(self) -> None:
        with pytest.raises(CatalogueLanguageError):
            asyncio.run(_service().synthesise("hi", language="fr-FR"))

    def test_a_catalogue_language_the_provider_cannot_speak_says_so(self) -> None:
        provider = FakeSynthesisProvider(languages=["en-IN"])
        with pytest.raises(UnsupportedSpeechLanguageError) as caught:
            asyncio.run(_service(provider).synthesise("hi", language="ta-IN"))
        message = str(caught.value)
        assert "supported BhashaBench language" in message
        assert "cannot synthesise speech in it" in message

    def test_auto_is_accepted_when_the_provider_offers_it(self) -> None:
        result = asyncio.run(_service().synthesise("hello", language="auto"))
        assert result.language == "auto"

    def test_a_provider_level_value_the_provider_lacks_is_rejected(self) -> None:
        """The fake offers `auto` but not `hi-en`."""
        with pytest.raises(UnsupportedSpeechLanguageError, match="hi-en"):
            asyncio.run(_service().synthesise("hello", language="hi-en"))

    def test_an_unknown_voice_is_rejected_when_the_roster_is_complete(self) -> None:
        with pytest.raises(UnsupportedVoiceError) as caught:
            asyncio.run(_service().synthesise("hi", language="en-IN", voice="Siri"))
        assert caught.value.voice == "Siri"
        assert "Testa" in str(caught.value)

    def test_a_known_voice_is_accepted(self) -> None:
        result = asyncio.run(_service().synthesise("hi", language="en-IN", voice="Testa"))
        assert result.voice == "Testa"

    def test_an_unsupported_container_is_rejected(self) -> None:
        from dataclasses import replace

        class NoMp3(FakeSynthesisProvider):
            @property
            def capabilities(self) -> SynthesisCapabilities:
                return replace(super().capabilities, containers=frozenset({AudioContainer.WAV}))

        with pytest.raises(UnsupportedAudioConfigError, match="container"):
            asyncio.run(
                _service(NoMp3()).synthesise(
                    "hi", language="en-IN", audio=AudioConfig(container=AudioContainer.MP3)
                )
            )

    def test_an_unsupported_sample_rate_is_rejected(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="Hz"):
            asyncio.run(
                _service().synthesise(
                    "hi", language="en-IN", audio=AudioConfig(sample_rate_hz=11025)
                )
            )

    def test_validation_order_checks_language_before_audio(self) -> None:
        """A request for Odia never has its audio configuration examined."""
        provider = FakeSynthesisProvider(languages=["en-IN"])
        with pytest.raises(UnsupportedSpeechLanguageError):
            asyncio.run(
                _service(provider).synthesise(
                    "hi", language="or-IN", audio=AudioConfig(sample_rate_hz=11025)
                )
            )


class TestAudioTagValidation:
    """A tag the model ignores is *spoken aloud*, which is worse than an error."""

    def test_a_tag_is_rejected_when_the_provider_has_none(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="read out as words"):
            asyncio.run(_service().synthesise("hello <laugh> there", language="en-IN"))

    def test_plain_text_with_no_angle_brackets_passes(self) -> None:
        result = asyncio.run(_service().synthesise("hello there", language="en-IN"))
        assert result.size_bytes > 0

    def test_a_documented_tag_passes_on_a_provider_that_supports_them(self) -> None:
        from dataclasses import replace

        class Tagged(FakeSynthesisProvider):
            @property
            def capabilities(self) -> SynthesisCapabilities:
                return replace(
                    super().capabilities,
                    audio_tags=contract.AUDIO_TAGS,
                    supports_audio_tags=True,
                )

        result = asyncio.run(_service(Tagged()).synthesise("hello <laugh> there", language="en-IN"))
        assert result.size_bytes > 0

    def test_an_undocumented_tag_is_rejected_even_on_a_tagging_provider(self) -> None:
        from dataclasses import replace

        class Tagged(FakeSynthesisProvider):
            @property
            def capabilities(self) -> SynthesisCapabilities:
                return replace(
                    super().capabilities,
                    audio_tags=contract.AUDIO_TAGS,
                    supports_audio_tags=True,
                )

        with pytest.raises(UnsupportedAudioConfigError, match="not documented audio tags"):
            asyncio.run(_service(Tagged()).synthesise("hello <sings> there", language="en-IN"))

    def test_a_less_than_sign_in_ordinary_text_is_not_a_tag(self) -> None:
        """`5 < 10` must not be mistaken for an expression tag."""
        result = asyncio.run(
            _service().synthesise("the premium is < 10 thousand rupees", language="en-IN")
        )
        assert result.size_bytes > 0


class TestServiceBehaviour:
    def test_it_synthesises_and_reports_the_provider(self) -> None:
        result = asyncio.run(_service().synthesise(TAMIL_LINE, language="ta-IN"))
        assert result.provider == "fake"
        assert result.requested_language == "ta-IN"
        assert result.size_bytes > 0

    def test_latency_is_measured_end_to_end_not_taken_from_the_adapter(self) -> None:
        provider = FakeSynthesisProvider(
            FakeSpeechScript(
                failures=[unavailable_failure(), unavailable_failure(), None], latency_ms=3.0
            )
        )
        result = asyncio.run(_service(provider).synthesise("hi", language="en-IN"))
        assert result.attempts == 3
        assert result.latency_ms != 3.0

    def test_attempts_is_one_on_a_clean_call(self) -> None:
        assert asyncio.run(_service().synthesise("hi", language="en-IN")).attempts == 1

    def test_the_correlation_id_reaches_the_provider(self) -> None:
        provider = FakeSynthesisProvider()
        asyncio.run(_service(provider).synthesise("hi", language="en-IN", correlation_id="run-3"))
        assert provider.script.requests[0].correlation_id == "run-3"

    def test_a_permanent_failure_is_surfaced_after_one_attempt(self) -> None:
        provider = FakeSynthesisProvider(FakeSpeechScript(failures=[auth_failure()]))
        with pytest.raises(SpeechAuthenticationError):
            asyncio.run(_service(provider).synthesise("hi", language="en-IN"))
        assert provider.script.calls == ["synthesise"]

    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_no_credential_failure_is_retried(self, status: int) -> None:
        provider = FakeSynthesisProvider(FakeSpeechScript(failures=[auth_failure(status)] * 5))
        with pytest.raises(SpeechAuthenticationError):
            asyncio.run(_service(provider).synthesise("hi", language="en-IN"))
        assert len(provider.script.calls) == 1

    def test_retries_are_exhausted_then_the_error_is_raised(self) -> None:
        provider = FakeSynthesisProvider(FakeSpeechScript(failures=[unavailable_failure()] * 5))
        with pytest.raises(SpeechProviderUnavailableError):
            asyncio.run(_service(provider).synthesise("hi", language="en-IN"))
        assert len(provider.script.calls) == 3

    def test_a_rate_limit_is_retried(self) -> None:
        provider = FakeSynthesisProvider(
            FakeSpeechScript(failures=[rate_limit_failure(retry_after=0.0), None])
        )
        result = asyncio.run(_service(provider).synthesise("hi", language="en-IN"))
        assert result.attempts == 2

    def test_an_empty_provider_response_is_surfaced_as_malformed(self) -> None:
        provider = FakeSynthesisProvider(FakeSpeechScript(empty_response=True))
        with pytest.raises(MalformedSpeechResponseError):
            asyncio.run(_service(provider).synthesise("hi", language="en-IN"))

    def test_retryable_flags_match_intent(self) -> None:
        assert SpeechTimeoutError("t").retryable is True
        assert SpeechRateLimitError("r").retryable is True
        assert SpeechProviderUnavailableError("u").retryable is True
        assert SpeechAuthenticationError("a").retryable is False
        assert InvalidTextError("i").retryable is False
        assert UnsupportedVoiceError("v").retryable is False
        assert MalformedSpeechResponseError("m").retryable is False
        assert UnsupportedAudioConfigError("c").retryable is False

    def test_close_releases_the_provider(self) -> None:
        provider = FakeSynthesisProvider()
        asyncio.run(_service(provider).close())
        assert provider.closed


class TestErrorClassification:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (SpeechAuthenticationError("x"), "speech_authentication_error"),
            (SpeechRateLimitError("x"), "speech_rate_limit_error"),
            (InvalidTextError("x"), "invalid_text_error"),
            (UnsupportedVoiceError("x"), "unsupported_voice_error"),
            (UnsupportedSpeechLanguageError("x"), "unsupported_speech_language_error"),
            (UnsupportedAudioConfigError("x"), "unsupported_audio_config_error"),
            (MalformedSpeechResponseError("x"), "malformed_speech_response_error"),
            (SpeechTimeoutError("x"), "speech_timeout_error"),
        ],
    )
    def test_each_error_gets_a_stable_snake_case_category(
        self, error: SpeechError, expected: str
    ) -> None:
        from app.speech.service import classify

        assert classify(error) == expected


class TestSpeedHandling:
    @pytest.mark.parametrize("speed", [0.85, 1.0, 1.15])
    def test_documented_numeric_speeds_are_accepted(self, speed: float) -> None:
        result = asyncio.run(_service().synthesise("hi", language="en-IN", speed=speed))
        assert result.speed == speed

    @pytest.mark.parametrize("alias", list(SpeechSpeed))
    def test_documented_aliases_are_accepted(self, alias: SpeechSpeed) -> None:
        result = asyncio.run(_service().synthesise("hi", language="en-IN", speed=alias))
        assert result.speed == alias
