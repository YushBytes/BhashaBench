"""Check that a connected bot answers, through the adapter a run would use.

"Connection successful" must mean what a run will find, so the check is
not a reimplementation of either protocol. It calls the same adapter code a
run calls, with the same outbound guard and address pinning:

- **http** (`bhashabench-text-bot/1`): open a session, send one short text
  turn, close the session. That proves the URL, the credential, the session
  lifecycle and the reply shape.
- **ws_voice** (`bhashabench-voice-bot/1`): open the WebSocket, send `start`
  with the exact audio format a run streams (16 kHz `pcm_s16le`, 20 ms
  frames) and wait for `ready`, then hang up. That proves the URL, the
  credential, the protocol and that the bot accepts the audio format. It does
  **not** prove the bot answers audio well, or yields to a barge-in: those are
  what a run measures, and the result says so (`verified` holds `None` for
  them, never `True`).

Every failure is mapped to one outcome a person can act on, and every message
that might carry bot text is redacted and truncated. The token never appears.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import websockets
from pydantic import SecretStr

from app.core.outbound import OutboundPolicy, Resolver
from app.pipeline.bots.http_text import CAPABILITIES as HTTP_CAPABILITIES
from app.pipeline.bots.http_text import HttpBotConfig, HttpTextBotAdapter
from app.pipeline.bots.protocol import BotCapabilities
from app.pipeline.bots.ws_voice import CAPABILITIES as WS_CAPABILITIES
from app.pipeline.bots.ws_voice import PROTOCOL as WS_PROTOCOL
from app.pipeline.bots.ws_voice import connect_pinned
from app.pipeline.errors import (
    BotAdapterError,
    BotAuthenticationError,
    BotProtocolError,
    BotTargetRefusedError,
    BotTimeoutError,
    BotUnavailableError,
)
from app.pipeline.streaming import FRAME_MS, SAMPLE_RATE_HZ
from app.transcription.redaction import redact

PROBE_TEXT = "Hello, this is a BhashaBench connection check."
"""The one turn the HTTP check sends. Plain and short, and says what it is, so a
bot's own logs show where it came from."""


class ProbeOutcome(StrEnum):
    CONNECTED = "connected"
    AUTHENTICATION_FAILED = "authentication_failed"
    TARGET_REFUSED = "target_refused"
    """BhashaBench's own safety rules refused the URL before connecting."""
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"
    """The bot answered, but not in the protocol it is configured for."""
    SESSION_REJECTED = "session_rejected"
    """A voice bot refused `start` - most often the audio format."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    outcome: ProbeOutcome
    message: str
    protocol: str
    latency_ms: float | None
    verified: dict[str, bool | None]
    """Capability -> True (seen working), False (seen failing) or None (not
    exercised by a connection check; a run measures it)."""
    declared: BotCapabilities
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome is ProbeOutcome.CONNECTED

    def as_record(self) -> dict[str, Any]:
        """JSON for `BotIntegration.last_check`. No credential, by construction."""
        return {
            "outcome": self.outcome.value,
            "message": self.message,
            "protocol": self.protocol,
            "latency_ms": self.latency_ms,
            "verified": dict(self.verified),
            "detail": dict(self.detail),
        }


def _message(exc: Exception) -> str:
    return redact(str(exc))[:300]


def _classify(exc: Exception) -> ProbeOutcome:
    if isinstance(exc, BotTargetRefusedError):
        return ProbeOutcome.TARGET_REFUSED
    if isinstance(exc, BotAuthenticationError):
        return ProbeOutcome.AUTHENTICATION_FAILED
    if isinstance(exc, BotTimeoutError):
        return ProbeOutcome.TIMEOUT
    if isinstance(exc, BotUnavailableError):
        return ProbeOutcome.UNREACHABLE
    if isinstance(exc, BotProtocolError):
        return ProbeOutcome.PROTOCOL_ERROR
    return ProbeOutcome.PROTOCOL_ERROR


HTTP_UNVERIFIED: dict[str, bool | None] = {
    "reachable": None,
    "authenticated": None,
    "session_lifecycle": None,
    "text_exchange": None,
    "audio_input": False,
    "audio_output": False,
}
"""The text protocol carries no audio at all: False is a fact about the
protocol, not a test result."""


async def probe_http(
    *,
    url: str,
    token: SecretStr,
    policy: OutboundPolicy,
    language: str,
    timeout_seconds: float,
    resolver: Resolver | None = None,
) -> ProbeResult:
    verified = dict(HTTP_UNVERIFIED)
    probe_id = uuid.uuid4()
    started = time.monotonic()
    try:
        adapter = HttpTextBotAdapter(
            HttpBotConfig(
                base_url=url, token=token, policy=policy,
                timeout_seconds=timeout_seconds, max_attempts=1,
            ),
            resolver=resolver,
        )  # fmt: skip
        session = await adapter.open_session(run_id=probe_id, language=language)
        verified.update(reachable=True, authenticated=True)
        reply = await adapter.send_text(
            PROBE_TEXT, session_id=session.session_id, run_id=probe_id, turn_index=0
        )
        verified["text_exchange"] = True
        await adapter.close_session(session_id=session.session_id, run_id=probe_id)
        verified["session_lifecycle"] = True
    except BotAdapterError as exc:
        outcome = _classify(exc)
        if outcome is ProbeOutcome.AUTHENTICATION_FAILED:
            verified.update(reachable=True, authenticated=False)
        return ProbeResult(
            outcome, _message(exc), "http", None, verified, HTTP_CAPABILITIES,
            {"stage": _stage(verified)},
        )  # fmt: skip
    latency = round((time.monotonic() - started) * 1000, 1)
    return ProbeResult(
        ProbeOutcome.CONNECTED,
        "The bot opened a session, answered one text turn and closed the session.",
        "http",
        latency,
        verified,
        HTTP_CAPABILITIES,
        {
            "greeting_returned": session.greeting is not None,
            "reply_chars": len(reply.text),
            "turn_latency_ms": reply.latency_ms,
        },
    )


def _stage(verified: dict[str, bool | None]) -> str:
    """The first step that did not succeed, for the failure message."""
    for step in ("reachable", "authenticated", "text_exchange", "session_lifecycle"):
        if verified.get(step) is not True:
            return step
    return "complete"


WS_UNVERIFIED: dict[str, bool | None] = {
    "reachable": None,
    "authenticated": None,
    "protocol_accepted": None,
    "audio_format_accepted": None,
    "audio_output": None,
    "caller_barge_in": None,
}


async def probe_ws_voice(
    *,
    url: str,
    token: SecretStr,
    policy: OutboundPolicy,
    language: str,
    timeout_seconds: float,
    resolver: Resolver | None = None,
) -> ProbeResult:
    verified = dict(WS_UNVERIFIED)
    started = time.monotonic()
    fmt = {"sample_rate_hz": SAMPLE_RATE_HZ, "encoding": "pcm_s16le", "frame_ms": FRAME_MS}

    def fail(outcome: ProbeOutcome, message: str) -> ProbeResult:
        return ProbeResult(
            outcome, message, "ws_voice", None, verified, WS_CAPABILITIES, {"format": fmt}
        )

    try:
        socket = await connect_pinned(
            url,
            policy,
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            timeout_seconds=timeout_seconds,
            resolver=resolver,
        )
    except BotTargetRefusedError as exc:
        return fail(ProbeOutcome.TARGET_REFUSED, _message(exc))
    except websockets.InvalidStatus as exc:
        code = exc.response.status_code
        verified["reachable"] = True
        if code in (401, 403):
            verified["authenticated"] = False
            return fail(
                ProbeOutcome.AUTHENTICATION_FAILED,
                f"the bot refused the credential during the WebSocket handshake ({code})",
            )
        return fail(ProbeOutcome.PROTOCOL_ERROR, f"the handshake was answered with HTTP {code}")
    except websockets.InvalidHandshake as exc:
        return fail(ProbeOutcome.PROTOCOL_ERROR, f"the WebSocket handshake failed: {_message(exc)}")
    except TimeoutError:
        return fail(ProbeOutcome.TIMEOUT, f"no WebSocket connection within {timeout_seconds:g}s")
    except OSError as exc:
        return fail(ProbeOutcome.UNREACHABLE, f"could not connect ({type(exc).__name__})")

    verified.update(reachable=True, authenticated=True)
    try:
        await socket.send(json.dumps({
            "type": "start", "protocol": WS_PROTOCOL, "language": language,
            **fmt, "run_id": f"connection-check-{uuid.uuid4()}",
        }))  # fmt: skip
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=timeout_seconds)
        except TimeoutError:
            return fail(
                ProbeOutcome.TIMEOUT, f"the bot did not answer `start` within {timeout_seconds:g}s"
            )
        except websockets.ConnectionClosed:
            return fail(
                ProbeOutcome.SESSION_REJECTED, "the bot closed the connection after `start`"
            )
        try:
            answer = json.loads(raw) if isinstance(raw, str) else None
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            return fail(
                ProbeOutcome.PROTOCOL_ERROR, "the bot's answer to `start` is not a JSON message"
            )
        if answer.get("type") == "error":
            verified.update(protocol_accepted=True, audio_format_accepted=False)
            return fail(
                ProbeOutcome.SESSION_REJECTED,
                "the bot refused the session: " + redact(str(answer.get("message", "")))[:200],
            )
        if answer.get("type") != "ready":
            return fail(ProbeOutcome.PROTOCOL_ERROR, "the bot did not answer `start` with `ready`")
        verified.update(protocol_accepted=True, audio_format_accepted=True)
    finally:
        # The socket may already be closed by the bot; hanging up is courtesy.
        with contextlib.suppress(Exception):
            await socket.send(json.dumps({"type": "hangup", "reason": "connection_check"}))
        await socket.close()

    return ProbeResult(
        ProbeOutcome.CONNECTED,
        "The bot accepted the WebSocket, the credential and the audio format "
        "(16 kHz pcm_s16le, 20 ms frames). Audio replies and barge-in are measured by a run.",
        "ws_voice",
        round((time.monotonic() - started) * 1000, 1),
        verified,
        WS_CAPABILITIES,
        {"format": fmt},
    )


async def probe(
    protocol: str,
    *,
    url: str,
    token: SecretStr,
    policy: OutboundPolicy,
    language: str,
    timeout_seconds: float,
    resolver: Resolver | None = None,
) -> ProbeResult:
    """Check one bot. Never raises for anything the bot or the network did."""
    if protocol == "http":
        return await probe_http(
            url=url, token=token, policy=policy, language=language,
            timeout_seconds=timeout_seconds, resolver=resolver,
        )  # fmt: skip
    if protocol == "ws_voice":
        return await probe_ws_voice(
            url=url, token=token, policy=policy, language=language,
            timeout_seconds=timeout_seconds, resolver=resolver,
        )  # fmt: skip
    raise ValueError(f"unknown protocol '{protocol}'")


__all__ = ["PROBE_TEXT", "ProbeOutcome", "ProbeResult", "probe"]
