"""Encrypt a credential a user stored, so the database never holds it in clear.

Used for the bearer token of a bot integration. That token is the one secret
in this system that a *user* supplies and that must be read back (it is sent
to their bot), so it cannot be hashed like a session token.

- **AES-256-GCM** from `cryptography`: authenticated, so a tampered or swapped
  ciphertext fails to decrypt instead of yielding a wrong token.
- **The key is derived from `SECRET_KEY`** with HKDF-SHA256 and a purpose label,
  so it is never the signing key itself and no new secret has to be
  provisioned. Consequence, stated: rotating `SECRET_KEY` makes every stored
  credential unreadable. The integration then reports that and asks for the
  credential again (`docs/DEPLOYMENT.md`, "Rotate a secret").
- **Associated data binds a ciphertext to its row** (the integration id), so a
  ciphertext copied onto another integration does not decrypt there.
- **Versioned format**: `b"v1" + nonce(12) + ciphertext+tag`, so a later key
  scheme can coexist with this one.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = b"v1"
NONCE_BYTES = 12
_INFO = b"bhashabench/bot-integration-credential/v1"


class CredentialUnreadableError(ValueError):
    """The stored credential cannot be decrypted with the current key.

    Never carries the ciphertext or any part of the plaintext.
    """


def _key(secret_key: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret_key.encode("utf-8")
    )


def seal(plaintext: str, *, secret_key: str, bound_to: bytes) -> bytes:
    """Encrypt `plaintext`, bound to `bound_to` (the owning row's id)."""
    nonce = os.urandom(NONCE_BYTES)
    return (
        VERSION
        + nonce
        + AESGCM(_key(secret_key)).encrypt(nonce, plaintext.encode("utf-8"), bound_to)
    )


def open_sealed(sealed: bytes, *, secret_key: str, bound_to: bytes) -> str:
    """Decrypt what `seal` produced.

    Raises:
        CredentialUnreadableError: wrong version, wrong key, tampered bytes, or
            a ciphertext from another row.
    """
    if not sealed.startswith(VERSION) or len(sealed) <= len(VERSION) + NONCE_BYTES:
        raise CredentialUnreadableError("the stored credential is not in a known format")
    nonce = sealed[len(VERSION) : len(VERSION) + NONCE_BYTES]
    try:
        plain = AESGCM(_key(secret_key)).decrypt(
            nonce, sealed[len(VERSION) + NONCE_BYTES :], bound_to
        )
    except InvalidTag as exc:
        raise CredentialUnreadableError(
            "the stored credential cannot be decrypted with the current SECRET_KEY; enter it again"
        ) from exc
    return plain.decode("utf-8")


def hint(plaintext: str) -> str:
    """What may be shown of a credential: its length class and last four characters."""
    return f"…{plaintext[-4:]}" if len(plaintext) >= 12 else "…"


__all__ = ["CredentialUnreadableError", "hint", "open_sealed", "seal"]
