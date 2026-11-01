"""Business logic for test suites."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.suite import TestSuite
from app.repositories import scenarios as scenario_repo
from app.repositories import suites as suite_repo
from app.services.errors import ConflictError, NotFoundError


def create_suite(session: Session, *, name: str, description: str | None) -> TestSuite:
    """Create a suite, rejecting a duplicate name.

    The name is checked first so the common case returns a clear 409, and the
    `IntegrityError` is still caught because that check and the insert are not
    atomic - two concurrent requests can both pass the check, and the database
    constraint is what actually guarantees uniqueness.
    """
    if suite_repo.get_by_name(session, name) is not None:
        raise ConflictError(f"a suite named '{name}' already exists")

    suite = TestSuite(name=name, description=description)
    try:
        suite_repo.add(session, suite)
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"a suite named '{name}' already exists") from exc

    session.commit()
    return suite


def get_suite(session: Session, suite_id: uuid.UUID) -> TestSuite:
    """Return a suite or raise `NotFoundError`."""
    suite = suite_repo.get_by_id(session, suite_id)
    if suite is None:
        raise NotFoundError("suite", suite_id)
    return suite


def count_scenarios(session: Session, suite_id: uuid.UUID) -> int:
    """Return how many scenarios a suite holds.

    Counted with SQL rather than `len(suite.scenarios)`. Loading every
    scenario row to measure the collection would be wasteful for a large
    suite, and the loaded collection can be stale if rows were inserted
    through a different identity map since it was populated.
    """
    return scenario_repo.count_for_suite(session, suite_id)


def list_suites(session: Session, *, limit: int, offset: int) -> tuple[list[TestSuite], int]:
    """Return a page of suites and the total count."""
    return (
        suite_repo.list_suites(session, limit=limit, offset=offset),
        suite_repo.count_suites(session),
    )
