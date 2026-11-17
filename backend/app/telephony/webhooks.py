"""Webhook signatures for provider events.

**This is BhashaBench's own scheme, used by the mock provider.** It is not
any vendor's: a real adapter verifies its vendor's documented signature in
its own module, and nothing here may be presented as compatible with one.

    X-BhashaBench-Timestamp: <unix seconds>
    X-BhashaBench-Signature: v1=<hex HMAC-SHA256(secret, "<timestamp>.<raw body>")>

The signature covers the raw bytes as received, before any JSON parsing, so
a re-serialised body cannot pass. A timestamp outside `TOLERANCE` is refused,
which bounds replay; event ids are deduplicated on top of that by the
service, so a replay inside the window changes nothing either.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta

TIMESTAMP_HEADER = "X-BhashaBench-Timestamp"
SIGNATURE_HEADER = "X-BhashaBench-Signature"
TOLERANCE = timedelta(minutes=5)
MIN_SECRET_LENGTH = 32


class WebhookSignatureError(Exception):
    pass


def _digest(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def sign(secret: str, body: bytes, *, now: datetime) -> dict[str, str]:
    timestamp = str(int(now.timestamp()))
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: f"v1={_digest(secret, timestamp, body)}"}


def verify(
    secret: str, body: bytes, *, timestamp: str | None, signature: str | None, now: datetime
) -> None:
    if len(secret) < MIN_SECRET_LENGTH:
        raise WebhookSignatureError("the webhook secret is not configured")
    if not timestamp or not signature:
        raise WebhookSignatureError("the event is not signed")
    try:
        sent = int(timestamp)
    except ValueError as exc:
        raise WebhookSignatureError("the event timestamp is malformed") from exc
    if abs(now.timestamp() - sent) > TOLERANCE.total_seconds():
        raise WebhookSignatureError("the event timestamp is outside the accepted window")
    scheme, _, value = signature.partition("=")
    if scheme != "v1" or not hmac.compare_digest(value, _digest(secret, timestamp, body)):
        raise WebhookSignatureError("the event signature does not match")


__all__ = [
    "MIN_SECRET_LENGTH",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "TOLERANCE",
    "WebhookSignatureError",
    "sign",
    "verify",
]
