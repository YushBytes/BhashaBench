"""The speech endpoints, through the real app.

Drives the actual FastAPI routes with `TestClient`: real request validation,
the real dependency graph, the real exception handlers. Only the vendor call is
replaced, by overriding `get_speech_service_factory` with the offline fake.

No database is wired in. Phase 5 persists nothing, so these endpoints work
with PostgreSQL down, and that is asserted rather than assumed.
"""

from __future__ import annotations

import logging
import wave
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_database_probe
from app.api.v1.speech import get_speech_service_factory
from app.core.config import AppEnv, Settings, get_settings
from app.main import create_app
from app.speech.providers import timbre_contract as contract
from app.speech.providers.fake import (
    FakeSynthesisProvider,
    auth_failure,
    rate_limit_failure,
    timeout_failure,
    unavailable_failure,
)
from app.speech.service import SpeechService

TAMIL_LINE = "வணக்கம், உங்கள் பயிர் காப்பீட்டு விண்ணப்பத்தின் நிலையைச் சரிபார்க்கிறேன்."

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def speech_provider() -> FakeSynthesisProvider:
    """An offline synthesis provider with default scripted behaviour."""
    return FakeSynthesisProvider()


@pytest.fixture
def speech_settings() -> Settings:
    """Settings selecting the offline fake, with retries that do not sleep."""
    return Settings(
        app_env=AppEnv.TEST,
        app_version="0.1.0",
        secret_key="test-secret-key-not-used-for-anything",
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
        speech_provider="fake",
        speech_max_attempts=3,
        speech_initial_backoff_seconds=0.0,
        speech_max_backoff_seconds=0.0,
        _env_file=None,
    )


def _app(settings: Settings, provider: FakeSynthesisProvider) -> FastAPI:
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_database_probe] = lambda: lambda: (True, "ok")
    app.dependency_overrides[get_speech_service_factory] = lambda: (
        lambda: SpeechService(provider, settings=settings)
    )
    return app


@pytest.fixture
def speech_client(
    speech_settings: Settings, speech_provider: FakeSynthesisProvider
) -> Iterator[TestClient]:
    """HTTP client whose speech routes use the offline fake."""
    with TestClient(_app(speech_settings, speech_provider)) as client:
        yield client


def _generate(client: TestClient, **payload: object) -> object:
    body: dict[str, object] = {"text": TAMIL_LINE, "language": "ta-IN"}
    body.update(payload)
    return client.post("/api/v1/speech/generate", json=body)


# ---------------------------------------------------------------------------
# POST /api/v1/speech/generate
# ---------------------------------------------------------------------------


class TestGenerateEndpoint:
    def test_a_valid_request_returns_binary_audio(self, speech_client: TestClient) -> None:
        response = _generate(speech_client)
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert len(response.content) > 44  # more than a bare WAV header

    def test_the_returned_audio_is_a_parsable_wav(self, speech_client: TestClient) -> None:
        """The endpoint's whole output is the audio, so it had better decode."""
        response = _generate(speech_client)
        with wave.open(BytesIO(response.content), "rb") as handle:
            assert handle.getframerate() == 8000
            assert handle.getnchannels() == 1
            assert handle.getnframes() > 0

    def test_it_is_not_a_json_endpoint_on_success(self, speech_client: TestClient) -> None:
        response = _generate(speech_client)
        assert "json" not in response.headers["content-type"]

    def test_metadata_travels_in_headers(self, speech_client: TestClient) -> None:
        response = _generate(speech_client)
        assert response.headers["x-speech-provider"] == "fake"
        assert response.headers["x-speech-language"] == "ta-IN"
        assert response.headers["x-speech-container"] == "wav"
        assert int(response.headers["x-speech-size-bytes"]) == len(response.content)
        assert float(response.headers["x-speech-latency-ms"]) >= 0
        assert response.headers["x-speech-attempts"] == "1"

    def test_verified_measurements_appear_in_headers(self, speech_client: TestClient) -> None:
        response = _generate(speech_client)
        assert response.headers["x-speech-sample-rate-hz"] == "8000"
        assert float(response.headers["x-speech-duration-seconds"]) == pytest.approx(0.5)
        assert response.headers["x-speech-channels"] == "1"

    def test_the_requested_rate_is_always_reported(self, speech_client: TestClient) -> None:
        """So a provider that ignored it is visible rather than assumed away."""
        response = _generate(speech_client)
        assert response.headers["x-speech-requested-sample-rate-hz"] == "8000"

    def test_unmeasurable_fields_are_omitted_not_guessed(self, speech_client: TestClient) -> None:
        """An MP3's rate is unknown without a decoder. An absent header means
        'not measurable', which differs from a wrong number."""
        response = _generate(speech_client, container="mp3")
        assert response.status_code == 200
        assert "x-speech-sample-rate-hz" not in response.headers
        assert "x-speech-duration-seconds" not in response.headers
        assert response.headers["x-speech-requested-sample-rate-hz"] == "8000"

    def test_the_correlation_id_is_echoed(self, speech_client: TestClient) -> None:
        response = _generate(speech_client, correlation_id="run-9-turn-2")
        assert response.headers["x-speech-correlation-id"] == "run-9-turn-2"

    def test_no_correlation_header_when_none_supplied(self, speech_client: TestClient) -> None:
        assert "x-speech-correlation-id" not in _generate(speech_client).headers

    @pytest.mark.parametrize(
        ("container", "content_type"),
        [
            ("wav", "audio/wav"),
            ("mp3", "audio/mpeg"),
            ("ogg", "audio/ogg"),
            ("raw", "application/octet-stream"),
        ],
    )
    def test_each_container_sets_its_content_type(
        self, speech_client: TestClient, container: str, content_type: str
    ) -> None:
        response = _generate(speech_client, container=container)
        assert response.status_code == 200
        assert response.headers["content-type"] == content_type

    @pytest.mark.parametrize("container", ["mulaw", "alaw"])
    def test_the_g711_containers_return_audio_basic(
        self, speech_client: TestClient, container: str
    ) -> None:
        response = _generate(speech_client, container=container, sample_rate_hz=8000)
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/basic"

    def test_a_voice_is_reported_back(self, speech_client: TestClient) -> None:
        response = _generate(speech_client, voice="Testo")
        assert response.headers["x-speech-voice"] == "Testo"

    def test_auto_language_is_accepted(self, speech_client: TestClient) -> None:
        response = _generate(speech_client, language="auto")
        assert response.status_code == 200
        assert response.headers["x-speech-language"] == "auto"

    def test_a_retried_request_reports_its_attempts(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        speech_provider.script.failures = [unavailable_failure(), None]
        response = _generate(speech_client)
        assert response.status_code == 200
        assert response.headers["x-speech-attempts"] == "2"

    def test_it_works_without_a_database(self, speech_client: TestClient) -> None:
        """Phase 5 persists nothing; this fixture wires no database at all."""
        assert _generate(speech_client).status_code == 200


class TestGenerateValidation:
    def test_missing_text_is_a_validation_error(self, speech_client: TestClient) -> None:
        response = speech_client.post("/api/v1/speech/generate", json={"language": "ta-IN"})
        assert response.status_code == 422

    def test_missing_language_is_a_validation_error(self, speech_client: TestClient) -> None:
        response = speech_client.post("/api/v1/speech/generate", json={"text": "hi"})
        assert response.status_code == 422

    def test_empty_text_is_rejected_by_the_schema(self, speech_client: TestClient) -> None:
        """`min_length=1` means this never reaches a handler."""
        assert _generate(speech_client, text="").status_code == 422

    def test_whitespace_only_text_is_rejected_by_the_service(
        self, speech_client: TestClient
    ) -> None:
        """It passes `min_length` but is still nothing to speak."""
        response = _generate(speech_client, text="   ")
        assert response.status_code == 422
        assert response.json()["error"]["type"] == "invalid_text_error"

    def test_over_long_text_is_rejected_before_a_handler_runs(
        self, speech_client: TestClient
    ) -> None:
        from app.schemas.speech import MAX_TEXT_CHARS

        response = _generate(speech_client, text="x" * (MAX_TEXT_CHARS + 1))
        assert response.status_code == 422

    def test_an_unknown_language_is_422_with_the_supported_list(
        self, speech_client: TestClient
    ) -> None:
        response = _generate(speech_client, language="fr-FR")
        assert response.status_code == 422
        assert "hi-IN" in response.json()["error"]["message"]

    def test_an_unknown_voice_is_422(self, speech_client: TestClient) -> None:
        response = _generate(speech_client, voice="Siri")
        assert response.status_code == 422
        assert response.json()["error"]["type"] == "unsupported_voice_error"

    def test_an_unsupported_sample_rate_is_415(self, speech_client: TestClient) -> None:
        response = _generate(speech_client, sample_rate_hz=11025)
        assert response.status_code == 415
        assert response.json()["error"]["type"] == "unsupported_audio_config_error"

    def test_an_invalid_container_is_a_schema_error(self, speech_client: TestClient) -> None:
        assert _generate(speech_client, container="flac").status_code == 422

    def test_an_audio_tag_the_provider_lacks_is_415(self, speech_client: TestClient) -> None:
        """Otherwise `<laugh>` is read out as a word."""
        response = _generate(speech_client, text="hello <laugh> there")
        assert response.status_code == 415
        assert "read out as words" in response.json()["error"]["message"]

    def test_a_negative_channel_count_is_a_schema_error(self, speech_client: TestClient) -> None:
        assert _generate(speech_client, channels=0).status_code == 422


class TestGenerateErrorMapping:
    @pytest.mark.parametrize(
        ("failure", "expected_status", "expected_type"),
        [
            (auth_failure(401), 502, "speech_authentication_error"),
            (auth_failure(402), 502, "speech_authentication_error"),
            (auth_failure(403), 502, "speech_authentication_error"),
            (rate_limit_failure(), 429, "speech_rate_limit_error"),
            (timeout_failure(), 504, "speech_timeout_error"),
            (unavailable_failure(), 502, "speech_provider_unavailable_error"),
        ],
    )
    def test_each_provider_failure_maps_to_its_status(
        self,
        speech_client: TestClient,
        speech_provider: FakeSynthesisProvider,
        failure: Exception,
        expected_status: int,
        expected_type: str,
    ) -> None:
        speech_provider.script.failures = [failure] * 5  # type: ignore[list-item]
        response = _generate(speech_client)
        assert response.status_code == expected_status
        assert response.json()["error"]["type"] == expected_type

    def test_a_provider_401_is_not_returned_as_401(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        """Our API is unauthenticated here; a 401 would tell the caller to fix
        credentials they do not have."""
        speech_provider.script.failures = [auth_failure(401)]
        assert _generate(speech_client).status_code == 502

    def test_an_empty_provider_body_is_502(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        speech_provider.script.empty_response = True
        response = _generate(speech_client)
        assert response.status_code == 502
        assert response.json()["error"]["type"] == "malformed_speech_response_error"

    def test_every_error_uses_the_shared_envelope(self, speech_client: TestClient) -> None:
        body = _generate(speech_client, language="fr-FR").json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"type", "message", "status_code"}

    def test_an_error_response_is_json_not_audio(self, speech_client: TestClient) -> None:
        response = _generate(speech_client, language="fr-FR")
        assert "application/json" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# GET /api/v1/speech/providers
# ---------------------------------------------------------------------------


class TestProvidersEndpoint:
    def test_it_lists_every_registered_provider(self, speech_client: TestClient) -> None:
        body = speech_client.get("/api/v1/speech/providers").json()
        assert {p["name"] for p in body["providers"]} == {"fake", "timbre"}

    def test_it_flags_the_selected_provider(self, speech_client: TestClient) -> None:
        body = speech_client.get("/api/v1/speech/providers").json()
        assert body["selected"] == "fake"
        assert [p["name"] for p in body["providers"] if p["selected"]] == ["fake"]

    def test_an_unconfigured_provider_is_listed_with_its_reason(
        self, speech_client: TestClient
    ) -> None:
        body = speech_client.get("/api/v1/speech/providers").json()
        timbre = next(p for p in body["providers"] if p["name"] == "timbre")
        assert timbre["available"] is False
        assert "GNANI_API_KEY" in timbre["unavailable_reason"]

    def test_the_fake_needs_no_credentials(self, speech_client: TestClient) -> None:
        body = speech_client.get("/api/v1/speech/providers").json()
        fake = next(p for p in body["providers"] if p["name"] == "fake")
        assert fake["requires_credentials"] is False

    def test_the_fake_publishes_its_voices(self, speech_client: TestClient) -> None:
        body = speech_client.get("/api/v1/speech/providers").json()
        fake = next(p for p in body["providers"] if p["name"] == "fake")
        assert {v["name"] for v in fake["voices"]} == {"Testa", "Testo"}


class TestProvidersEndpointWithTimbreConfigured:
    @pytest.fixture
    def client(self, speech_provider: FakeSynthesisProvider) -> Iterator[TestClient]:
        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            speech_provider="timbre",
            gnani_api_key="timbre-key-0123456789abcdef",
            _env_file=None,
        )
        with TestClient(_app(settings, speech_provider)) as client:
            yield client

    def _timbre(self, client: TestClient) -> dict[str, object]:
        body = client.get("/api/v1/speech/providers").json()
        return next(p for p in body["providers"] if p["name"] == "timbre")

    def test_timbre_reports_its_ten_languages(self, client: TestClient) -> None:
        assert len(self._timbre(client)["languages"]) == 10  # type: ignore[arg-type]

    def test_timbre_names_the_three_it_cannot_speak(self, client: TestClient) -> None:
        assert self._timbre(client)["unsupported_catalogue_languages"] == [
            "as-IN",
            "or-IN",
            "ur-IN",
        ]

    def test_timbre_publishes_auto_and_hinglish_separately(self, client: TestClient) -> None:
        """They are provider vocabulary, not catalogue tags, so keeping them in
        their own field leaves the catalogue gap computable."""
        assert self._timbre(client)["extra_language_values"] == ["auto", "hi-en"]

    def test_timbre_publishes_thirteen_voices_with_characters(self, client: TestClient) -> None:
        voices = self._timbre(client)["voices"]
        assert len(voices) == 13  # type: ignore[arg-type]
        for voice in voices:  # type: ignore[union-attr]
            assert voice["gender"] in {"female", "male"}
            assert voice["character"]

    def test_timbre_declares_its_roster_exhaustive_for_v3(self, client: TestClient) -> None:
        assert self._timbre(client)["voices_are_exhaustive"] is True

    def test_timbre_publishes_eleven_audio_tags(self, client: TestClient) -> None:
        assert len(self._timbre(client)["audio_tags"]) == 11  # type: ignore[arg-type]
        assert self._timbre(client)["supports_audio_tags"] is True

    def test_timbre_does_not_claim_streaming(self, client: TestClient) -> None:
        assert self._timbre(client)["supports_streaming"] is False

    def test_timbre_publishes_its_speed_range(self, client: TestClient) -> None:
        timbre = self._timbre(client)
        assert timbre["speed_min"] == contract.SPEED_MIN
        assert timbre["speed_max"] == contract.SPEED_MAX

    def test_timbre_declares_that_it_serialises_requests(self, client: TestClient) -> None:
        assert self._timbre(client)["serialises_requests"] is True

    def test_timbre_publishes_the_documentation_gaps(self, client: TestClient) -> None:
        assert len(self._timbre(client)["notes"]) >= 6  # type: ignore[arg-type]

    def test_the_api_key_never_appears_in_the_response(self, client: TestClient) -> None:
        raw = client.get("/api/v1/speech/providers").text
        assert "timbre-key-0123456789abcdef" not in raw


# ---------------------------------------------------------------------------
# Resource cleanup
# ---------------------------------------------------------------------------


class TestResourceCleanup:
    """Every request must release its provider client, on both paths.

    Phase 4 shipped this leak once; the dependency is the fix and these tests
    are what stop it regressing in the new subsystem.
    """

    def test_the_provider_is_closed_after_a_successful_request(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        assert not speech_provider.closed
        assert _generate(speech_client).status_code == 200
        assert speech_provider.closed

    def test_the_provider_is_closed_after_a_validation_failure(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        assert _generate(speech_client, language="fr-FR").status_code == 422
        assert speech_provider.closed

    def test_the_provider_is_closed_after_a_provider_failure(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        speech_provider.script.failures = [auth_failure()]
        assert _generate(speech_client).status_code == 502
        assert speech_provider.closed

    def test_the_provider_is_closed_after_retries_are_exhausted(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        speech_provider.script.failures = [unavailable_failure()] * 5
        assert _generate(speech_client).status_code == 502
        assert speech_provider.closed
        assert len(speech_provider.script.calls) == 3

    def test_the_provider_is_closed_after_an_unexpected_exception(
        self, speech_settings: Settings, speech_provider: FakeSynthesisProvider
    ) -> None:
        """The path most likely to leak: an error nobody anticipated."""

        async def explode(*_: object, **__: object) -> None:
            raise RuntimeError("unexpected")

        speech_provider.synthesise = explode  # type: ignore[method-assign]
        client = TestClient(_app(speech_settings, speech_provider), raise_server_exceptions=False)
        response = client.post("/api/v1/speech/generate", json={"text": "hi", "language": "en-IN"})
        assert response.status_code == 500
        assert speech_provider.closed

    def test_an_owned_timbre_client_is_closed(self) -> None:
        import asyncio

        from app.speech.providers.timbre import GnaniTimbreProvider

        provider = GnaniTimbreProvider(api_key="k" * 30)
        client = provider._http
        assert not client.is_closed
        asyncio.run(provider.close())
        assert client.is_closed

    def test_the_registry_builds_a_provider_that_owns_its_client(self) -> None:
        from app.speech.registry import build_provider

        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            speech_provider="timbre",
            gnani_api_key="k" * 30,
            _env_file=None,
        )
        assert build_provider(settings)._owns_client is True  # type: ignore[attr-defined]

    def test_the_capability_endpoint_opens_no_client(self, speech_client: TestClient) -> None:
        assert speech_client.get("/api/v1/speech/providers").status_code == 200


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_an_error_body_never_carries_a_key(
        self, speech_client: TestClient, speech_provider: FakeSynthesisProvider
    ) -> None:
        from app.speech.errors import SpeechAuthenticationError

        secret = "gnani_tts_key_abcdef0123456789"
        speech_provider.script.failures = [
            SpeechAuthenticationError(f"rejected api_key={secret}", provider="fake")
        ]
        response = _generate(speech_client)
        assert secret not in response.text

    def test_an_unexpected_error_returns_a_generic_message(
        self, speech_settings: Settings, speech_provider: FakeSynthesisProvider
    ) -> None:
        async def explode(*_: object, **__: object) -> None:
            raise RuntimeError("internal detail at /srv/app/secret_module.py line 9")

        speech_provider.synthesise = explode  # type: ignore[method-assign]
        client = TestClient(_app(speech_settings, speech_provider), raise_server_exceptions=False)
        response = client.post("/api/v1/speech/generate", json={"text": "hi", "language": "en-IN"})
        assert response.status_code == 500
        assert "secret_module" not in response.text

    def test_no_database_url_appears_in_the_capability_listing(
        self, speech_provider: FakeSynthesisProvider
    ) -> None:
        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            database_url="postgresql+psycopg://u:dbpassword123@localhost:5432/x",
            speech_provider="fake",
            _env_file=None,
        )
        with TestClient(_app(settings, speech_provider)) as client:
            raw = client.get("/api/v1/speech/providers").text
        assert "dbpassword123" not in raw

    def test_the_env_example_declares_every_phase_5_setting(self) -> None:
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        for name in (
            "SPEECH_PROVIDER",
            "SPEECH_TIMEOUT_SECONDS",
            "SPEECH_MAX_ATTEMPTS",
            "SPEECH_MAX_TEXT_CHARS",
            "SPEECH_LIVE_TESTS",
            "GNANI_TTS_MODEL",
            "GNANI_TTS_VOICE",
        ):
            assert name in text, name

    def test_the_env_example_adds_no_second_credential(self) -> None:
        """One Gnani key; a TTS-specific placeholder would mislead."""
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "GNANI_TTS_API_KEY" not in text
        assert "TIMBRE_API_KEY" not in text

    def test_no_source_file_hardcodes_a_credential(self) -> None:
        import re

        suspicious = re.compile(
            r"""(?ix)
            (gnani[_-]?api[_-]?key|api[_-]?key[_-]?id)
            \s*[:=]\s*
            ["'][A-Za-z0-9_\-]{16,}["']
            """
        )
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / "backend" / "app" / "speech").rglob("*.py")
            if suspicious.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogging:
    def test_a_completed_synthesis_logs_safe_metadata(
        self, speech_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="bhashabench.speech"):
            _generate(speech_client, correlation_id="run-1")
        record = next(r for r in caplog.records if r.message == "speech.completed")
        assert record.provider == "fake"  # type: ignore[attr-defined]
        assert record.language == "ta-IN"  # type: ignore[attr-defined]
        assert record.correlation_id == "run-1"  # type: ignore[attr-defined]
        assert record.attempts == 1  # type: ignore[attr-defined]

    def test_the_text_is_not_logged_only_its_length(
        self, speech_client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Caller text can carry whatever a scenario put in a persona's mouth."""
        secret = "my policy number is 4455 6677 8899"
        with caplog.at_level(logging.DEBUG):
            _generate(speech_client, text=secret)
        assert secret not in caplog.text
        record = next(r for r in caplog.records if r.message == "speech.completed")
        assert record.text_chars == len(secret)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


class TestApiSurface:
    def test_both_endpoints_are_in_the_openapi_document(self, speech_client: TestClient) -> None:
        paths = speech_client.get("/openapi.json").json()["paths"]
        assert "/api/v1/speech/generate" in paths
        assert "/api/v1/speech/providers" in paths

    def test_the_generate_endpoint_documents_its_binary_response(
        self, speech_client: TestClient
    ) -> None:
        """A client has to know it is not getting JSON."""
        schema = speech_client.get("/openapi.json").json()
        ok = schema["paths"]["/api/v1/speech/generate"]["post"]["responses"]["200"]
        assert "audio/wav" in ok["content"]

    def test_the_generate_endpoint_documents_its_failure_statuses(
        self, speech_client: TestClient
    ) -> None:
        schema = speech_client.get("/openapi.json").json()
        responses = schema["paths"]["/api/v1/speech/generate"]["post"]["responses"]
        for status in ("415", "422", "429", "502", "504"):
            assert status in responses

    def test_the_phase_1_to_4_surface_is_untouched(self, speech_client: TestClient) -> None:
        paths = set(speech_client.get("/openapi.json").json()["paths"])
        for existing in (
            "/api/v1/health",
            "/api/v1/languages",
            "/api/v1/suites",
            "/api/v1/scenarios",
            "/api/v1/transcription",
            "/api/v1/transcription/providers",
        ):
            assert existing in paths

    def test_health_claims_no_speech_component(self, speech_client: TestClient) -> None:
        """Nothing probes the provider at startup, so health must not imply it."""
        body = speech_client.get("/api/v1/health").json()
        assert "speech" not in {c["name"] for c in body["components"]}
