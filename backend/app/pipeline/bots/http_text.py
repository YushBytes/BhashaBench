"""A text bot reached over HTTP, speaking `bhashabench-text-bot/1`.

The first adapter that sends a request outside this process, so the first one
whose every request passes the outbound guard (`app/core/outbound.py`). The
contract it speaks is `docs/BOT_PROTOCOL.md`; it does not adapt itself to any
vendor's API, and it invents none.

**Text only, and says so everywhere.** It moves no audio. A run that uses it
is a `text_bot_test`, its capabilities accept no audio container, and
`send_turn` - the audio method of `BotAdapter` - refuses. What a text exchange
measures is what the bot says, nothing about how it hears or sounds.

Controls, each of which the tests drive over a real socket:

- **Destination.** The base URL is checked at construction and every request
  URL again immediately before sending: scheme, allowlist, resolved addresses.
  Redirects are never followed.
- **Credential.** The bearer token is a `SecretStr`, sent only in the
  `Authorization` header, and never placed in an exception, a log line, the
  reply metadata or the evidence. Any text from the bot that reaches an error
  message is passed through `redact` and truncated.
- **Bounds.** A ceiling on the whole exchange (`asyncio.timeout`), a body cap
  enforced while streaming rather than after, and a reply-length cap.
- **Retries.** Only where repeating cannot change the outcome: a connection
  that never opened, or a `502`/`503`/`504`. A turn is retried with the same
  `Idempotency-Key`; session creation, which has none, is retried only when
  the connection never opened, so a bot cannot be handed two sessions.
- **Correlation.** `X-Correlation-ID: <run>:<turn>` on every request.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx2
from pydantic import SecretStr

from app.core.outbound import OutboundPolicy, OutboundTargetRefusedError, check_url
from app.pipeline.bots.protocol import BotCapabilities, BotReply
from app.pipeline.errors import (
    BotAdapterError,
    BotAuthenticationError,
    BotProtocolError,
    BotTargetRefusedError,
    BotTimeoutError,
    BotUnavailableError,
)
from app.transcription.redaction import redact

PROVIDER_NAME = "http"
PROTOCOL_VERSION = "bhashabench-text-bot/1"
MAX_BODY_BYTES = 64 * 1024
MAX_REPLY_CHARS = 4000
TRANSIENT_STATUSES = frozenset({502, 503, 504})

CAPABILITIES = BotCapabilities(
    name=PROVIDER_NAME,
    display_name="HTTP text bot (bhashabench-text-bot/1)",
    contacts_external_system=True,
    supports_sessions=True,
    requires_credentials=True,
    accepts_containers=frozenset(),
    notes=(
        "Text only. Sends the caller's words and records the bot's words; no "
        "audio is synthesised, sent, received or transcribed.",
        "Speaks the protocol in docs/BOT_PROTOCOL.md. A bot that does not "
        "implement it needs its own adapter.",
        "Every request is checked against BOT_HTTP_ALLOWED_HOSTS and the "
        "outbound address rules; redirects are not followed.",
    ),
)


@dataclass(frozen=True, slots=True)
class HttpBotConfig:
    base_url: str
    token: SecretStr
    policy: OutboundPolicy
    timeout_seconds: float = 10.0
    max_attempts: int = 2
    backoff_seconds: float = 0.2

    def __post_init__(self) -> None:
        if not self.token.get_secret_value():
            raise BotAuthenticationError(
                "BOT_HTTP_TOKEN is not set; the HTTP bot adapter will not send "
                "an unauthenticated request",
                adapter=PROVIDER_NAME,
            )
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be in (0, 120]")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")


@dataclass(frozen=True, slots=True)
class TextBotSession:
    session_id: str
    greeting: str | None
    latency_ms: float


@dataclass(frozen=True, slots=True)
class TextBotReply:
    """One bot utterance as text, and what is known about where it came from."""

    text: str
    end_session: bool
    session_id: str
    latency_ms: float
    """The successful attempt only, measured with a monotonic clock."""
    attempts: int
    correlation_id: str
    received_from_bot: bool = True
    """Always True here: this adapter only returns what a bot sent."""
    metadata: dict[str, str] = field(default_factory=dict)


Sleep = Callable[[float], Awaitable[None]]


def _snippet(text: str) -> str:
    return redact(text)[:200]


class HttpTextBotAdapter:
    """A `TextBotAdapter` over HTTP. One instance serves one run."""

    def __init__(
        self,
        config: HttpBotConfig,
        *,
        client: httpx2.AsyncClient | None = None,
        resolver: Callable[[str, int], Any] | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._config = config
        self._resolver = resolver
        self._check(config.base_url)
        self._base = config.base_url.rstrip("/")
        # An injected client belongs to its injector. Otherwise a client is
        # opened per logical request and closed with it: the API tears its
        # engine down synchronously, so a client held across requests could
        # outlive the event loop that opened its connection.
        self._client = client
        self._sleep = sleep

    @property
    def capabilities(self) -> BotCapabilities:
        return CAPABILITIES

    def _check(self, url: str) -> None:
        try:
            if self._resolver is None:
                check_url(url, self._config.policy)
            else:
                check_url(url, self._config.policy, resolver=self._resolver)
        except OutboundTargetRefusedError as exc:
            raise BotTargetRefusedError(
                f"the bot URL was refused: {exc}", adapter=PROVIDER_NAME
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        correlation_id: str,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        retry_on_transient_status: bool,
    ) -> tuple[int, dict[str, Any] | None, float, int]:
        """Send one logical request with bounded retries.

        Returns (status, parsed JSON body or None, latency_ms, attempts).
        """
        url = f"{self._base}{path}"
        headers = {
            "Authorization": f"Bearer {self._config.token.get_secret_value()}",
            "X-Correlation-ID": correlation_id,
            "Accept": "application/json",
            "User-Agent": f"BhashaBench ({PROTOCOL_VERSION})",
        }
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        last: BotAdapterError | None = None
        for attempt in range(1, self._config.max_attempts + 1):
            # Re-checked per attempt: resolution can change between attempts.
            await asyncio.to_thread(self._check, url)
            started = time.monotonic()
            try:
                status, payload = await self._send(method, url, headers, body)
            except httpx2.ConnectError as exc:
                last = BotUnavailableError(
                    f"could not connect to the bot ({type(exc).__name__})",
                    adapter=PROVIDER_NAME,
                    retryable=True,
                )
            except (httpx2.TimeoutException, TimeoutError) as exc:
                raise BotTimeoutError(
                    f"the bot did not answer within {self._config.timeout_seconds:g}s",
                    adapter=PROVIDER_NAME,
                    retryable=False,
                ) from exc
            except httpx2.TransportError as exc:
                raise BotUnavailableError(
                    f"the connection to the bot failed ({type(exc).__name__})",
                    adapter=PROVIDER_NAME,
                ) from exc
            else:
                latency = round((time.monotonic() - started) * 1000, 3)
                if status in TRANSIENT_STATUSES and retry_on_transient_status:
                    last = BotUnavailableError(
                        f"the bot answered {status}", adapter=PROVIDER_NAME, retryable=True
                    )
                else:
                    return status, payload, latency, attempt
            if attempt < self._config.max_attempts:
                await self._sleep(self._config.backoff_seconds * attempt)
        raise last  # type: ignore[misc] - set on every path that reaches here

    @asynccontextmanager
    async def _client_for_request(self) -> AsyncIterator[httpx2.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx2.AsyncClient(
            follow_redirects=False,
            timeout=self._config.timeout_seconds,
            limits=httpx2.Limits(max_keepalive_connections=0),
        ) as client:
            yield client

    async def _send(
        self, method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> tuple[int, dict[str, Any] | None]:
        async with (
            asyncio.timeout(self._config.timeout_seconds),
            self._client_for_request() as client,
            client.stream(method, url, headers=headers, json=body) as response,
        ):
            if 300 <= response.status_code < 400:
                raise BotProtocolError(
                    f"the bot answered {response.status_code} (a redirect); redirects "
                    "are not followed",
                    adapter=PROVIDER_NAME,
                )
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise BotProtocolError(
                        f"the bot's response exceeded {MAX_BODY_BYTES} bytes",
                        adapter=PROVIDER_NAME,
                    )
                chunks.append(chunk)
            raw = b"".join(chunks)
            if not raw:
                return response.status_code, None
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return response.status_code, None
            return response.status_code, parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _failure(status: int, payload: dict[str, Any] | None, action: str) -> BotAdapterError:
        detail = ""
        error = (payload or {}).get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            detail = f": {_snippet(f'{code} - {message}')}"
        if status in (401, 403):
            return BotAuthenticationError(
                f"the bot refused the credential when asked to {action} ({status}){detail}",
                adapter=PROVIDER_NAME,
            )
        if status in TRANSIENT_STATUSES or status == 429 or status >= 500:
            return BotUnavailableError(
                f"the bot failed to {action} ({status}){detail}", adapter=PROVIDER_NAME
            )
        return BotProtocolError(
            f"the bot refused to {action} ({status}){detail}", adapter=PROVIDER_NAME
        )

    async def open_session(self, *, run_id: uuid.UUID, language: str) -> TextBotSession:
        correlation = f"{run_id}:session"
        status, payload, latency, _ = await self._request(
            "POST",
            "/v1/sessions",
            correlation_id=correlation,
            body={"language": language, "metadata": {"run_id": str(run_id)}},
            retry_on_transient_status=False,
        )
        if status != 201:
            raise self._failure(status, payload, "open a session")
        session_id = (payload or {}).get("session_id")
        if not isinstance(session_id, str) or not 0 < len(session_id) <= 200:
            raise BotProtocolError(
                "the bot's session response has no valid 'session_id'", adapter=PROVIDER_NAME
            )
        greeting = (payload or {}).get("greeting")
        if greeting is not None and not isinstance(greeting, str):
            raise BotProtocolError(
                "the bot's 'greeting' is neither text nor null", adapter=PROVIDER_NAME
            )
        return TextBotSession(session_id, greeting[:MAX_REPLY_CHARS] if greeting else None, latency)

    async def send_text(
        self, text: str, *, session_id: str, run_id: uuid.UUID, turn_index: int
    ) -> TextBotReply:
        correlation = f"{run_id}:{turn_index}"
        status, payload, latency, attempts = await self._request(
            "POST",
            f"/v1/sessions/{_path_segment(session_id)}/turns",
            correlation_id=correlation,
            body={"text": text, "turn_index": turn_index},
            idempotency_key=correlation,
            retry_on_transient_status=True,
        )
        if status != 200:
            raise self._failure(status, payload, "answer a turn")
        if payload is None or not isinstance(payload.get("text"), str):
            raise BotProtocolError(
                "the bot's turn response is not JSON with a string 'text'", adapter=PROVIDER_NAME
            )
        reply = payload["text"]
        if len(reply) > MAX_REPLY_CHARS:
            raise BotProtocolError(
                f"the bot's reply is longer than {MAX_REPLY_CHARS} characters",
                adapter=PROVIDER_NAME,
            )
        end = payload.get("end_session", False)
        if not isinstance(end, bool):
            raise BotProtocolError(
                "the bot's 'end_session' is not a boolean", adapter=PROVIDER_NAME
            )
        return TextBotReply(
            text=reply,
            end_session=end,
            session_id=session_id,
            latency_ms=latency,
            attempts=attempts,
            correlation_id=correlation,
            metadata={"protocol": PROTOCOL_VERSION, "status": str(status)},
        )

    async def close_session(self, *, session_id: str, run_id: uuid.UUID) -> None:
        status, payload, _, _ = await self._request(
            "DELETE",
            f"/v1/sessions/{_path_segment(session_id)}",
            correlation_id=f"{run_id}:close",
            retry_on_transient_status=True,
        )
        if status not in (204, 404):
            raise self._failure(status, payload, "end the session")

    async def send_turn(self, audio: bytes, **_: Any) -> BotReply:
        """The audio method of `BotAdapter`. This adapter carries no audio."""
        raise BotProtocolError(
            "the HTTP bot adapter is text only and cannot carry audio; use the "
            "text_bot_test execution mode",
            adapter=PROVIDER_NAME,
        )

    async def close(self) -> None:
        """Nothing is held between requests; an injected client is not ours."""


def _path_segment(value: str) -> str:
    """A session id as one URL path segment; it is opaque bot data."""
    return quote(value, safe="")


__all__ = [
    "CAPABILITIES",
    "PROVIDER_NAME",
    "HttpBotConfig",
    "HttpTextBotAdapter",
    "TextBotReply",
    "TextBotSession",
]
