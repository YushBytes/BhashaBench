"""Scenario endpoints.

Two routers are exported because the paths are not all nested under a suite:
creating and listing scenarios is suite-scoped, while fetching, updating and
deleting one addresses it by its own id. Splitting them keeps the URL shapes
honest rather than forcing a redundant suite id into every path.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, PaginationParams
from app.models.scenario import Scenario
from app.schemas.common import ErrorResponse
from app.schemas.scenario import (
    BundleEntryErrorRead,
    BundleExportResponse,
    BundleImportRequest,
    BundleImportResponse,
    ScenarioCopyRequest,
    ScenarioCreate,
    ScenarioMoveRequest,
    ScenarioRead,
    ScenarioSummary,
    ScenarioUpdate,
    ScenarioValidateRequest,
    ScenarioValidateResponse,
    ValidationFieldError,
)
from app.schemas.suite import Page
from app.services import scenario_service
from app.services.scenario_loader import (
    ScenarioSyntaxError,
    ScenarioTooLargeError,
    ScenarioValidationError,
)

# Nested under a suite: POST/GET /suites/{suite_id}/scenarios
suite_scenarios_router = APIRouter(prefix="/suites/{suite_id}/scenarios", tags=["scenarios"])

# Addressed directly: GET/PUT/DELETE /scenarios/{scenario_id}, POST /scenarios/validate
scenarios_router = APIRouter(prefix="/scenarios", tags=["scenarios"])

_YAML_ERROR_RESPONSES = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Suite not found"},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Duplicate name"},
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": ErrorResponse,
        "description": "YAML too large",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Invalid YAML or scenario",
    },
}


def _to_read(scenario: Scenario) -> ScenarioRead:
    """Shape a scenario for a detail response."""
    return ScenarioRead.model_validate(scenario)


@suite_scenarios_router.post(
    "",
    response_model=ScenarioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scenario from YAML",
    responses=_YAML_ERROR_RESPONSES,
)
def create_scenario(
    suite_id: uuid.UUID, payload: ScenarioCreate, session: DbSession
) -> ScenarioRead:
    """Validate the YAML and store it as a scenario in this suite."""
    scenario = scenario_service.create_scenario(session, suite_id=suite_id, content=payload.yaml)
    return _to_read(scenario)


@suite_scenarios_router.get(
    "",
    response_model=Page[ScenarioSummary],
    summary="List a suite's scenarios",
    description="Ordered by name. Summaries omit the full specification.",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"}},
)
def list_scenarios(
    suite_id: uuid.UUID, session: DbSession, pagination: PaginationParams
) -> Page[ScenarioSummary]:
    """Return a page of the suite's scenarios."""
    scenarios, total = scenario_service.list_scenarios(
        session, suite_id, limit=pagination.limit, offset=pagination.offset
    )
    return Page[ScenarioSummary](
        items=[ScenarioSummary.model_validate(scenario) for scenario in scenarios],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@scenarios_router.post(
    "/validate",
    response_model=ScenarioValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate scenario YAML without storing it",
    description=(
        "Returns 200 whether or not the YAML is valid; `valid` carries the "
        "verdict. On success the normalised specification is returned both as "
        "JSON and as canonical YAML. Nothing is persisted, and no suite is "
        "required."
    ),
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "YAML exceeds the size limit",
        }
    },
)
def validate_scenario(payload: ScenarioValidateRequest) -> ScenarioValidateResponse:
    """Validate YAML and report the verdict.

    A size overrun is the one failure that still raises, because returning a
    200 body for input the server refused to parse would be misleading - and
    the limit is a property of the request, not of the scenario.
    """
    try:
        spec, normalized_yaml = scenario_service.validate_yaml(payload.yaml)
    except ScenarioTooLargeError:
        raise
    except ScenarioSyntaxError as exc:
        return ScenarioValidateResponse(
            valid=False,
            errors=[ValidationFieldError(field="<document>", message=str(exc), type="yaml_syntax")],
        )
    except ScenarioValidationError as exc:
        return ScenarioValidateResponse(
            valid=False,
            errors=[ValidationFieldError(**error.as_dict()) for error in exc.errors],
        )

    return ScenarioValidateResponse(valid=True, normalized=spec, normalized_yaml=normalized_yaml)


@scenarios_router.get(
    "/{scenario_id}",
    response_model=ScenarioRead,
    summary="Retrieve a scenario",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"}},
)
def get_scenario(scenario_id: uuid.UUID, session: DbSession) -> ScenarioRead:
    """Return one scenario, including its full specification."""
    return _to_read(scenario_service.get_scenario(session, scenario_id))


@scenarios_router.put(
    "/{scenario_id}",
    response_model=ScenarioRead,
    summary="Replace a scenario's definition",
    description=(
        "Replaces the whole definition. The scenario keeps its id, so existing "
        "references stay valid. Renaming is allowed if the new name is free "
        "within the same suite."
    ),
    responses=_YAML_ERROR_RESPONSES,
)
def update_scenario(
    scenario_id: uuid.UUID, payload: ScenarioUpdate, session: DbSession
) -> ScenarioRead:
    """Validate the YAML and replace the stored definition."""
    scenario = scenario_service.replace_scenario(session, scenario_id, content=payload.yaml)
    return _to_read(scenario)


@scenarios_router.delete(
    "/{scenario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scenario",
    description="Returns 204. Fails with 409 if a recorded call still references it.",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"},
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Referenced by call history",
        },
    },
)
def delete_scenario(scenario_id: uuid.UUID, session: DbSession) -> None:
    """Delete a scenario."""
    scenario_service.delete_scenario(session, scenario_id)


@scenarios_router.get(
    "",
    response_model=Page[ScenarioSummary],
    summary="Search the scenario library",
    description=(
        "Searches across every suite by default. Filters combine with AND: "
        "`language` must match exactly, `name` is a case-insensitive substring, "
        "and `tag` may be repeated to require several tags at once. Ordered by "
        "name then id, so paging stays stable even when two suites hold a "
        "scenario with the same name."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Suite not found"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Unsupported language or malformed parameter",
        },
    },
)
def search_scenarios(
    session: DbSession,
    pagination: PaginationParams,
    suite_id: Annotated[
        uuid.UUID | None, Query(description="Restrict to one suite. Must exist.")
    ] = None,
    language: Annotated[str | None, Query(description="Exact language tag, e.g. `hi-IN`.")] = None,
    name: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Case-insensitive substring of the scenario name.",
        ),
    ] = None,
    tag: Annotated[
        list[str] | None,
        Query(description="Require this tag. Repeat the parameter to require several."),
    ] = None,
) -> Page[ScenarioSummary]:
    """Return a filtered page of scenarios."""
    scenarios, total = scenario_service.search_scenarios(
        session,
        suite_id=suite_id,
        language=language,
        name_contains=name,
        tags=tag,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page[ScenarioSummary](
        items=[ScenarioSummary.model_validate(scenario) for scenario in scenarios],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@scenarios_router.post(
    "/{scenario_id}/copy",
    response_model=ScenarioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Copy a scenario into another suite",
    description=(
        "Creates an independent scenario with a new id and its own timestamps; "
        "the source is untouched. The specification is re-validated on the way "
        "through, so a copy of an older stored document comes out normalised to "
        "the current schema. Copying within the same suite is allowed and then "
        "requires `new_name`."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Scenario or target suite not found",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Name already used in the target suite",
        },
    },
)
def copy_scenario(
    scenario_id: uuid.UUID, payload: ScenarioCopyRequest, session: DbSession
) -> ScenarioRead:
    """Copy a scenario into the target suite."""
    copy = scenario_service.copy_scenario(
        session,
        scenario_id,
        target_suite_id=payload.target_suite_id,
        new_name=payload.new_name,
    )
    return _to_read(copy)


@scenarios_router.post(
    "/{scenario_id}/move",
    response_model=ScenarioRead,
    summary="Move a scenario to another suite",
    description=(
        "Keeps the scenario's id, so anything already referencing it stays "
        "valid; only its suite changes. Moving to the suite it already belongs "
        "to is a no-op, which keeps a retried request safe. Supply `new_name` "
        "when the destination already uses the name."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Scenario or target suite not found",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Name already used in the target suite",
        },
    },
)
def move_scenario(
    scenario_id: uuid.UUID, payload: ScenarioMoveRequest, session: DbSession
) -> ScenarioRead:
    """Move a scenario into the target suite."""
    moved = scenario_service.move_scenario(
        session,
        scenario_id,
        target_suite_id=payload.target_suite_id,
        new_name=payload.new_name,
    )
    return _to_read(moved)


@suite_scenarios_router.post(
    "/import",
    response_model=BundleImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Import a scenario bundle into a suite",
    description=(
        "Validates the whole bundle before writing anything. Atomic by default: "
        "one failed or duplicate entry abandons the import and `committed` is "
        "false. Use `dry_run` to see exactly what would happen against a real "
        "suite without writing. Existing scenarios are never overwritten - a "
        "name collision is reported as a duplicate. Returns 200 rather than 201 "
        "because the useful outcome is the report, and an abandoned import "
        "creates nothing."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Suite not found"},
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "A colliding name was created concurrently",
        },
        status.HTTP_413_CONTENT_TOO_LARGE: {
            "model": ErrorResponse,
            "description": "Bundle exceeds the size limit",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Not a bundle, or unsafe/malformed YAML",
        },
    },
)
def import_bundle(
    suite_id: uuid.UUID, payload: BundleImportRequest, session: DbSession
) -> BundleImportResponse:
    """Import a bundle, atomically by default."""
    result = scenario_service.import_bundle(
        session,
        suite_id=suite_id,
        content=payload.yaml,
        dry_run=payload.dry_run,
        atomic=payload.atomic,
    )
    return BundleImportResponse(
        total=result.total,
        valid=result.valid,
        imported=result.imported,
        failed=result.failed,
        duplicates=result.duplicates,
        entry_errors=[
            BundleEntryErrorRead(
                index=entry.index,
                name=entry.name,
                errors=[ValidationFieldError(**error.as_dict()) for error in entry.errors],
            )
            for entry in result.entry_errors
        ],
        dry_run=result.dry_run,
        committed=result.committed,
    )


@suite_scenarios_router.get(
    "/export",
    response_model=BundleExportResponse,
    summary="Export a suite as a scenario bundle",
    description=(
        "Returns every scenario in the suite as one re-importable document. "
        "Output is deterministic - no ids, no timestamps, declared field order - "
        "so exporting twice gives byte-identical YAML and a diff between two "
        "exports shows only real changes. An empty suite exports an empty "
        "`scenarios` list rather than failing."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Suite not found"}
    },
)
def export_suite(suite_id: uuid.UUID, session: DbSession) -> BundleExportResponse:
    """Export the suite's scenarios as a bundle."""
    document = scenario_service.export_suite(session, suite_id)
    _, count = scenario_service.list_scenarios(session, suite_id, limit=1, offset=0)
    return BundleExportResponse(yaml=document, scenario_count=count)
