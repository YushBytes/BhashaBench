"""Business logic for scenarios.

Converts between the YAML authoring format, the validated `ScenarioSpec` and
the persisted `Scenario` row. YAML parsing itself lives in
`app.services.scenario_loader`; this module only orchestrates.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import languages
from app.models.scenario import Scenario
from app.repositories import scenarios as scenario_repo
from app.repositories import suites as suite_repo
from app.schemas.scenario_spec import SPEC_VERSION, ScenarioSpec
from app.services.bundle import BundleEntryError, build_bundle, parse_bundle
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


def search_scenarios(
    session: Session,
    *,
    suite_id: uuid.UUID | None = None,
    language: str | None = None,
    name_contains: str | None = None,
    tags: Sequence[str] | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Scenario], int]:
    """Return a filtered page of scenarios and the matching total.

    Cross-suite by default. When `suite_id` is given the suite must exist, so
    that an unknown suite is a 404 rather than an empty page that reads like
    an empty suite.

    Language is validated against the catalogue before querying: a typo should
    say so, not silently return nothing.
    """
    if suite_id is not None and suite_repo.get_by_id(session, suite_id) is None:
        raise NotFoundError("suite", suite_id)

    if language is not None:
        languages.validate_tag(language)

    normalised_tags = sorted({tag.strip().lower() for tag in tags}) if tags else None

    return (
        scenario_repo.search(
            session,
            suite_id=suite_id,
            language=language,
            name_contains=name_contains,
            tags=normalised_tags,
            limit=limit,
            offset=offset,
        ),
        scenario_repo.count_search(
            session,
            suite_id=suite_id,
            language=language,
            name_contains=name_contains,
            tags=normalised_tags,
        ),
    )


def _resolve_target_name(
    session: Session,
    *,
    target_suite_id: uuid.UUID,
    desired_name: str,
    exclude_scenario_id: uuid.UUID | None = None,
) -> str:
    """Validate that `desired_name` is free in the target suite.

    Raises `ConflictError` naming the clash rather than inventing a suffixed
    name: silently renaming someone's scenario to `appointment_booking_2` is a
    surprise, and the caller is better placed to choose.
    """
    clash = scenario_repo.get_by_name_in_suite(session, target_suite_id, desired_name)
    if clash is not None and clash.id != exclude_scenario_id:
        raise ConflictError(
            f"a scenario named '{desired_name}' already exists in the target suite; "
            "supply new_name to choose a different one"
        )
    return desired_name


def copy_scenario(
    session: Session,
    scenario_id: uuid.UUID,
    *,
    target_suite_id: uuid.UUID,
    new_name: str | None = None,
) -> Scenario:
    """Copy a scenario into another suite as an independent row.

    The copy gets a fresh UUID and its own timestamps; the source is left
    untouched. The specification document is deep-copied through
    `ScenarioSpec`, so the two rows never share a mutable structure and the
    copy is re-validated rather than trusted - a stored v1 document is
    normalised to the current schema on the way through.

    Copying into the same suite is allowed, and is the natural way to fork a
    scenario, but then `new_name` is required because the original already
    holds the name.
    """
    source = get_scenario(session, scenario_id)

    if suite_repo.get_by_id(session, target_suite_id) is None:
        raise NotFoundError("suite", target_suite_id)

    # Re-validate rather than copying the raw dict: it normalises an older
    # stored document and guarantees the copy is a legal scenario.
    spec = ScenarioSpec.model_validate(source.spec)
    if new_name is not None:
        spec = spec.model_copy(update={"name": new_name})

    name = _resolve_target_name(session, target_suite_id=target_suite_id, desired_name=spec.name)

    copy = Scenario(suite_id=target_suite_id, **_spec_to_columns(spec))
    try:
        scenario_repo.add(session, copy)
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"a scenario named '{name}' already exists in the target suite"
        ) from exc

    session.commit()
    return copy


def move_scenario(
    session: Session,
    scenario_id: uuid.UUID,
    *,
    target_suite_id: uuid.UUID,
    new_name: str | None = None,
) -> Scenario:
    """Move a scenario to another suite, keeping its identity.

    The UUID is preserved deliberately: anything already referencing this
    scenario - a recorded call session, a bookmark, a CI config - stays valid.
    Only `suite_id` changes, and optionally the name when the destination
    already uses it.

    Moving to the suite it is already in is a no-op rather than an error,
    which keeps a retried request safe.
    """
    scenario = get_scenario(session, scenario_id)

    if suite_repo.get_by_id(session, target_suite_id) is None:
        raise NotFoundError("suite", target_suite_id)

    if scenario.suite_id == target_suite_id and new_name is None:
        return scenario

    desired_name = new_name if new_name is not None else scenario.name
    _resolve_target_name(
        session,
        target_suite_id=target_suite_id,
        desired_name=desired_name,
        exclude_scenario_id=scenario.id,
    )

    if new_name is not None:
        # Keep the stored document in step with the column, so the spec's own
        # `name` never disagrees with the row it lives on.
        spec = ScenarioSpec.model_validate(scenario.spec).model_copy(update={"name": new_name})
        for column, value in _spec_to_columns(spec).items():
            setattr(scenario, column, value)

    scenario.suite_id = target_suite_id

    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(
            f"a scenario named '{desired_name}' already exists in the target suite"
        ) from exc

    session.commit()
    return scenario


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Outcome of a bundle import."""

    total: int
    """Entries the bundle contained."""
    valid: int
    """Entries that passed schema validation."""
    imported: int
    """Entries actually written. Zero for a dry run, or when an atomic import
    was abandoned."""
    duplicates: list[str]
    """Names already present in the target suite."""
    entry_errors: list[BundleEntryError]
    """Per-entry validation failures, never silently dropped."""
    dry_run: bool
    committed: bool
    """Whether anything was persisted. False for a dry run and for an
    abandoned atomic import, so a caller can tell "nothing to do" from
    "nothing was done"."""

    @property
    def failed(self) -> int:
        """Entries that could not be imported, for any reason."""
        return len(self.entry_errors) + len(self.duplicates)


def import_bundle(
    session: Session,
    *,
    suite_id: uuid.UUID,
    content: str,
    dry_run: bool = False,
    atomic: bool = True,
) -> ImportResult:
    """Validate a bundle and import its scenarios into an existing suite.

    The whole document is parsed and every entry validated *before* anything
    is written, so a malformed bundle never leaves a half-populated suite.

    `atomic` (the default) means all or nothing: if any entry fails validation
    or collides with an existing name, nothing is written and `committed` is
    False. With `atomic=False` the valid, non-colliding entries are imported
    and the rest are reported - useful when topping up a library from a file
    that partly overlaps it.

    `dry_run` validates and reports exactly what would happen without writing,
    and is the safe way to check a bundle against a real suite.

    Duplicate names are reported, never overwritten. Silently replacing a
    scenario someone else authored because the names matched would be the
    worst possible default for a test library.
    """
    if suite_repo.get_by_id(session, suite_id) is None:
        raise NotFoundError("suite", suite_id)

    parsed = parse_bundle(content)

    existing_names = scenario_repo.names_in_suite(session, suite_id)
    duplicates = [spec.name for spec in parsed.specs if spec.name in existing_names]
    importable = [spec for spec in parsed.specs if spec.name not in existing_names]

    blocked = bool(parsed.entry_errors or duplicates)

    if dry_run or (atomic and blocked):
        return ImportResult(
            total=parsed.total,
            valid=len(parsed.specs),
            imported=0,
            duplicates=duplicates,
            entry_errors=parsed.entry_errors,
            dry_run=dry_run,
            committed=False,
        )

    for spec in importable:
        session.add(Scenario(suite_id=suite_id, **_spec_to_columns(spec)))

    try:
        session.flush()
    except IntegrityError as exc:
        # A concurrent import could have inserted one of these names between
        # the check above and this flush. Roll the whole batch back rather
        # than leaving part of it applied.
        session.rollback()
        raise ConflictError(
            "import failed: a scenario name in this bundle was created "
            "concurrently. Retry the import."
        ) from exc

    session.commit()

    return ImportResult(
        total=parsed.total,
        valid=len(parsed.specs),
        imported=len(importable),
        duplicates=duplicates,
        entry_errors=parsed.entry_errors,
        dry_run=False,
        committed=True,
    )


def export_suite(session: Session, suite_id: uuid.UUID) -> str:
    """Export every scenario in a suite as a bundle document.

    An empty suite exports a bundle with an empty `scenarios` list rather than
    failing: "this suite has nothing in it" is a legitimate answer, and a
    caller scripting a backup should not have to special-case it.
    """
    suite = suite_repo.get_by_id(session, suite_id)
    if suite is None:
        raise NotFoundError("suite", suite_id)

    scenarios = scenario_repo.list_all_for_suite(session, suite_id)
    specs = [ScenarioSpec.model_validate(scenario.spec) for scenario in scenarios]

    return build_bundle(specs, suite_name=suite.name, suite_description=suite.description)


def export_scenarios(session: Session, scenario_ids: Sequence[uuid.UUID]) -> str:
    """Export specific scenarios as a bundle, in the order requested.

    No suite metadata, because the selection may span suites. Every id must
    exist; a partial export would silently omit what the caller asked for.
    """
    specs: list[ScenarioSpec] = []
    for scenario_id in scenario_ids:
        scenario = scenario_repo.get_by_id(session, scenario_id)
        if scenario is None:
            raise NotFoundError("scenario", scenario_id)
        specs.append(ScenarioSpec.model_validate(scenario.spec))

    return build_bundle(specs)
