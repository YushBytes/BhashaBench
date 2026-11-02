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


def update_suite(
    session: Session,
    suite_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    clear_description: bool = False,
) -> TestSuite:
    """Update a suite's editable metadata.

    Only `name` and `description` are editable; `id`, `created_at` and the
    scenario relationship are not, so a mistaken payload cannot detach a
    suite's scenarios.

    `description` is distinguished from "not supplied" by `clear_description`.
    Without that flag there is no way to tell "leave the description alone"
    from "set it to null", and a partial update would silently erase it.

    Scenarios are untouched: the suite row is updated in place, so every
    `scenarios.suite_id` still points at the same id.
    """
    suite = get_suite(session, suite_id)

    if name is not None and name != suite.name:
        clash = suite_repo.get_by_name(session, name)
        if clash is not None and clash.id != suite.id:
            raise ConflictError(f"a suite named '{name}' already exists")
        suite.name = name

    if clear_description:
        suite.description = None
    elif description is not None:
        suite.description = description

    try:
        session.flush()
    except IntegrityError as exc:
        # The check above and this flush are not atomic; the unique constraint
        # is what actually guarantees the name is free.
        session.rollback()
        raise ConflictError(f"a suite named '{name}' already exists") from exc

    session.commit()
    return suite


def delete_suite(session: Session, suite_id: uuid.UUID, *, cascade: bool = False) -> int:
    """Delete a suite, refusing by default to take its scenarios with it.

    The database-level foreign key is ON DELETE CASCADE, so a bare DELETE
    would silently remove every scenario in the suite. That is the wrong
    default for a destructive API: a suite is a container, and losing its
    contents to a single call is not recoverable.

    So this refuses with `ConflictError` when the suite still holds scenarios,
    and only proceeds when the caller passes `cascade=True` - an explicit
    acknowledgement that the scenarios go too. An empty suite deletes
    straightforwardly.

    Returns the number of scenarios deleted alongside it, so the caller can
    report what actually happened.

    A scenario referenced by recorded call history cannot be deleted at all
    (`call_sessions.scenario_id` is ON DELETE RESTRICT); that surfaces as an
    IntegrityError and is reported as a conflict rather than a 500.
    """
    suite = get_suite(session, suite_id)
    scenario_count = scenario_repo.count_for_suite(session, suite_id)

    if scenario_count and not cascade:
        raise ConflictError(
            f"suite '{suite.name}' still contains {scenario_count} scenario(s). "
            "Delete them first, or repeat the request with cascade=true to "
            "delete the suite and its scenarios together."
        )

    try:
        suite_repo.delete(session, suite)
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"suite '{suite.name}' cannot be deleted because one of its scenarios is "
            "referenced by recorded call history"
        ) from exc

    session.commit()
    return scenario_count
