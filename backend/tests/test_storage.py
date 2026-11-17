"""Phase 10 blob storage: the key rules, the local filesystem adapter, the
registry's refusal of backends that do not exist, and the artefact store on
top of it."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.caller.artefacts import AudioArtefactStore
from app.caller.errors import CallerError
from app.caller.schemas import Speaker
from app.core.config import Settings
from app.storage import (
    BlobStore,
    LocalFilesystemStore,
    StorageError,
    build_blob_store,
    validate_key,
)


class TestKeys:
    @pytest.mark.parametrize(
        "key", ["a", "a/b.wav", f"{uuid.uuid4()}/0001-bot.wav", "x/y/z-1_2.raw"]
    )
    def test_safe_keys_pass(self, key: str) -> None:
        assert validate_key(key) == key

    @pytest.mark.parametrize(
        "key",
        [
            "",
            "/etc/passwd",
            "../x",
            "a/../b",
            "a//b",
            "a/./b",
            "a\\b",
            "a\x00b",
            ".hidden",
            "a/-x",
            "x" * 513,
        ],
    )
    def test_unsafe_keys_are_refused(self, key: str) -> None:
        with pytest.raises(StorageError):
            validate_key(key)


@pytest.fixture
def store(tmp_path: Path) -> LocalFilesystemStore:
    return LocalFilesystemStore(tmp_path / "store")


class TestLocalFilesystemStore:
    def test_it_meets_the_protocol(self, store: LocalFilesystemStore) -> None:
        assert isinstance(store, BlobStore)

    def test_round_trip_size_and_overwrite(self, store: LocalFilesystemStore) -> None:
        store.put("c/1.wav", b"abc")
        assert (store.get("c/1.wav"), store.size("c/1.wav"), store.exists("c/1.wav")) == (
            b"abc",
            3,
            True,
        )
        store.put("c/1.wav", b"de")
        assert store.get("c/1.wav") == b"de"

    def test_a_missing_object(self, store: LocalFilesystemStore) -> None:
        assert store.exists("nope") is False
        assert store.size("nope") is None
        with pytest.raises(StorageError):
            store.get("nope")

    def test_delete_is_idempotent(self, store: LocalFilesystemStore) -> None:
        store.put("c/1.wav", b"abc")
        assert store.delete("c/1.wav") is True
        assert store.delete("c/1.wav") is False

    def test_delete_prefix_removes_only_that_prefix(self, store: LocalFilesystemStore) -> None:
        for key in ("a/1.wav", "a/2.wav", "a/sub/3.wav", "b/1.wav"):
            store.put(key, b"x")
        assert store.delete_prefix("a") == 3
        assert list(store.keys("a")) == []
        assert list(store.keys("b")) == ["b/1.wav"]
        assert store.delete_prefix("a") == 0

    def test_writes_are_atomic_and_leave_no_temporary_files(
        self, store: LocalFilesystemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store.put("c/1.wav", b"original")

        def failing_replace(*_: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError):
            store.put("c/1.wav", b"partial")
        monkeypatch.undo()
        assert store.get("c/1.wav") == b"original"
        assert [p.name for p in (store.root / "c").iterdir()] == ["1.wav"]

    def test_a_symlink_out_of_the_root_is_refused(
        self, store: LocalFilesystemStore, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.wav").write_bytes(b"secret")
        store.root.mkdir(parents=True, exist_ok=True)
        try:
            (store.root / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("this platform does not allow creating symlinks here")
        with pytest.raises(StorageError):
            store.get("link/secret.wav")
        assert store.exists("link/secret.wav") is False


class TestRegistry:
    def test_local_is_the_only_backend(self, tmp_path: Path) -> None:
        assert build_blob_store("local", tmp_path).name == "local"

    @pytest.mark.parametrize("backend", ["s3", "gcs", "memory"])
    def test_anything_else_is_refused_with_a_reason(self, tmp_path: Path, backend: str) -> None:
        with pytest.raises(StorageError, match="not available"):
            build_blob_store(backend, tmp_path)

    def test_settings_refuse_an_unavailable_backend_at_startup(self) -> None:
        with pytest.raises(ValueError, match="paid bucket"):
            Settings(storage_backend="s3", _env_file=None)
        assert Settings(storage_backend=" LOCAL ", _env_file=None).storage_backend == "local"


class TestArtefactStoreOnBlobs:
    def test_writes_go_through_the_blob_store(self, store: LocalFilesystemStore) -> None:
        artefacts = AudioArtefactStore(blobs=store)
        conversation = uuid.uuid4()
        stored = artefacts.write(
            b"RIFF....", conversation_id=conversation, turn_index=1, speaker=Speaker.BOT,
            container="wav", content_type="audio/wav",
        )  # fmt: skip
        assert store.get(stored.reference) == b"RIFF...."
        assert artefacts.read(stored.reference) == b"RIFF...."

    def test_deleting_a_conversation_removes_its_files_only(
        self, store: LocalFilesystemStore
    ) -> None:
        artefacts = AudioArtefactStore(blobs=store)
        keep, drop = uuid.uuid4(), uuid.uuid4()
        for conversation in (keep, drop):
            for turn in range(3):
                artefacts.write(
                    b"x", conversation_id=conversation, turn_index=turn, speaker=Speaker.CALLER,
                    container="wav", content_type="audio/wav",
                )  # fmt: skip
        assert artefacts.delete_conversation(drop) == 3
        assert len(list(store.keys(str(keep)))) == 3
        assert list(store.keys(str(drop))) == []

    def test_exactly_one_of_root_or_blobs(
        self, store: LocalFilesystemStore, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError):
            AudioArtefactStore()
        with pytest.raises(ValueError):
            AudioArtefactStore(tmp_path, blobs=store)

    def test_a_traversal_reference_is_refused(self, store: LocalFilesystemStore) -> None:
        with pytest.raises(CallerError):
            AudioArtefactStore(blobs=store).read("../../etc/passwd")
