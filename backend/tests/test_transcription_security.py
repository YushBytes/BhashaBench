"""Security properties of the transcription subsystem.

Each test here guards a property that is cheap to assert and expensive to
notice the absence of: a credential in a log, a traversal path reaching the
filesystem, an unbounded read, a secret in an API response.

The repository's second rule is "never commit a secret". These tests cover the
adjacent failure, which is *leaking* one that was correctly configured - via a
log aggregator, an error body, or a frontend bundle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.transcription import audio as audio_tools
from app.transcription.errors import AuthenticationError
from app.transcription.models import AudioEncoding, TranscriptionRequest
from app.transcription.providers.prisma import GnaniPrismaProvider
from app.transcription.redaction import (
    PLACEHOLDER,
    mask_secret,
    redact,
    redact_headers,
)
from app.transcription.registry import describe_providers

SECRET = "gnani_live_key_9f3a21c7b85e4d06af12"
"""A fabricated credential-shaped string. Every test below asserts it does not
escape through some channel."""

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Redaction primitives
# ---------------------------------------------------------------------------


class TestRedaction:
    @pytest.mark.parametrize(
        "text",
        [
            f"api_key={SECRET}",
            f"api-key: {SECRET}",
            f'{{"api_key": "{SECRET}"}}',
            f"X-API-Key-ID: {SECRET}",
            f"authorization=Bearer {SECRET}",
            f"access_token={SECRET}",
            f"secret_key={SECRET}",
            f"password={SECRET}",
        ],
    )
    def test_credential_shaped_assignments_are_replaced(self, text: str) -> None:
        cleaned = redact(text)
        assert SECRET not in cleaned
        assert PLACEHOLDER in cleaned

    def test_a_password_in_a_url_is_replaced(self) -> None:
        """A DATABASE_URL in an exception message is the classic case."""
        cleaned = redact("postgresql://bhashabench:s3cr3tpw@localhost:5434/db")
        assert "s3cr3tpw" not in cleaned
        assert "bhashabench" in cleaned  # the user is not the secret
        assert "localhost:5434" in cleaned  # nor is the host

    def test_ordinary_text_is_left_alone(self) -> None:
        message = "could not reach https://api.vachana.ai/stt/v3 after 3 attempts"
        assert redact(message) == message

    def test_it_accepts_an_exception_rather_than_requiring_str(self) -> None:
        """Callers pass exceptions; requiring `str()` is easy to forget."""
        assert SECRET not in redact(ValueError(f"api_key={SECRET}"))

    def test_sensitive_headers_are_masked_but_their_names_kept(self) -> None:
        """Knowing which header was sent is what you need to debug a 401."""
        cleaned = redact_headers({"X-API-Key-ID": SECRET, "Content-Type": "multipart/form-data"})
        assert cleaned["X-API-Key-ID"] == PLACEHOLDER
        assert cleaned["Content-Type"] == "multipart/form-data"

    @pytest.mark.parametrize("name", ["x-api-key-id", "X-API-KEY-ID", "Authorization", "cookie"])
    def test_header_matching_is_case_insensitive(self, name: str) -> None:
        """Prisma's own docs spell the same header two different ways."""
        assert redact_headers({name: SECRET})[name] == PLACEHOLDER

    def test_mask_secret_fingerprints_without_disclosing(self) -> None:
        masked = mask_secret(SECRET)
        assert SECRET not in masked
        assert masked.startswith("***")
        assert len(masked) < len(SECRET)

    def test_mask_secret_hides_a_short_secret_entirely(self) -> None:
        """Revealing four of six characters is not masking."""
        assert mask_secret("abc123") == PLACEHOLDER

    def test_mask_secret_describes_an_unset_value(self) -> None:
        assert mask_secret("") == "<unset>"
        assert mask_secret(None) == "<unset>"


# ---------------------------------------------------------------------------
# The credential never escapes
# ---------------------------------------------------------------------------


def _prisma(handler) -> GnaniPrismaProvider:  # type: ignore[no-untyped-def]
    return GnaniPrismaProvider(
        api_key=SECRET, client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )


def _request(audio: bytes) -> TranscriptionRequest:
    return TranscriptionRequest(audio=audio, language="hi-IN", encoding=AudioEncoding.WAV)


class TestCredentialContainment:
    @pytest.mark.parametrize("status", [401, 402, 403, 429, 500])
    def test_no_error_message_contains_the_key(self, wav_8k: bytes, status: int) -> None:
        with pytest.raises(Exception) as caught:
            asyncio.run(
                _prisma(lambda _: httpx2.Response(status, json={})).transcribe_batch(
                    _request(wav_8k)
                )
            )
        assert SECRET not in str(caught.value)

    def test_a_401_message_fingerprints_the_key_instead(self, wav_8k: bytes) -> None:
        """Enough to tell two environments apart, not enough to authenticate."""
        with pytest.raises(AuthenticationError) as caught:
            asyncio.run(
                _prisma(lambda _: httpx2.Response(401, json={})).transcribe_batch(_request(wav_8k))
            )
        assert SECRET not in str(caught.value)
        assert mask_secret(SECRET) in str(caught.value)

    def test_a_provider_echoing_the_key_back_is_redacted(self, wav_8k: bytes) -> None:
        """Providers do echo requests into error bodies. This is the second
        line of defence; the first is never putting it in a message."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(400, json={"message": f"invalid request with api_key={SECRET}"})

        with pytest.raises(Exception) as caught:
            asyncio.run(_prisma(handler).transcribe_batch(_request(wav_8k)))
        assert SECRET not in str(caught.value)

    def test_a_transport_error_carrying_the_url_is_redacted(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError(f"failed connecting with api_key={SECRET}")

        with pytest.raises(Exception) as caught:
            asyncio.run(_prisma(handler).transcribe_batch(_request(wav_8k)))
        assert SECRET not in str(caught.value)

    def test_nothing_logged_during_a_transcription_contains_the_key(
        self, wav_8k: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            asyncio.run(
                _prisma(
                    lambda _: httpx2.Response(
                        200,
                        json={
                            "success": True,
                            "transcript": "haan",
                            "request_id": "r1",
                            "model": "prisma-v3.0",
                            "detected_language_code": "hi-IN",
                            "processing_time": 0.1,
                        },
                    )
                ).transcribe_batch(_request(wav_8k))
            )
        assert SECRET not in caplog.text

    def test_nothing_logged_during_provider_selection_contains_the_key(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="prisma",
            gnani_api_key=SECRET,
            _env_file=None,
        )
        with caplog.at_level(logging.DEBUG):
            describe_providers(settings)
        assert SECRET not in caplog.text

    def test_the_providers_endpoint_response_contains_no_key(self) -> None:
        from app.api.deps import get_database_probe
        from app.core.config import get_settings
        from app.main import create_app

        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            transcription_provider="prisma",
            gnani_api_key=SECRET,
            _env_file=None,
        )
        app = create_app(settings=settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_database_probe] = lambda: lambda: (True, "ok")
        with TestClient(app) as client:
            raw = client.get("/api/v1/transcription/providers").text
        assert SECRET not in raw

    def test_the_providers_endpoint_reports_no_database_url_either(self) -> None:
        from app.api.deps import get_database_probe
        from app.core.config import get_settings
        from app.main import create_app

        settings = Settings(
            app_env=AppEnv.TEST,
            secret_key="test-secret-key-not-used-for-anything",
            database_url="postgresql+psycopg://u:dbpassword123@localhost:5432/x",
            transcription_provider="fake",
            _env_file=None,
        )
        app = create_app(settings=settings)
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_database_probe] = lambda: lambda: (True, "ok")
        with TestClient(app) as client:
            raw = client.get("/api/v1/transcription/providers").text
        assert "dbpassword123" not in raw

    def test_an_error_response_body_never_carries_a_key(
        self, transcription_client: TestClient, fake_provider, wav_8k: bytes
    ) -> None:  # type: ignore[no-untyped-def]
        from app.transcription.errors import AuthenticationError as AuthError

        fake_provider.script.failures = [
            AuthError(f"rejected key api_key={SECRET}", provider="fake")
        ]
        response = transcription_client.post(
            "/api/v1/transcription",
            files={"audio": ("call.wav", wav_8k, "audio/wav")},
            data={"language": "hi-IN"},
        )
        assert SECRET not in response.text

    def test_a_stream_failure_frame_never_carries_a_key(
        self, transcription_client: TestClient, fake_provider
    ) -> None:  # type: ignore[no-untyped-def]
        from app.transcription.errors import AuthenticationError as AuthError

        fake_provider.script.failures = [AuthError(f"api_key={SECRET} rejected", provider="fake")]
        with transcription_client.websocket_connect(
            "/api/v1/transcription/stream?language=hi-IN&sample_rate_hz=8000"
        ) as ws:
            ws.send_text("EOS")
            frame = ws.receive_json()
        assert SECRET not in json.dumps(frame)


class TestInternalsAreNotLeaked:
    def test_an_unexpected_error_returns_a_generic_message(
        self,
        transcription_settings: Settings,
        fake_provider,
        wav_8k: bytes,
    ) -> None:  # type: ignore[no-untyped-def]
        """A stack trace or a module path is information a client does not need.

        Built with `raise_server_exceptions=False` because `TestClient`
        otherwise re-raises the exception instead of letting the application's
        catch-all handler shape a response - which would test Starlette's test
        harness rather than our error envelope.
        """
        from app.api.deps import get_database_probe
        from app.api.v1.transcription import get_service_factory
        from app.core.config import get_settings
        from app.main import create_app
        from app.services.transcription_service import TranscriptionService

        async def explode(*_: object, **__: object) -> None:
            raise RuntimeError("internal detail at /srv/app/secret_module.py line 42")

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
        assert "secret_module" not in response.text
        assert response.json()["error"]["message"] == ("An unexpected internal error occurred.")

    def test_a_provider_html_error_page_is_not_relayed_whole(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(502, text="<html>" + "detail " * 10_000 + "</html>")

        with pytest.raises(Exception) as caught:
            asyncio.run(_prisma(handler).transcribe_batch(_request(wav_8k)))
        assert len(str(caught.value)) < 1000


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------


class TestFileHandling:
    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "/etc/shadow",
            "\\\\server\\share\\secret.wav",
        ],
    )
    def test_a_traversal_filename_is_neutralised_in_the_outbound_request(
        self, wav_8k: bytes, hostile: str
    ) -> None:
        seen: dict[str, bytes] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = request.content
            return httpx2.Response(
                200,
                json={
                    "success": True,
                    "transcript": "ok",
                    "request_id": "r",
                    "model": "prisma-v3.0",
                    "detected_language_code": "hi-IN",
                    "processing_time": 0.1,
                },
            )

        asyncio.run(
            _prisma(handler).transcribe_batch(
                TranscriptionRequest(
                    audio=wav_8k,
                    language="hi-IN",
                    encoding=AudioEncoding.WAV,
                    metadata={"filename": hostile},
                )
            )
        )
        body = seen["body"]
        assert hostile.encode() not in body
        assert b"../" not in body
        assert b"..\\" not in body

    def test_an_upload_filename_never_reaches_the_filesystem(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        """Audio stays in memory; nothing is written under a client-chosen name."""
        target = REPO_ROOT / "etc_passwd_marker"
        response = transcription_client.post(
            "/api/v1/transcription",
            files={"audio": ("../../etc_passwd_marker", wav_8k, "audio/wav")},
            data={"language": "hi-IN"},
        )
        assert response.status_code == 200
        assert not target.exists()

    def test_the_upload_read_is_capped(self, transcription_client: TestClient) -> None:
        """`UploadFile` spools to a temp file, so an uncapped read lets one
        request write an arbitrary amount to disk before any size check."""
        import inspect

        from app.api.v1 import transcription as module

        source = inspect.getsource(module.transcribe_file)
        assert "audio.read(limit + 1)" in source
        assert "audio.read()" not in source

    def test_a_declared_content_type_is_not_trusted(
        self, transcription_client: TestClient, audio_fixtures: Path
    ) -> None:
        """Claiming `audio/wav` for an HTML page must not get it accepted."""
        payload = (audio_fixtures / "not_audio.wav").read_bytes()
        response = transcription_client.post(
            "/api/v1/transcription",
            files={"audio": ("real.wav", payload, "audio/wav")},
            data={"language": "hi-IN"},
        )
        assert response.status_code == 415

    def test_no_temporary_file_is_left_behind(
        self, transcription_client: TestClient, wav_8k: bytes
    ) -> None:
        import tempfile

        temp = Path(tempfile.gettempdir())
        before = set(temp.glob("*"))
        transcription_client.post(
            "/api/v1/transcription",
            files={"audio": ("call.wav", wav_8k, "audio/wav")},
            data={"language": "hi-IN"},
        )
        leaked = {
            p
            for p in set(temp.glob("*")) - before
            # Other processes write to the temp directory too; only an
            # audio-shaped leftover would be ours.
            if p.suffix in {".wav", ".pcm", ".raw"}
        }
        assert leaked == set()

    def test_the_safe_filename_helper_is_what_the_adapter_uses(self) -> None:
        """A second sanitiser would be a second thing to get wrong."""
        import inspect

        from app.transcription.providers import prisma as module

        assert "safe_filename" in inspect.getsource(module.GnaniPrismaProvider)


# ---------------------------------------------------------------------------
# Repository hygiene
# ---------------------------------------------------------------------------


class TestRepositoryHygiene:
    def test_the_env_example_declares_the_key_with_no_value(self) -> None:
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "GNANI_API_KEY=" in text
        for line in text.splitlines():
            if line.startswith("GNANI_API_KEY="):
                assert line.strip() == "GNANI_API_KEY=", "a placeholder must stay empty"

    def test_the_env_example_declares_every_phase_4_setting(self) -> None:
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        for name in (
            "TRANSCRIPTION_PROVIDER",
            "TRANSCRIPTION_TIMEOUT_SECONDS",
            "TRANSCRIPTION_MAX_ATTEMPTS",
            "TRANSCRIPTION_MAX_UPLOAD_BYTES",
            "TRANSCRIPTION_LIVE_TESTS",
            "GNANI_API_KEY",
            "GNANI_API_BASE_URL",
            "GNANI_STT_MODEL",
        ):
            assert name in text, name

    def test_dot_env_is_still_ignored(self) -> None:
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert ".env" in ignore

    def test_no_source_file_hardcodes_a_credential(self) -> None:
        """Checks the shape, not a known value: a real key never existed here."""
        import re

        suspicious = re.compile(
            r"""(?ix)
            (gnani[_-]?api[_-]?key|api[_-]?key[_-]?id)
            \s*[:=]\s*
            ["'][A-Za-z0-9_\-]{16,}["']
            """
        )
        offenders: list[str] = []
        for path in (REPO_ROOT / "backend" / "app").rglob("*.py"):
            if suspicious.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == []

    def test_the_frontend_bundle_carries_no_provider_credential(self) -> None:
        """Next.js only exposes NEXT_PUBLIC_* variables, but the frontend
        should not reference the Gnani key at all."""
        frontend = REPO_ROOT / "frontend"
        offenders: list[str] = []
        for pattern in ("*.ts", "*.tsx", "*.mjs", "*.json"):
            for path in frontend.rglob(pattern):
                if "node_modules" in path.parts or ".next" in path.parts:
                    continue
                if "GNANI_API_KEY" in path.read_text(encoding="utf-8", errors="ignore"):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == []

    def test_the_audio_fixtures_are_binary_safe_in_git(self) -> None:
        """A `.pcm` under `* text=auto` risks line-ending rewriting of samples."""
        attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
        assert "*.pcm" in attributes
        assert "*.wav binary" in attributes

    def test_the_fixtures_stay_small_enough_for_a_repository(self) -> None:
        audio_dir = REPO_ROOT / "backend" / "tests" / "fixtures" / "audio"
        total = sum(p.stat().st_size for p in audio_dir.iterdir() if p.is_file())
        assert total < 1024 * 1024, f"audio fixtures total {total} bytes"


class TestAudioLimitsAreEnforced:
    def test_the_provider_ceiling_cannot_be_raised_by_configuration(self) -> None:
        provider = GnaniPrismaProvider(api_key=SECRET, max_audio_bytes=1 << 40)
        from app.transcription.providers import prisma_contract as contract

        assert provider.capabilities.max_batch_bytes == contract.BATCH_MAX_BYTES_PER_FILE

    def test_validation_rejects_before_allocating_more(self, wav_8k: bytes) -> None:
        """Size is checked first so a huge upload costs nothing to refuse."""
        from app.transcription.errors import AudioTooLargeError

        with pytest.raises(AudioTooLargeError):
            audio_tools.validate(
                wav_8k * 10, accepted=audio_tools.CONTAINER_ENCODINGS, max_bytes=1024
            )
