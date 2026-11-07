"""The Gnani Timbre adapter, driven against a mocked transport.

**What these prove and what they do not.** They prove the adapter sends the
request the published contract describes and handles every documented response
and status correctly. They do **not** prove Gnani agrees: no live call is made
here, and a mock cannot disagree with the fixture that produced it. Live
verification is `test_speech_live.py`, deselected without credentials.

`httpx2.MockTransport` intercepts at the socket, so the adapter's real path
runs - JSON body construction, headers, status handling, binary decoding.
"""

from __future__ import annotations

import asyncio
import json
import struct
import wave
from collections.abc import Callable
from io import BytesIO

import httpx2
import pytest

from app.core.languages import SUPPORTED_CODES
from app.speech.errors import (
    InvalidTextError,
    MalformedSpeechResponseError,
    SpeechAuthenticationError,
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
    SpeechRequest,
    SpeechSpeed,
)
from app.speech.providers import timbre_contract as contract
from app.speech.providers.fake import build_wav
from app.speech.providers.timbre import GnaniTimbreProvider

API_KEY = "timbre-test-key-0123456789abcdef"
"""A fabricated value. Several tests assert it never escapes."""

TAMIL_LINE = "வணக்கம், உங்கள் பயிர் காப்பீட்டு விண்ணப்பத்தின் நிலையைச் சரிபார்க்கிறேன்."

WAV_8K = build_wav(sample_rate=8000, channels=1, seconds=0.5)


def streaming_wav(
    *, frames: int, sample_rate: int = 8000, channels: int = 1, width: int = 2
) -> bytes:
    """Build a WAV with `0xFFFFFFFF` size fields - what Timbre actually sends.

    Hand-built rather than written with the stdlib `wave` module, because that
    writer always back-fills the real length. That is exactly why this header
    shape never appeared in an offline fixture and the first live call was what
    found it.
    """
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
        + struct.pack("<I", 0xFFFFFFFF)
        + samples
    )
    return b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + body


def _provider(
    handler: Callable[[httpx2.Request], httpx2.Response], **kwargs: object
) -> GnaniTimbreProvider:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return GnaniTimbreProvider(api_key=API_KEY, client=client, **kwargs)


def _audio_response(payload: bytes = WAV_8K, content_type: str = "audio/wav") -> httpx2.Response:
    return httpx2.Response(200, content=payload, headers={"content-type": content_type})


def _ok(_: httpx2.Request) -> httpx2.Response:
    return _audio_response()


def _request(text: str = TAMIL_LINE, **kwargs: object) -> SpeechRequest:
    payload: dict[str, object] = {"text": text, "language": "ta-IN"}
    payload.update(kwargs)
    return SpeechRequest(**payload)  # type: ignore[arg-type]


def _body(request: httpx2.Request) -> dict[str, object]:
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


class TestRequestShape:
    def test_it_posts_to_the_documented_url(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["url"] = str(request.url)
            seen["method"] = request.method
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request()))
        assert seen["url"] == "https://api.vachana.ai/api/v1/tts/inference"
        assert seen["method"] == "POST"

    def test_it_sends_the_key_in_the_documented_header(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["key"] = request.headers.get("x-api-key-id")
            seen["authorization"] = request.headers.get("authorization")
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request()))
        assert seen["key"] == API_KEY
        # Not a bearer scheme; sending one would silently fail to authenticate.
        assert seen["authorization"] is None

    def test_it_sends_json_not_multipart(self) -> None:
        """Unlike the STT endpoint, which takes multipart."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["content_type"] = request.headers.get("content-type", "")
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request()))
        assert "application/json" in str(seen["content_type"])

    def test_the_body_carries_every_documented_field(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = _body(request)
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(voice="Kalpana", speed=1.0)))
        body = seen["body"]
        assert body["text"] == TAMIL_LINE  # type: ignore[index]
        assert body["model"] == "timbre-v3.0"  # type: ignore[index]
        assert body["voice"] == "Kalpana"  # type: ignore[index]
        assert body["language"] == "ta-IN"  # type: ignore[index]
        assert body["speed"] == 1.0  # type: ignore[index]
        assert "audio_config" in body  # type: ignore[operator]

    def test_the_audio_config_object_uses_the_documented_names(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["config"] = _body(request)["audio_config"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request()))
        config = seen["config"]
        assert config == {  # type: ignore[comparison-overlap]
            "sample_rate": 8000,
            "num_channels": 1,
            "sample_width": 2,
            "encoding": "linear_pcm",
            "container": "wav",
        }

    def test_speed_is_omitted_when_not_requested(self) -> None:
        """Sending a null speed is not the same as omitting the field."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = _body(request)
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request()))
        assert "speed" not in seen["body"]  # type: ignore[operator]

    def test_bitrate_is_sent_only_for_mp3(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["config"] = _body(request)["audio_config"]
            return _audio_response(b"\xff\xfb\x90\x00", "audio/mpeg")

        asyncio.run(
            _provider(handler).synthesise(
                _request(audio=AudioConfig(container=AudioContainer.MP3, bitrate="128k"))
            )
        )
        assert seen["config"]["bitrate"] == "128k"  # type: ignore[index]

    def test_the_default_voice_is_sent_explicitly(self) -> None:
        """Relying on an undeclared provider default would make a run
        irreproducible."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = _body(request)
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request()))
        assert seen["body"]["voice"] == contract.DEFAULT_VOICE  # type: ignore[index]

    def test_utf8_text_survives_the_json_encoding(self) -> None:
        """Every Indian-language utterance depends on this."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["body"] = _body(request)
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(TAMIL_LINE)))
        assert seen["body"]["text"] == TAMIL_LINE  # type: ignore[index]


class TestConstruction:
    def test_an_undocumented_model_is_refused(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="not a documented Timbre model"):
            GnaniTimbreProvider(api_key=API_KEY, model="elevenlabs-v2")

    def test_an_empty_api_key_is_refused(self) -> None:
        with pytest.raises(SpeechAuthenticationError, match="GNANI_API_KEY"):
            GnaniTimbreProvider(api_key="")

    def test_capabilities_open_no_client(self) -> None:
        provider = GnaniTimbreProvider(api_key=API_KEY)
        for _ in range(3):
            assert provider.capabilities.name == "timbre"
        assert provider._client is None


# ---------------------------------------------------------------------------
# Validation before the network
# ---------------------------------------------------------------------------


class TestValidation:
    @staticmethod
    def _never(_: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no request should be sent for an invalid input")

    def test_empty_text_never_reaches_the_provider(self) -> None:
        with pytest.raises(InvalidTextError, match="empty"):
            asyncio.run(_provider(self._never).synthesise(_request("   ")))

    def test_over_long_text_is_rejected_with_the_setting_named(self) -> None:
        with pytest.raises(InvalidTextError, match="SPEECH_MAX_TEXT_CHARS"):
            asyncio.run(_provider(self._never, max_text_chars=10).synthesise(_request("x" * 11)))

    @pytest.mark.parametrize("language", ["ur-IN", "or-IN", "as-IN"])
    def test_each_unspeakable_catalogue_language_is_refused(self, language: str) -> None:
        with pytest.raises(UnsupportedSpeechLanguageError):
            asyncio.run(_provider(self._never).synthesise(_request(language=language)))

    @pytest.mark.parametrize("language", contract.PROVIDER_LANGUAGE_CODES)
    def test_every_documented_language_is_accepted_and_sent(self, language: str) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["language"] = _body(request)["language"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(language=language)))
        assert seen["language"] == language

    @pytest.mark.parametrize("value", ["auto", "hi-en"])
    def test_documented_provider_level_values_are_forwarded(self, value: str) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["language"] = _body(request)["language"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(language=value)))
        assert seen["language"] == value

    def test_an_undocumented_voice_is_refused_for_v3(self) -> None:
        with pytest.raises(UnsupportedVoiceError) as caught:
            asyncio.run(_provider(self._never).synthesise(_request(voice="Siri")))
        assert caught.value.voice == "Siri"
        assert "Kalpana" in str(caught.value)

    @pytest.mark.parametrize("voice", sorted(contract.V3_VOICE_NAMES))
    def test_every_documented_v3_voice_is_accepted(self, voice: str) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["voice"] = _body(request)["voice"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(voice=voice)))
        assert seen["voice"] == voice

    def test_a_differently_cased_voice_is_corrected_to_the_documented_spelling(self) -> None:
        """Case sensitivity is undocumented, so the published spelling is sent
        rather than whatever the caller typed."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["voice"] = _body(request)["voice"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(voice="kALPANA")))
        assert seen["voice"] == "Kalpana"

    def test_an_unlisted_v25_voice_is_forwarded_not_refused(self) -> None:
        """The v2.5 roster is incomplete, so rejecting an unlisted name would
        refuse valid input - the provider's own rejection is better."""
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["voice"] = _body(request)["voice"]
            return _audio_response()

        provider = _provider(handler, model=contract.MODEL_V25)
        asyncio.run(provider.synthesise(_request(voice="SomeUndocumentedV25Voice")))
        assert seen["voice"] == "SomeUndocumentedV25Voice"

    @pytest.mark.parametrize("speed", [0.84, 1.16, 2.0, 0.0])
    def test_a_speed_outside_the_documented_range_is_refused(self, speed: float) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="documented range"):
            asyncio.run(_provider(self._never).synthesise(_request(speed=speed)))

    @pytest.mark.parametrize("speed", [0.85, 1.0, 1.15])
    def test_documented_boundary_speeds_are_accepted(self, speed: float) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["speed"] = _body(request)["speed"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(speed=speed)))
        assert seen["speed"] == speed

    @pytest.mark.parametrize("alias", list(SpeechSpeed))
    def test_documented_speed_aliases_are_forwarded_as_strings(self, alias: SpeechSpeed) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["speed"] = _body(request)["speed"]
            return _audio_response()

        asyncio.run(_provider(handler).synthesise(_request(speed=alias)))
        assert seen["speed"] == alias.value

    def test_an_undocumented_sample_rate_is_refused(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="not documented"):
            asyncio.run(
                _provider(self._never).synthesise(_request(audio=AudioConfig(sample_rate_hz=11025)))
            )

    @pytest.mark.parametrize("container", ["mulaw", "alaw"])
    def test_a_g711_container_rejects_a_non_8khz_rate(self, container: str) -> None:
        """They are 8 kHz telephony codecs; any other rate is a combination the
        vendor does not describe."""
        with pytest.raises(UnsupportedAudioConfigError, match="8 kHz telephony codec"):
            asyncio.run(
                _provider(self._never).synthesise(
                    _request(
                        audio=AudioConfig(container=AudioContainer(container), sample_rate_hz=16000)
                    )
                )
            )

    def test_a_g711_container_accepts_8khz(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(b"\x00" * 4000, "audio/basic")

        result = asyncio.run(
            _provider(handler).synthesise(
                _request(audio=AudioConfig(container=AudioContainer.MULAW, sample_rate_hz=8000))
            )
        )
        assert result.container is AudioContainer.MULAW

    def test_a_bitrate_on_a_non_mp3_container_is_refused(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="mp3 container only"):
            asyncio.run(
                _provider(self._never).synthesise(
                    _request(audio=AudioConfig(container=AudioContainer.WAV, bitrate="128k"))
                )
            )

    def test_an_undocumented_bitrate_is_refused(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError, match="not a documented bitrate"):
            asyncio.run(
                _provider(self._never).synthesise(
                    _request(audio=AudioConfig(container=AudioContainer.MP3, bitrate="256k"))
                )
            )


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


class TestResponseHandling:
    def test_a_wav_response_is_measured_from_its_header(self) -> None:
        result = asyncio.run(_provider(_ok).synthesise(_request()))
        assert result.sample_rate_hz == 8000
        assert result.channels == 1
        assert result.duration_seconds == pytest.approx(0.5)
        assert result.rate_was_honoured is True

    def test_the_returned_audio_is_a_real_parsable_wav(self) -> None:
        result = asyncio.run(_provider(_ok).synthesise(_request()))
        with wave.open(BytesIO(result.audio), "rb") as handle:
            assert handle.getnframes() > 0

    def test_a_provider_ignoring_the_requested_rate_is_visible(self) -> None:
        """The reason the result keeps both numbers."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(build_wav(sample_rate=48000, seconds=0.1))

        result = asyncio.run(_provider(handler).synthesise(_request()))
        assert result.requested_sample_rate_hz == 8000
        assert result.sample_rate_hz == 48000
        assert result.rate_was_honoured is False

    def test_an_mp3_response_leaves_measurements_unset(self) -> None:
        """Decoding is out of scope, so nothing is claimed - rather than the
        requested values being echoed back as if verified."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(b"\xff\xfb\x90\x00" * 100, "audio/mpeg")

        result = asyncio.run(
            _provider(handler).synthesise(_request(audio=AudioConfig(container=AudioContainer.MP3)))
        )
        assert result.sample_rate_hz is None
        assert result.duration_seconds is None
        assert result.rate_was_honoured is None
        assert result.size_bytes == 400

    def test_a_g711_response_duration_is_derived_from_the_byte_count(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(b"\x00" * 8000, "audio/basic")

        result = asyncio.run(
            _provider(handler).synthesise(
                _request(audio=AudioConfig(container=AudioContainer.MULAW))
            )
        )
        assert result.sample_rate_hz == 8000
        assert result.duration_seconds == pytest.approx(1.0)

    def test_a_raw_response_claims_nothing(self) -> None:
        """Headerless PCM: the rate is not in the bytes, so verifying it would
        mean trusting the request - which is the assumption being avoided."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(b"\x00" * 1000, "application/octet-stream")

        result = asyncio.run(
            _provider(handler).synthesise(_request(audio=AudioConfig(container=AudioContainer.RAW)))
        )
        assert result.sample_rate_hz is None
        assert result.duration_seconds is None

    @pytest.mark.parametrize(
        ("container", "expected"),
        [
            ("wav", "audio/wav"),
            ("mp3", "audio/mpeg"),
            ("ogg", "audio/ogg"),
            ("mulaw", "audio/basic"),
            ("alaw", "audio/basic"),
            ("raw", "application/octet-stream"),
        ],
    )
    def test_the_content_type_matches_the_container(self, container: str, expected: str) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(WAV_8K if container == "wav" else b"\x00" * 800, expected)

        audio = (
            AudioConfig(container=AudioContainer(container), sample_rate_hz=8000)
            if container in {"mulaw", "alaw"}
            else AudioConfig(container=AudioContainer(container))
        )
        result = asyncio.run(_provider(handler).synthesise(_request(audio=audio)))
        assert result.content_type == expected

    def test_the_model_and_voice_used_are_reported(self) -> None:
        result = asyncio.run(_provider(_ok).synthesise(_request(voice="Riyaa")))
        assert result.model == "timbre-v3.0"
        assert result.voice == "Riyaa"

    def test_latency_is_measured_by_us(self) -> None:
        result = asyncio.run(_provider(_ok).synthesise(_request()))
        assert result.latency_ms >= 0

    def test_no_provider_request_id_is_invented(self) -> None:
        """Timbre's documented response carries none, unlike Prisma's."""
        assert asyncio.run(_provider(_ok).synthesise(_request())).provider_request_id is None


class TestStreamingWavHeader:
    """The header shape Gnani Timbre really returns.

    Every one of these would have passed before the first live call and told us
    nothing, because the fixtures were built by a writer that knows its own
    length. They exist now so the regression cannot come back.
    """

    def test_a_streaming_header_is_accepted_and_measured(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(streaming_wav(frames=35200))

        result = asyncio.run(_provider(handler).synthesise(_request()))
        assert result.sample_rate_hz == 8000
        assert result.channels == 1
        assert result.duration_seconds == pytest.approx(4.4)
        assert result.rate_was_honoured is True

    def test_the_measured_duration_comes_from_the_bytes_not_the_sentinel(self) -> None:
        """The sentinel implies about 2.1 billion frames. Reporting that as a
        duration would be absurd; reporting the real 1.0 s is the point."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(streaming_wav(frames=8000))

        result = asyncio.run(_provider(handler).synthesise(_request()))
        assert result.duration_seconds == pytest.approx(1.0)

    def test_the_audio_is_returned_intact_and_decodable(self) -> None:
        payload = streaming_wav(frames=1000)

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(payload)

        result = asyncio.run(_provider(handler).synthesise(_request()))
        assert result.audio == payload
        with wave.open(BytesIO(result.audio), "rb") as handle:
            assert handle.getframerate() == 8000

    @pytest.mark.parametrize(
        ("sample_rate", "channels"), [(8000, 1), (16000, 1), (24000, 1), (48000, 2)]
    )
    def test_a_streaming_header_is_measured_at_any_rate(
        self, sample_rate: int, channels: int
    ) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(
                streaming_wav(frames=1000, sample_rate=sample_rate, channels=channels)
            )

        result = asyncio.run(
            _provider(handler).synthesise(
                _request(audio=AudioConfig(sample_rate_hz=sample_rate, channels=channels))
            )
        )
        assert result.sample_rate_hz == sample_rate
        assert result.channels == channels
        assert result.duration_seconds == pytest.approx(1000 / sample_rate)

    def test_a_genuinely_corrupt_wav_is_still_rejected(self) -> None:
        """The allowance must not have reopened the hole beside it."""
        truncated = WAV_8K[: len(WAV_8K) // 3]

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(truncated)

        with pytest.raises(MalformedSpeechResponseError):
            asyncio.run(_provider(handler).synthesise(_request()))


class TestMalformedResponses:
    def test_an_empty_body_with_200_is_rejected(self) -> None:
        """A status check alone would call this success."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=b"", headers={"content-type": "audio/wav"})

        with pytest.raises(MalformedSpeechResponseError, match="empty body"):
            asyncio.run(_provider(handler).synthesise(_request()))

    def test_a_json_body_with_200_is_rejected_not_decoded_as_audio(self) -> None:
        """The other thing that gets past a status check."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                json={"success": False, "message": "voice unavailable"},
            )

        with pytest.raises(MalformedSpeechResponseError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert "voice unavailable" in str(caught.value)

    def test_a_text_body_with_200_is_rejected(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, text="not audio", headers={"content-type": "text/plain"})

        with pytest.raises(MalformedSpeechResponseError):
            asyncio.run(_provider(handler).synthesise(_request()))

    def test_a_corrupt_wav_is_rejected_rather_than_returned(self) -> None:
        """A broken header would fail much later and much less clearly."""

        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(WAV_8K[: len(WAV_8K) // 3])

        with pytest.raises(MalformedSpeechResponseError, match="could not be"):
            asyncio.run(_provider(handler).synthesise(_request()))

    def test_a_non_wav_payload_claiming_to_be_wav_is_rejected(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return _audio_response(b"<html>error</html>", "audio/wav")

        with pytest.raises(MalformedSpeechResponseError):
            asyncio.run(_provider(handler).synthesise(_request()))

    def test_a_malformed_response_is_not_retryable(self) -> None:
        assert MalformedSpeechResponseError("x").retryable is False


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------


class TestStatusMapping:
    @pytest.mark.parametrize("status", [401, 402, 403])
    def test_credential_statuses_become_permanent_auth_errors(self, status: int) -> None:
        with pytest.raises(SpeechAuthenticationError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(status, json={})).synthesise(_request())
            )
        assert caught.value.retryable is False
        assert caught.value.status_code == status

    def test_a_403_explains_that_scopes_are_per_capability(self) -> None:
        """A key that demonstrably works for Prisma failing here is otherwise
        baffling."""
        with pytest.raises(SpeechAuthenticationError, match="does not necessarily"):
            asyncio.run(_provider(lambda _: httpx2.Response(403, json={})).synthesise(_request()))

    def test_402_mentions_credit(self) -> None:
        with pytest.raises(SpeechAuthenticationError, match="insufficient credit"):
            asyncio.run(_provider(lambda _: httpx2.Response(402, json={})).synthesise(_request()))

    def test_400_becomes_a_permanent_parameter_error(self) -> None:
        with pytest.raises(UnsupportedAudioConfigError) as caught:
            asyncio.run(_provider(lambda _: httpx2.Response(400, json={})).synthesise(_request()))
        assert caught.value.retryable is False

    def test_429_becomes_a_retryable_rate_limit(self) -> None:
        with pytest.raises(SpeechRateLimitError) as caught:
            asyncio.run(_provider(lambda _: httpx2.Response(429, json={})).synthesise(_request()))
        assert caught.value.retryable is True

    def test_a_retry_after_header_is_carried_onto_the_error(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(429, json={}, headers={"Retry-After": "7"})

        with pytest.raises(SpeechRateLimitError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert caught.value.retry_after == 7.0

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_server_errors_are_retryable(self, status: int) -> None:
        with pytest.raises(SpeechProviderUnavailableError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(status, json={})).synthesise(_request())
            )
        assert caught.value.retryable is True

    def test_an_undocumented_4xx_is_not_retried(self) -> None:
        with pytest.raises(SpeechError) as caught:
            asyncio.run(_provider(lambda _: httpx2.Response(418, json={})).synthesise(_request()))
        assert caught.value.retryable is False

    def test_a_timeout_becomes_a_retryable_timeout_error(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("too slow")

        with pytest.raises(SpeechTimeoutError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert caught.value.retryable is True

    def test_a_connection_failure_becomes_provider_unavailable(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection reset")

        with pytest.raises(SpeechProviderUnavailableError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert caught.value.retryable is True


class TestErrorBodyShapes:
    """Timbre documents two different error envelopes."""

    def test_the_400_and_500_shape_is_read(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                400,
                json={"success": False, "message": "speed out of range", "status_code": 400},
            )

        with pytest.raises(UnsupportedAudioConfigError, match="speed out of range"):
            asyncio.run(_provider(handler).synthesise(_request()))

    def test_the_401_and_429_shape_is_read(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                401,
                json={
                    "detail": {
                        "error_code": "INVALID_API_KEY",
                        "message": "the key was not recognised",
                        "status_code": 401,
                    }
                },
            )

        with pytest.raises(SpeechAuthenticationError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert "not recognised" in str(caught.value)
        assert caught.value.error_code == "INVALID_API_KEY"

    def test_a_non_json_error_body_is_tolerated(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(502, text="<html>Bad Gateway</html>")

        with pytest.raises(SpeechProviderUnavailableError, match="Bad Gateway"):
            asyncio.run(_provider(handler).synthesise(_request()))

    def test_an_html_error_page_is_truncated(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(502, text="<html>" + "x" * 50_000 + "</html>")

        with pytest.raises(SpeechProviderUnavailableError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert len(str(caught.value)) < 1000


# ---------------------------------------------------------------------------
# Credential containment
# ---------------------------------------------------------------------------


class TestCredentialContainment:
    @pytest.mark.parametrize("status", [400, 401, 402, 403, 429, 500])
    def test_no_error_message_contains_the_key(self, status: int) -> None:
        with pytest.raises(SpeechError) as caught:
            asyncio.run(
                _provider(lambda _: httpx2.Response(status, json={})).synthesise(_request())
            )
        assert API_KEY not in str(caught.value)

    def test_a_401_fingerprints_the_key_instead(self) -> None:
        from app.transcription.redaction import mask_secret

        with pytest.raises(SpeechAuthenticationError) as caught:
            asyncio.run(_provider(lambda _: httpx2.Response(401, json={})).synthesise(_request()))
        assert API_KEY not in str(caught.value)
        assert mask_secret(API_KEY) in str(caught.value)

    def test_a_provider_echoing_the_key_back_is_redacted(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                400, json={"success": False, "message": f"bad request api_key={API_KEY}"}
            )

        with pytest.raises(SpeechError) as caught:
            asyncio.run(_provider(handler).synthesise(_request()))
        assert API_KEY not in str(caught.value)

    def test_nothing_logged_contains_the_key(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.DEBUG):
            asyncio.run(_provider(_ok).synthesise(_request()))
        assert API_KEY not in caplog.text

    def test_the_synthesised_text_is_not_logged_only_its_length(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Caller text can carry whatever a scenario put in a persona's mouth."""
        import logging

        secret = "my policy number is 9988 7766 5544"
        with caplog.at_level(logging.DEBUG):
            asyncio.run(_provider(_ok).synthesise(_request(secret)))
        assert secret not in caplog.text
        record = next(r for r in caplog.records if r.message == "speech.synthesised")
        assert record.text_chars == len(secret)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Concurrency and lifecycle
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_concurrent_calls_on_one_provider_are_serialised(self) -> None:
        """The owner reports a one-active-request limit. It is not in the
        vendor's published pages, so this guard is conservative - but if it
        ever stops working, the symptom is intermittent 429s that look like
        rate limiting and are self-inflicted.
        """
        active = 0
        peak = 0

        def handler(_: httpx2.Request) -> httpx2.Response:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            active -= 1
            return _audio_response()

        provider = _provider(handler)

        async def drive() -> None:
            await asyncio.gather(*(provider.synthesise(_request()) for _ in range(5)))

        asyncio.run(drive())
        assert peak == 1

    def test_the_capability_declares_the_serialisation(self) -> None:
        assert GnaniTimbreProvider(api_key=API_KEY).capabilities.serialises_requests is True


class TestLifecycle:
    def test_an_owned_client_is_closed(self) -> None:
        provider = GnaniTimbreProvider(api_key=API_KEY)
        client = provider._http
        assert not client.is_closed
        asyncio.run(provider.close())
        assert client.is_closed
        assert provider._client is None

    def test_an_injected_client_is_left_open(self) -> None:
        """It belongs to whoever passed it - tests and the live fixture do."""
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(_ok))
        provider = GnaniTimbreProvider(api_key=API_KEY, client=client)
        asyncio.run(provider.close())
        assert not client.is_closed

    def test_closing_twice_is_harmless(self) -> None:
        provider = GnaniTimbreProvider(api_key=API_KEY)
        asyncio.run(provider.close())
        asyncio.run(provider.close())


class TestCapabilities:
    def test_v3_reports_thirteen_voices_and_eleven_tags(self) -> None:
        caps = GnaniTimbreProvider(api_key=API_KEY, model=contract.MODEL_V3).capabilities
        assert len(caps.voices) == 13
        assert len(caps.audio_tags) == 11
        assert caps.supports_audio_tags is True
        assert caps.voices_are_exhaustive is True

    def test_v25_reports_no_voices_and_no_tags(self) -> None:
        """Its roster is incomplete, so publishing a partial list as if it were
        the whole thing would be worse than publishing none."""
        caps = GnaniTimbreProvider(api_key=API_KEY, model=contract.MODEL_V25).capabilities
        assert caps.voices == ()
        assert caps.audio_tags == ()
        assert caps.supports_audio_tags is False
        assert caps.voices_are_exhaustive is False

    def test_streaming_is_not_claimed(self) -> None:
        """Timbre documents SSE and WebSocket transports; neither is built."""
        assert GnaniTimbreProvider(api_key=API_KEY).capabilities.supports_streaming is False

    def test_it_publishes_the_documentation_gaps(self) -> None:
        assert (
            GnaniTimbreProvider(api_key=API_KEY).capabilities.notes == contract.DOCUMENTATION_GAPS
        )

    def test_the_unspeakable_catalogue_languages_are_computable(self) -> None:
        caps = GnaniTimbreProvider(api_key=API_KEY).capabilities
        assert set(SUPPORTED_CODES) - caps.languages == {"ur-IN", "or-IN", "as-IN"}

    def test_every_documented_encoding_and_container_is_offered(self) -> None:
        caps = GnaniTimbreProvider(api_key=API_KEY).capabilities
        assert {c.value for c in caps.containers} == contract.CONTAINERS
        assert {e.value for e in caps.encodings} == contract.ENCODINGS
        assert caps.sample_rates == contract.SAMPLE_RATES
        assert caps.speed_range == (contract.SPEED_MIN, contract.SPEED_MAX)


class TestBaseUrlOverride:
    def test_a_custom_base_url_is_used(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["url"] = str(request.url)
            return _audio_response()

        provider = _provider(handler, base_url="http://localhost:9999")
        asyncio.run(provider.synthesise(_request()))
        assert seen["url"] == "http://localhost:9999/api/v1/tts/inference"

    def test_a_trailing_slash_does_not_double_up(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["url"] = str(request.url)
            return _audio_response()

        provider = _provider(handler, base_url="https://api.vachana.ai/")
        asyncio.run(provider.synthesise(_request()))
        assert seen["url"] == "https://api.vachana.ai/api/v1/tts/inference"


def test_audio_encoding_names_cover_the_contract() -> None:
    """A guard that the enum and the contract have not drifted apart."""
    assert {e.value for e in AudioEncodingName} == contract.ENCODINGS
