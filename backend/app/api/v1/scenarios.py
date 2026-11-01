"""Scenario endpoints.

Two routers are exported because the paths are not all nested under a suite:
creating and listing scenarios is suite-scoped, while fetching, updating and
deleting one addresses it by its own id. Splitting them keeps the URL shapes
honest rather than forcing a redundant suite id into every path.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import DbSession, PaginationParams
from app.models.scenario import Scenario
from app.schemas.common import ErrorResponse
from app.schemas.scenario import (
    ScenarioCreate,
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
