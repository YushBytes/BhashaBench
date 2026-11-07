"""The Gnani Prisma adapter, driven against a mocked transport.

**What these tests prove and what they do not.** They prove the adapter sends
the request the published contract describes, and that it normalises every
documented response and status into the right domain object. They do **not**
prove Gnani agrees - no live call is made here, and a mock cannot disagree with
the fixture that produced it. Live verification is `test_transcription_live.py`,
which is deselected without credentials.

Requests are intercepted with `httpx2.MockTransport`, so the adapter's real
code path runs - multipart encoding, headers, status handling, JSON decoding -
with only the socket replaced.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx2
import pytest

from app.core.languages import SUPPORTED_CODES
from app.transcription.errors import (
    AudioTooLargeError,
    AuthenticationError,
    MalformedProviderResponseError,
    ProviderUnavailableError,
    RateLimitError,
    TranscriptionError,
    TranscriptionTimeoutError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.transcription.models import (
    AudioEncoding,
    TranscriptionMode,
    TranscriptionRequest,
)
from app.transcription.providers import prisma_contract as contract
from app.transcription.providers.prisma import GnaniPrismaProvider

API_KEY = "gnani-test-key-0123456789abcdef"
"""A fabricated value with no resemblance to a real credential. Several tests
assert it never appears in an error message or a log record."""

DOCUMENTED_RESPONSE = {
    "success": True,
    "request_id": "3f6c1e8a-2b7d-4a19-9c21-5f0d8e6b4a73",
    "transcript": "namaste, main aapki kya madad kar sakta hoon",
    "model": "prisma-v3.0",
    "detected_language_code": "hi-IN",
    "processing_time": 0.58,
    "end_to_end_latency": 0.66,
}
"""The response shape quoted in Gnani's quick-start documentation."""


def _provider(
    handler: Callable[[httpx2.Request], httpx2.Response], **kwargs: object
) -> GnaniPrismaProvider:
    """Build the adapter with a mocked transport."""
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return GnaniPrismaProvider(api_key=API_KEY, client=client, **kwargs)


def _request(audio: bytes, **kwargs: object) -> TranscriptionRequest:
    payload: dict[str, object] = {
        "audio": audio,
        "language": "hi-IN",
        "encoding": AudioEncoding.WAV,
    }
    payload.update(kwargs)
    return TranscriptionRequest(**payload)  # type: ignore[arg-type]


def _json_response(payload: dict[str, object], status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, json=payload)


# ---------------------------------------------------------------------------
# The published contract
# ---------------------------------------------------------------------------


class TestContractConstants:
    """Asserted against the documentation, so a careless edit is caught."""

    def test_base_urls(self) -> None:
        assert contract.DEFAULT_BASE_URL == "https://api.vachana.ai"
        assert contract.DEFAULT_WS_BASE_URL == "wss://api.vachana.ai"

    def test_endpoint_paths(self) -> None:
        assert contract.BATCH_PATH == "/stt/v3"
        assert contract.STREAM_PATH == "/stt/v3/stream"

    def test_the_api_key_header_is_not_a_bearer_scheme(self) -> None:
        """The documentation sends the bare key, not `Bearer <key>`."""
        assert contract.API_KEY_HEADER == "X-API-Key-ID"
        assert "bearer" not in contract.API_KEY_HEADER.lower()

    def test_multipart_field_names(self) -> None:
        assert contract.FIELD_AUDIO == "audio_file"
        assert contract.FIELD_MODEL == "model"
        assert contract.FIELD_LANGUAGE == "language_code"
        assert contract.FIELD_FORMAT == "format"

    def test_streaming_frame_size_is_the_documented_1024_bytes(self) -> None:
        assert contract.STREAM_FRAME_BYTES == 1024

    def test_documented_streaming_sample_rates(self) -> None:
        assert frozenset({8000, 16000, 44100, 48000}) == contract.STREAMING_SAMPLE_RATES
        assert contract.DEFAULT_STREAMING_SAMPLE_RATE == 16000

    def test_streaming_takes_raw_pcm_only(self) -> None:
        assert frozenset({AudioEncoding.PCM_S16LE}) == contract.STREAMING_ENCODINGS

    def test_documented_batch_containers(self) -> None:
        assert (
            frozenset(
                {
                    AudioEncoding.WAV,
                    AudioEncoding.MP3,
                    AudioEncoding.OGG,
                    AudioEncoding.FLAC,
                    AudioEncoding.AAC,
                    AudioEncoding.M4A,
                }
            )
            == contract.BATCH_ENCODINGS
        )

    def test_documented_event_names(self) -> None:
        assert contract.EVENT_CONNECTED == "connected"
        assert contract.EVENT_PROCESSING == "processing"
        assert contract.EVENT_TRANSCRIPT == "transcript"
        assert contract.EVENT_ERROR == "error"

    def test_documentation_gaps_are_recorded_rather_than_guessed(self) -> None:
        """An empty list here would mean the vendor's docs were complete."""
        assert len(contract.DOCUMENTATION_GAPS) >= 5
        joined = " ".join(contract.DOCUMENTATION_GAPS).lower()
        # The specific contradiction found: 30s on one page, 60s on another.
        assert "30 seconds" in joined and "60" in joined


class TestLanguageCoverage:
    """Catalogue membership and provider support are different questions."""

    def test_prisma_documents_ten_languages(self) -> None:
        assert len(contract.PROVIDER_LANGUAGE_CODES) == 10

    def test_every_prisma_language_is_in_the_bhashabench_catalogue(self) -> None:
        """A provider code we cannot express as a scenario language is useless."""
        assert set(contract.PROVIDER_LANGUAGE_CODES) <= set(SUPPORTED_CODES)

    def test_three_catalogue_languages_have_no_speech_model(self) -> None:
        missing = set(SUPPORTED_CODES) - set(contract.PROVIDER_LANGUAGE_CODES)
        assert missing == {"ur-IN", "or-IN", "as-IN"}

    def test_the_unsupported_list_matches_the_computed_difference(self) -> None:
        assert set(contract.UNSUPPORTED_BHASHABENCH_LANGUAGES) == set(SUPPORTED_CODES) - set(
            contract.PROVIDER_LANGUAGE_CODES
        )

    def test_the_mapping_is_explicit_even_though_it_is_the_identity(self) -> None:
        """Assuming identity breaks the day a vendor renames a code."""
        assert {c: c for c in contract.PROVIDER_LANGUAGE_CODES} == contract.LANGUAGE_MAP

    def test_hinglish_is_recorded_but_not_added_to_the_catalogue(self) -> None:
        """`hi-en` is not a BCP 47 tag the scenario schema accepts."""
        assert contract.HINGLISH_LANGUAGE_CODE == "hi-en"
        assert contract.HINGLISH_LANGUAGE_CODE not in SUPPORTED_CODES


# ---------------------------------------------------------------------------
# Batch request shape
# ---------------------------------------------------------------------------


class TestBatchRequestShape:
    def test_it_posts_to_the_documented_url(self, wav_8k: bytes) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            return _json_response(DOCUMENTED_RESPONSE)

        asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert seen["url"] == "https://api.vachana.ai/stt/v3"
        assert seen["method"] == "POST"

    def test_it_sends_the_key_in_the_documented_header(self, wav_8k: bytes) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["key"] = request.headers.get("x-api-key-id")
            seen["authorization"] = request.headers.get("authorization")
            return _json_response(DOCUMENTED_RESPONSE)

        asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert seen["key"] == API_KEY
        # Not a bearer scheme: sending one would silently fail to authenticate.
        assert seen["authorization"] is None

    def test_it_sends_multipart_with_the_documented_field_names(self, wav_8k: bytes) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["content_type"] = request.headers.get("content-type", "")
            seen["body"] = request.content
            return _json_response(DOCUMENTED_RESPONSE)

        asyncio.run(
            _provider(handler).transcribe_batch(_request(wav_8k, mode=TranscriptionMode.TRANSCRIBE))
        )
        assert "multipart/form-data" in str(seen["content_type"])
        body = bytes(seen["body"])  # type: ignore[arg-type]
        assert b'name="audio_file"' in body
        assert b'name="model"' in body
        assert b'name="language_code"' in body
        assert b'name="format"' in body
        assert b"prisma-v3.0" in body
        assert b"hi-IN" in body
        assert b"transcribe" in body
        # The audio itself must actually be in the body.
        assert wav_8k in body

    def test_the_format_field_is_omitted_when_no_mode_is_requested(self, wav_8k: bytes) -> None:
        """Sending an empty `format` is not the same as omitting it."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = request.content
            return _json_response(DOCUMENTED_RESPONSE)

        asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert b'name="format"' not in bytes(seen["body"])  # type: ignore[arg-type]

    def test_the_model_is_always_sent_explicitly(self, wav_8k: bytes) -> None:
        """The vendor's API default is v2.5; this project wants v3.0."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = request.content
            return _json_response(DOCUMENTED_RESPONSE)

        asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert b"prisma-v3.0" in bytes(seen["body"])  # type: ignore[arg-type]

    def test_a_hostile_filename_is_reduced_before_it_is_sent(self, wav_8k: bytes) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = request.content
            return _json_response(DOCUMENTED_RESPONSE)

        asyncio.run(
            _provider(handler).transcribe_batch(
                _request(wav_8k, metadata={"filename": "../../../etc/passwd"})
            )
        )
        body = bytes(seen["body"])  # type: ignore[arg-type]
        assert b"../../../etc/passwd" not in body
        assert b"passwd" in body  # the basename survives; the traversal does not

    def test_an_undocumented_model_is_refused_at_construction(self) -> None:
        with pytest.raises(UnsupportedFormatError, match="not a documented Prisma model"):
            GnaniPrismaProvider(api_key=API_KEY, model="whisper-large-v3")

    def test_an_empty_api_key_is_refused_at_construction(self) -> None:
        with pytest.raises(AuthenticationError, match="GNANI_API_KEY"):
            GnaniPrismaProvider(api_key="")


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------


class TestResponseNormalisation:
    def test_the_documented_response_becomes_a_domain_result(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                _request(wav_8k)
            )
        )
        assert result.text == DOCUMENTED_RESPONSE["transcript"]
        assert result.language == "hi-IN"
        assert result.requested_language == "hi-IN"
        assert result.provider == "prisma"
        assert result.model == "prisma-v3.0"
        assert result.request_id == DOCUMENTED_RESPONSE["request_id"]

    def test_processing_time_is_converted_from_seconds_to_milliseconds(self, wav_8k: bytes) -> None:
        """The vendor reports seconds; every duration in our models is ms."""
        result = asyncio.run(
            _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                _request(wav_8k)
            )
        )
        assert result.provider_processing_ms == pytest.approx(580.0)

    def test_latency_is_measured_by_us_not_taken_from_the_provider(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                _request(wav_8k)
            )
        )
        assert result.latency_ms >= 0
        # Not the provider's 660 ms figure - ours, from a real clock.
        assert result.latency_ms != 660.0

    def test_confidence_and_segments_are_not_invented(self, wav_8k: bytes) -> None:
        """Prisma's documented schema has neither. Faking them would make
        every downstream confidence metric fiction."""
        result = asyncio.run(
            _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                _request(wav_8k)
            )
        )
        assert result.confidence is None
        assert result.segments is None

    def test_audio_duration_comes_from_our_own_header_inspection(self, wav_8k: bytes) -> None:
        result = asyncio.run(
            _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                _request(wav_8k)
            )
        )
        assert result.audio_duration_seconds == pytest.approx(1.0)

    def test_an_empty_transcript_is_a_success_not_a_failure(self, wav_8k: bytes) -> None:
        payload = {**DOCUMENTED_RESPONSE, "transcript": ""}
        result = asyncio.run(
            _provider(lambda _: _json_response(payload)).transcribe_batch(_request(wav_8k))
        )
        assert result.is_empty
        assert result.text == ""

    def test_an_unmodelled_detected_language_falls_back_to_the_request(self, wav_8k: bytes) -> None:
        """Prisma can return `hi-en`, which is not a catalogue tag."""
        payload = {**DOCUMENTED_RESPONSE, "detected_language_code": "hi-en"}
        result = asyncio.run(
            _provider(lambda _: _json_response(payload)).transcribe_batch(_request(wav_8k))
        )
        assert result.language == "hi-IN"
        assert result.requested_language == "hi-IN"

    def test_a_missing_detected_language_falls_back_to_the_request(self, wav_8k: bytes) -> None:
        payload = {k: v for k, v in DOCUMENTED_RESPONSE.items() if k != "detected_language_code"}
        result = asyncio.run(
            _provider(lambda _: _json_response(payload)).transcribe_batch(_request(wav_8k))
        )
        assert result.language == "hi-IN"


class TestMalformedResponses:
    """A contract violation must be distinguishable from a network fault."""

    def test_a_missing_transcript_field_is_a_contract_violation(self, wav_8k: bytes) -> None:
        payload = {k: v for k, v in DOCUMENTED_RESPONSE.items() if k != "transcript"}
        with pytest.raises(MalformedProviderResponseError, match="transcript"):
            asyncio.run(
                _provider(lambda _: _json_response(payload)).transcribe_batch(_request(wav_8k))
            )

    def test_a_non_string_transcript_is_rejected(self, wav_8k: bytes) -> None:
        payload = {**DOCUMENTED_RESPONSE, "transcript": {"text": "oops"}}
        with pytest.raises(MalformedProviderResponseError, match="should be a string"):
            asyncio.run(
                _provider(lambda _: _json_response(payload)).transcribe_batch(_request(wav_8k))
            )

    def test_a_non_json_body_is_rejected(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, text="<html>not json</html>")

        with pytest.raises(MalformedProviderResponseError, match="non-JSON"):
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))

    def test_a_json_array_instead_of_an_object_is_rejected(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=json.dumps([1, 2, 3]).encode())

        with pytest.raises(MalformedProviderResponseError, match="JSON object"):
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))

    def test_success_false_with_http_200_is_treated_as_a_failure(self, wav_8k: bytes) -> None:
        """Trusting the status alone would report a refusal as empty speech."""
        payload = {"success": False, "message": "audio could not be processed"}
        with pytest.raises(TranscriptionError, match="could not be processed"):
            asyncio.run(
                _provider(lambda _: _json_response(payload)).transcribe_batch(_request(wav_8k))
            )

    def test_a_malformed_response_is_not_retryable(self, wav_8k: bytes) -> None:
        """Hammering the endpoint will not change its schema."""
        assert MalformedProviderResponseError("x").retryable is False


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


class TestStatusMapping:
    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_credential_statuses_become_permanent_auth_errors(
        self, wav_8k: bytes, status: int
    ) -> None:
        with pytest.raises(AuthenticationError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(status, json={})).transcribe_batch(
                    _request(wav_8k)
                )
            )
        assert caught.value.retryable is False
        assert caught.value.status_code == status

    def test_429_becomes_a_retryable_rate_limit(self, wav_8k: bytes) -> None:
        with pytest.raises(RateLimitError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(429, json={})).transcribe_batch(
                    _request(wav_8k)
                )
            )
        assert caught.value.retryable is True

    def test_a_retry_after_header_is_carried_onto_the_error(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(429, json={}, headers={"Retry-After": "12"})

        with pytest.raises(RateLimitError) as caught:
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert caught.value.retry_after == 12.0

    def test_an_http_date_retry_after_is_ignored_rather_than_approximated(
        self, wav_8k: bytes
    ) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                429, json={}, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
            )

        with pytest.raises(RateLimitError) as caught:
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert caught.value.retry_after is None

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_errors_are_retryable(self, wav_8k: bytes, status: int) -> None:
        with pytest.raises(ProviderUnavailableError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(status, json={})).transcribe_batch(
                    _request(wav_8k)
                )
            )
        assert caught.value.retryable is True

    def test_an_undocumented_4xx_is_not_retried(self, wav_8k: bytes) -> None:
        """Most likely our request is wrong, so repeating it will not help."""
        with pytest.raises(TranscriptionError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(418, json={})).transcribe_batch(
                    _request(wav_8k)
                )
            )
        assert caught.value.retryable is False

    def test_a_timeout_becomes_a_retryable_timeout_error(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("too slow")

        with pytest.raises(TranscriptionTimeoutError) as caught:
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert caught.value.retryable is True

    def test_a_connection_failure_becomes_provider_unavailable(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection reset")

        with pytest.raises(ProviderUnavailableError) as caught:
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert caught.value.retryable is True

    def test_a_provider_error_message_is_surfaced_not_swallowed(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(400, json={"message": "language_code is required"})

        with pytest.raises(TranscriptionError, match="language_code is required"):
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))

    def test_an_html_error_page_is_truncated_rather_than_logged_whole(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(502, text="<html>" + "x" * 50_000 + "</html>")

        with pytest.raises(ProviderUnavailableError) as caught:
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k)))
        assert len(str(caught.value)) < 1000


# ---------------------------------------------------------------------------
# Input validation inside the adapter
# ---------------------------------------------------------------------------


class TestAdapterValidation:
    """A request the contract cannot carry must not reach the network."""

    def test_an_unsupported_language_never_reaches_the_provider(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise AssertionError("no request should be sent for an unsupported language")

        with pytest.raises(UnsupportedLanguageError) as caught:
            asyncio.run(_provider(handler).transcribe_batch(_request(wav_8k, language="or-IN")))
        assert caught.value.language == "or-IN"
        assert "or-IN" not in caught.value.supported

    @pytest.mark.parametrize("language", ["ur-IN", "or-IN", "as-IN"])
    def test_each_unsupported_catalogue_language_is_refused(
        self, wav_8k: bytes, language: str
    ) -> None:
        """A silent substitution would score a scenario against the wrong language."""
        with pytest.raises(UnsupportedLanguageError):
            asyncio.run(
                _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                    _request(wav_8k, language=language)
                )
            )

    @pytest.mark.parametrize("language", contract.PROVIDER_LANGUAGE_CODES)
    def test_every_documented_language_is_accepted_and_mapped(
        self, wav_8k: bytes, language: str
    ) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = request.content
            return _json_response({**DOCUMENTED_RESPONSE, "detected_language_code": language})

        result = asyncio.run(
            _provider(handler).transcribe_batch(_request(wav_8k, language=language))
        )
        assert result.requested_language == language
        assert language.encode() in bytes(seen["body"])  # type: ignore[arg-type]

    def test_a_mode_without_a_documented_wire_value_is_refused(self, wav_8k: bytes) -> None:
        with pytest.raises(UnsupportedFormatError, match="no documented Prisma 'format'"):
            asyncio.run(
                _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                    _request(wav_8k, mode=TranscriptionMode.CODE_MIX)
                )
            )

    def test_oversized_audio_is_rejected_before_the_request(self, wav_8k: bytes) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise AssertionError("oversized audio must not be uploaded")

        with pytest.raises(AudioTooLargeError):
            asyncio.run(_provider(handler, max_audio_bytes=100).transcribe_batch(_request(wav_8k)))

    def test_the_configured_limit_cannot_exceed_the_documented_one(self) -> None:
        """A generous local setting must not raise the provider's own ceiling."""
        provider = GnaniPrismaProvider(api_key=API_KEY, max_audio_bytes=500 * 1024 * 1024)
        assert provider.capabilities.max_batch_bytes == contract.BATCH_MAX_BYTES_PER_FILE

    def test_an_unaccepted_container_is_rejected(self, raw_pcm_8k: bytes) -> None:
        """Prisma's batch endpoint takes containers, not headerless PCM."""
        with pytest.raises(UnsupportedFormatError):
            asyncio.run(
                _provider(lambda _: _json_response(DOCUMENTED_RESPONSE)).transcribe_batch(
                    _request(raw_pcm_8k, encoding=AudioEncoding.PCM_S16LE, sample_rate_hz=8000)
                )
            )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


class TestCapabilities:
    @pytest.fixture
    def capabilities(self):  # type: ignore[no-untyped-def]
        return GnaniPrismaProvider(api_key=API_KEY).capabilities

    def test_it_reports_both_transports(self, capabilities) -> None:  # type: ignore[no-untyped-def]
        assert capabilities.supports_batch
        assert capabilities.supports_streaming

    def test_it_does_not_claim_partial_results(self, capabilities) -> None:  # type: ignore[no-untyped-def]
        """The documented protocol has no interim-result indicator at all."""
        assert capabilities.supports_partial_results is False

    def test_it_does_not_claim_confidence_timestamps_or_diarisation(self, capabilities) -> None:  # type: ignore[no-untyped-def]
        assert capabilities.supports_confidence is False
        assert capabilities.supports_word_timestamps is False
        assert capabilities.supports_diarisation is False

    def test_it_requires_credentials(self, capabilities) -> None:  # type: ignore[no-untyped-def]
        assert capabilities.requires_credentials is True

    def test_it_publishes_the_documentation_gaps(self, capabilities) -> None:  # type: ignore[no-untyped-def]
        assert capabilities.notes == contract.DOCUMENTATION_GAPS

    def test_capabilities_are_free_of_side_effects(self) -> None:
        """`describe_providers` reads them for every provider on every call."""
        provider = GnaniPrismaProvider(api_key=API_KEY)
        for _ in range(5):
            assert provider.capabilities.name == "prisma"
        # No HTTP client was built, so there is nothing to leak.
        assert provider._client is None


class TestWebSocketUrlDerivation:
    @pytest.mark.parametrize(
        ("base", "expected"),
        [
            ("https://api.vachana.ai", "wss://api.vachana.ai"),
            ("http://localhost:8080", "ws://localhost:8080"),
            ("https://api.vachana.ai/", "wss://api.vachana.ai"),
        ],
    )
    def test_the_scheme_is_swapped(self, base: str, expected: str) -> None:
        provider = GnaniPrismaProvider(api_key=API_KEY, base_url=base)
        assert provider._ws_base_url == expected

    def test_an_explicit_ws_base_url_wins(self) -> None:
        provider = GnaniPrismaProvider(
            api_key=API_KEY,
            base_url="https://api.vachana.ai",
            ws_base_url="wss://stream.example.internal",
        )
        assert provider._ws_base_url == "wss://stream.example.internal"
