"""Aggregation SQL over pipeline runs and their latest evaluations. Never commits.

Grouping and counting happen in PostgreSQL, not in Python: a request handler
must not load every run to count them. Each run contributes its **latest**
evaluation only (`DISTINCT ON`), so re-evaluating a run never double-counts
it; runs never evaluated are counted as such rather than dropped.

Every filter value is a bound parameter. The grouping dimension is chosen from
a fixed mapping, so no client string reaches SQL as an identifier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, cast, func, literal, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models.evaluation import RunEvaluation
from app.models.test_run import TestRun
from app.repositories.pipeline_runs import PIPELINE_NAMESPACE

DIMENSIONS = ("language", "scenario_name", "bot_adapter", "mode", "outcome", "suite_id")


@dataclass(frozen=True, slots=True)
class RunFilter:
    """Which runs a query covers. Every field is optional."""

    suite_id: uuid.UUID | None = None
    mode: str | None = None
    language: str | None = None
    scenario_name: str | None = None
    bot_adapter: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    run_ids: tuple[uuid.UUID, ...] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in self.__slots__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            if value is not None:
                out[name] = (
                    [str(v) for v in value]
                    if isinstance(value, tuple)
                    else (str(value) if not isinstance(value, str) else value)
                )
        return out


def latest_evaluations_subquery() -> Any:
    return (
        select(
            RunEvaluation.test_run_id.label("run_id"),
            RunEvaluation.verdict.label("verdict"),
            RunEvaluation.evaluator_version.label("evaluator_version"),
            RunEvaluation.results.label("results"),
        )
        .ext(distinct_on(RunEvaluation.test_run_id))
        .order_by(
            RunEvaluation.test_run_id,
            RunEvaluation.created_at.desc(),
            RunEvaluation.id.desc(),
        )
        .subquery("latest")
    )


def _dimension(name: str) -> Any:
    if name not in DIMENSIONS:
        raise ValueError(f"unknown dimension {name!r}; choose one of {DIMENSIONS}")
    if name == "suite_id":
        return cast(TestRun.suite_id, String)
    return TestRun.run_metadata[PIPELINE_NAMESPACE][name].astext


def _filtered(statement: Select[Any], run_filter: RunFilter) -> Select[Any]:
    pipeline = TestRun.run_metadata[PIPELINE_NAMESPACE]
    statement = statement.where(TestRun.run_metadata.has_key(PIPELINE_NAMESPACE))
    if run_filter.suite_id is not None:
        statement = statement.where(TestRun.suite_id == run_filter.suite_id)
    for key in ("mode", "language", "scenario_name", "bot_adapter"):
        value = getattr(run_filter, key)
        if value is not None:
            statement = statement.where(pipeline[key].astext == value)
    if run_filter.created_after is not None:
        statement = statement.where(TestRun.created_at >= run_filter.created_after)
    if run_filter.created_before is not None:
        statement = statement.where(TestRun.created_at < run_filter.created_before)
    if run_filter.run_ids is not None:
        statement = statement.where(TestRun.id.in_(run_filter.run_ids))
    return statement


def verdict_counts(
    session: Session, run_filter: RunFilter, *, group_by: str | None = None
) -> list[tuple[str | None, str | None, int]]:
    """(group, verdict or None for never evaluated, count) rows."""
    latest = latest_evaluations_subquery()
    group = _dimension(group_by) if group_by is not None else literal(None)
    statement = (
        select(group.label("grp"), latest.c.verdict, func.count().label("n"))
        .select_from(TestRun)
        .outerjoin(latest, latest.c.run_id == TestRun.id)
    )
    statement = _filtered(statement, run_filter).group_by(group, latest.c.verdict)
    return [
        (row.grp, None if row.verdict is None else row.verdict.value, int(row.n))
        for row in session.execute(statement)
    ]


def evaluator_versions(session: Session, run_filter: RunFilter) -> list[str]:
    latest = latest_evaluations_subquery()
    statement = (
        select(latest.c.evaluator_version)
        .select_from(TestRun)
        .join(latest, latest.c.run_id == TestRun.id)
    )
    statement = _filtered(statement, run_filter).distinct()
    return sorted(v for v in session.scalars(statement) if v)


def metric_rows(session: Session, run_filter: RunFilter) -> list[tuple[uuid.UUID, dict[str, Any]]]:
    """(run id, latest evaluation's metrics) for evaluated runs.

    Only the `metrics` sub-document is selected, so a large `criteria` list is
    not shipped to Python just to be discarded.
    """
    latest = latest_evaluations_subquery()
    statement = (
        select(TestRun.id, latest.c.results["metrics"].label("metrics"))
        .select_from(TestRun)
        .join(latest, latest.c.run_id == TestRun.id)
    )
    statement = _filtered(statement, run_filter)
    return [(row.id, dict(row.metrics or {})) for row in session.execute(statement)]


def trend_counts(
    session: Session, run_filter: RunFilter, *, bucket: str
) -> list[tuple[datetime, str | None, int]]:
    if bucket not in {"day", "week"}:
        raise ValueError("bucket must be 'day' or 'week'")
    latest = latest_evaluations_subquery()
    period = func.date_trunc(bucket, TestRun.created_at)
    statement = (
        select(period.label("period"), latest.c.verdict, func.count().label("n"))
        .select_from(TestRun)
        .outerjoin(latest, latest.c.run_id == TestRun.id)
    )
    statement = _filtered(statement, run_filter).group_by(period, latest.c.verdict).order_by(period)
    return [
        (row.period, None if row.verdict is None else row.verdict.value, int(row.n))
        for row in session.execute(statement)
    ]


def runs_with_latest(
    session: Session, run_filter: RunFilter, *, limit: int
) -> list[tuple[TestRun, str | None, dict[str, Any] | None]]:
    """Runs newest first, each with its latest verdict and metrics, for export."""
    latest = latest_evaluations_subquery()
    statement = (
        select(TestRun, latest.c.verdict, latest.c.results["metrics"].label("metrics"))
        .select_from(TestRun)
        .outerjoin(latest, latest.c.run_id == TestRun.id)
    )
    statement = (
        _filtered(statement, run_filter)
        .order_by(TestRun.created_at.desc(), TestRun.id.desc())
        .limit(limit)
    )
    return [
        (row[0], None if row.verdict is None else row.verdict.value, row.metrics)
        for row in session.execute(statement)
    ]


__all__ = [
    "DIMENSIONS",
    "RunFilter",
    "evaluator_versions",
    "latest_evaluations_subquery",
    "metric_rows",
    "runs_with_latest",
    "trend_counts",
    "verdict_counts",
]
