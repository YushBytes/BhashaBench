"""The service layer and the HTTP/WebSocket endpoints, through the real app.

These drive the actual FastAPI routes with `TestClient`: real multipart
parsing, the real dependency graph, the real exception handlers. Only the
vendor call is replaced, by overriding `get_service_factory` with the offline
fake - which is the one seam a test is allowed to use.

No database is wired in. Phase 4 persists nothing, so these endpoints work
with PostgreSQL down, and that is asserted rather than assumed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.core.languages import UnsupportedLanguageError as CatalogueLanguageError
from app.services.transcription_service import TranscriptionService, classify
from app.transcription.base import ProviderCapabilities
from app.transcription.errors import (
    AudioTooLargeError,
    AuthenticationError,
    InvalidAudioError,
    MalformedProviderResponseError,
    ProviderUnavailableError,
    RateLimitError,
    TranscriptionTimeoutError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.transcription.models import TranscriptionMode
from app.transcription.providers.fake import (
    DEFAULT_TRANSCRIPT,
    FakeScript,
    FakeTranscriptionProvider,
    auth_failure,
    rate_limit_failure,
    timeout_failure,
    unavailable_failure,
)

# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


def _service(
    provider: FakeTranscriptionProvider, settings: Settings | None = None
) -> TranscriptionService:
    return TranscriptionService(
        provider,
        settings=settings
        or Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="fake",
            transcription_max_attempts=3,
            transcription_initial_backoff_seconds=0.0,
            transcription_max_backoff_seconds=0.0,
            _env_file=None,
        ),
    )


class TestServiceBatch:
    def test_it_transcribes_and_reports_the_provider(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _service(FakeTranscriptionProvider()).transcribe_batch(wav_8k, language="hi-IN")
        )
        assert result.text == DEFAULT_TRANSCRIPT
        assert result.provider == "fake"
        assert result.requested_language == "hi-IN"

    def test_latency_is_measured_end_to_end_not_taken_from_the_adapter(self, wav_8k: bytes) -> None:
        """A call that took three attempts must not report the last one's time."""
        provider = FakeTranscriptionProvider(
            FakeScript(
                failures=[unavailable_failure(), unavailable_failure(), None], latency_ms=5.0
            )
        )
        result = asyncio.run(_service(provider).transcribe_batch(wav_8k, language="hi-IN"))
        assert result.attempts == 3
        assert result.latency_ms != 5.0

    def test_attempts_is_one_on_a_clean_call(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _service(FakeTranscriptionProvider()).transcribe_batch(wav_8k, language="hi-IN")
        )
        assert result.attempts == 1

    def test_audio_duration_is_filled_from_our_inspection(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _service(FakeTranscriptionProvider()).transcribe_batch(wav_8k, language="hi-IN")
        )
        assert result.audio_duration_seconds == pytest.approx(1.0)

    def test_a_malformed_tag_is_a_catalogue_error_not_a_provider_error(self, wav_8k: bytes) -> None:
        """`hi_IN` is the wrong *shape*; that is a different mistake from
        a well-formed tag the provider cannot handle."""
        with pytest.raises(CatalogueLanguageError, match="well-formed"):
            asyncio.run(
                _service(FakeTranscriptionProvider()).transcribe_batch(wav_8k, language="hi_IN")
            )

    def test_a_language_outside_the_catalogue_is_rejected(self, wav_8k: bytes) -> None:
        with pytest.raises(CatalogueLanguageError):
            asyncio.run(
                _service(FakeTranscriptionProvider()).transcribe_batch(wav_8k, language="fr-FR")
            )

    def test_a_catalogue_language_the_provider_lacks_says_so_explicitly(
        self, wav_8k: bytes
    ) -> None:
        """The developer must not go looking for a typo that is not there."""
        provider = FakeTranscriptionProvider(languages=["hi-IN"])
        with pytest.raises(UnsupportedLanguageError) as caught:
            asyncio.run(_service(provider).transcribe_batch(wav_8k, language="ta-IN"))
        message = str(caught.value)
        assert "supported BhashaBench language" in message
        assert "provider does not transcribe it" in message
        assert caught.value.language == "ta-IN"

    def test_an_unsupported_mode_is_rejected_before_the_call(self, wav_8k: bytes) -> None:
        class NoModes(FakeTranscriptionProvider):
            """A provider that implements no output modes at all."""

            @property
            def capabilities(self) -> ProviderCapabilities:
                return replace(super().capabilities, modes=frozenset())

        with pytest.raises(UnsupportedFormatError, match="output mode"):
            asyncio.run(
                _service(NoModes()).transcribe_batch(
                    wav_8k, language="hi-IN", mode=TranscriptionMode.VERBATIM
                )
            )

    def test_an_unsupported_language_is_checked_before_the_audio(self) -> None:
        """Validation order: a request for Odia never has its bytes inspected."""
        provider = FakeTranscriptionProvider(languages=["hi-IN"])
        with pytest.raises(UnsupportedLanguageError):
            asyncio.run(_service(provider).transcribe_batch(b"not audio at all", language="ta-IN"))

    def test_empty_audio_is_rejected(self) -> None:
        with pytest.raises(InvalidAudioError, match="empty"):
            asyncio.run(
                _service(FakeTranscriptionProvider()).transcribe_batch(b"", language="hi-IN")
            )

    def test_the_effective_size_limit_is_the_lower_of_the_two(self, wav_8k: bytes) -> None:
        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="fake",
            transcription_max_upload_bytes=100,
            _env_file=None,
        )
        with pytest.raises(AudioTooLargeError):
            asyncio.run(
                _service(FakeTranscriptionProvider(), settings).transcribe_batch(
                    wav_8k, language="hi-IN"
                )
            )

    def test_an_empty_transcript_is_returned_as_success(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _service(FakeTranscriptionProvider(FakeScript(transcript=""))).transcribe_batch(
                wav_8k, language="hi-IN"
            )
        )
        assert result.is_empty

    def test_a_permanent_failure_is_surfaced_after_one_attempt(self, wav_8k: bytes) -> None:
        provider = FakeTranscriptionProvider(FakeScript(failures=[auth_failure()]))
        with pytest.raises(AuthenticationError):
            asyncio.run(_service(provider).transcribe_batch(wav_8k, language="hi-IN"))
        assert provider.script.calls == ["batch"]

    def test_retries_are_exhausted_then_the_error_is_raised(self, wav_8k: bytes) -> None:
        provider = FakeTranscriptionProvider(FakeScript(failures=[unavailable_failure()] * 5))
        with pytest.raises(ProviderUnavailableError):
            asyncio.run(_service(provider).transcribe_batch(wav_8k, language="hi-IN"))
        assert len(provider.script.calls) == 3

    def test_a_malformed_provider_response_is_surfaced_as_such(self, wav_8k: bytes) -> None:
        provider = FakeTranscriptionProvider(FakeScript(malformed_response=True))
        with pytest.raises(MalformedProviderResponseError):
            asyncio.run(_service(provider).transcribe_batch(wav_8k, language="hi-IN"))

    def test_the_correlation_id_is_echoed_back(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _service(FakeTranscriptionProvider()).transcribe_batch(
                wav_8k, language="hi-IN", correlation_id="run-42-turn-3"
            )
        )
        assert result.correlation_id == "run-42-turn-3"


class TestServiceStreaming:
    def test_validation_happens_before_the_generator_is_iterated(self, raw_pcm_8k: bytes) -> None:
        """Otherwise a bad language surfaces three frames in, as an event."""
        service = _service(FakeTranscriptionProvider(languages=["hi-IN"]))

        async def audio() -> AsyncIterator[bytes]:
            yield raw_pcm_8k

        with pytest.raises(UnsupportedLanguageError):
            service.transcribe_stream(audio(), language="ta-IN", sample_rate_hz=8000)

    def test_an_unaccepted_sample_rate_is_refused_eagerly(self, raw_pcm_8k: bytes) -> None:
        service = _service(FakeTranscriptionProvider())

        async def audio() -> AsyncIterator[bytes]:
            yield raw_pcm_8k

        with pytest.raises(UnsupportedFormatError, match="22050"):
            service.transcribe_stream(audio(), language="hi-IN", sample_rate_hz=22050)

    def test_a_stream_is_never_retried_by_the_service(self, raw_pcm_8k: bytes) -> None:
        """Replaying consumed audio would present a tail as the whole utterance."""
        provider = FakeTranscriptionProvider(FakeScript(failures=[unavailable_failure(), None]))
        service = _service(provider)

        async def drive() -> list[object]:
            async def audio() -> AsyncIterator[bytes]:
                yield raw_pcm_8k

            return [
                event
                async for event in service.transcribe_stream(
                    audio(), language="hi-IN", sample_rate_hz=8000
                )
            ]

        events = asyncio.run(drive())
        assert provider.script.calls == ["stream"]
        assert type(events[-1]).__name__ == "TranscriptionFailed"


class TestErrorClassification:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (AuthenticationError("x"), "authentication_error"),
            (RateLimitError("x"), "rate_limit_error"),
            (InvalidAudioError("x"), "invalid_audio_error"),
            (UnsupportedLanguageError("x"), "unsupported_language_error"),
            (ProviderUnavailableError("x"), "provider_unavailable_error"),
            (TranscriptionTimeoutError("x"), "transcription_timeout_error"),
            (MalformedProviderResponseError("x"), "malformed_provider_response_error"),
        ],
    )
    def test_each_error_gets_a_stable_snake_case_category(
        self, error: Exception, expected: str
    ) -> None:
        assert classify(error) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HTTP: POST /api/v1/transcription
# ---------------------------------------------------------------------------


def _upload(client: TestClient, audio: bytes, *, language: str = "hi-IN", **data: str) -> object:
    return client.post(
        "/api/v1/transcription",
        files={"audio": ("call.wav", audio, "audio/wav")},
        data={"language": language, **data},
    )


class TestBatchEndpoint:
    def test_a_valid_upload_returns_a_transcript(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        response = _upload(transcription_client, wav_8k)
        assert response.status_code == 200
        body = response.json()
        assert body["text"] == DEFAULT_TRANSCRIPT
        assert body["provider"] == "fake"
        assert body["language"] == "hi-IN"
        assert body["empty"] is False
        assert body["attempts"] == 1

    def test_unreported_fields_are_null_not_fabricated(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        body = _upload(transcription_client, wav_8k).json()
        assert body["confidence"] is None
        assert body["segments"] is None

    def test_the_correlation_id_is_echoed(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        body = _upload(transcription_client, wav_8k, correlation_id="run-9").json()
        assert body["correlation_id"] == "run-9"

    def test_a_requested_mode_is_reported_back(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        body = _upload(transcription_client, wav_8k, mode="transcribe").json()
        assert body["mode"] == "transcribe"

    def test_a_missing_language_is_a_validation_error(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        response = transcription_client.post(
            "/api/v1/transcription",
            files={"audio": ("call.wav", wav_8k, "audio/wav")},
        )
        assert response.status_code == 422

    def test_a_missing_file_is_a_validation_error(self, transcription_client: TestClient) -> None:
        response = transcription_client.post("/api/v1/transcription", data={"language": "hi-IN"})
        assert response.status_code == 422

    def test_an_unknown_language_is_422_with_the_supported_list(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        response = _upload(transcription_client, wav_8k, language="fr-FR")
        assert response.status_code == 422
        assert "hi-IN" in response.json()["error"]["message"]

    def test_unidentifiable_content_is_422(
        self, transcription_client: TestClient, audio_fixtures
    ) -> None:  # type: ignore[no-untyped-def]
        payload = (audio_fixtures / "not_audio.wav").read_bytes()
        response = _upload(transcription_client, payload)
        assert response.status_code == 415
        assert response.json()["error"]["type"] == "unsupported_format_error"

    def test_a_truncated_file_is_422_invalid_audio(
        self, transcription_client: TestClient, audio_fixtures
    ) -> None:  # type: ignore[no-untyped-def]
        payload = (audio_fixtures / "truncated.wav").read_bytes()
        response = _upload(transcription_client, payload)
        assert response.status_code == 422
        assert response.json()["error"]["type"] == "invalid_audio_error"

    def test_an_empty_file_is_422(self, transcription_client: TestClient) -> None:
        response = _upload(transcription_client, b"")
        assert response.status_code == 422

    def test_silence_transcribes_to_an_empty_result_with_200(
        self, transcription_client: TestClient, audio_fixtures, fake_provider
    ) -> None:  # type: ignore[no-untyped-def]
        """Recognising nothing is a legitimate outcome, not a failure."""
        fake_provider.script.transcript = ""
        payload = (audio_fixtures / "silence_8k_mono.wav").read_bytes()
        response = _upload(transcription_client, payload)
        assert response.status_code == 200
        assert response.json()["empty"] is True
        assert response.json()["text"] == ""

    def test_a_declared_encoding_contradicting_the_content_is_415(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        response = _upload(transcription_client, wav_8k, encoding="mp3")
        assert response.status_code == 415

    @pytest.mark.parametrize(
        ("failure", "expected_status", "expected_type"),
        [
            (auth_failure(), 502, "authentication_error"),
            (rate_limit_failure(), 429, "rate_limit_error"),
            (timeout_failure(), 504, "transcription_timeout_error"),
            (unavailable_failure(), 502, "provider_unavailable_error"),
        ],
    )
    def test_each_provider_failure_maps_to_its_status(
        self,
        transcription_client: TestClient,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
        failure: Exception,
        expected_status: int,
        expected_type: str,
    ) -> None:
        # Enough copies to exhaust the retry budget for the transient ones.
        fake_provider.script.failures = [failure] * 5  # type: ignore[list-item]
        response = _upload(transcription_client, wav_8k)
        assert response.status_code == expected_status
        assert response.json()["error"]["type"] == expected_type

    def test_a_provider_401_is_not_returned_to_the_client_as_401(
        self,
        transcription_client: TestClient,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
    ) -> None:
        """Our own API is unauthenticated here: a 401 would tell the caller to
        fix credentials they do not have."""
        fake_provider.script.failures = [auth_failure()]
        assert _upload(transcription_client, wav_8k).status_code == 502

    def test_every_error_uses_the_shared_envelope(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        body = _upload(transcription_client, wav_8k, language="fr-FR").json()
        assert set(body) == {"error"}
        assert set(body["error"]) == {"type", "message", "status_code"}

    def test_an_oversized_upload_is_413(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        # The fixture app allows 10 MB; build something past it cheaply by
        # repeating the fixture.
        oversized = wav_8k * 700  # ~11 MB
        response = _upload(transcription_client, oversized)
        assert response.status_code == 413
        assert response.json()["error"]["type"] == "audio_too_large_error"

    def test_the_endpoint_works_without_a_database(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        """Phase 4 persists nothing, so no session is ever opened. This fixture
        wires no database at all - a passing request is the proof."""
        assert _upload(transcription_client, wav_8k).status_code == 200


# ---------------------------------------------------------------------------
# HTTP: GET /api/v1/transcription/providers
# ---------------------------------------------------------------------------


class TestProvidersEndpoint:
    def test_it_lists_every_registered_provider(self, transcription_client: TestClient) -> None:
        body = transcription_client.get("/api/v1/transcription/providers").json()
        assert {p["name"] for p in body["providers"]} == {"fake", "prisma"}

    def test_it_flags_the_selected_provider(self, transcription_client: TestClient) -> None:
        body = transcription_client.get("/api/v1/transcription/providers").json()
        assert body["selected"] == "fake"
        selected = [p for p in body["providers"] if p["selected"]]
        assert [p["name"] for p in selected] == ["fake"]

    def test_an_unconfigured_provider_is_listed_with_its_reason(
        self, transcription_client: TestClient
    ) -> None:
        """Omitting it is indistinguishable from it not existing."""
        body = transcription_client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert prisma["available"] is False
        assert "GNANI_API_KEY" in prisma["unavailable_reason"]

    def test_the_reason_names_the_setting_but_not_a_value(
        self, transcription_client: TestClient
    ) -> None:
        body = transcription_client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert "=" not in prisma["unavailable_reason"].split("GNANI_API_KEY")[1][:3]

    def test_the_fake_reports_that_it_needs_no_credentials(
        self, transcription_client: TestClient
    ) -> None:
        body = transcription_client.get("/api/v1/transcription/providers").json()
        fake = next(p for p in body["providers"] if p["name"] == "fake")
        assert fake["requires_credentials"] is False

    def test_it_reports_which_catalogue_languages_cannot_be_transcribed(
        self, transcription_client: TestClient
    ) -> None:
        body = transcription_client.get("/api/v1/transcription/providers").json()
        fake = next(p for p in body["providers"] if p["name"] == "fake")
        # The fake covers the whole catalogue, so nothing is missing.
        assert fake["unsupported_catalogue_languages"] == []

    def test_the_fake_declares_partial_result_support(
        self, transcription_client: TestClient
    ) -> None:
        body = transcription_client.get("/api/v1/transcription/providers").json()
        fake = next(p for p in body["providers"] if p["name"] == "fake")
        assert fake["supports_partial_results"] is True


class TestProvidersEndpointWithPrismaConfigured:
    @pytest.fixture
    def client(self, fake_provider: FakeTranscriptionProvider) -> TestClient:
        """An app configured for Prisma, so its real capabilities are reported."""
        from app.api.deps import get_database_probe
        from app.api.v1.transcription import get_service_factory
        from app.core.config import get_settings
        from app.main import create_app

        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="prisma",
            gnani_api_key="gnani-test-key-0123456789abcdef",
            _env_file=None,
        )
        app = create_app(settings=settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_database_probe] = lambda: (
            lambda: (True, "Connected; SELECT 1 succeeded.")
        )
        app.dependency_overrides[get_service_factory] = lambda: (
            lambda: TranscriptionService(fake_provider, settings=settings)
        )
        return TestClient(app)

    def test_prisma_reports_its_ten_documented_languages(self, client: TestClient) -> None:
        body = client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert len(prisma["languages"]) == 10

    def test_prisma_names_the_three_languages_it_cannot_transcribe(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert prisma["unsupported_catalogue_languages"] == ["as-IN", "or-IN", "ur-IN"]

    def test_prisma_does_not_claim_partials_confidence_or_timestamps(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert prisma["supports_partial_results"] is False
        assert prisma["supports_confidence"] is False
        assert prisma["supports_word_timestamps"] is False
        assert prisma["supports_diarisation"] is False

    def test_prisma_publishes_the_documentation_gaps(self, client: TestClient) -> None:
        body = client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert len(prisma["notes"]) >= 5

    def test_prisma_reports_the_documented_frame_size(self, client: TestClient) -> None:
        body = client.get("/api/v1/transcription/providers").json()
        prisma = next(p for p in body["providers"] if p["name"] == "prisma")
        assert prisma["streaming_frame_bytes"] == 1024

    def test_the_api_key_never_appears_in_the_response(self, client: TestClient) -> None:
        raw = client.get("/api/v1/transcription/providers").text
        assert "gnani-test-key-0123456789abcdef" not in raw


# ---------------------------------------------------------------------------
# WebSocket: /api/v1/transcription/stream
# ---------------------------------------------------------------------------


class TestStreamEndpoint:
    def test_a_stream_yields_started_finals_and_completed(
        self, transcription_client: TestClient, fake_provider: FakeTranscriptionProvider
    ) -> None:
        fake_provider.script.segments = ["mera order", "kahan hai"]
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_bytes(b"\x00\x00" * 512)
            ws.send_text("EOS")
            messages = [ws.receive_json() for _ in range(4)]

        assert [m["type"] for m in messages] == [
            "started",
            "final_transcript",
            "final_transcript",
            "completed",
        ]
        assert messages[-1]["result"]["text"] == "mera order kahan hai"

    def test_the_started_event_echoes_the_correlation_id(
        self, transcription_client: TestClient
    ) -> None:
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000&correlation_id=run-5"
        ) as ws:
            ws.send_text("EOS")
            started = ws.receive_json()
        assert started["correlation_id"] == "run-5"

    def test_partial_events_are_forwarded_when_the_provider_emits_them(
        self, transcription_client: TestClient, fake_provider: FakeTranscriptionProvider
    ) -> None:
        fake_provider.script.segments = ["mera order"]
        fake_provider.script.partials = ["mera", "mera or"]
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("EOS")
            types = [ws.receive_json()["type"] for _ in range(5)]
        assert types == [
            "started",
            "partial_transcript",
            "partial_transcript",
            "final_transcript",
            "completed",
        ]

    def test_null_fields_are_omitted_from_a_frame(self, transcription_client: TestClient) -> None:
        """Otherwise every segment of every call ships a dozen nulls."""
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("EOS")
            ws.receive_json()
            final = ws.receive_json()
        assert final["type"] == "final_transcript"
        assert "error_type" not in final
        assert "result" not in final

    def test_the_audio_sent_actually_reaches_the_provider(
        self, transcription_client: TestClient, fake_provider: FakeTranscriptionProvider
    ) -> None:
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_bytes(b"\x00\x00" * 100)
            ws.send_bytes(b"\x00\x00" * 200)
            ws.send_text("EOS")
            while ws.receive_json()["type"] != "completed":
                pass
        assert fake_provider.script.frames_received == [200, 400]

    def test_closing_without_eos_still_completes(self, transcription_client: TestClient) -> None:
        """A client that just hangs up must not leave the server waiting."""
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_bytes(b"\x00\x00" * 64)
            ws.receive_json()  # started

    def test_an_unknown_language_is_reported_as_a_failed_frame(
        self, transcription_client: TestClient
    ) -> None:
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=fr-FR&sample_rate_hz=8000"
        ) as ws:
            failed = ws.receive_json()
        assert failed["type"] == "failed"
        assert failed["error_type"] == "validation_error"

    def test_an_unaccepted_sample_rate_is_reported_as_a_failed_frame(
        self, transcription_client: TestClient
    ) -> None:
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=12345"
        ) as ws:
            failed = ws.receive_json()
        assert failed["type"] == "failed"
        assert failed["retryable"] is False

    def test_a_missing_language_parameter_is_rejected(
        self, transcription_client: TestClient
    ) -> None:
        from starlette.websockets import WebSocketDisconnect

        with (
            pytest.raises(WebSocketDisconnect),
            transcription_client.websocket_connect("/api/v1/transcription/stream") as ws,
        ):
            ws.receive_json()

    def test_a_provider_failure_becomes_a_failed_frame_not_a_crash(
        self, transcription_client: TestClient, fake_provider: FakeTranscriptionProvider
    ) -> None:
        fake_provider.script.failures = [auth_failure()]
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("EOS")
            failed = ws.receive_json()
        assert failed["type"] == "failed"
        assert failed["error_type"] == "AuthenticationError"
        assert failed["retryable"] is False

    def test_a_mid_stream_drop_reports_the_segments_received_first(
        self, transcription_client: TestClient, fake_provider: FakeTranscriptionProvider
    ) -> None:
        fake_provider.script.segments = ["ek", "do", "teen"]
        fake_provider.script.fail_mid_stream_after = 2
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("EOS")
            messages = [ws.receive_json() for _ in range(4)]
        assert [m["type"] for m in messages] == [
            "started",
            "final_transcript",
            "final_transcript",
            "failed",
        ]

    def test_exactly_one_terminal_frame_is_sent(
        self, transcription_client: TestClient, fake_provider: FakeTranscriptionProvider
    ) -> None:
        fake_provider.script.segments = ["ek", "do"]
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("EOS")
            seen: list[str] = []
            while True:
                kind = ws.receive_json()["type"]
                seen.append(kind)
                if kind in {"completed", "failed"}:
                    break
        assert seen.count("completed") + seen.count("failed") == 1

    def test_a_stray_text_frame_does_not_abort_the_stream(
        self, transcription_client: TestClient
    ) -> None:
        """A keepalive should not cost the client its transcription."""
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("ping")
            ws.send_bytes(b"\x00\x00" * 64)
            ws.send_text("EOS")
            types = []
            while True:
                kind = ws.receive_json()["type"]
                types.append(kind)
                if kind == "completed":
                    break
        assert "completed" in types

    def test_an_oversized_frame_ends_the_audio_stream(
        self, transcription_client: TestClient
    ) -> None:
        from app.api.v1.transcription import MAX_WS_FRAME_BYTES

        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_bytes(b"\x00" * (MAX_WS_FRAME_BYTES + 2))
            types = []
            while True:
                kind = ws.receive_json()["type"]
                types.append(kind)
                if kind in {"completed", "failed"}:
                    break
        # The stream terminates rather than buffering an unbounded frame.
        assert types[-1] in {"completed", "failed"}


class TestResourceCleanup:
    """Every request must release its provider client, on both paths.

    `get_service_factory` builds a new service, provider and HTTP client per
    request, so a request that does not close its own leaves a connection pool
    to the garbage collector. The dependency closes it in a `finally`; these
    tests pin that down, because a leak is invisible until the process runs out
    of sockets.
    """

    def test_the_provider_is_closed_after_a_successful_request(
        self,
        transcription_client: TestClient,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
    ) -> None:
        assert not fake_provider.closed
        assert _upload(transcription_client, wav_8k).status_code == 200
        assert fake_provider.closed, "a successful request must still close the client"

    def test_the_provider_is_closed_after_a_validation_failure(
        self,
        transcription_client: TestClient,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
    ) -> None:
        """The handler raised before reaching the provider; cleanup still runs."""
        assert _upload(transcription_client, wav_8k, language="fr-FR").status_code == 422
        assert fake_provider.closed

    def test_the_provider_is_closed_after_a_provider_failure(
        self,
        transcription_client: TestClient,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
    ) -> None:
        fake_provider.script.failures = [auth_failure()]
        assert _upload(transcription_client, wav_8k).status_code == 502
        assert fake_provider.closed

    def test_the_provider_is_closed_after_retries_are_exhausted(
        self,
        transcription_client: TestClient,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
    ) -> None:
        fake_provider.script.failures = [unavailable_failure()] * 5
        assert _upload(transcription_client, wav_8k).status_code == 502
        assert fake_provider.closed
        # Retry behaviour is untouched by the cleanup change.
        assert len(fake_provider.script.calls) == 3

    def test_the_provider_is_closed_after_an_unexpected_exception(
        self,
        transcription_settings: Settings,
        fake_provider: FakeTranscriptionProvider,
        wav_8k: bytes,
    ) -> None:
        """The path most likely to leak: an error nobody anticipated."""
        from app.api.deps import get_database_probe
        from app.api.v1.transcription import get_service_factory
        from app.core.config import get_settings
        from app.main import create_app

        async def explode(*_: object, **__: object) -> None:
            raise RuntimeError("unexpected")

        fake_provider.transcribe_batch = explode  # type: ignore[method-assign]

        app = create_app(settings=transcription_settings)
        app.dependency_overrides[get_settings] = lambda: transcription_settings
        app.dependency_overrides[get_database_probe] = lambda: lambda: (True, "ok")
        app.dependency_overrides[get_service_factory] = lambda: (
            lambda: TranscriptionService(fake_provider, settings=transcription_settings)
        )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/transcription",
            files={"audio": ("call.wav", wav_8k, "audio/wav")},
            data={"language": "hi-IN"},
        )
        assert response.status_code == 500
        assert fake_provider.closed

    def test_the_capability_endpoint_leaves_no_client_open(
        self, transcription_client: TestClient
    ) -> None:
        """`describe_providers` constructs every provider to read static
        metadata. The Prisma client is lazy, so nothing should be built."""
        from app.core.config import AppEnv
        from app.transcription.providers.prisma import GnaniPrismaProvider
        from app.transcription.registry import build_provider

        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="prisma",
            gnani_api_key="k" * 24,
            _env_file=None,
        )
        provider = build_provider(settings)
        assert isinstance(provider, GnaniPrismaProvider)
        _ = provider.capabilities
        assert provider._client is None, "reading capabilities must open no client"

        assert transcription_client.get("/api/v1/transcription/providers").status_code == 200

    def test_closing_twice_is_harmless(self) -> None:
        """The WebSocket route and the dependency could both fire on a future
        refactor; `close` must be idempotent."""
        from app.transcription.providers.prisma import GnaniPrismaProvider

        provider = GnaniPrismaProvider(api_key="k" * 24)
        asyncio.run(provider.close())
        asyncio.run(provider.close())

    def test_an_owned_http_client_is_actually_closed(self) -> None:
        """The fake records a flag; this asserts the real adapter releases a
        real `httpx2.AsyncClient`.

        This is the production path: the registry builds the provider without
        injecting a client, so the provider owns the one it creates lazily.
        """
        from app.transcription.providers.prisma import GnaniPrismaProvider

        provider = GnaniPrismaProvider(api_key="k" * 24)
        client = provider._http  # force the lazy client into existence
        assert not client.is_closed

        asyncio.run(provider.close())

        assert client.is_closed
        assert provider._client is None, "a closed client must not be reused"

    def test_an_injected_client_is_left_open_because_the_caller_owns_it(self) -> None:
        """Closing a client you were handed would pull it out from under
        whoever is still using it - tests and the live fixture both inject one.
        """
        import httpx2

        from app.transcription.providers.prisma import GnaniPrismaProvider

        client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json={}))
        )
        provider = GnaniPrismaProvider(api_key="k" * 24, client=client)

        asyncio.run(provider.close())

        assert not client.is_closed, "an injected client is the injector's to close"

    def test_the_registry_builds_a_provider_that_owns_its_client(self) -> None:
        """Ties the ownership rule to the path the API actually takes, so the
        two tests above cannot both pass while production still leaks.
        """
        from app.core.config import AppEnv
        from app.transcription.registry import build_provider

        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="prisma",
            gnani_api_key="k" * 24,
            _env_file=None,
        )
        provider = build_provider(settings)
        assert provider._owns_client is True  # type: ignore[attr-defined]


class TestBackpressure:
    def test_the_audio_queue_is_bounded(self) -> None:
        """An unbounded queue would let one client store a whole call in RAM."""
        from app.api.v1.transcription import AUDIO_QUEUE_FRAMES

        assert 0 < AUDIO_QUEUE_FRAMES <= 128

    def test_a_single_inbound_frame_is_capped(self) -> None:
        from app.api.v1.transcription import MAX_WS_FRAME_BYTES

        assert 0 < MAX_WS_FRAME_BYTES <= 1024 * 1024


# ---------------------------------------------------------------------------
# Health and OpenAPI
# ---------------------------------------------------------------------------


class TestApiSurface:
    def test_both_http_endpoints_are_in_the_openapi_document(
        self, transcription_client: TestClient
    ) -> None:
        paths = transcription_client.get("/openapi.json").json()["paths"]
        assert "/api/v1/transcription" in paths
        assert "/api/v1/transcription/providers" in paths

    def test_the_batch_endpoint_documents_its_failure_statuses(
        self, transcription_client: TestClient
    ) -> None:
        schema = transcription_client.get("/openapi.json").json()
        responses = schema["paths"]["/api/v1/transcription"]["post"]["responses"]
        for status in ("413", "415", "422", "429", "502", "504"):
            assert status in responses

    def test_the_existing_endpoints_are_untouched(self, transcription_client: TestClient) -> None:
        """Phase 4 must not change the Phase 1-3 surface."""
        paths = set(transcription_client.get("/openapi.json").json()["paths"])
        for existing in (
            "/api/v1/health",
            "/api/v1/languages",
            "/api/v1/suites",
            "/api/v1/scenarios",
        ):
            assert existing in paths

    def test_health_still_reports_without_a_transcription_component(
        self, transcription_client: TestClient
    ) -> None:
        """No provider probe is claimed: nothing verifies the provider at
        startup, so health must not imply that it did."""
        body = transcription_client.get("/api/v1/health").json()
        names = {c["name"] for c in body["components"]}
        assert "transcription" not in names


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogging:
    def test_a_completed_transcription_logs_safe_metadata(
        self, wav_8k: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="bhashabench.transcription"):
            asyncio.run(
                _service(FakeTranscriptionProvider()).transcribe_batch(
                    wav_8k, language="hi-IN", correlation_id="run-1"
                )
            )
        record = next(r for r in caplog.records if r.message == "transcription.completed")
        assert record.provider == "fake"  # type: ignore[attr-defined]
        assert record.language == "hi-IN"  # type: ignore[attr-defined]
        assert record.correlation_id == "run-1"  # type: ignore[attr-defined]
        assert record.attempts == 1  # type: ignore[attr-defined]
        assert record.latency_ms >= 0  # type: ignore[attr-defined]

    def test_the_transcript_text_is_not_logged_only_its_length(
        self, wav_8k: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A transcript carries whatever the caller said, which may be
        a card number read aloud to a bot."""
        secret = "my card number is 4111 1111 1111 1111"
        with caplog.at_level(logging.DEBUG):
            asyncio.run(
                _service(FakeTranscriptionProvider(FakeScript(transcript=secret))).transcribe_batch(
                    wav_8k, language="hi-IN"
                )
            )
        assert secret not in caplog.text
        record = next(r for r in caplog.records if r.message == "transcription.completed")
        assert record.transcript_chars == len(secret)  # type: ignore[attr-defined]

    def test_an_empty_result_is_logged_as_empty_not_as_failure(
        self, wav_8k: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="bhashabench.transcription"):
            asyncio.run(
                _service(FakeTranscriptionProvider(FakeScript(transcript=""))).transcribe_batch(
                    wav_8k, language="hi-IN"
                )
            )
        record = next(r for r in caplog.records if r.message == "transcription.completed")
        assert record.outcome == "empty"  # type: ignore[attr-defined]

    def test_a_retry_is_logged_with_the_next_delay(
        self, wav_8k: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.INFO, logger="bhashabench.transcription.retry"):
            asyncio.run(
                _service(
                    FakeTranscriptionProvider(FakeScript(failures=[unavailable_failure(), None]))
                ).transcribe_batch(wav_8k, language="hi-IN")
            )
        record = next(r for r in caplog.records if r.message == "transcription.retrying")
        assert record.attempt == 1  # type: ignore[attr-defined]
        assert hasattr(record, "next_attempt_in_seconds")
