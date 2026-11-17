"""Data access for test suites."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.suite import TestSuite


def get_by_id(session: Session, suite_id: uuid.UUID) -> TestSuite | None:
    """Return one suite, or None."""
    return session.get(TestSuite, suite_id)


def get_by_name(session: Session, name: str, project_id: uuid.UUID) -> TestSuite | None:
    """Return a suite by exact name within a project, or None.

    Used to detect a duplicate before attempting an insert, so the caller can
    return a clean 409 instead of surfacing an integrity error. Names are
    unique per project, so the same name in another project is not a clash.
    """
    statement = select(TestSuite).where(TestSuite.name == name, TestSuite.project_id == project_id)
    return session.scalars(statement).first()


def _scoped(statement: Any, project_ids: Sequence[uuid.UUID] | None) -> Any:
    """Restrict to `project_ids`; `None` means unscoped (the trusted CLI)."""
    return (
        statement if project_ids is None else statement.where(TestSuite.project_id.in_(project_ids))
    )


def list_suites(
    session: Session,
    *,
    limit: int,
    offset: int,
    project_ids: Sequence[uuid.UUID] | None = None,
) -> list[TestSuite]:
    """Return a page of suites, newest first.

    Ordered by `created_at` with `id` as a tiebreaker: timestamps can collide,
    and an unstable sort makes pagination skip or repeat rows.
    """
    statement = (
        _scoped(select(TestSuite), project_ids)
        .order_by(TestSuite.created_at.desc(), TestSuite.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def count_suites(session: Session, project_ids: Sequence[uuid.UUID] | None = None) -> int:
    """Return the total number of suites, for pagination metadata."""
    statement = _scoped(select(func.count()).select_from(TestSuite), project_ids)
    return session.scalar(statement) or 0


def count_in_project(session: Session, project_id: uuid.UUID) -> int:
    statement = (
        select(func.count()).select_from(TestSuite).where(TestSuite.project_id == project_id)
    )
    return session.scalar(statement) or 0


def add(session: Session, suite: TestSuite) -> TestSuite:
    """Stage a new suite and flush it.

    Flushing (not committing) assigns defaults and surfaces constraint
    violations now, while the caller still controls the transaction.
    """
    session.add(suite)
    session.flush()
    return suite


def delete(session: Session, suite: TestSuite) -> None:
    """Stage a suite for deletion. Its scenarios cascade."""
    session.delete(suite)
    session.flush()
