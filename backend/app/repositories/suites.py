"""Data access for test suites."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.suite import TestSuite


def get_by_id(session: Session, suite_id: uuid.UUID) -> TestSuite | None:
    """Return one suite, or None."""
    return session.get(TestSuite, suite_id)


def get_by_name(session: Session, name: str) -> TestSuite | None:
    """Return a suite by exact name, or None.

    Used to detect a duplicate before attempting an insert, so the caller can
    return a clean 409 instead of surfacing an integrity error.
    """
    return session.scalars(select(TestSuite).where(TestSuite.name == name)).first()


def list_suites(session: Session, *, limit: int, offset: int) -> list[TestSuite]:
    """Return a page of suites, newest first.

    Ordered by `created_at` with `id` as a tiebreaker: timestamps can collide,
    and an unstable sort makes pagination skip or repeat rows.
    """
    statement = (
        select(TestSuite)
        .order_by(TestSuite.created_at.desc(), TestSuite.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def count_suites(session: Session) -> int:
    """Return the total number of suites, for pagination metadata."""
    return session.scalar(select(func.count()).select_from(TestSuite)) or 0


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
