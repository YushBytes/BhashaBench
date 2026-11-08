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
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.caller.errors import CallerError
from app.caller.schemas import Speaker

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

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        """The resolved storage root."""
        return self._root

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

    def _absolute(self, relative: Path) -> Path:
        """Resolve a reference under the root, refusing anything that escapes.

        The containment check is the point. `Path.resolve` collapses `..`, so
        comparing the resolved result against the resolved root catches a
        traversal regardless of how it was spelled - and `is_relative_to` is an
        exact ancestor test rather than a string prefix, so a sibling directory
        whose name merely starts with the root's name cannot pass.
        """
        candidate = (self._root / relative).resolve()
        if not candidate.is_relative_to(self._root):
            raise CallerError(
                "the resolved audio path escapes the storage root; refusing to "
                "read or write outside it"
            )
        return candidate

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
        target = self._absolute(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)

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
        target = self._absolute(Path(reference))
        if not target.is_file():
            raise CallerError(f"no stored audio artefact at '{reference}'")
        return target.read_bytes()

    def exists(self, reference: str) -> bool:
        """Whether a reference names a readable file."""
        try:
            return self._absolute(Path(reference)).is_file()
        except CallerError:
            return False


__all__ = [
    "ARTEFACT_VARIANTS",
    "MAX_ARTEFACT_BYTES",
    "AudioArtefactStore",
    "StoredArtefact",
]
