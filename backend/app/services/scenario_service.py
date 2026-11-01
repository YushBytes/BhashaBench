"""Business logic for scenarios.

Converts between the YAML authoring format, the validated `ScenarioSpec` and
the persisted `Scenario` row. YAML parsing itself lives in
`app.services.scenario_loader`; this module only orchestrates.
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.scenario import Scenario
from app.repositories import scenarios as scenario_repo
from app.repositories import suites as suite_repo
from app.schemas.scenario_spec import SPEC_VERSION, ScenarioSpec
from app.services.errors import ConflictError, NotFoundError
from app.services.scenario_loader import spec_from_yaml, spec_to_yaml


def _spec_to_columns(spec: ScenarioSpec) -> dict[str, object]:
    """Project a spec onto the scenario's own columns.

    `name`, `description` and `language` are duplicated out of the JSONB
    document into real columns because they are the fields the API filters,
    sorts and enforces uniqueness on - none of which a JSONB document does
    efficiently. The spec remains the source of truth; these are a projection
    of it, written only here so the two cannot drift.
    """
    return {
        "name": spec.name,
        "description": spec.description,
        "language": spec.language,
        "spec": spec.model_dump(mode="json"),
        "spec_version": SPEC_VERSION,
    }


def validate_yaml(content: str) -> tuple[ScenarioSpec, str]:
    """Validate YAML and return the spec with its canonical serialisation.

    Raises the `ScenarioLoadError` subclasses from `scenario_loader`.
    """
    spec = spec_from_yaml(content)
    return spec, spec_to_yaml(spec)


def create_scenario(session: Session, *, suite_id: uuid.UUID, content: str) -> Scenario:
    """Validate YAML and persist it as a scenario in the given suite."""
    if suite_repo.get_by_id(session, suite_id) is None:
        raise NotFoundError("suite", suite_id)

    spec = spec_from_yaml(content)

    if scenario_repo.get_by_name_in_suite(session, suite_id, spec.name) is not None:
        raise ConflictError(f"a scenario named '{spec.name}' already exists in this suite")

    scenario = Scenario(suite_id=suite_id, **_spec_to_columns(spec))
    try:
        scenario_repo.add(session, scenario)
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"a scenario named '{spec.name}' already exists in this suite") from exc

    session.commit()
    return scenario


def get_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario:
    """Return a scenario or raise `NotFoundError`."""
    scenario = scenario_repo.get_by_id(session, scenario_id)
    if scenario is None:
        raise NotFoundError("scenario", scenario_id)
    return scenario


def list_scenarios(
    session: Session, suite_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[Scenario], int]:
    """Return a page of a suite's scenarios and the total count.

    Raises `NotFoundError` when the suite does not exist, so that an unknown
    suite is a 404 rather than an empty list that looks like an empty suite.
    """
    if suite_repo.get_by_id(session, suite_id) is None:
        raise NotFoundError("suite", suite_id)

    return (
        scenario_repo.list_for_suite(session, suite_id, limit=limit, offset=offset),
        scenario_repo.count_for_suite(session, suite_id),
    )


def replace_scenario(session: Session, scenario_id: uuid.UUID, *, content: str) -> Scenario:
    """Replace a scenario's definition with newly validated YAML.

    A rename is allowed, but only to a name not already used in the same
    suite. The scenario's id is stable across updates so existing references
    to it stay valid.
    """
    scenario = get_scenario(session, scenario_id)
    spec = spec_from_yaml(content)

    if spec.name != scenario.name:
        clash = scenario_repo.get_by_name_in_suite(session, scenario.suite_id, spec.name)
        if clash is not None and clash.id != scenario.id:
            raise ConflictError(f"a scenario named '{spec.name}' already exists in this suite")

    for column, value in _spec_to_columns(spec).items():
        setattr(scenario, column, value)

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(f"a scenario named '{spec.name}' already exists in this suite") from exc

    session.commit()
    return scenario


def delete_scenario(session: Session, scenario_id: uuid.UUID) -> None:
    """Delete a scenario."""
    scenario = get_scenario(session, scenario_id)
    scenario_repo.delete(session, scenario)
    session.commit()
