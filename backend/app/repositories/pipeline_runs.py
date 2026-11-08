"""Every SQL statement the pipeline issues beyond what Phase 6 already does.

Deliberately thin. Phase 6's `caller_conversations` repository already owns the
conversation and turn statements, and duplicating them here would mean two
places to keep correct. What is left is the `test_runs` row - which Phase 6
creates but never reads back or updates - plus the run's pipeline metadata.

**No new table.** `TestRun` already carries a status, a start and finish time,
an error message and a JSONB `run_metadata` whose docstring says it is for
"execution context captured at run time: tool versions, resolved audio
profile, seed". That is exactly what a pipeline run needs to record, so the
pipeline writes there under its own namespace rather than adding columns.

Functions here never commit. The service owns the transaction boundary.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.call_session import CallSession
from app.models.test_run import RunStatus, TestRun
from app.utils.timing import utc_now

PIPELINE_NAMESPACE = "pipeline"
"""The `run_metadata` key the pipeline owns.

Namespaced like Phase 6's `caller` key in `call_metadata`, so a later phase
recording its own run context cannot collide with this one.
"""


def get_run(session: Session, run_id: uuid.UUID) -> TestRun | None:
    """Fetch one run.

    No eager loading of `call_sessions`: the relationship is
    `lazy="raise_on_sql"`, and the pipeline reaches a run's conversation
    through `conversation_of` instead - a run holds exactly one, so loading a
    collection to take its first element would be the wrong shape.
    """
    return session.execute(select(TestRun).where(TestRun.id == run_id)).scalar_one_or_none()


def conversation_of(session: Session, run_id: uuid.UUID) -> CallSession | None:
    """The conversation belonging to a run.

    One per run in this phase: a pipeline run drives a single scenario. Phase 9
    may fan a run out over many, at which point this becomes a list and the
    engine gains a loop - the single-conversation assumption is here, named,
    rather than scattered.
    """
    statement = (
        select(CallSession)
        .where(CallSession.test_run_id == run_id)
        .options(selectinload(CallSession.turns), selectinload(CallSession.scenario))
        .order_by(CallSession.created_at)
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def pipeline_metadata_of(run: TestRun) -> dict[str, Any]:
    """The pipeline's slice of `run_metadata`, or an empty dict."""
    return dict((run.run_metadata or {}).get(PIPELINE_NAMESPACE) or {})


def update_pipeline_metadata(session: Session, run: TestRun, metadata: dict[str, Any]) -> TestRun:
    """Replace the pipeline's slice of `run_metadata`.

    Reassigns the whole dict rather than mutating in place: SQLAlchemy does not
    track mutation inside a JSONB value, so an in-place edit is silently
    dropped at flush. The same trap Phase 6 documents, and the reason this is a
    function rather than something each caller does for itself.
    """
    merged = dict(run.run_metadata or {})
    merged[PIPELINE_NAMESPACE] = metadata
    run.run_metadata = merged
    session.add(run)
    session.flush()
    return run


def mark_running(session: Session, run: TestRun, metadata: dict[str, Any]) -> TestRun:
    """Move a run into `running`, setting its start time once.

    Idempotent on `started_at`: restarting a run that already began must not
    rewrite when it began, or its duration becomes a fiction.
    """
    run.status = RunStatus.RUNNING
    if run.started_at is None:
        run.started_at = utc_now()
    return update_pipeline_metadata(session, run, metadata)


def finish_run(
    session: Session,
    run: TestRun,
    *,
    status: RunStatus,
    metadata: dict[str, Any],
    error_message: str | None = None,
) -> TestRun:
    """Close a run, honouring the `finished_at_matches_status` constraint.

    That CHECK requires a finish time for exactly the terminal statuses, so
    setting one without the other fails at the database rather than silently.
    """
    run.status = status
    run.finished_at = utc_now()
    if error_message is not None:
        # Truncated: the column is unbounded Text, but a provider traceback
        # pasted whole makes a run row unreadable in any admin tool, and the
        # full detail already went to the log.
        run.error_message = error_message[:2000]
    return update_pipeline_metadata(session, run, metadata)


__all__ = [
    "PIPELINE_NAMESPACE",
    "conversation_of",
    "finish_run",
    "get_run",
    "mark_running",
    "pipeline_metadata_of",
    "update_pipeline_metadata",
]
