"""HTTP hardening (Phase 14, part 2): rate limits and security headers.

**Rate limits.** A sliding one-minute window per key, in process memory:

- every `/api/` request, keyed by client address, at
  `RATE_LIMIT_REQUESTS_PER_MINUTE`;
- `POST /api/v1/auth/login`, keyed by client address *and* separately by the
  email tried, at `RATE_LIMIT_LOGINS_PER_MINUTE` - so guessing one account
  from many addresses, or many accounts from one, is bounded either way.

Over the limit is **429** with `Retry-After`. 0 disables a limit. Liveness
(`/health`, `/api/v1/health`) is never limited, so an orchestrator's probe
cannot be throttled into restarting a healthy container.

Stated limits of the design: the window lives in one process, so N
processes allow N times the rate; and the client address is the socket peer
unless `TRUST_FORWARDED_FOR` is set, in which case the left-most
`X-Forwarded-For` entry is used - set it only behind a proxy that
overwrites that header, or a client can choose its own key.

**Security headers**, on every response: `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a
`Permissions-Policy` denying device APIs, `Cross-Origin-Opener-Policy`,
and a `Content-Security-Policy` of `default-src 'none'; frame-ancestors
'none'` for API responses (they are data, never pages). The interactive docs
(`/docs`, `/redoc`, development only) load their own scripts and are left
without the CSP. `Strict-Transport-Security` is added in staging and
production, where the API is served over HTTPS. Authentication responses
are `Cache-Control: no-store`.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from starlette.requests import Request

WINDOW_SECONDS = 60.0
UNLIMITED_PATHS = frozenset({"/health", "/api/v1/health"})
DOCS_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class SlidingWindowLimiter:
    """At most `limit` events per key in any `WINDOW_SECONDS`."""

    def __init__(self, limit: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    def hit(self, key: str) -> float | None:
        """Record an event. `None` if allowed; otherwise seconds until it would be."""
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] >= WINDOW_SECONDS:
                events.popleft()
            if len(events) >= self._limit:
                return max(WINDOW_SECONDS - (now - events[0]), 1.0)
            events.append(now)
            if len(self._events) > 100_000:  # bound memory under a key flood
                self._events = {k: v for k, v in self._events.items() if v}
            return None


def client_key(request: Request, *, trust_forwarded_for: bool) -> str:
    if trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def security_headers(path: str, *, deployed: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if not path.startswith(DOCS_PREFIXES):
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if deployed:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if path.startswith("/api/v1/auth/"):
        headers["Cache-Control"] = "no-store"
    return headers


__all__ = [
    "UNLIMITED_PATHS",
    "WINDOW_SECONDS",
    "SlidingWindowLimiter",
    "client_key",
    "security_headers",
]
