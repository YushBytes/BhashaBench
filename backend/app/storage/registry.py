"""Which blob store a deployment uses. `local` only, on purpose."""

from __future__ import annotations

from pathlib import Path

from app.storage.base import BlobStore, StorageError
from app.storage.local import LocalFilesystemStore

SUPPORTED_BACKENDS = ("local",)

_NOT_IMPLEMENTED = {
    "s3": (
        "an S3-compatible adapter is not implemented: it needs a paid bucket and the boto3 "
        "dependency, neither authorised. Use STORAGE_BACKEND=local with a persistent volume."
    ),
}


def build_blob_store(backend: str, root: Path | str) -> BlobStore:
    if backend == "local":
        return LocalFilesystemStore(root)
    reason = _NOT_IMPLEMENTED.get(backend, f"supported backends are {list(SUPPORTED_BACKENDS)}")
    raise StorageError(f"STORAGE_BACKEND={backend!r} is not available: {reason}")


__all__ = ["SUPPORTED_BACKENDS", "build_blob_store"]
