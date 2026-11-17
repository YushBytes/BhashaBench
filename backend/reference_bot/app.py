"""The reference text bot: a real HTTP service speaking the BhashaBench bot protocol.

It is the system under test for the HTTP adapter's integration tests and for
local end-to-end runs, and the executable form of `docs/BOT_PROTOCOL.md`. It
holds sessions in memory, answers from a deterministic script, and is **not a
voice bot**: it accepts and returns text only, so a run against it is a
`text_bot_test` and establishes nothing about audio.

Protocol summary (the document is the authority):

    GET    /health                     -> 200 {"status": "ok", "protocol": ...}
    POST   /v1/sessions                -> 201 {"session_id", "greeting"}
    POST   /v1/sessions/{id}/turns     -> 200 {"text", "end_session", "turn_index"}
    DELETE /v1/sessions/{id}           -> 204

Every `/v1` call needs `Authorization: Bearer <token>`. Errors use
`{"error": {"code", "message"}}`. `X-Correlation-ID` is echoed. A turn with an
`Idempotency-Key` already seen in that session returns the stored reply and
does not advance the conversation, which is what makes a client's retry safe.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from reference_bot.responder import DEFAULT_SCRIPT, Script
from reference_bot.voice import DEFAULT_VOICE_SCRIPT, VoiceTurn, register_voice

PROTOCOL_VERSION = "bhashabench-text-bot/1"
CORRELATION_HEADER = "X-Correlation-ID"
MAX_TEXT_CHARS = 4000


@dataclass(frozen=True, slots=True)
class BotConfig:
    token: str
    """Required. A reference service with no authentication would teach the
    adapter's users that a bot endpoint may be left open."""
    script: Script = DEFAULT_SCRIPT
    max_sessions: int = 1000
    session_ttl_seconds: float = 1800.0
    max_turns_per_session: int = 100
    voice_script: tuple[VoiceTurn, ...] = DEFAULT_VOICE_SCRIPT
    """Per-turn behaviour of the `/v1/voice` endpoint (Phase 9)."""

    def __post_init__(self) -> None:
        if len(self.token) < 16:
            raise ValueError("the reference bot's token must be at least 16 characters")


@dataclass
class _Session:
    language: str
    created: float
    turns: int = 0
    ended: bool = False
    replies: dict[str, dict[str, Any]] = field(default_factory=dict)


class _ProtocolError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class CreateSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = Field(min_length=2, max_length=35)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=MAX_TEXT_CHARS)
    turn_index: int = Field(ge=0)


class SessionStore:
    """Thread-safe, bounded and expiring. Oldest sessions are evicted first."""

    def __init__(self, config: BotConfig, clock: Any = time.monotonic) -> None:
        self._config = config
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, _Session] = OrderedDict()

    def _expire(self) -> None:
        cutoff = self._clock() - self._config.session_ttl_seconds
        while self._sessions:
            sid, session = next(iter(self._sessions.items()))
            if session.created >= cutoff:
                break
            del self._sessions[sid]

    def create(self, language: str) -> str:
        with self._lock:
            self._expire()
            if len(self._sessions) >= self._config.max_sessions:
                raise _ProtocolError(503, "capacity", "the bot has no free session slots")
            sid = uuid.uuid4().hex
            self._sessions[sid] = _Session(language=language, created=self._clock())
            return sid

    def turn(self, sid: str, body: Turn, idempotency_key: str | None) -> dict[str, Any]:
        with self._lock:
            self._expire()
            session = self._sessions.get(sid)
            if session is None:
                raise _ProtocolError(404, "session_not_found", "no such session")
            if idempotency_key and idempotency_key in session.replies:
                return session.replies[idempotency_key]
            if session.ended:
                raise _ProtocolError(409, "session_ended", "the session has ended")
            if session.turns >= self._config.max_turns_per_session:
                raise _ProtocolError(409, "turn_limit", "the session's turn limit is reached")
            reply = self._config.script.respond(body.text)
            session.turns += 1
            session.ended = reply.end_session
            payload = {
                "text": reply.text,
                "end_session": reply.end_session,
                "turn_index": body.turn_index,
            }
            if idempotency_key:
                session.replies[idempotency_key] = payload
            return payload

    def delete(self, sid: str) -> None:
        with self._lock:
            if self._sessions.pop(sid, None) is None:
                raise _ProtocolError(404, "session_not_found", "no such session")

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


def _error(status: int, code: str, message: str, correlation: str | None) -> JSONResponse:
    headers = {CORRELATION_HEADER: correlation} if correlation else None
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status, headers=headers
    )


def create_app(config: BotConfig) -> FastAPI:
    app = FastAPI(
        title="BhashaBench reference text bot",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    store = SessionStore(config)
    app.state.store = store
    expected = f"Bearer {config.token}".encode()

    @app.middleware("http")
    async def correlate_and_authenticate(request: Request, call_next: Any) -> Response:
        correlation = request.headers.get(CORRELATION_HEADER)
        if correlation is not None and (len(correlation) > 128 or not correlation.isprintable()):
            correlation = None
        if request.url.path.startswith("/v1/"):
            supplied = request.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(supplied, expected):
                return _error(401, "unauthorized", "a valid bearer token is required", correlation)
        response = await call_next(request)
        if correlation:
            response.headers[CORRELATION_HEADER] = correlation
        return response

    @app.exception_handler(_ProtocolError)
    async def protocol_error(request: Request, exc: _ProtocolError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message, request.headers.get(CORRELATION_HEADER))

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(
            422,
            "invalid_request",
            "the request body does not match the protocol",
            request.headers.get(CORRELATION_HEADER),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(
            exc.status_code, "http_error", str(exc.detail), request.headers.get(CORRELATION_HEADER)
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "protocol": PROTOCOL_VERSION, "sessions": len(store)}

    @app.post("/v1/sessions", status_code=201)
    def create_session(body: CreateSession) -> dict[str, Any]:
        return {"session_id": store.create(body.language), "greeting": config.script.greeting}

    @app.post("/v1/sessions/{session_id}/turns")
    def turn(session_id: str, body: Turn, request: Request) -> dict[str, Any]:
        key = request.headers.get("Idempotency-Key")
        if key is not None and not (0 < len(key) <= 200):
            raise _ProtocolError(422, "invalid_request", "Idempotency-Key must be 1-200 characters")
        return store.turn(session_id, body, key)

    register_voice(app, token=config.token, script=config.voice_script)

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def end_session(session_id: str) -> Response:
        store.delete(session_id)
        return Response(status_code=204)

    return app


def generate_token() -> str:
    """A token suitable for `REFERENCE_BOT_TOKEN`."""
    return secrets.token_urlsafe(32)
