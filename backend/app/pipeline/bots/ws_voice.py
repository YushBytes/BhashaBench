"""The streaming voice adapter: `bhashabench-voice-bot/1` over a WebSocket.

One socket per run, opened on the first turn. Each turn the caller's audio is
streamed in real time - 20 ms frames, 20 ms apart - while the bot's frames are
received concurrently and fed to `BotTurnTracker`, which decides when the
bot's turn ended: its own `turn_end`, end-of-turn silence, a silence timeout,
or the per-turn deadline. If the bot speaks before the caller has finished
(a barge-in), the caller yields: its remaining frames are not sent, which is
what a person would do and is recorded as `caller_truncated`.

**Real time on purpose.** Streaming faster than real time would make every
latency figure fiction; this is the one adapter whose timings describe what
a person on the line would experience, so it is not accelerated in tests
either.

Speaks the project's own protocol (docs/BOT_PROTOCOL.md), never a vendor's.
Every URL passes the outbound guard. The token is never logged or returned.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import uuid
import wave
from dataclasses import dataclass, field
from typing import Any

import websockets
import websockets.asyncio.client
from pydantic import SecretStr

from app.core.outbound import OutboundPolicy, OutboundTargetRefusedError, check_url
from app.pipeline.bots.protocol import BotCapabilities, BotReply
from app.pipeline.degradation import decode_pcm16_wav, resample, to_mono
from app.pipeline.errors import (
    BotAdapterError,
    BotTargetRefusedError,
    BotTimeoutError,
    BotUnavailableError,
)
from app.pipeline.streaming import (
    FRAME_BYTES,
    FRAME_MS,
    SAMPLE_RATE_HZ,
    BotTurnTracker,
    EndedBy,
    TurnPolicy,
    frames,
)
from app.transcription.redaction import redact
from app.utils.timing import monotonic_seconds

PROVIDER_NAME = "ws_voice"
PROTOCOL = "bhashabench-voice-bot/1"
MAX_BOT_FRAME_BYTES = FRAME_BYTES * 4

CAPABILITIES = BotCapabilities(
    name=PROVIDER_NAME,
    display_name="Streaming voice bot (bhashabench-voice-bot/1)",
    contacts_external_system=True,
    supports_sessions=True,
    requires_credentials=True,
    accepts_containers=frozenset({"wav"}),
    notes=(
        "Streams 16 kHz pcm_s16le in 20 ms frames, in real time, over a WebSocket.",
        "Voice activity is energy-based; its threshold is recorded with every turn.",
        "Bot latency is caller end to first voiced bot frame, on our monotonic clock.",
        "Speaks the project's own protocol, not any vendor's.",
    ),
)


class _connect_without_redirects(websockets.asyncio.client.connect):  # noqa: N801
    """`websockets.connect` that never follows a redirect.

    The library follows 3xx answers to the handshake, cross-origin included,
    and sends the same headers - the bot's bearer token - to the new URI. That
    URI never passed `check_url`, so following it would let an allowlisted bot
    point this process at any address and collect the credential. A redirect
    is therefore a failed handshake, as `follow_redirects=False` makes it for
    the HTTP adapter.
    """

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


@dataclass(frozen=True, slots=True)
class VoiceBotConfig:
    url: str
    token: SecretStr
    policy: OutboundPolicy
    turn_policy: TurnPolicy = field(default_factory=TurnPolicy)
    connect_timeout_seconds: float = 10.0


def _wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE_HZ)
        handle.writeframes(pcm)
    return buffer.getvalue()


def _caller_pcm(audio: bytes) -> bytes:
    samples, rate, channels = decode_pcm16_wav(audio)
    return resample(
        to_mono(samples, channels), source_rate=rate, target_rate=SAMPLE_RATE_HZ
    ).tobytes()


class WebSocketVoiceBotAdapter:
    def __init__(self, config: VoiceBotConfig) -> None:
        try:
            check_url(
                config.url.replace("ws://", "http://").replace("wss://", "https://"), config.policy
            )
        except OutboundTargetRefusedError as exc:
            raise BotTargetRefusedError(
                f"the bot URL was refused: {exc}", adapter=PROVIDER_NAME
            ) from exc
        if not config.url.startswith(("ws://", "wss://")):
            raise BotTargetRefusedError(
                "the voice bot URL must be ws:// or wss://", adapter=PROVIDER_NAME
            )
        self._config = config
        self._socket: Any = None
        self._run: uuid.UUID | None = None

    @property
    def capabilities(self) -> BotCapabilities:
        return CAPABILITIES

    async def _connect(self, run_id: uuid.UUID, language: str) -> Any:
        if self._socket is not None and self._run == run_id:
            return self._socket
        await self.close()
        headers = {"Authorization": f"Bearer {self._config.token.get_secret_value()}"}
        try:
            socket = await asyncio.wait_for(
                _connect_without_redirects(
                    self._config.url, additional_headers=headers, max_size=MAX_BOT_FRAME_BYTES * 64
                ),
                timeout=self._config.connect_timeout_seconds,
            )
        except (TimeoutError, OSError, websockets.InvalidHandshake) as exc:
            raise BotUnavailableError(
                f"the voice bot could not be reached: {type(exc).__name__}: {redact(exc)}",
                adapter=PROVIDER_NAME,
            ) from exc
        await socket.send(json.dumps({
            "type": "start", "protocol": PROTOCOL, "language": language,
            "sample_rate_hz": SAMPLE_RATE_HZ, "encoding": "pcm_s16le", "frame_ms": FRAME_MS,
            "run_id": str(run_id),
        }))  # fmt: skip
        try:
            ready = json.loads(
                await asyncio.wait_for(socket.recv(), timeout=self._config.connect_timeout_seconds)
            )
        except (TimeoutError, websockets.ConnectionClosed, ValueError) as exc:
            await socket.close()
            raise BotUnavailableError(
                "the voice bot did not answer the start message", adapter=PROVIDER_NAME
            ) from exc
        if ready.get("type") != "ready":
            await socket.close()
            raise BotAdapterError(
                "the voice bot refused the session: "
                + redact(str(ready.get("message", ready)))[:200],
                adapter=PROVIDER_NAME,
            )
        self._socket, self._run = socket, run_id
        return socket

    async def send_turn(
        self,
        audio: bytes,
        *,
        run_id: uuid.UUID,
        turn_index: int,
        content_type: str,
        language: str,
        timeout_seconds: float,
        session_id: str | None = None,
    ) -> BotReply:
        socket = await self._connect(run_id, language)
        try:
            caller = frames(_caller_pcm(audio))
        except Exception as exc:
            raise BotAdapterError(
                f"the caller audio could not be framed: {exc}", adapter=PROVIDER_NAME
            ) from exc
        policy = self._config.turn_policy
        tracker = BotTurnTracker(policy=policy, caller_started_at=monotonic_seconds())
        ended: asyncio.Future[EndedBy] = asyncio.get_running_loop().create_future()
        sent = 0

        async def stream_caller() -> None:
            nonlocal sent
            for frame in caller:
                if tracker.barged_in and policy.yield_on_barge_in:
                    break
                await socket.send(frame)
                sent += 1
                await asyncio.sleep(FRAME_MS / 1000)
            await socket.send(json.dumps({"type": "caller_turn_end", "turn_index": turn_index}))
            tracker.caller_ended_at = monotonic_seconds()

        async def listen() -> None:
            while not ended.done():
                try:
                    message = await asyncio.wait_for(socket.recv(), timeout=FRAME_MS / 1000)
                except TimeoutError:
                    reason = tracker.check(monotonic_seconds())
                    if reason is not None and not ended.done():
                        ended.set_result(reason)
                    continue
                if isinstance(message, bytes):
                    if len(message) > MAX_BOT_FRAME_BYTES:
                        raise BotAdapterError(
                            "the bot sent an oversized audio frame", adapter=PROVIDER_NAME
                        )
                    reason = tracker.observe(message, monotonic_seconds())
                elif (
                    json.loads(message).get("type") == "turn_end"
                    and tracker.speech_started_at is not None
                ):
                    reason = EndedBy.BOT_SIGNAL if tracker.caller_ended_at is not None else None
                elif json.loads(message).get("type") == "hangup":
                    reason = EndedBy.BOT_HANGUP
                else:
                    reason = None
                if reason is not None and not ended.done():
                    ended.set_result(reason)

        sender = asyncio.create_task(stream_caller())
        listener = asyncio.create_task(listen())
        try:
            async with asyncio.timeout(timeout_seconds):
                await sender
                reason = await ended
        except TimeoutError as exc:
            raise BotTimeoutError(
                f"no complete bot turn within {timeout_seconds:g}s", adapter=PROVIDER_NAME
            ) from exc
        except websockets.ConnectionClosed as exc:
            raise BotUnavailableError(
                "the voice bot closed the connection mid-turn", adapter=PROVIDER_NAME
            ) from exc
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await listener
            if not sender.done():
                sender.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await sender

        evidence = tracker.evidence(
            reason,
            caller_frames_sent=sent,
            caller_frames_total=len(caller),
            ended_at=monotonic_seconds(),
        )
        bot_audio = b"" if tracker.speech_started_at is None else _wav(bytes(tracker.audio))
        return BotReply(
            audio=bot_audio,
            content_type="audio/wav",
            received_from_bot=True,
            session_id=session_id,
            latency_ms=tracker.latency_ms(),
            stream=evidence,
        )

    async def close(self) -> None:
        if self._socket is not None:
            with contextlib.suppress(Exception):
                await self._socket.send(json.dumps({"type": "hangup", "reason": "run_finished"}))
                await self._socket.close()
        self._socket, self._run = None, None


__all__ = ["CAPABILITIES", "PROTOCOL", "VoiceBotConfig", "WebSocketVoiceBotAdapter"]
