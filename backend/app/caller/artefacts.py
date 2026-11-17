"""Where conversation audio is kept.

§7 says avoid putting large binary audio in PostgreSQL, use the existing
storage strategy if there is one, and otherwise implement something minimal
without adding an external dependency. There is no existing strategy - but
`.gitignore` already reserves `storage/` and `audio_storage/`, which is the
convention this follows.

So: files on the local filesystem under a configured root, and only a
*reference* in the database. A four-second utterance is ~70 KB; a twenty-turn
conversation is over a megabyte, and a run of a hundred scenarios is hundreds
of megabytes of bytea that every `SELECT *` would drag through the connection.

**Path safety is the whole of the rest of this module.** §13 forbids unsafe
audio paths and arbitrary filesystem writes, so no caller-supplied string ever
reaches a path: a filename is built solely from the conversation UUID, the turn
index and the speaker, all of which are generated or validated upstream. The
resolved path is then checked to be inside the root before anything is written,
which catches a misconfigured root as well as a hypothetical injection.

**Phase 10.** The bytes now go through a `BlobStore` (`app/storage/`); this
class keeps what is specific to audio - the naming rules, the container and
variant whitelists, the size cap - and the store keeps containment and atomic
writes. Constructed from a root, it uses the local filesystem adapter, so
every existing caller is unchanged.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.caller.errors import CallerError
from app.caller.schemas import Speaker
from app.storage import BlobStore, LocalFilesystemStore, StorageError

logger = logging.getLogger("bhashabench.caller.artefacts")

# Containers the store will write. Restricted to what the speech and
# transcription subsystems actually produce, so an unexpected value is a bug
# rather than a new file type on disk.
_ALLOWED_SUFFIXES = frozenset({"wav", "mp3", "ogg", "raw", "mulaw", "alaw"})

ARTEFACT_VARIANTS = frozenset({"original", "degraded"})
"""Named versions of one turn's audio.

Phase 7 degrades the caller's speech before sending it to a bot, and §8 of that
phase requires the original to survive: a degraded artefact is only evidence if
the thing it was derived from is still there to compare against. So one turn
can hold two files, distinguished by this suffix.

A whitelist rather than a free string, for the same reason the containers are
one - every component of a path here is generated or validated, never supplied.

Phase 6 passes no variant and keeps its original filenames, so adding this
changed nothing already on disk.
"""

MAX_ARTEFACT_BYTES = 25 * 1024 * 1024
"""Refuse to write anything larger.

A single conversation turn is seconds of speech. Twenty-five megabytes is
roughly twenty-five minutes of 8 kHz mono PCM - far beyond any plausible turn,
so hitting it means something upstream is wrong and writing it would just fill
the disk quietly.
"""


@dataclass(frozen=True, slots=True)
class StoredArtefact:
    """A written audio file, as the database should record it."""

    reference: str
    """Storage-root-relative path. What goes in `turn_metadata`.

    Relative rather than absolute, so a conversation recorded on one machine
    can be read on another with a different root - and so an absolute
    filesystem path never appears in an API response.
    """
    size_bytes: int
    content_type: str
    container: str
    variant: str | None = None
    """Which version of the turn's audio this is, when there is more than one."""


class AudioArtefactStore:
    """Writes and reads conversation audio under one root directory."""

    def __init__(self, root: Path | str | None = None, *, blobs: BlobStore | None = None) -> None:
        if (root is None) == (blobs is None):
            raise ValueError("give exactly one of a root directory or a blob store")
        self._blobs: BlobStore = blobs if blobs is not None else LocalFilesystemStore(root)  # type: ignore[arg-type]

    @property
    def blobs(self) -> BlobStore:
        return self._blobs

    @property
    def root(self) -> Path:
        """The local root, for the filesystem adapter only."""
        root = getattr(self._blobs, "root", None)
        if root is None:
            raise CallerError("this artefact store is not backed by a local directory")
        return Path(root)

    def _relative_for(
        self,
        conversation_id: uuid.UUID,
        turn_index: int,
        speaker: Speaker,
        container: str,
        variant: str | None = None,
    ) -> Path:
        """Build the reference path from trusted values only.

        Every component is generated, not supplied: a UUID, a non-negative
        integer, an enum member and a whitelisted suffix. There is no code path
        by which a caller-controlled string becomes part of a filename.
        """
        if container not in _ALLOWED_SUFFIXES:
            raise CallerError(
                f"'{container}' is not an audio container this store will write; "
                f"allowed containers are {sorted(_ALLOWED_SUFFIXES)}"
            )
        if turn_index < 0:
            raise CallerError(f"turn index must not be negative, got {turn_index}")
        if variant is not None and variant not in ARTEFACT_VARIANTS:
            raise CallerError(
                f"'{variant}' is not an audio variant this store will write; "
                f"allowed variants are {sorted(ARTEFACT_VARIANTS)}"
            )

        # Sharded by conversation so one directory never holds every file of
        # every run.
        suffix = "" if variant is None else f"-{variant}"
        return Path(str(conversation_id)) / f"{turn_index:04d}-{speaker.value}{suffix}.{container}"

    def write(
        self,
        audio: bytes,
        *,
        conversation_id: uuid.UUID,
        turn_index: int,
        speaker: Speaker,
        container: str,
        content_type: str,
        variant: str | None = None,
    ) -> StoredArtefact:
        """Write one turn's audio and return its reference.

        `variant` distinguishes two files for the same turn - Phase 7's
        original and degraded caller audio. Omitting it writes the filename
        Phase 6 has always written.

        Raises:
            CallerError: empty audio, an oversized payload, a disallowed
                container or variant, or a path that would escape the root.
        """
        if not audio:
            raise CallerError("refusing to store an empty audio artefact")
        if len(audio) > MAX_ARTEFACT_BYTES:
            raise CallerError(
                f"the audio artefact is {len(audio)} bytes, which exceeds the "
                f"{MAX_ARTEFACT_BYTES} byte limit for one conversation turn"
            )

        relative = self._relative_for(conversation_id, turn_index, speaker, container, variant)
        try:
            self._blobs.put(relative.as_posix(), audio)
        except StorageError as exc:
            raise CallerError(f"the audio artefact could not be stored: {exc}") from exc

        logger.info(
            "caller.artefact_written",
            extra={
                "conversation_id": str(conversation_id),
                "turn_index": turn_index,
                "speaker": speaker.value,
                "variant": variant,
                "container": container,
                "size_bytes": len(audio),
                # The reference, never the absolute path: an API response or a
                # log aggregator has no business knowing the server's layout.
                "reference": relative.as_posix(),
            },
        )
        return StoredArtefact(
            reference=relative.as_posix(),
            size_bytes=len(audio),
            content_type=content_type,
            container=container,
            variant=variant,
        )

    def read(self, reference: str) -> bytes:
        """Read back a stored artefact by its reference.

        Raises:
            CallerError: the reference escapes the root or names nothing.
        """
        try:
            return self._blobs.get(reference)
        except StorageError as exc:
            raise CallerError(f"no stored audio artefact at '{reference}'") from exc

    def exists(self, reference: str) -> bool:
        """Whether a reference names a readable file."""
        return self._blobs.exists(reference)

    def write_recording(self, audio: bytes, *, conversation_id: uuid.UUID) -> StoredArtefact:
        """Store a conversation's assembled recording beside its turn files.

        The name is fixed, so a re-assembly replaces the previous one, and it
        lives under the conversation's prefix, so `delete_conversation`
        removes it with the turns.
        """
        if not audio:
            raise CallerError("refusing to store an empty recording")
        reference = f"{conversation_id}/conversation.wav"
        try:
            self._blobs.put(reference, audio)
        except StorageError as exc:
            raise CallerError(f"the recording could not be stored: {exc}") from exc
        return StoredArtefact(
            reference=reference, size_bytes=len(audio), content_type="audio/wav", container="wav"
        )

    def delete_conversation(self, conversation_id: uuid.UUID) -> int:
        """Remove every artefact of one conversation. Returns how many files."""
        return self._blobs.delete_prefix(str(conversation_id))


__all__ = [
    "ARTEFACT_VARIANTS",
    "MAX_ARTEFACT_BYTES",
    "AudioArtefactStore",
    "StoredArtefact",
]
