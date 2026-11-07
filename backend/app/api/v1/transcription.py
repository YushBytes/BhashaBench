"""Transcription endpoints.

Three of them, which is the minimum that makes the subsystem usable: submit a
file, stream a call, and ask what the provider can do.

**Why these handlers are `async def`.** `docs/ARCHITECTURE.md` explains that
database handlers are synchronous so FastAPI runs them in a worker thread.
These touch no database - Phase 4 persists nothing - and they are entirely
network-bound, so running them on the event loop is right rather than a
departure. The streaming endpoint could not be synchronous at all: it
interleaves receiving client audio with forwarding provider events.

**Why WebSocket for streaming.** The transport has to carry audio *up* while
events come *down*, which rules out an HTTP streaming response. It also
mirrors the provider's own protocol, so neither side needs buffering to adapt
between a request-shaped and a stream-shaped API. Phase 8's Twilio Media
Streams are a WebSocket too, so this is the transport the orchestrator will
already be speaking.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, WebSocket, status
from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.api.deps import SettingsDep
from app.core import languages
from app.schemas.common import ErrorResponse
from app.schemas.transcription import (
    ProviderCapabilitiesResponse,
    ProviderListResponse,
    StreamMessage,
    TranscriptionResponse,
)
from app.services.transcription_service import TranscriptionService, classify
from app.transcription.base import ProviderCapabilities
from app.transcription.errors import (
    AudioTooLargeError,
    ConfigurationError,
    TranscriptionError,
)
from app.transcription.models import (
    AudioEncoding,
    StreamEventType,
    TranscriptionCompleted,
    TranscriptionMode,
)
from app.transcription.redaction import redact
from app.transcription.registry import build_provider, describe_providers
from app.utils.timing import utc_now

logger = logging.getLogger("bhashabench.api.transcription")

router = APIRouter(prefix="/transcription", tags=["transcription"])

# Upper bound on a single inbound WebSocket audio frame. The provider reframes
# to its own size anyway, so a client has no reason to send more, and without a
# cap one client could make the server buffer without limit.
MAX_WS_FRAME_BYTES = 64 * 1024

# How many audio frames may sit between the socket and the provider. Small on
# purpose: the queue exists to decouple receive from send, not to store the
# call. When it fills, the reader stops reading and TCP backpressure reaches
# the client, which is the behaviour that keeps memory flat on a slow provider.
AUDIO_QUEUE_FRAMES = 32

WS_CLOSE_INVALID_REQUEST = 1008
"""RFC 6455 "policy violation" - used for a bad language or sample rate."""
WS_CLOSE_INTERNAL_ERROR = 1011


def get_service_factory(settings: SettingsDep) -> Callable[[], TranscriptionService]:
    """Return a callable that builds the configured service.

    A factory rather than the service itself, because the WebSocket route needs
    construction to be *deferred*. A `ConfigurationError` raised while FastAPI
    is resolving dependencies happens before `accept()`, and there is no open
    socket to report it on - the client sees a bare connection failure instead
    of being told which setting is missing. Returning a lambda lets that route
    accept the connection first and then build, so the error becomes a `failed`
    frame.

    It is also the single override point for tests: replacing this one
    dependency swaps the provider for both the HTTP and the WebSocket route.
    """
    return lambda: TranscriptionService(build_provider(settings), settings=settings)


ServiceFactoryDep = Annotated[Callable[[], TranscriptionService], Depends(get_service_factory)]


def get_transcription_service(factory: ServiceFactoryDep) -> TranscriptionService:
    """Build the configured transcription service for a request.

    Per-request rather than a cached singleton: `Settings` is already cached
    and the Prisma adapter builds its HTTP client lazily, so this is cheap.
    """
    return factory()


ServiceDep = Annotated[TranscriptionService, Depends(get_transcription_service)]


@router.post(
    "",
    response_model=TranscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Transcribe an audio file",
    description=(
        "Submit one audio file as `multipart/form-data` and receive a "
        "structured transcript.\n\n"
        "The container is identified from the file's own bytes; a declared "
        "content type or filename extension is treated as a hint, not as "
        "evidence. `GET /api/v1/transcription/providers` lists the encodings, "
        "languages and output modes the configured provider accepts.\n\n"
        "`confidence` and `segments` are `null` when the provider does not "
        "report them. They are never synthesised."
    ),
    responses={
        status.HTTP_200_OK: {"description": "Transcription completed, possibly with empty text."},
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "Audio exceeds the configured or provider limit.",
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "model": ErrorResponse,
            "description": "Audio format or sample rate the provider does not accept.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Invalid audio, or a language the provider cannot transcribe.",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "The provider is rate limiting.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "The provider was unreachable or replied unusably.",
        },
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "model": ErrorResponse,
            "description": "The provider did not respond in time.",
        },
    },
)
async def transcribe_file(
    service: ServiceDep,
    settings: SettingsDep,
    audio: Annotated[UploadFile, File(description="The audio file to transcribe.")],
    language: Annotated[str, Form(description="BhashaBench language tag, e.g. `hi-IN`.")],
    mode: Annotated[
        TranscriptionMode | None,
        Form(description="Requested output mode. Provider default when omitted."),
    ] = None,
    sample_rate_hz: Annotated[
        int | None,
        Form(description="Required only for headerless `pcm_s16le` audio."),
    ] = None,
    encoding: Annotated[
        AudioEncoding | None,
        Form(
            description="Declare the encoding. Required for raw `pcm_s16le`; "
            "for container formats a declaration that contradicts the file's "
            "content is rejected rather than trusted."
        ),
    ] = None,
    correlation_id: Annotated[
        str | None,
        Form(description="Your identifier, echoed into the response and the logs."),
    ] = None,
) -> TranscriptionResponse:
    """Transcribe an uploaded file."""
    # Read with a cap rather than unbounded. `UploadFile` spools to a temp file
    # past a threshold, so reading without a limit lets one request write an
    # arbitrary amount to disk before any size check can run.
    limit = settings.transcription_max_upload_bytes
    payload = await audio.read(limit + 1)
    if len(payload) > limit:
        # Raised from the service's own error family so the existing handler
        # maps it; the route does not choose a status code itself.
        raise AudioTooLargeError(
            f"the upload exceeds the {limit} byte limit (TRANSCRIPTION_MAX_UPLOAD_BYTES)"
        )

    result = await service.transcribe_batch(
        payload,
        language=language,
        mode=mode,
        declared_encoding=encoding,
        sample_rate_hz=sample_rate_hz,
        correlation_id=correlation_id,
        # Client-supplied and therefore untrusted; reduced to a safe basename
        # before it reaches the provider or a log line.
        filename=audio.filename,
    )
    return TranscriptionResponse.of(result)


@router.get(
    "/providers",
    response_model=ProviderListResponse,
    summary="List transcription providers and their capabilities",
    description=(
        "Describes every registered provider, whether or not it is currently "
        "usable. A provider missing a credential is listed as `available: "
        "false` with the reason - it is never omitted, because an absent entry "
        "and an unconfigured one look identical to a caller.\n\n"
        "`notes` carries verified vendor documentation gaps. "
        "`unsupported_catalogue_languages` lists languages a scenario may be "
        "authored in that this provider cannot transcribe."
    ),
)
def list_providers(settings: SettingsDep) -> ProviderListResponse:
    """Describe all registered providers.

    Synchronous: it reads static metadata and opens no connection.
    """
    catalogue = set(languages.SUPPORTED_CODES)
    described: list[ProviderCapabilitiesResponse] = []

    for name, capabilities, reason in describe_providers(settings):
        if capabilities is None:
            described.append(
                _unavailable_provider(
                    name, reason, selected=name == settings.transcription_provider
                )
            )
            continue

        if not isinstance(capabilities, ProviderCapabilities):  # pragma: no cover
            # describe_providers' signature is deliberately loose to avoid an
            # import cycle; this narrows it without trusting the annotation.
            raise TypeError(f"provider '{name}' reported unusable capabilities")
        described.append(
            ProviderCapabilitiesResponse(
                name=capabilities.name,
                display_name=capabilities.display_name,
                selected=capabilities.name == settings.transcription_provider,
                available=True,
                unavailable_reason=None,
                languages=sorted(capabilities.languages),
                unsupported_catalogue_languages=sorted(catalogue - capabilities.languages),
                batch_encodings=sorted(capabilities.batch_encodings),
                streaming_encodings=sorted(capabilities.streaming_encodings),
                modes=sorted(capabilities.modes),
                supports_batch=capabilities.supports_batch,
                supports_streaming=capabilities.supports_streaming,
                supports_partial_results=capabilities.supports_partial_results,
                supports_confidence=capabilities.supports_confidence,
                supports_word_timestamps=capabilities.supports_word_timestamps,
                supports_diarisation=capabilities.supports_diarisation,
                streaming_sample_rates=sorted(capabilities.streaming_sample_rates),
                streaming_frame_bytes=capabilities.streaming_frame_bytes,
                max_batch_bytes=capabilities.max_batch_bytes,
                max_batch_duration_seconds=capabilities.max_batch_duration_seconds,
                requires_credentials=capabilities.requires_credentials,
                notes=list(capabilities.notes),
            )
        )

    return ProviderListResponse(selected=settings.transcription_provider, providers=described)


def _unavailable_provider(
    name: str, reason: str | None, *, selected: bool
) -> ProviderCapabilitiesResponse:
    """Describe a provider that cannot currently be constructed.

    Capabilities are unknown because the adapter was never built, so the
    booleans are reported false and the lists empty rather than guessed. The
    reason is the useful part.
    """
    return ProviderCapabilitiesResponse(
        name=name,
        display_name=name,
        selected=selected,
        available=False,
        unavailable_reason=reason,
        languages=[],
        unsupported_catalogue_languages=[],
        batch_encodings=[],
        streaming_encodings=[],
        modes=[],
        supports_batch=False,
        supports_streaming=False,
        supports_partial_results=False,
        supports_confidence=False,
        supports_word_timestamps=False,
        supports_diarisation=False,
        streaming_sample_rates=[],
        streaming_frame_bytes=None,
        max_batch_bytes=None,
        max_batch_duration_seconds=None,
        requires_credentials=True,
        notes=[],
    )


@router.websocket("/stream")
async def transcribe_websocket(
    websocket: WebSocket,
    factory: ServiceFactoryDep,
    language: Annotated[str, Query(description="BhashaBench language tag.")],
    sample_rate_hz: Annotated[
        int, Query(description="Sample rate of the PCM you will send.")
    ] = 16000,
    mode: Annotated[TranscriptionMode | None, Query(description="Output mode.")] = None,
    correlation_id: Annotated[str | None, Query(description="Your identifier.")] = None,
) -> None:
    """Stream raw PCM up, receive transcription events down.

    Protocol, from the client's side:

    1. Connect with `language` (and optionally `sample_rate_hz`, `mode`,
       `correlation_id`) as query parameters. Query parameters rather than
       headers because browsers cannot set headers on a WebSocket.
    2. Send binary frames of signed 16-bit little-endian mono PCM at the
       declared sample rate. Frame size is up to you; the provider's own
       framing is handled server-side.
    3. Send the text frame `EOS` when the audio is finished, or just close.
    4. Receive JSON events: `started`, then `final_transcript` per settled
       segment (and `partial_transcript` from providers that emit interim
       results - Prisma does not), then exactly one `completed` or `failed`.

    The service is injected as a *factory* and built after `accept()`. A
    `ConfigurationError` raised while dependencies are being resolved would
    happen before the handshake, leaving no socket to report it on; building
    it here turns a missing setting into a `failed` frame the client can read.
    """
    await websocket.accept()

    try:
        service = factory()
    except ConfigurationError as exc:
        await _send_failure(websocket, exc)
        await websocket.close(code=WS_CLOSE_INTERNAL_ERROR)
        return

    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=AUDIO_QUEUE_FRAMES)
    reader = asyncio.create_task(
        _read_client_audio(websocket, queue), name="transcription-ws-reader"
    )

    try:
        events = service.transcribe_stream(
            _drain(queue),
            language=language,
            sample_rate_hz=sample_rate_hz,
            mode=mode,
            correlation_id=correlation_id,
        )
    except (TranscriptionError, languages.UnsupportedLanguageError) as exc:
        # Eager validation failure - a bad language or sample rate. Reported
        # before any audio is consumed.
        reader.cancel()
        await _send_failure(websocket, exc)
        await websocket.close(code=WS_CLOSE_INVALID_REQUEST)
        return

    try:
        async for event in events:
            await websocket.send_json(_encode_event(event))
    except WebSocketDisconnect:
        # The client went away mid-stream. Normal, not an error: the `finally`
        # closes the provider connection.
        logger.info(
            "transcription.ws_client_disconnected",
            extra={"correlation_id": correlation_id, "language": language},
        )
    except TranscriptionError as exc:
        await _send_failure(websocket, exc)
    except Exception:
        logger.exception("transcription.ws_unexpected_error")
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close(code=WS_CLOSE_INTERNAL_ERROR)
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        # `aclose()` on the event generator runs the adapter's own `finally`,
        # which cancels its sender task and closes the provider socket. Without
        # it a client that disconnects early would leave both alive.
        await events.aclose()
        await service.close()
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close()


async def _read_client_audio(websocket: WebSocket, queue: asyncio.Queue[bytes | None]) -> None:
    """Move client frames onto the queue until the stream ends.

    `await queue.put` is the backpressure: once `AUDIO_QUEUE_FRAMES` frames are
    waiting, this coroutine stops reading the socket and the client's own
    sends start to block. Nothing here grows without bound.
    """
    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                await queue.put(None)
                return

            data = message.get("bytes")
            if data is not None:
                if len(data) > MAX_WS_FRAME_BYTES:
                    logger.warning(
                        "transcription.ws_frame_too_large",
                        extra={"bytes": len(data), "limit": MAX_WS_FRAME_BYTES},
                    )
                    await queue.put(None)
                    return
                await queue.put(data)
                continue

            text = message.get("text")
            if text is not None and text.strip().upper() == "EOS":
                await queue.put(None)
                return
            # Any other text frame is ignored rather than fatal: a client
            # sending a stray keepalive should not lose its transcription.
    except asyncio.CancelledError:
        raise
    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is what Starlette raises for a receive after close.
        await queue.put(None)


async def _drain(queue: asyncio.Queue[bytes | None]) -> AsyncIterator[bytes]:
    """Yield queued audio frames until the sentinel arrives."""
    while True:
        chunk = await queue.get()
        if chunk is None:
            return
        yield chunk


def _encode_event(event: object) -> dict[str, object]:
    """Serialise a domain stream event into a `StreamMessage` frame.

    Unset fields are dropped so a `final_transcript` frame does not ship a
    dozen nulls on every segment of every call.
    """
    kind = getattr(event, "type", None)
    if kind is None:  # pragma: no cover - every StreamEvent declares one
        raise TypeError(f"{type(event).__name__} is not a stream event")

    if isinstance(event, TranscriptionCompleted):
        message = StreamMessage(
            type=str(StreamEventType.COMPLETED),
            at=event.at,
            result=TranscriptionResponse.of(event.result),
        )
    else:
        fields = event.model_dump()  # type: ignore[attr-defined]
        fields["type"] = str(kind)
        message = StreamMessage.model_validate(fields)

    return jsonable_encoder(message, exclude_none=True)


async def _send_failure(websocket: WebSocket, exc: Exception) -> None:
    """Send one terminal `failed` frame, if the socket is still open.

    The message is redacted here as well as in the adapters: this is the only
    route by which a streaming error reaches a client, so it is the right place
    for the guarantee to hold even if an adapter forgets. No traceback and no
    provider payload is included.
    """
    if websocket.client_state is not WebSocketState.CONNECTED:
        return

    retryable = exc.retryable if isinstance(exc, TranscriptionError) else False
    error_type = classify(exc) if isinstance(exc, TranscriptionError) else "validation_error"
    try:
        await websocket.send_json(
            {
                "type": str(StreamEventType.FAILED),
                "at": utc_now().isoformat(),
                "error_type": error_type,
                "message": redact(exc),
                "retryable": retryable,
            }
        )
    except (WebSocketDisconnect, RuntimeError):
        # The client is already gone; there is nobody to tell.
        return


__all__ = ["get_transcription_service", "router"]
