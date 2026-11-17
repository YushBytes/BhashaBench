"""Password hashing with scrypt, from the standard library.

Why scrypt and why stdlib: scrypt is a memory-hard KDF that OWASP's
Password Storage Cheat Sheet accepts, and `hashlib.scrypt` is OpenSSL's
implementation, so there is no compiled third-party dependency to build on a
new CPython release (the reason `uvicorn[standard]` is avoided here too).

The stored string is self-describing:

    scrypt$<log2 N>$<r>$<p>$<salt, base64>$<key, base64>

so a cost raised later still verifies every existing hash, and
`needs_rehash` says when a successful login should upgrade one. The default
cost is OWASP's minimum for scrypt (N = 2^17, r = 8, p = 1); configuration may
lower it for tests, and `Settings` refuses anything below it when deployed.

Verification compares with `hmac.compare_digest`. A malformed stored hash
verifies as false rather than raising, so a corrupted row cannot be turned
into an error that tells an attacker which accounts exist.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

SCHEME = "scrypt"
DEFAULT_LOG2_N = 17
MIN_DEPLOYED_LOG2_N = 17
R = 8
P = 1
SALT_BYTES = 16
KEY_BYTES = 32
MAX_PASSWORD_CHARS = 1024
"""Bounded so a multi-megabyte 'password' cannot be used to burn CPU."""
MIN_PASSWORD_CHARS = 12


@dataclass(frozen=True, slots=True)
class _Parsed:
    log2_n: int
    r: int
    p: int
    salt: bytes
    key: bytes


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    n = 1 << log2_n
    # scrypt needs 128 * r * N bytes; give OpenSSL headroom above that or it
    # refuses with "memory limit exceeded".
    maxmem = 128 * r * n * 2 + (1 << 20)
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=KEY_BYTES
    )


def hash_password(password: str, *, log2_n: int = DEFAULT_LOG2_N) -> str:
    if not 10 <= log2_n <= 20:
        raise ValueError("log2_n must be between 10 and 20")
    if len(password) > MAX_PASSWORD_CHARS:
        raise ValueError(f"password longer than {MAX_PASSWORD_CHARS} characters")
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, log2_n, R, P)
    return f"{SCHEME}${log2_n}${R}${P}${_b64(salt)}${_b64(key)}"


def _parse(stored: str) -> _Parsed | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return None
    try:
        log2_n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4], validate=True)
        key = base64.b64decode(parts[5], validate=True)
    except ValueError:
        return None
    if not (10 <= log2_n <= 20 and 1 <= r <= 32 and 1 <= p <= 16 and salt and key):
        return None
    return _Parsed(log2_n, r, p, salt, key)


def verify_password(password: str, stored: str) -> bool:
    if len(password) > MAX_PASSWORD_CHARS:
        return False
    parsed = _parse(stored)
    if parsed is None:
        return False
    candidate = _derive(password, parsed.salt, parsed.log2_n, parsed.r, parsed.p)
    return hmac.compare_digest(candidate, parsed.key)


def needs_rehash(stored: str, *, log2_n: int) -> bool:
    parsed = _parse(stored)
    return parsed is None or (parsed.log2_n, parsed.r, parsed.p) != (log2_n, R, P)


def password_problem(password: str, *, email: str = "") -> str | None:
    """Why a new password is refused, or `None`. Length over composition rules,
    per NIST SP 800-63B: composition rules push users to predictable
    patterns, while length is what resists guessing."""
    if len(password) < MIN_PASSWORD_CHARS:
        return f"password must be at least {MIN_PASSWORD_CHARS} characters"
    if len(password) > MAX_PASSWORD_CHARS:
        return f"password must be at most {MAX_PASSWORD_CHARS} characters"
    if not password.strip():
        return "password must not be only whitespace"
    if email and password.casefold() == email.casefold():
        return "password must not be the email address"
    return None


__all__ = [
    "DEFAULT_LOG2_N",
    "MAX_PASSWORD_CHARS",
    "MIN_DEPLOYED_LOG2_N",
    "MIN_PASSWORD_CHARS",
    "hash_password",
    "needs_rehash",
    "password_problem",
    "verify_password",
]
