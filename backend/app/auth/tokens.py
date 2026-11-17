"""Opaque session tokens.

A token is 32 random bytes from `secrets`, URL-safe base64 encoded, with a
fixed `bbs_` prefix so a leaked one is recognisable to a secret scanner. Only
its SHA-256 is stored. SHA-256 rather than a slow KDF is correct here: the
input has 256 bits of entropy, so there is nothing for a slow hash to protect
against, and the lookup runs on every request.
"""

from __future__ import annotations

import hashlib
import re
import secrets

PREFIX = "bbs_"
_SHAPE = re.compile(r"^bbs_[A-Za-z0-9_-]{43}$")


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", errors="replace")).hexdigest()


def well_formed(token: str) -> bool:
    """Shape check before any database lookup, so garbage costs nothing."""
    return bool(_SHAPE.fullmatch(token))


__all__ = ["PREFIX", "new_token", "token_hash", "well_formed"]
