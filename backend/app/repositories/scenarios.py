"""Data access for scenarios."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.scenario import Scenario


def get_by_id(session: Session, scenario_id: uuid.UUID) -> Scenario | None:
    """Return one scenario, or None."""
    return session.get(Scenario, scenario_id)


def get_by_name_in_suite(session: Session, suite_id: uuid.UUID, name: str) -> Scenario | None:
    """Return a scenario by name within one suite, or None.

    Scoped to the suite because the uniqueness constraint is
    `(suite_id, name)`, not `name` alone.
    """
    statement = select(Scenario).where(Scenario.suite_id == suite_id, Scenario.name == name)
    return session.scalars(statement).first()


def list_for_suite(
    session: Session, suite_id: uuid.UUID, *, limit: int, offset: int
) -> list[Scenario]:
    """Return a page of scenarios in one suite.

    Ordered by name, which is stable and is how a suite's contents are read.
    """
    statement = (
        select(Scenario)
        .where(Scenario.suite_id == suite_id)
        .order_by(Scenario.name.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def count_for_suite(session: Session, suite_id: uuid.UUID) -> int:
    """Return the number of scenarios in a suite, for pagination metadata."""
    statement = select(func.count()).select_from(Scenario).where(Scenario.suite_id == suite_id)
    return session.scalar(statement) or 0


def add(session: Session, scenario: Scenario) -> Scenario:
    """Stage a new scenario and flush it."""
    session.add(scenario)
    session.flush()
    return scenario


def delete(session: Session, scenario: Scenario) -> None:
    """Stage a scenario for deletion."""
    session.delete(scenario)
    session.flush()
