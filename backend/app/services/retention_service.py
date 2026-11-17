"""Deleting runs: one at a time on request, or by retention period.

What a deletion removes: the run row, and with it (by `ON DELETE CASCADE`)
its conversations, turns, evaluations and reviewed references; then every
stored artefact of its conversations, the full recording included. The
suite and its scenarios are untouched.

Three rules:

- **A run still in flight is never deleted.** Its status must be terminal
  (`completed`, `failed`, `cancelled`); a stuck run is closed with
  `runs recover-stale` first, which is a separate, explicit judgement.
- **The two protected historical runs are never deleted**, by request or by
  retention (`app.pipeline.recovery.PROTECTED_RUN_IDS`).
- **Rows first, then files.** The database delete commits before any file
  is removed, so a failure leaves orphaned files (which a re-run removes)
  rather than a run whose evidence is gone. Files that could not be removed
  are reported, never silently ignored.

Retention is off unless `RETENTION_DAYS` is set, and the sweep is dry-run
unless asked to apply - the same shape as `recover-stale`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.models.call_session import CallSession
from app.models.test_run import RunStatus, TestRun
from app.pipeline.recovery import PROTECTED_RUN_IDS
from app.services.errors import ConflictError, NotFoundError

logger = logging.getLogger("bhashabench.retention")

TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)


@dataclass(frozen=True, slots=True)
class Deleted:
    run_id: uuid.UUID
    files_deleted: int
    files_not_deleted: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "artefact_files_deleted": self.files_deleted,
            "artefact_files_not_deleted": self.files_not_deleted,
        }


@dataclass(frozen=True, slots=True)
class Expired:
    run_id: uuid.UUID
    finished_at: datetime
    suite_id: uuid.UUID


def _refuse_if_not_deletable(run: TestRun) -> None:
    if run.id in PROTECTED_RUN_IDS:
        raise ConflictError(f"run {run.id} is a protected historical run and is never deleted")
    if run.status not in TERMINAL:
        raise ConflictError(
            f"run {run.id} is {run.status.value}; only a finished run can be deleted "
            "(close a stuck one with `bhashabench runs recover-stale` first)"
        )


def delete_run(session: Session, artefacts: AudioArtefactStore, run_id: uuid.UUID) -> Deleted:
    """Delete one finished run and its stored artefacts. Commits."""
    run = session.get(TestRun, run_id)
    if run is None:
        raise NotFoundError("TestRun", run_id)
    _refuse_if_not_deletable(run)
    conversations = list(
        session.scalars(select(CallSession.id).where(CallSession.test_run_id == run_id))
    )
    session.delete(run)
    session.commit()

    removed, failed = 0, []
    for conversation_id in conversations:
        try:
            removed += artefacts.delete_conversation(conversation_id)
        except Exception as exc:  # reported to the caller, and logged
            failed.append(str(conversation_id))
            logger.warning(
                "retention.artefacts_not_deleted",
                extra={"run_id": str(run_id), "conversation_id": str(conversation_id),
                       "error": type(exc).__name__},
            )  # fmt: skip
    logger.info(
        "retention.run_deleted",
        extra={"run_id": str(run_id), "files_deleted": removed, "files_failed": len(failed)},
    )
    return Deleted(run_id, removed, failed)


def expired_runs(session: Session, *, retention_days: int, now: datetime) -> list[Expired]:
    """Finished runs older than the retention period. Reads only."""
    if retention_days < 1:
        raise ValueError("a retention period must be at least one day")
    cutoff = now - timedelta(days=retention_days)
    rows = session.execute(
        select(TestRun.id, TestRun.finished_at, TestRun.suite_id)
        .where(
            TestRun.status.in_(TERMINAL),
            TestRun.finished_at.is_not(None),
            TestRun.finished_at < cutoff,
        )
        .order_by(TestRun.finished_at, TestRun.id)
    )
    return [
        Expired(run_id, finished_at, suite_id)
        for run_id, finished_at, suite_id in rows
        if run_id not in PROTECTED_RUN_IDS
    ]


def purge(
    session: Session,
    artefacts: AudioArtefactStore,
    *,
    retention_days: int,
    now: datetime,
    apply: bool,
) -> tuple[list[Expired], list[Deleted]]:
    """List, and with `apply` delete, every run past retention."""
    expired = expired_runs(session, retention_days=retention_days, now=now)
    if not apply:
        return expired, []
    return expired, [delete_run(session, artefacts, run.run_id) for run in expired]


__all__ = ["Deleted", "Expired", "delete_run", "expired_runs", "purge"]
