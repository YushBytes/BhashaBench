"""Signed, expiring links to stored audio (Phase 10).

A link lets a player, a download or a teammate's browser fetch one recording
without a session, for a few minutes. It is HMAC-SHA256 over a canonical
message naming exactly what it opens:

    v1 | <path> | <variant or -> | <expires, unix seconds> | <user id>

so a signature for turn 3 opens nothing else, an edited expiry or variant
fails, and the link carries the user who minted it - whose access is checked
again when it is used, so removing someone from the workspace revokes their
outstanding links too.

The key is derived from `SECRET_KEY` with a fixed label, so this signature
cannot be confused with any other use of the same secret. Rotating
`SECRET_KEY` invalidates every link, which is the intended way to revoke all
of them at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

VERSION = "v1"
MAX_TTL = timedelta(minutes=15)
DEFAULT_TTL = timedelta(minutes=5)
_LABEL = b"bhashabench/artefact-url/v1"


class InvalidSignatureError(Exception):
    """The link is malformed, tampered with, expired or not yet valid."""


@dataclass(frozen=True, slots=True)
class LinkClaims:
    path: str
    variant: str | None
    expires: int
    user_id: uuid.UUID


def _key(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), _LABEL, hashlib.sha256).digest()


def _message(claims: LinkClaims) -> bytes:
    variant = claims.variant or "-"
    return f"{VERSION}|{claims.path}|{variant}|{claims.expires}|{claims.user_id}".encode()


def _sign(secret: str, claims: LinkClaims) -> str:
    digest = hmac.new(_key(secret), _message(claims), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def mint(
    secret: str,
    *,
    path: str,
    variant: str | None,
    user_id: uuid.UUID,
    now: datetime,
    ttl: timedelta = DEFAULT_TTL,
) -> tuple[str, datetime]:
    """A signed query string for `path`, and when it stops working."""
    if not timedelta(seconds=1) <= ttl <= MAX_TTL:
        raise ValueError(f"a link may live between 1 second and {MAX_TTL}")
    expires_at = now + ttl
    claims = LinkClaims(path, variant, int(expires_at.timestamp()), user_id)
    query = f"expires={claims.expires}&user={user_id}&signature={_sign(secret, claims)}"
    if variant:
        query = f"variant={variant}&{query}"
    return query, expires_at


def verify(
    secret: str,
    *,
    path: str,
    variant: str | None,
    expires: str,
    user: str,
    signature: str,
    now: datetime,
) -> LinkClaims:
    """The claims of a valid link, or `InvalidSignatureError`."""
    try:
        claims = LinkClaims(path, variant, int(expires), uuid.UUID(user))
    except ValueError as exc:
        raise InvalidSignatureError("the link is malformed") from exc
    if not hmac.compare_digest(_sign(secret, claims), signature):
        raise InvalidSignatureError("the link's signature does not match")
    remaining = claims.expires - now.timestamp()
    if remaining <= 0:
        raise InvalidSignatureError("the link has expired")
    if remaining > MAX_TTL.total_seconds() + 5:
        raise InvalidSignatureError("the link claims a lifetime longer than any link is given")
    return claims


__all__ = ["DEFAULT_TTL", "MAX_TTL", "InvalidSignatureError", "LinkClaims", "mint", "verify"]
