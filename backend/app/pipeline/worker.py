"""Background execution of runs, and recovery that needs no operator (Phase 9).

**Background runs.** `POST /test-runs/{id}/start?background=true` answers 202
and hands the run to `RunWorker`, which drives it on the server's event loop
with its own database session and engine - the request's session closes when
the response is sent, so it cannot be borrowed. The concurrency limit still
applies: a run is admitted only if a slot is free *before* the 202, so the
answer never promises work the server cannot start.

**A crash finishes the run.** Any exception that escapes the engine marks the
run `failed` with outcome `abandoned` and a redacted reason, through the same
`recovery.abandon` that stale-run recovery uses, so a crashed run never stays
`running`. A run already terminal, or protected, is left alone.

**Recovery on its own.** `RecoveryLoop` runs the stale-run sweep every
`PIPELINE_RECOVERY_INTERVAL_SECONDS` (0 disables it). A run whose worker died
with its process - a restart, a kill - is caught by it, with the threshold
never shorter than `PIPELINE_RUN_TIMEOUT_SECONDS`, the same rule the CLI
enforces. The two protected historical runs are never touched.

In-process by design: no queue, no broker, nothing that costs money. A
second server process would run its own loop; the sweep is idempotent and
`abandon` only touches runs still in flight, so two loops cannot disagree.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.test_run import RunStatus
from app.pipeline import recovery
from app.repositories import pipeline_runs as repo
from app.transcription.redaction import redact
from app.utils.timing import utc_now

logger = logging.getLogger("bhashabench.pipeline.worker")

SessionFactory = Callable[[], Session]


def finish_crashed(session: Session, run_id: uuid.UUID, error: BaseException) -> bool:
    """Close a run whose execution raised. `True` if it was closed here."""
    run = repo.get_run(session, run_id)
    if run is None or run.id in recovery.PROTECTED_RUN_IDS:
        return False
    if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        return False
    meta = repo.pipeline_metadata_of(run)
    now = utc_now()
    stale = recovery.StaleRun(
        run=run,
        scenario_name=str(meta.get("scenario_name", "")),
        mode=str(meta.get("mode", "")),
        pipeline_status=str(meta.get("status", "")),
        last_activity_at=run.updated_at or now,
        idle=timedelta(0),
    )
    recovery.abandon(
        session,
        stale,
        now=now,
        by="background worker",
        reason=redact(f"the run's execution raised {type(error).__name__}: {error}")[:300],
    )
    session.commit()
    return True


class RunWorker:
    """Owns the background tasks, so none is garbage-collected mid-run."""

    def __init__(self) -> None:
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def running(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def submit(
        self,
        run_id: uuid.UUID,
        execute: Callable[[], Awaitable[None]],
        session_factory: SessionFactory,
    ) -> asyncio.Task[None]:
        async def guarded() -> None:
            try:
                await execute()
            except Exception as exc:  # recorded on the run, never lost
                logger.warning(
                    "pipeline.background_run_crashed",
                    extra={"run_id": str(run_id), "error": type(exc).__name__},
                )
                session = session_factory()
                try:
                    finish_crashed(session, run_id, exc)
                finally:
                    session.close()

        task = asyncio.get_running_loop().create_task(guarded(), name=f"run-{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return task

    async def drain(self) -> None:
        """Wait for every background run; used at shutdown and by tests."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)


@lru_cache(maxsize=1)
def run_worker() -> RunWorker:
    """Process-wide, like the concurrency limiter, for the same reason."""
    return RunWorker()


RECOVERY_LOCK_KEY = 0x6262_7265_6376  # "bbrecv": one key for the stale-run sweep


class RecoveryLoop:
    """Closes stale runs periodically, so a run whose process died ends itself."""

    def __init__(
        self, session_factory: SessionFactory, *, interval_seconds: float, threshold_seconds: float
    ) -> None:
        self._sessions = session_factory
        self._interval = interval_seconds
        self._threshold = timedelta(seconds=threshold_seconds)
        self._task: asyncio.Task[None] | None = None

    def sweep_once(self) -> int:
        """Close stale runs once. Returns how many; 0 if another process is sweeping.

        With `UVICORN_WORKERS` > 1 every worker runs this loop. A transaction-
        scoped advisory lock lets one sweep at a time, so two workers never
        abandon the same run twice; it is released at commit or rollback, so a
        worker that dies mid-sweep cannot strand it.
        """
        session = self._sessions()
        try:
            got = session.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": RECOVERY_LOCK_KEY}
            ).scalar()
            if not got:
                return 0  # another process is sweeping; `close` ends this transaction
            now = utc_now()
            stale = recovery.find_stale_runs(session, older_than=self._threshold, now=now)
            for item in stale:
                recovery.abandon(session, item, now=now, by="automatic recovery")
            session.commit()
            return len(stale)
        finally:
            session.close()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                closed = await asyncio.to_thread(self.sweep_once)
                if closed:
                    logger.info("pipeline.recovered", extra={"runs": closed})
            except Exception as exc:  # the loop outlives one bad sweep
                logger.warning("pipeline.recovery_failed", extra={"error": type(exc).__name__})

    def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._loop(), name="recovery")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None


__all__ = ["RecoveryLoop", "RunWorker", "finish_crashed", "run_worker"]
