"""Gnani Prisma speech-to-text adapter.

The only module that knows Prisma's wire format. Everything vendor-specific is
either here or in `prisma_contract`, so the service layer, the API and the
evaluation phases that follow deal exclusively in
`app.transcription.models`.

**Verification status.** The request and response shapes are transcribed from
Gnani's official documentation (see `prisma_contract`). No live request has
been made against the service from this repository: no credentials have been
issued to it. The adapter is therefore *contract-verified* but not
*transport-verified*, and `docs/PROVIDERS.md` says so in those words. The
distinction is the whole point - an adapter that compiles and has passing unit
tests against a mocked transport has not proven the vendor agrees with it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx2
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK, InvalidStatus

from app.transcription import audio as audio_tools
from app.transcription.base import ProviderCapabilities
from app.transcription.errors import (
    AuthenticationError,
    MalformedProviderResponseError,
    ProviderUnavailableError,
    RateLimitError,
    StreamClosedError,
    TranscriptionError,
    TranscriptionTimeoutError,
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.transcription.models import (
    AudioEncoding,
    FinalTranscript,
    StreamEvent,
    TranscriptionCompleted,
    TranscriptionFailed,
    TranscriptionMode,
    TranscriptionRequest,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionStarted,
)
from app.transcription.providers import prisma_contract as contract
from app.transcription.redaction import mask_secret, redact
from app.utils.timing import utc_now

logger = logging.getLogger("bhashabench.transcription.prisma")

PROVIDER_NAME = "prisma"

# Cap on how much text a single stream may accumulate before the adapter
# refuses to continue. Prevents a provider that never stops emitting segments
# from growing our process without bound - the streaming path has no other
# natural limit, because the caller controls when the audio ends.
MAX_STREAM_TRANSCRIPT_CHARS = 1_000_000


def _ms(seconds: float) -> float:
    """Convert seconds to milliseconds, rounded to microsecond precision."""
    return round(seconds * 1000, 3)


class GnaniPrismaProvider:
    """`TranscriptionProvider` backed by Gnani Prisma.

    One instance owns one pooled `httpx2.AsyncClient`. It is built by the
    registry from settings and cached for the process lifetime, because
    rebuilding a client per request discards the connection pool and pays a
    TLS handshake on every transcription.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = contract.DEFAULT_BASE_URL,
        ws_base_url: str | None = None,
        model: str = contract.DEFAULT_MODEL,
        timeout_seconds: float = 30.0,
        max_audio_bytes: int = contract.BATCH_MAX_BYTES_PER_FILE,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            # Defensive: the registry checks this first and raises
            # ConfigurationError with actionable text. Reaching here means the
            # adapter was constructed directly, and failing now beats sending
            # an unauthenticated request and reporting a 401 as a provider
            # fault.
            raise AuthenticationError(
                "a Gnani API key is required; set GNANI_API_KEY",
                provider=PROVIDER_NAME,
            )
        if model not in contract.SUPPORTED_MODELS:
            raise UnsupportedFormatError(
                f"'{model}' is not a documented Prisma model; "
                f"supported models are {sorted(contract.SUPPORTED_MODELS)}",
                provider=PROVIDER_NAME,
            )

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # Derived from the REST base URL by default so a single
        # GNANI_API_BASE_URL override moves both transports together; an
        # explicit ws_base_url wins when a deployment splits them.
        self._ws_base_url = (ws_base_url or self._derive_ws_base(self._base_url)).rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_audio_bytes = min(max_audio_bytes, contract.BATCH_MAX_BYTES_PER_FILE)
        self._owns_client = client is None
        # Created on first use, not here. `describe_providers` constructs every
        # registered provider just to read its static capabilities, and an
        # eager client would leak a connection pool on each of those calls.
        self._client: httpx2.AsyncClient | None = client

    @property
    def _http(self) -> httpx2.AsyncClient:
        """The pooled HTTP client, built on first use."""
        if self._client is None:
            # No default headers: the key is attached per request so it cannot
            # be captured in a client repr that some library decides to log.
            self._client = httpx2.AsyncClient(timeout=httpx2.Timeout(self._timeout_seconds))
        return self._client

    @staticmethod
    def _derive_ws_base(base_url: str) -> str:
        """Map an `http(s)` base URL onto its `ws(s)` equivalent."""
        if base_url.startswith("https://"):
            return "wss://" + base_url[len("https://") :]
        if base_url.startswith("http://"):
            return "ws://" + base_url[len("http://") :]
        return base_url

    # -- Capabilities -------------------------------------------------------

    @property
    def capabilities(self) -> ProviderCapabilities:
        """What Prisma documents support for.

        Built from `prisma_contract`, so it cannot drift from the constants the
        adapter actually sends.
        """
        return ProviderCapabilities(
            name=PROVIDER_NAME,
            display_name="Gnani Prisma",
            languages=frozenset(contract.LANGUAGE_MAP),
            batch_encodings=contract.BATCH_ENCODINGS,
            streaming_encodings=contract.STREAMING_ENCODINGS,
            modes=contract.SUPPORTED_MODES,
            supports_batch=True,
            supports_streaming=True,
            # Documented protocol has no interim-result indicator.
            supports_partial_results=False,
            supports_confidence=False,
            supports_word_timestamps=False,
            supports_diarisation=False,
            streaming_sample_rates=contract.STREAMING_SAMPLE_RATES,
            streaming_frame_bytes=contract.STREAM_FRAME_BYTES,
            max_batch_bytes=self._max_audio_bytes,
            # Not published consistently by the vendor; see DOCUMENTATION_GAPS.
            max_batch_duration_seconds=None,
            requires_credentials=True,
            notes=contract.DOCUMENTATION_GAPS,
        )

    # -- Shared validation --------------------------------------------------

    def _provider_language(self, language: str) -> str:
        """Map a BhashaBench tag to Prisma's `language_code`.

        Raises rather than falling back. A silent substitution would make a
        Malayalam scenario score against a Tamil transcript.
        """
        code = contract.LANGUAGE_MAP.get(language)
        if code is None:
            raise UnsupportedLanguageError(
                f"Gnani Prisma does not document speech recognition for '{language}'; "
                f"supported languages are {sorted(contract.LANGUAGE_MAP)}",
                language=language,
                supported=tuple(sorted(contract.LANGUAGE_MAP)),
                provider=PROVIDER_NAME,
            )
        return code

    def _provider_format(self, mode: TranscriptionMode | None) -> str | None:
        """Map an output mode to Prisma's `format`, or `None` to omit it."""
        if mode is None:
            return None
        value = contract.MODE_MAP.get(mode)
        if value is None:
            raise UnsupportedFormatError(
                f"output mode '{mode.value}' has no documented Prisma 'format' value; "
                f"supported modes are {sorted(m.value for m in contract.SUPPORTED_MODES)}",
                provider=PROVIDER_NAME,
            )
        return value

    # -- Batch --------------------------------------------------------------

    async def transcribe_batch(self, request: TranscriptionRequest) -> TranscriptionResult:
        """Transcribe one file via `POST /stt/v3`.

        Validation happens before the network call so an obviously bad request
        costs nothing and produces a precise message rather than a vendor
        error that has to be interpreted.
        """
        language_code = self._provider_language(request.language)
        format_value = self._provider_format(request.mode)

        metadata = audio_tools.validate(
            request.audio,
            accepted=contract.BATCH_ENCODINGS,
            max_bytes=self._max_audio_bytes,
            declared=request.encoding if request.encoding is AudioEncoding.PCM_S16LE else None,
            sample_rate_hz=request.sample_rate_hz,
        )

        filename = audio_tools.safe_filename(
            request.metadata.get("filename"), encoding=metadata.encoding
        )
        files = {
            contract.FIELD_AUDIO: (
                filename,
                request.audio,
                audio_tools.MIME_TYPES[metadata.encoding],
            )
        }
        data: dict[str, str] = {
            contract.FIELD_MODEL: self._model,
            contract.FIELD_LANGUAGE: language_code,
        }
        if format_value is not None:
            data[contract.FIELD_FORMAT] = format_value

        url = f"{self._base_url}{contract.BATCH_PATH}"
        started = asyncio.get_running_loop().time()

        try:
            response = await self._http.post(
                url,
                files=files,
                data=data,
                headers={contract.API_KEY_HEADER: self._api_key},
            )
        except httpx2.TimeoutException as exc:
            raise TranscriptionTimeoutError(
                f"Gnani Prisma did not respond within {self._timeout_seconds:g}s",
                provider=PROVIDER_NAME,
            ) from exc
        except httpx2.RequestError as exc:
            # Covers connection resets, DNS failures and TLS errors. `redact`
            # because an httpx error message can carry the full request URL.
            raise ProviderUnavailableError(
                f"could not reach Gnani Prisma: {redact(exc)}",
                provider=PROVIDER_NAME,
            ) from exc

        latency_ms = _ms(asyncio.get_running_loop().time() - started)
        self._raise_for_status(response)
        payload = self._decode_json(response)

        result = self._normalise_batch(
            payload,
            request=request,
            latency_ms=latency_ms,
            audio_duration_seconds=metadata.duration_seconds,
        )

        logger.info(
            "transcription.batch_completed",
            extra={
                "provider": PROVIDER_NAME,
                "operation": "batch",
                "language": request.language,
                "model": result.model,
                "request_id": result.request_id,
                "correlation_id": request.correlation_id,
                "latency_ms": latency_ms,
                "provider_processing_ms": result.provider_processing_ms,
                "audio_bytes": metadata.size_bytes,
                "audio_duration_seconds": metadata.duration_seconds,
                "transcript_chars": len(result.text),
                "empty_transcript": result.is_empty,
            },
        )
        return result

    def _raise_for_status(self, response: httpx2.Response) -> None:
        """Map a Prisma HTTP status onto a structured error.

        Only the statuses the vendor documents get specific types. Everything
        else is classified by class: 5xx is transient, other 4xx is not.
        """
        status = response.status_code
        if status < 400:
            return

        detail = redact(self._error_detail(response))

        if status == contract.STATUS_UNAUTHORIZED:
            raise AuthenticationError(
                f"Gnani Prisma rejected the API key (401). Check GNANI_API_KEY "
                f"(currently {mask_secret(self._api_key)}). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
            )
        if status == contract.STATUS_PAYMENT_REQUIRED:
            raise AuthenticationError(
                f"Gnani Prisma reports insufficient credit (402). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
            )
        if status == contract.STATUS_FORBIDDEN:
            raise AuthenticationError(
                f"the Gnani API key lacks the scope for speech-to-text (403). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
            )
        if status == contract.STATUS_RATE_LIMITED:
            raise RateLimitError(
                f"Gnani Prisma rate limit reached (429). {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
                retry_after=self._retry_after(response),
            )
        if status >= 500:
            raise ProviderUnavailableError(
                f"Gnani Prisma returned {status}. {detail}",
                provider=PROVIDER_NAME,
                status_code=status,
            )

        # A 4xx the vendor does not document. Most likely our request is wrong,
        # so it is not retried.
        raise TranscriptionError(
            f"Gnani Prisma rejected the request with {status}. {detail}",
            provider=PROVIDER_NAME,
            status_code=status,
            retryable=False,
        )

    @staticmethod
    def _retry_after(response: httpx2.Response) -> float | None:
        """Parse `Retry-After` when present.

        Only the delay-seconds form is handled; the HTTP-date form is ignored
        rather than approximated, and the caller's own backoff applies instead.
        """
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return max(float(raw.strip()), 0.0)
        except ValueError:
            return None

    @staticmethod
    def _error_detail(response: httpx2.Response) -> str:
        """Extract a short, safe description of an error response.

        Truncated: a provider that returns an HTML error page should not put a
        kilobyte of markup into our error message or logs.
        """
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            text = response.text.strip()
            return f"Response body: {text[:300]}" if text else "No response body."
        if isinstance(body, dict):
            for key in ("message", "error", "detail", "reason"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:300]
        return f"Response body: {str(body)[:300]}"

    @staticmethod
    def _decode_json(response: httpx2.Response) -> dict[str, object]:
        """Parse a success response, or report a contract violation."""
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise MalformedProviderResponseError(
                f"Gnani Prisma returned a non-JSON body for a {response.status_code} "
                f"response: {redact(response.text[:200])}",
                provider=PROVIDER_NAME,
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedProviderResponseError(
                f"expected a JSON object from Gnani Prisma, got {type(payload).__name__}",
                provider=PROVIDER_NAME,
                status_code=response.status_code,
            )
        return payload

    def _normalise_batch(
        self,
        payload: dict[str, object],
        *,
        request: TranscriptionRequest,
        latency_ms: float,
        audio_duration_seconds: float | None,
    ) -> TranscriptionResult:
        """Convert a documented Prisma response into a `TranscriptionResult`.

        `success: false` with HTTP 200 is treated as a failure: the documented
        schema carries the flag, so trusting the status code alone would report
        a provider-side refusal as an empty transcript.
        """
        success = payload.get(contract.RESPONSE_SUCCESS)
        if success is False:
            raise TranscriptionError(
                f"Gnani Prisma reported failure: {redact(self._payload_message(payload))}",
                provider=PROVIDER_NAME,
                request_id=self._opt_str(payload.get(contract.RESPONSE_REQUEST_ID)),
                retryable=False,
            )

        transcript = payload.get(contract.RESPONSE_TRANSCRIPT)
        if transcript is None:
            raise MalformedProviderResponseError(
                f"the Gnani Prisma response has no '{contract.RESPONSE_TRANSCRIPT}' field; "
                f"keys present: {sorted(payload)}",
                provider=PROVIDER_NAME,
                request_id=self._opt_str(payload.get(contract.RESPONSE_REQUEST_ID)),
            )
        if not isinstance(transcript, str):
            raise MalformedProviderResponseError(
                f"'{contract.RESPONSE_TRANSCRIPT}' should be a string but was "
                f"{type(transcript).__name__}",
                provider=PROVIDER_NAME,
            )

        detected = self._opt_str(payload.get(contract.RESPONSE_DETECTED_LANGUAGE))
        # Prisma's detected code may be one we do not model (`hi-en`), or the
        # field may be absent. The requested language is the honest fallback -
        # it is what the audio was transcribed as.
        language = detected if detected in contract.LANGUAGE_MAP else request.language

        processing = self._opt_float(payload.get(contract.RESPONSE_PROCESSING_TIME))

        return TranscriptionResult(
            text=transcript,
            language=language,
            requested_language=request.language,
            provider=PROVIDER_NAME,
            model=self._opt_str(payload.get(contract.RESPONSE_MODEL)) or self._model,
            request_id=self._opt_str(payload.get(contract.RESPONSE_REQUEST_ID)),
            correlation_id=request.correlation_id,
            mode=request.mode,
            latency_ms=latency_ms,
            # Documented in seconds; our model is milliseconds throughout.
            provider_processing_ms=_ms(processing) if processing is not None else None,
            audio_duration_seconds=audio_duration_seconds,
            # Prisma documents neither, so they stay unset rather than faked.
            confidence=None,
            segments=None,
        )

    @staticmethod
    def _payload_message(payload: dict[str, object]) -> str:
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        return "no message supplied"

    @staticmethod
    def _opt_str(value: object) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _opt_float(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    # -- Streaming ----------------------------------------------------------

    async def transcribe_stream(
        self,
        audio: AsyncIterator[bytes],
        *,
        language: str,
        sample_rate_hz: int = contract.DEFAULT_STREAMING_SAMPLE_RATE,
        mode: TranscriptionMode | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream audio to `/stt/v3/stream`, yielding events as they arrive.

        Structure: one task pumps caller audio into the socket while this
        generator reads events from it. They have to be concurrent - the
        provider emits a transcript mid-utterance, so a send-everything-then-
        receive design would both stall and buffer the whole call.

        Backpressure comes from the socket. The sender awaits `send()` for each
        1024-byte frame and paces itself to real time, so a caller producing
        audio faster than the network accepts it blocks on its own iterator
        rather than filling a queue. There is no unbounded buffer anywhere in
        this path: frames are fixed-size, the partial-frame remainder is at
        most 1023 bytes, and accumulated transcript text is capped.

        Cancellation: abandoning this generator triggers its `finally`, which
        cancels the sender and closes the socket.
        """
        language_code = self._provider_language(language)
        format_value = self._provider_format(mode)

        if sample_rate_hz not in contract.STREAMING_SAMPLE_RATES:
            raise UnsupportedFormatError(
                f"Gnani Prisma streaming does not accept {sample_rate_hz} Hz; "
                f"accepted rates are {sorted(contract.STREAMING_SAMPLE_RATES)} Hz",
                provider=PROVIDER_NAME,
            )

        headers = {
            contract.WS_API_KEY_HEADER: self._api_key,
            contract.FIELD_MODEL: self._model,
            contract.FIELD_LANGUAGE: language_code,
            "x-sample-rate": str(sample_rate_hz),
        }
        if format_value is not None:
            headers[contract.FIELD_FORMAT] = format_value

        url = f"{self._ws_base_url}{contract.STREAM_PATH}"
        loop = asyncio.get_running_loop()
        started_at = loop.time()

        segments: list[TranscriptionSegment] = []
        texts: list[str] = []
        total_chars = 0
        sender: asyncio.Task[None] | None = None

        try:
            try:
                connection = await ws_connect(url, additional_headers=headers)
            except InvalidStatus as exc:
                # The upgrade was refused with an HTTP status - which is how
                # authentication failure arrives on this transport.
                status = exc.response.status_code
                if status in (
                    contract.STATUS_UNAUTHORIZED,
                    contract.STATUS_PAYMENT_REQUIRED,
                    contract.STATUS_FORBIDDEN,
                ):
                    raise AuthenticationError(
                        f"Gnani Prisma refused the streaming upgrade with {status}; "
                        f"check GNANI_API_KEY (currently {mask_secret(self._api_key)})",
                        provider=PROVIDER_NAME,
                        status_code=status,
                    ) from exc
                if status == contract.STATUS_RATE_LIMITED:
                    raise RateLimitError(
                        "Gnani Prisma rate limit reached on the streaming endpoint (429)",
                        provider=PROVIDER_NAME,
                        status_code=status,
                    ) from exc
                raise ProviderUnavailableError(
                    f"Gnani Prisma refused the streaming upgrade with {status}",
                    provider=PROVIDER_NAME,
                    status_code=status,
                ) from exc
            except (OSError, ConnectionClosed) as exc:
                raise ProviderUnavailableError(
                    f"could not open a stream to Gnani Prisma: {redact(exc)}",
                    provider=PROVIDER_NAME,
                ) from exc

            async with connection:
                yield TranscriptionStarted(
                    provider=PROVIDER_NAME,
                    language=language,
                    sample_rate_hz=sample_rate_hz,
                    correlation_id=correlation_id,
                    at=utc_now(),
                )

                sender = asyncio.create_task(
                    self._pump_audio(connection, audio, sample_rate_hz),
                    name="prisma-stream-sender",
                )

                while True:
                    try:
                        raw = await connection.recv()
                    except ConnectionClosedOK:
                        # No end-of-stream acknowledgement is documented, so a
                        # clean close is how a finished stream looks.
                        break
                    except ConnectionClosed as exc:
                        raise StreamClosedError(
                            f"Gnani Prisma closed the stream unexpectedly: {redact(exc)}",
                            provider=PROVIDER_NAME,
                        ) from exc

                    event = self._parse_stream_message(raw)
                    if event is None:
                        continue

                    kind, body = event

                    if kind == contract.EVENT_ERROR:
                        raise ProviderUnavailableError(
                            "Gnani Prisma reported a stream error: "
                            f"{redact(self._payload_message(body))}",
                            provider=PROVIDER_NAME,
                        )

                    if kind != contract.EVENT_TRANSCRIPT:
                        # `connected` and `processing` are lifecycle notices
                        # with no transcript content. They are not surfaced as
                        # events of their own: `started` already told the
                        # consumer the stream is live, and inventing a public
                        # event per vendor notice would leak the vendor's
                        # protocol into our interface.
                        continue

                    text = self._opt_str(body.get("text")) or ""
                    total_chars += len(text)
                    if total_chars > MAX_STREAM_TRANSCRIPT_CHARS:
                        raise StreamClosedError(
                            "the Gnani Prisma stream exceeded "
                            f"{MAX_STREAM_TRANSCRIPT_CHARS} transcript characters; "
                            "abandoning it rather than buffering without bound",
                            provider=PROVIDER_NAME,
                        )

                    duration_ms = self._opt_float(body.get("audio_duration_ms"))
                    index = body.get("segment_index")
                    segment_index = index if isinstance(index, int) else len(segments)

                    segments.append(
                        TranscriptionSegment(
                            text=text,
                            # Prisma sends a per-segment duration but no
                            # absolute offsets, so only the duration is
                            # modelled. Deriving offsets from arrival order
                            # would be a guess that silence does not exist.
                            start_seconds=None,
                            end_seconds=None,
                            speaker=None,
                            confidence=None,
                        )
                    )
                    if text:
                        texts.append(text)

                    # Every documented `transcript` event is settled, so this
                    # is always final - never a partial.
                    yield FinalTranscript(
                        text=text,
                        segment_index=segment_index,
                        segment_id=self._opt_str(body.get("segment_id")),
                        audio_duration_ms=duration_ms,
                        latency_ms=self._opt_float(body.get("latency")),
                        at=utc_now(),
                    )

                # The sender may still be mid-flush on a short utterance.
                if sender is not None:
                    await asyncio.gather(sender, return_exceptions=True)

                result = TranscriptionResult(
                    text=" ".join(texts).strip(),
                    language=language,
                    requested_language=language,
                    provider=PROVIDER_NAME,
                    model=self._model,
                    correlation_id=correlation_id,
                    mode=mode,
                    latency_ms=_ms(loop.time() - started_at),
                    audio_duration_seconds=None,
                    confidence=None,
                    segments=segments or None,
                )
                logger.info(
                    "transcription.stream_completed",
                    extra={
                        "provider": PROVIDER_NAME,
                        "operation": "stream",
                        "language": language,
                        "correlation_id": correlation_id,
                        "segments": len(segments),
                        "latency_ms": result.latency_ms,
                        "transcript_chars": len(result.text),
                    },
                )
                yield TranscriptionCompleted(result=result, at=utc_now())

        except TranscriptionError as exc:
            logger.warning(
                "transcription.stream_failed",
                extra={
                    "provider": PROVIDER_NAME,
                    "operation": "stream",
                    "language": language,
                    "correlation_id": correlation_id,
                    "error_type": type(exc).__name__,
                    "retryable": exc.retryable,
                },
            )
            yield TranscriptionFailed(
                error_type=type(exc).__name__,
                message=redact(exc),
                retryable=exc.retryable,
                request_id=exc.request_id,
                at=utc_now(),
            )
        finally:
            # Runs on normal completion, on error, and on the GeneratorExit
            # that a cancelling consumer triggers - so an abandoned stream
            # cannot leave the sender task or the socket alive.
            if sender is not None and not sender.done():
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)

    async def _pump_audio(
        self,
        connection: object,
        audio: AsyncIterator[bytes],
        sample_rate_hz: int,
    ) -> None:
        """Send caller audio as exactly-1024-byte frames, paced to real time.

        Prisma requires the exact frame size and warns that bursting degrades
        its voice-activity detection, so chunks from the caller are re-framed
        rather than forwarded as they arrive. The remainder carried between
        chunks is bounded by the frame size.
        """
        frame_bytes = contract.STREAM_FRAME_BYTES
        samples_per_frame = frame_bytes // 2
        frame_interval = samples_per_frame / sample_rate_hz

        buffer = bytearray()
        try:
            async for chunk in audio:
                if not chunk:
                    continue
                buffer.extend(chunk)
                while len(buffer) >= frame_bytes:
                    frame = bytes(buffer[:frame_bytes])
                    del buffer[:frame_bytes]
                    await connection.send(frame)  # type: ignore[attr-defined]
                    await asyncio.sleep(frame_interval)

            if buffer:
                # Pad the tail so the final frame still matches the required
                # size. Silence is the correct padding for PCM; truncating
                # would drop the end of the last word.
                await connection.send(  # type: ignore[attr-defined]
                    bytes(buffer) + b"\x00" * (frame_bytes - len(buffer))
                )
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            # The reader loop owns the lifecycle and will report the close.
            return

    def _parse_stream_message(self, raw: object) -> tuple[str, dict[str, object]] | None:
        """Decode one WebSocket message into `(type, body)`.

        Returns `None` for anything that is not a usable JSON object, so an
        unexpected frame is skipped rather than killing a live stream. A binary
        frame is not an error either: the documented protocol sends audio one
        way and JSON the other, and tolerating the unexpected is the right
        posture for a long-lived socket.
        """
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(raw, str):
            return None
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug(
                "transcription.stream_non_json_frame",
                extra={"provider": PROVIDER_NAME, "bytes": len(raw)},
            )
            return None
        if not isinstance(body, dict):
            return None
        kind = body.get("type")
        if not isinstance(kind, str):
            return None
        return kind, body

    # -- Lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        """Close the pooled HTTP client, if this provider owns it.

        A no-op when the client was never built, which is the normal case for
        a provider constructed only to report its capabilities.
        """
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


__all__ = ["MAX_STREAM_TRANSCRIPT_CHARS", "PROVIDER_NAME", "GnaniPrismaProvider"]
