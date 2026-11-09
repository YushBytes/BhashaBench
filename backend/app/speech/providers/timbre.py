"""Gnani Timbre text-to-speech adapter.

The only module that knows Timbre's wire format. Everything vendor-specific is
here or in `timbre_contract`, so the service layer, the API, and Phase 6's
caller agent deal exclusively in `app.speech.models`.

Two things make this adapter different from the Prisma one, and both are
response-handling problems rather than request-building problems.

**The response is binary, not JSON.** A success is raw audio bytes. So the
usual `response.json()` reflex is wrong twice over: it fails on success, and
on failure it is the *only* way to read the error. The adapter therefore
decides by status first and never decodes audio as text.

**A 200 is not proof of audio.** An empty body, or a JSON error delivered with
a 200, are both things an HTTP client reports as success. Both are checked.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx2

from app.speech.base import SynthesisCapabilities, VoiceDescriptor
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
    AudioContainer,
    AudioEncodingName,
    SpeechRequest,
    SpeechResult,
    SpeechSpeed,
)
from app.speech.providers import timbre_contract as contract
from app.transcription import audio as audio_tools
from app.transcription.redaction import mask_secret, redact
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.speech.timbre")

PROVIDER_NAME = "timbre"

# Bytes per sample for the 8-bit G.711 codecs, used to derive a duration that
# the container itself cannot report.
_G711_BYTES_PER_SAMPLE = 1


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 3)


class GnaniTimbreProvider:
    """`SynthesisProvider` backed by Gnani Timbre."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = contract.DEFAULT_BASE_URL,
        model: str = contract.DEFAULT_MODEL,
        default_voice: str = contract.DEFAULT_VOICE,
        timeout_seconds: float = 60.0,
        max_text_chars: int = 5000,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise SpeechAuthenticationError(
                "a Gnani API key is required; set GNANI_API_KEY",
                provider=PROVIDER_NAME,
            )
        if model not in contract.SUPPORTED_MODELS:
            raise UnsupportedAudioConfigError(
                f"'{model}' is not a documented Timbre model; "
                f"supported models are {sorted(contract.SUPPORTED_MODELS)}",
                provider=PROVIDER_NAME,
            )

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._default_voice = default_voice
        self._timeout_seconds = timeout_seconds
        self._max_text_chars = max_text_chars
        self._owns_client = client is None
        self._client: httpx2.AsyncClient | None = client

        # One in-flight request at a time.
        #
        # The project owner reports that the provider permits only one active
        # request per key. That limitation is *not* stated on any vendor page
        # consulted (see DOCUMENTATION_GAPS), so this is a conservative choice
        # rather than a documented requirement: serialising costs throughput we
        # do not yet need, while ignoring the limit would mean intermittent
        # 429s that look like rate limiting and are really self-inflicted.
        # Per instance, which is per request under the current wiring - the
        # guard matters when a caller reuses one provider, as Phase 6 will.
        self._gate = asyncio.Lock()

    @property
    def _http(self) -> httpx2.AsyncClient:
        """The pooled HTTP client, built on first use.

        Lazy for the same reason as Prisma's: `describe_providers` constructs
        every provider just to read static capabilities.
        """
        if self._client is None:
            self._client = httpx2.AsyncClient(timeout=httpx2.Timeout(self._timeout_seconds))
        return self._client

    # -- Capabilities -------------------------------------------------------

    @property
    def capabilities(self) -> SynthesisCapabilities:
        """What Timbre documents, for the configured model."""
        is_v3 = self._model == contract.MODEL_V3
        voices = (
            tuple(
                VoiceDescriptor(name=v.name, gender=v.gender, character=v.character)
                for v in contract.V3_VOICES
            )
            if is_v3
            else ()
        )
        return SynthesisCapabilities(
            name=PROVIDER_NAME,
            display_name="Gnani Timbre",
            languages=frozenset(contract.LANGUAGE_MAP),
            extra_language_values=frozenset(
                {contract.AUTO_LANGUAGE_CODE, contract.HINGLISH_LANGUAGE_CODE}
            ),
            voices=voices,
            # v3.0's 13 voices are fully documented. v2.5 has 42, of which only
            # nine were quoted, so its roster is not exhaustive and a name must
            # not be rejected for being absent from it.
            voices_are_exhaustive=is_v3,
            models=contract.SUPPORTED_MODELS,
            default_model=self._model,
            containers=frozenset(AudioContainer),
            encodings=frozenset(AudioEncodingName),
            sample_rates=contract.SAMPLE_RATES,
            speed_range=(contract.SPEED_MIN, contract.SPEED_MAX),
            speed_aliases=frozenset(contract.SPEED_ALIASES),
            audio_tags=contract.AUDIO_TAGS if is_v3 else (),
            supports_audio_tags=is_v3,
            # Timbre documents SSE and WebSocket streaming. Neither is
            # implemented: nothing consumes a stream before Phase 10, and an
            # unused transport is an untested transport.
            supports_streaming=False,
            max_text_chars=self._max_text_chars,
            requires_credentials=True,
            serialises_requests=True,
            notes=contract.DOCUMENTATION_GAPS,
        )

    # -- Validation ---------------------------------------------------------

    def _check_text(self, text: str) -> str:
        """Reject text the provider cannot usefully speak."""
        if not text.strip():
            raise InvalidTextError("the text to synthesise is empty", provider=PROVIDER_NAME)
        if len(text) > self._max_text_chars:
            raise InvalidTextError(
                f"the text is {len(text)} characters, which exceeds the "
                f"{self._max_text_chars} character limit "
                "(SPEECH_MAX_TEXT_CHARS; the provider publishes no limit of its own)",
                provider=PROVIDER_NAME,
            )
        return text

    def _check_language(self, language: str) -> str:
        """Map a BhashaBench tag, or pass a documented provider value through."""
        if language in contract.SUPPORTED_LANGUAGE_VALUES:
            return contract.LANGUAGE_MAP.get(language, language)
        raise UnsupportedSpeechLanguageError(
            f"Gnani Timbre does not document speech synthesis for '{language}'; "
            f"supported values are {sorted(contract.SUPPORTED_LANGUAGE_VALUES)}",
            language=language,
            supported=tuple(sorted(contract.SUPPORTED_LANGUAGE_VALUES)),
            provider=PROVIDER_NAME,
        )

    def _check_voice(self, voice: str | None) -> str:
        """Resolve a voice name to its documented spelling.

        For v3.0 the roster is complete, so an unknown name is refused with the
        list. For v2.5 it is not, so the name is forwarded as given - see the
        reasoning in `timbre_contract.V25_VOICE_EXAMPLES`.
        """
        name = (voice or self._default_voice).strip()
        if self._model != contract.MODEL_V3:
            return name

        documented = contract.voice_for(name)
        if documented is None:
            raise UnsupportedVoiceError(
                f"'{name}' is not a documented {contract.MODEL_V3} voice; "
                f"available voices are {sorted(contract.V3_VOICE_NAMES)}",
                voice=name,
                supported=tuple(sorted(contract.V3_VOICE_NAMES)),
                provider=PROVIDER_NAME,
            )
        # The documented capitalisation, not the caller's. Case sensitivity is
        # undocumented, so sending the published spelling is the safe choice.
        return documented.name

    def _check_speed(self, speed: float | SpeechSpeed | None) -> float | str | None:
        """Validate the speaking rate against the documented range or aliases."""
        if speed is None:
            return None
        if isinstance(speed, SpeechSpeed):
            return speed.value
        if isinstance(speed, str):
            if speed in contract.SPEED_ALIASES:
                return contract.SPEED_ALIASES[speed]
            raise UnsupportedAudioConfigError(
                f"'{speed}' is not a documented speed shortcut; "
                f"use one of {sorted(contract.SPEED_ALIASES)} or a number between "
                f"{contract.SPEED_MIN} and {contract.SPEED_MAX}",
                provider=PROVIDER_NAME,
            )
        if not contract.SPEED_MIN <= float(speed) <= contract.SPEED_MAX:
            raise UnsupportedAudioConfigError(
                f"a speed of {speed} is outside the documented range "
                f"{contract.SPEED_MIN}-{contract.SPEED_MAX}",
                provider=PROVIDER_NAME,
            )
        return float(speed)

    def _audio_config(self, request: SpeechRequest) -> dict[str, object]:
        """Build and validate the documented `audio_config` object."""
        audio = request.audio
        container = audio.container.value
        encoding = audio.encoding.value

        if audio.sample_rate_hz not in contract.SAMPLE_RATES:
            raise UnsupportedAudioConfigError(
                f"a sample rate of {audio.sample_rate_hz} Hz is not documented; "
                f"accepted rates are {sorted(contract.SAMPLE_RATES)} Hz",
                provider=PROVIDER_NAME,
            )
        # The G.711 containers are 8 kHz telephony codecs. Any other rate is a
        # combination the vendor does not describe, so it is refused rather
        # than sent hopefully.
        if (
            container in {"mulaw", "alaw"}
            and audio.sample_rate_hz != contract.MULAW_ALAW_SAMPLE_RATE
        ):
            raise UnsupportedAudioConfigError(
                f"the '{container}' container is an 8 kHz telephony codec and does "
                f"not accept {audio.sample_rate_hz} Hz",
                provider=PROVIDER_NAME,
            )
        if audio.bitrate is not None:
            if container != "mp3":
                raise UnsupportedAudioConfigError(
                    f"bitrate applies to the mp3 container only, not '{container}'",
                    provider=PROVIDER_NAME,
                )
            if audio.bitrate not in contract.BITRATES:
                raise UnsupportedAudioConfigError(
                    f"'{audio.bitrate}' is not a documented bitrate; "
                    f"accepted values are {sorted(contract.BITRATES)}",
                    provider=PROVIDER_NAME,
                )

        config: dict[str, object] = {
            contract.CONFIG_SAMPLE_RATE: audio.sample_rate_hz,
            contract.CONFIG_NUM_CHANNELS: audio.channels,
            contract.CONFIG_SAMPLE_WIDTH: audio.sample_width_bytes,
            contract.CONFIG_ENCODING: encoding,
            contract.CONFIG_CONTAINER: container,
        }
        if audio.bitrate is not None:
            config[contract.CONFIG_BITRATE] = audio.bitrate
        return config

    # -- Synthesis ----------------------------------------------------------

    async def synthesise(self, request: SpeechRequest) -> SpeechResult:
        """Render text as audio via `POST /api/v1/tts/inference`.

        Validation runs before the network call, cheapest first, so an obviously
        bad request costs nothing and reports precisely what was wrong.
        """
        text = self._check_text(request.text)
        language = self._check_language(request.language)
        voice = self._check_voice(request.voice)
        speed = self._check_speed(request.speed)
        audio_config = self._audio_config(request)

        payload: dict[str, object] = {
            contract.FIELD_TEXT: text,
            contract.FIELD_MODEL: self._model,
            contract.FIELD_VOICE: voice,
            contract.FIELD_LANGUAGE: language,
            contract.FIELD_AUDIO_CONFIG: audio_config,
        }
        if speed is not None:
            payload[contract.FIELD_SPEED] = speed

        url = f"{self._base_url}{contract.INFERENCE_PATH}"
        started = monotonic_seconds()

        async with self._gate:
            try:
                response = await self._http.post(
                    url,
                    json=payload,
                    headers={contract.API_KEY_HEADER: self._api_key},
                )
            except httpx2.TimeoutException as exc:
                raise SpeechTimeoutError(
                    f"Gnani Timbre did not respond within {self._timeout_seconds:g}s",
                    provider=PROVIDER_NAME,
                ) from exc
            except httpx2.RequestError as exc:
                raise SpeechProviderUnavailableError(
                    f"could not reach Gnani Timbre: {redact(exc)}",
                    provider=PROVIDER_NAME,
                ) from exc

        latency_ms = _ms(monotonic_seconds() - started)
        self._raise_for_status(response)
        result = self._normalise(
            response,
            request=request,
            voice=voice,
            speed=speed,
            language=language,
            latency_ms=latency_ms,
        )

        logger.info(
            "speech.synthesised",
            extra={
                "provider": PROVIDER_NAME,
                "operation": "synthesise",
                "model": result.model,
                "voice": result.voice,
                "language": result.language,
                "requested_language": result.requested_language,
                "correlation_id": request.correlation_id,
                "latency_ms": latency_ms,
                "container": result.container.value,
                "audio_bytes": result.size_bytes,
                "sample_rate_hz": result.sample_rate_hz,
                "duration_seconds": result.duration_seconds,
                "rate_was_honoured": result.rate_was_honoured,
                # Length, never content: caller text can carry a policy number
                # or anything else a scenario put in a persona's mouth.
                "text_chars": len(text),
            },
        )
        return result

    # -- Error mapping ------------------------------------------------------

    def _raise_for_status(self, response: httpx2.Response) -> None:
        """Map a Timbre HTTP status onto a structured error."""
        status = response.status_code
        if status < 400:
            return

        detail = redact(self._error_detail(response))
        code = self._error_code(response)

        if status == contract.STATUS_UNAUTHORIZED:
            raise SpeechAuthenticationError(
                f"Gnani Timbre rejected the API key (401). Check GNANI_API_KEY "
                f"(currently {mask_secret(self._api_key)}). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                error_code=code,
            )
        if status == contract.STATUS_PAYMENT_REQUIRED:
            raise SpeechAuthenticationError(
                f"Gnani Timbre reports insufficient credit (402). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                error_code=code,
            )
        if status == contract.STATUS_FORBIDDEN:
            raise SpeechAuthenticationError(
                "the Gnani API key lacks the scope for text-to-speech (403). "
                "A key that works for Prisma speech-to-text does not necessarily "
                f"carry the Timbre scope. {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                error_code=code,
            )
        if status == contract.STATUS_RATE_LIMITED:
            raise SpeechRateLimitError(
                f"Gnani Timbre rate limit reached (429). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                error_code=code,
                retry_after=self._retry_after(response),
            )
        if status == contract.STATUS_BAD_REQUEST:
            # Our request was wrong. Not retryable, and the provider's own
            # message is the most useful thing we can pass on.
            raise UnsupportedAudioConfigError(
                f"Gnani Timbre rejected the request parameters (400). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                error_code=code,
            )
        if status >= 500:
            raise SpeechProviderUnavailableError(
                f"Gnani Timbre returned {status}. {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                error_code=code,
            )

        raise SpeechError(
            f"Gnani Timbre rejected the request with {status}. {detail}",
            provider=PROVIDER_NAME,
            status_code=status,
            error_code=code,
            retryable=False,
        )

    @staticmethod
    def _error_body(response: httpx2.Response) -> dict[str, object] | None:
        """Parse an error body, tolerating both documented shapes.

        Guarded by a content-type check as well as a try: on an error the body
        should be JSON, but a gateway can return HTML, and feeding that to a
        JSON parser just to catch the exception is noisier than asking first.
        """
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            return None
        return body if isinstance(body, dict) else None

    @classmethod
    def _error_detail(cls, response: httpx2.Response) -> str:
        """Extract a short, safe description of an error response.

        Timbre documents two shapes:
          400/500     {"success": false, "message": "...", "status_code": n}
          401/403/429 {"detail": {"error_code": "...", "message": "...", ...}}
        """
        body = cls._error_body(response)
        if body is None:
            text = response.text.strip()
            return f"Response body: {text[:300]}" if text else "No response body."

        detail = body.get(contract.ERROR_FIELD_DETAIL)
        if isinstance(detail, dict):
            message = detail.get(contract.ERROR_FIELD_MESSAGE)
            if isinstance(message, str) and message.strip():
                return message.strip()[:300]
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:300]

        message = body.get(contract.ERROR_FIELD_MESSAGE)
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
        return f"Response body: {str(body)[:300]}"

    @classmethod
    def _error_code(cls, response: httpx2.Response) -> str | None:
        """Pull the provider's own error code, when it sends one."""
        body = cls._error_body(response)
        if body is None:
            return None
        detail = body.get(contract.ERROR_FIELD_DETAIL)
        if isinstance(detail, dict):
            code = detail.get(contract.ERROR_FIELD_CODE)
            if isinstance(code, str) and code.strip():
                return code.strip()[:100]
        return None

    @staticmethod
    def _retry_after(response: httpx2.Response) -> float | None:
        """Parse `Retry-After` when present, delay-seconds form only."""
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(float(raw.strip()), 0.0)
        except ValueError:
            return None

    # -- Response normalisation ---------------------------------------------

    def _normalise(
        self,
        response: httpx2.Response,
        *,
        request: SpeechRequest,
        voice: str,
        speed: float | str | None,
        language: str,
        latency_ms: float,
    ) -> SpeechResult:
        """Turn a binary response into a `SpeechResult`, verifying what it can.

        A 200 does not prove audio arrived. Two things get past a status check:
        an empty body, and a JSON error delivered with a success status. Both
        are caught here, because handing either to Phase 6 as "audio" would
        fail much later and much less clearly.
        """
        payload = response.content
        container = request.audio.container

        if not payload:
            raise MalformedSpeechResponseError(
                "Gnani Timbre returned a successful status with an empty body, "
                "so there is no audio to return",
                provider=PROVIDER_NAME,
                status_code=response.status_code,
            )

        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type.startswith("application/json") or content_type.startswith("text/"):
            # A JSON or text body on a 2xx means the provider reported
            # something other than audio. Never decoded as audio.
            raise MalformedSpeechResponseError(
                f"Gnani Timbre returned {content_type or 'a non-audio body'} with status "
                f"{response.status_code} where audio was expected: "
                f"{redact(self._error_detail(response))}",
                provider=PROVIDER_NAME,
                status_code=response.status_code,
            )

        sample_rate, channels, duration = self._measure(payload, container, request)

        return SpeechResult(
            audio=payload,
            container=container,
            content_type=contract.CONTENT_TYPES.get(container.value, "application/octet-stream"),
            provider=PROVIDER_NAME,
            model=self._model,
            voice=voice,
            language=language,
            requested_language=request.language,
            speed=request.speed,
            latency_ms=latency_ms,
            size_bytes=len(payload),
            sample_rate_hz=sample_rate,
            channels=channels,
            duration_seconds=duration,
            requested_sample_rate_hz=request.audio.sample_rate_hz,
            # The documented response carries no request identifier, unlike
            # Prisma's. Left unset rather than invented.
            provider_request_id=None,
        )

    def _measure(
        self, payload: bytes, container: AudioContainer, request: SpeechRequest
    ) -> tuple[int | None, int | None, float | None]:
        """Establish rate, channels and duration from the audio itself.

        Only from the bytes, never from what was requested. A provider that
        quietly ignored `sample_rate` should show up as a mismatch, which is
        impossible if the requested value is copied into the result.

        WAV carries a header, so all three are exact - reusing the Phase 4
        inspector rather than writing a second RIFF parser. The G.711
        containers are headerless but fixed at 8 kHz mono with one byte per
        sample, so duration follows from the byte count. MP3 and OGG need a
        decoder, so they stay unset.
        """
        if container is AudioContainer.WAV:
            try:
                metadata = audio_tools.inspect(payload)
            except Exception as exc:
                raise MalformedSpeechResponseError(
                    f"Gnani Timbre returned a wav container that could not be "
                    f"parsed: {redact(exc)}",
                    provider=PROVIDER_NAME,
                ) from exc
            return metadata.sample_rate_hz, metadata.channels, metadata.duration_seconds

        if container in {AudioContainer.MULAW, AudioContainer.ALAW}:
            rate = contract.MULAW_ALAW_SAMPLE_RATE
            return rate, 1, len(payload) / (rate * _G711_BYTES_PER_SAMPLE)

        if container is AudioContainer.RAW:
            # Headerless linear PCM: the rate is not in the bytes, so it cannot
            # be verified. Duration is derivable only by trusting the requested
            # rate, which is exactly the assumption this method avoids - so
            # nothing is reported.
            return None, None, None

        # mp3, ogg: decoding is out of scope for this phase.
        return None, None, None

    # -- Lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        """Close the pooled HTTP client, if this provider owns it."""
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


__all__ = ["PROVIDER_NAME", "GnaniTimbreProvider"]
