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
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.call_session import CallSession
from app.models.conversation_turn import ConversationTurn
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

    One per run in this phase: a pipeline run drives a single scenario. Phase 10
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


def _listing_statement(
    *,
    suite_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    mode: str | None = None,
    language: str | None = None,
    outcome: str | None = None,
    scenario_contains: str | None = None,
) -> Select[tuple[TestRun]]:
    """Build the filtered run-listing query.

    **Only runs the pipeline created.** `TestRun` is also the parent of a
    Phase 6 caller conversation, which writes no `pipeline` namespace, so an
    unfiltered listing would return rows whose `GET /test-runs/{id}` report is
    empty - a row leading nowhere. `has_key` keeps the listing to runs that
    can actually be opened; caller conversations stay addressable through the
    caller API, which is where they were started.

    The remaining filters read JSONB fields rather than columns. They go
    through SQLAlchemy's `astext` comparison, so each value is a bound
    parameter and none of them is interpolated into SQL.
    """
    pipeline = TestRun.run_metadata[PIPELINE_NAMESPACE]
    statement = select(TestRun).where(TestRun.run_metadata.has_key(PIPELINE_NAMESPACE))

    if suite_id is not None:
        statement = statement.where(TestRun.suite_id == suite_id)
    if status is not None:
        statement = statement.where(TestRun.status == status)
    if mode is not None:
        statement = statement.where(pipeline["mode"].astext == mode)
    if language is not None:
        statement = statement.where(pipeline["language"].astext == language)
    if outcome is not None:
        statement = statement.where(pipeline["outcome"].astext == outcome)
    if scenario_contains:
        # `ilike` on a JSONB field, escaped: a scenario name containing % or _
        # would otherwise widen the search rather than narrow it.
        escaped = scenario_contains.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(pipeline["scenario_name"].astext.ilike(f"%{escaped}%"))

    return statement


def search_runs(
    session: Session,
    *,
    suite_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    mode: str | None = None,
    language: str | None = None,
    outcome: str | None = None,
    scenario_contains: str | None = None,
    limit: int,
    offset: int,
) -> list[TestRun]:
    """Return a page of pipeline runs, newest first.

    Ordered by `created_at` descending with the id as tiebreaker: two runs
    created inside the same clock tick would otherwise be free to swap places
    between pages, which silently skips one and repeats the other.
    """
    statement = (
        _listing_statement(
            suite_id=suite_id,
            status=status,
            mode=mode,
            language=language,
            outcome=outcome,
            scenario_contains=scenario_contains,
        )
        .order_by(TestRun.created_at.desc(), TestRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def count_runs(
    session: Session,
    *,
    suite_id: uuid.UUID | None = None,
    status: RunStatus | None = None,
    mode: str | None = None,
    language: str | None = None,
    outcome: str | None = None,
    scenario_contains: str | None = None,
) -> int:
    """Count the runs matching the same filters, for the page envelope."""
    inner = _listing_statement(
        suite_id=suite_id,
        status=status,
        mode=mode,
        language=language,
        outcome=outcome,
        scenario_contains=scenario_contains,
    ).subquery()
    return session.scalar(select(func.count()).select_from(inner)) or 0


def turn_counts_for_runs(
    session: Session, run_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """Count turns per speaker for several runs in one query.

    The listing shows how far each conversation got, and the turn counts are
    the only figure there that is not already in `run_metadata`. Fetching them
    per row would be a query per run; this is one grouped query for the whole
    page.

    Runs with no turns are absent from the result rather than mapped to zero.
    The caller decides what no turns means - for a run that has not started it
    is not the same statement as a measured zero.
    """
    if not run_ids:
        return {}

    statement = (
        select(CallSession.test_run_id, ConversationTurn.speaker, func.count())
        .join(ConversationTurn, ConversationTurn.call_session_id == CallSession.id)
        .where(CallSession.test_run_id.in_(run_ids))
        .group_by(CallSession.test_run_id, ConversationTurn.speaker)
    )

    counts: dict[uuid.UUID, dict[str, int]] = {}
    for run_id, speaker, total in session.execute(statement):
        counts.setdefault(run_id, {})[speaker.value] = total
    return counts


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
    "count_runs",
    "finish_run",
    "get_run",
    "mark_running",
    "pipeline_metadata_of",
    "search_runs",
    "turn_counts_for_runs",
    "update_pipeline_metadata",
]
