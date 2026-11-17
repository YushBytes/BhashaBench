"""Blobs as files under one root directory.

Containment is checked twice: `validate_key` refuses an unsafe key outright,
and the resolved path must be inside the resolved root (`is_relative_to`,
an ancestor test, not a string prefix - so `/data/store-evil` cannot pass
for `/data/store`). The second check also catches a symlink planted inside
the root that points out of it.

A write goes to a temporary file in the same directory and is renamed into
place, so a reader never sees half an artefact and a crash leaves either the
old object or the new one.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

from app.storage.base import StorageError, validate_key


class LocalFilesystemStore:
    name = "local"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, key: str) -> Path:
        candidate = (self._root / validate_key(key)).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageError("the storage key resolves outside the storage root")
        return candidate

    def put(self, key: str, data: bytes) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def get(self, key: str) -> bytes:
        target = self._path(key)
        if not target.is_file():
            raise StorageError(f"no stored object at '{key}'")
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._path(key).is_file()
        except StorageError:
            return False

    def size(self, key: str) -> int | None:
        target = self._path(key)
        return target.stat().st_size if target.is_file() else None

    def delete(self, key: str) -> bool:
        target = self._path(key)
        if not target.is_file():
            return False
        target.unlink()
        return True

    def delete_prefix(self, prefix: str) -> int:
        directory = self._path(prefix)
        if not directory.is_dir():
            return 0
        count = sum(1 for p in directory.rglob("*") if p.is_file())
        shutil.rmtree(directory)
        return count

    def keys(self, prefix: str) -> Iterator[str]:
        directory = self._path(prefix)
        if not directory.is_dir():
            return
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.name.startswith(".tmp-"):
                yield path.relative_to(self._root).as_posix()


__all__ = ["LocalFilesystemStore"]
