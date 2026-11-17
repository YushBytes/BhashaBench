"""The storage contract every adapter meets.

Keys are relative, `/`-separated and built by the caller from trusted parts
only (UUIDs, integers, whitelisted suffixes). `validate_key` still refuses
anything that could address outside the store - an absolute path, a `..`
segment, a backslash, a NUL, an empty segment - so an adapter never has to
trust its caller's discipline. The filesystem adapter additionally checks the
resolved path stays under its root.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Protocol, runtime_checkable

MAX_KEY_LENGTH = 512
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StorageError(Exception):
    """A key was refused, or a stored object could not be read or written."""


def validate_key(key: str) -> str:
    """Return `key` unchanged if it is a safe relative key; raise otherwise."""
    if not key or len(key) > MAX_KEY_LENGTH:
        raise StorageError("a storage key must be 1 to 512 characters")
    if "\\" in key or "\x00" in key or key.startswith("/"):
        raise StorageError("a storage key must be relative and use '/' only")
    for segment in key.split("/"):
        if segment in ("", ".", "..") or not _SEGMENT.fullmatch(segment):
            raise StorageError(f"unsafe storage key segment {segment!r}")
    return key


@runtime_checkable
class BlobStore(Protocol):
    """Bytes under keys. Writes replace; deletes are idempotent."""

    name: str

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def size(self, key: str) -> int | None: ...

    def delete(self, key: str) -> bool:
        """Remove one object. `True` if something was removed."""
        ...

    def delete_prefix(self, prefix: str) -> int:
        """Remove every object under `prefix/`. Returns how many."""
        ...

    def keys(self, prefix: str) -> Iterator[str]: ...


__all__ = ["MAX_KEY_LENGTH", "BlobStore", "StorageError", "validate_key"]
