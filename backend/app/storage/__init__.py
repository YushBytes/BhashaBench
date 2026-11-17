"""Blob storage for artefacts (Phase 10). See docs/STORAGE.md.

One protocol, `BlobStore`, and one adapter, the local filesystem. There is
no cloud adapter: it would need a paid bucket and a new dependency, neither
of which is authorised, and an adapter that cannot be exercised is a claim
rather than a capability. `STORAGE_BACKEND` therefore accepts `local` only,
and anything else fails at startup with the reason.
"""

from app.storage.base import BlobStore, StorageError, validate_key
from app.storage.local import LocalFilesystemStore
from app.storage.registry import SUPPORTED_BACKENDS, build_blob_store

__all__ = [
    "SUPPORTED_BACKENDS",
    "BlobStore",
    "LocalFilesystemStore",
    "StorageError",
    "build_blob_store",
    "validate_key",
]
