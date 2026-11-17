"""The reference bot's voice endpoint: `bhashabench-voice-bot/1` (Phase 9).

Speaks no language. Its "speech" is a 440 Hz tone, because what this endpoint
exists to exercise is turn-taking - latency, barge-in, silence, a bot that
will not stop - and those are properties of *when* audio flows, not what it
says. Each turn follows a `VoiceTurn` from the script, so a test can make the
bot answer promptly, talk over the caller, stay silent, or run on.

Authentication is the same bearer token as the text API, checked before the
handshake is accepted (close 1008 otherwise).
"""

from __future__ import annotations

import asyncio
import json
import math
import struct
from dataclasses import dataclass
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

VOICE_PROTOCOL = "bhashabench-voice-bot/1"
SAMPLE_RATE = 16_000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

Behaviour = Literal["answer", "barge_in", "silent", "endless"]


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    behaviour: Behaviour = "answer"
    delay_ms: int = 300
    """After the caller's turn ends (for `answer`), or after the first caller
    frame (for `barge_in`)."""
    speech_ms: int = 600
    signal_end: bool = True
    """Send `turn_end` after speaking. Without it the caller must end-point."""


DEFAULT_VOICE_SCRIPT: tuple[VoiceTurn, ...] = (VoiceTurn(),)
"""The last entry repeats for every later turn."""


def _tone_frame(index: int, amplitude: int = 8000) -> bytes:
    start = index * FRAME_SAMPLES
    samples = [
        int(amplitude * math.sin(2 * math.pi * 440 * (start + i) / SAMPLE_RATE))
        for i in range(FRAME_SAMPLES)
    ]
    return struct.pack(f"<{FRAME_SAMPLES}h", *samples)


SILENT_FRAME = b"\x00\x00" * FRAME_SAMPLES


async def _speak(socket: WebSocket, milliseconds: int) -> None:
    for index in range(max(milliseconds // FRAME_MS, 1)):
        await socket.send_bytes(_tone_frame(index))
        await asyncio.sleep(FRAME_MS / 1000)


def register_voice(app: FastAPI, *, token: str, script: tuple[VoiceTurn, ...]) -> None:
    expected = f"Bearer {token}"

    @app.websocket("/v1/voice")
    async def voice(socket: WebSocket) -> None:
        if socket.headers.get("authorization") != expected:
            await socket.close(code=1008, reason="unauthorized")
            return
        await socket.accept()
        start = await socket.receive_json()
        if start.get("type") != "start" or start.get("protocol") != VOICE_PROTOCOL:
            await socket.send_json(
                {"type": "error", "code": "protocol", "message": "expected start"}
            )
            await socket.close(code=1002)
            return
        if start.get("sample_rate_hz") != SAMPLE_RATE or start.get("encoding") != "pcm_s16le":
            await socket.send_json(
                {"type": "error", "code": "format", "message": "16 kHz pcm_s16le only"}
            )
            await socket.close(code=1003)
            return
        await socket.send_json({"type": "ready", "protocol": VOICE_PROTOCOL})

        turn = 0
        speaking: asyncio.Task[None] | None = None
        caller_frames = 0
        try:
            while True:
                plan = script[min(turn, len(script) - 1)]
                message = await socket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    caller_frames += 1
                    if plan.behaviour == "barge_in" and caller_frames == 1 and speaking is None:

                        async def barge(p: VoiceTurn = plan, n: int = turn) -> None:
                            await asyncio.sleep(p.delay_ms / 1000)
                            await _speak(socket, p.speech_ms)
                            if p.signal_end:
                                await socket.send_json({"type": "turn_end", "turn_index": n})

                        speaking = asyncio.create_task(barge())
                    continue
                control = json.loads(message.get("text") or "{}")
                if control.get("type") == "hangup":
                    break
                if control.get("type") != "caller_turn_end":
                    continue
                if plan.behaviour == "answer":
                    await asyncio.sleep(plan.delay_ms / 1000)
                    await _speak(socket, plan.speech_ms)
                    if plan.signal_end:
                        await socket.send_json({"type": "turn_end", "turn_index": turn})
                elif plan.behaviour == "endless":
                    await asyncio.sleep(plan.delay_ms / 1000)
                    speaking = asyncio.create_task(_speak(socket, 10 * 60 * 1000))
                elif plan.behaviour == "barge_in" and speaking is not None:
                    await speaking
                # `silent`: say nothing at all.
                if speaking is not None and plan.behaviour != "endless":
                    speaking = None
                turn += 1
                caller_frames = 0
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if speaking is not None:
                speaking.cancel()


__all__ = ["DEFAULT_VOICE_SCRIPT", "VOICE_PROTOCOL", "VoiceTurn", "register_voice"]
