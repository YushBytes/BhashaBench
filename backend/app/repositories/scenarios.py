"""Data access for scenarios."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, select
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


def _search_statement(
    *,
    suite_id: uuid.UUID | None,
    language: str | None,
    name_contains: str | None,
    tags: Sequence[str] | None,
) -> Select[tuple[Scenario]]:
    """Build the shared WHERE clause for searching and counting.

    One builder for both so a filter can never apply to the page but not the
    total, which is how a list endpoint ends up reporting "3 of 1".
    """
    statement = select(Scenario)

    if suite_id is not None:
        statement = statement.where(Scenario.suite_id == suite_id)

    if language is not None:
        statement = statement.where(Scenario.language == language)

    if name_contains:
        # Case-insensitive substring. `ilike` with escaped wildcards so a
        # caller searching for a literal `%` or `_` gets what they asked for
        # rather than a match-everything query.
        escaped = name_contains.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        statement = statement.where(Scenario.name.ilike(f"%{escaped}%", escape="\\"))

    if tags:
        # JSONB containment against the whole document: `spec @> {"tags": [...]}`
        # is true only when every requested tag is present, giving AND
        # semantics. Written against `spec` rather than `spec['tags']` so the
        # GIN index on the column can serve it.
        statement = statement.where(Scenario.spec.contains({"tags": list(tags)}))

    return statement


def search(
    session: Session,
    *,
    suite_id: uuid.UUID | None = None,
    language: str | None = None,
    name_contains: str | None = None,
    tags: Sequence[str] | None = None,
    limit: int,
    offset: int,
) -> list[Scenario]:
    """Return a filtered page of scenarios across all suites.

    Ordered by name then id. `name` alone is unique only within a suite, so
    without the id tiebreaker a cross-suite page could skip or repeat a row.
    """
    statement = (
        _search_statement(
            suite_id=suite_id, language=language, name_contains=name_contains, tags=tags
        )
        .order_by(Scenario.name.asc(), Scenario.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def count_search(
    session: Session,
    *,
    suite_id: uuid.UUID | None = None,
    language: str | None = None,
    name_contains: str | None = None,
    tags: Sequence[str] | None = None,
) -> int:
    """Return the total number of scenarios matching the same filters."""
    inner = _search_statement(
        suite_id=suite_id, language=language, name_contains=name_contains, tags=tags
    ).subquery()
    return session.scalar(select(func.count()).select_from(inner)) or 0


def list_all_for_suite(session: Session, suite_id: uuid.UUID) -> list[Scenario]:
    """Return every scenario in a suite, unpaginated and ordered by name.

    For export, which must emit a whole suite rather than a page. Deliberately
    separate from `list_for_suite` so no caller accidentally drops pagination
    on a user-facing listing.
    """
    statement = select(Scenario).where(Scenario.suite_id == suite_id).order_by(Scenario.name.asc())
    return list(session.scalars(statement))


def names_in_suite(session: Session, suite_id: uuid.UUID) -> set[str]:
    """Return the set of scenario names already used in a suite.

    One query for bulk import, which would otherwise issue a duplicate check
    per scenario in the bundle.
    """
    statement = select(Scenario.name).where(Scenario.suite_id == suite_id)
    return set(session.scalars(statement))
