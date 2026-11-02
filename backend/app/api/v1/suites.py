"""Test suite endpoints.

Handlers are deliberately thin: validate input via the schema, call a service,
shape the response. Domain errors propagate to the exception handlers in
`app.main`, which own the HTTP mapping.

Handlers are `def`, not `async def`. The session is synchronous, so FastAPI
runs these in a worker thread and the event loop stays free - whereas blocking
database calls inside `async def` would stall every other request.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, PaginationParams
from app.models.suite import TestSuite
from app.schemas.common import ErrorResponse
from app.schemas.suite import (
    Page,
    SuiteCreate,
    SuiteDeleteResult,
    SuiteRead,
    SuiteSummary,
    SuiteUpdate,
)
from app.services import suite_service

router = APIRouter(prefix="/suites", tags=["suites"])


def _to_read(suite: TestSuite, scenario_count: int) -> SuiteRead:
    """Shape a suite for a detail response.

    The count is passed in rather than read from `suite.scenarios`, so a
    suite with many scenarios does not have to load them all to report a
    single number.
    """
    return SuiteRead(
        id=suite.id,
        name=suite.name,
        description=suite.description,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
        scenario_count=scenario_count,
    )


@router.post(
    "",
    response_model=SuiteRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a test suite",
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Name taken"}},
)
def create_suite(payload: SuiteCreate, session: DbSession) -> SuiteRead:
    """Create a suite. Suite names are unique."""
    suite = suite_service.create_suite(session, name=payload.name, description=payload.description)
    # A newly created suite has no scenarios yet.
    return _to_read(suite, scenario_count=0)


@router.get(
    "",
    response_model=Page[SuiteSummary],
    summary="List test suites",
    description="Newest first. Use `limit` and `offset` to page.",
)
def list_suites(session: DbSession, pagination: PaginationParams) -> Page[SuiteSummary]:
    """Return a page of suites."""
    suites, total = suite_service.list_suites(
        session, limit=pagination.limit, offset=pagination.offset
    )
    return Page[SuiteSummary](
        items=[SuiteSummary.model_validate(suite) for suite in suites],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get(
    "/{suite_id}",
    response_model=SuiteRead,
    summary="Retrieve a test suite",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"}},
)
def get_suite(suite_id: uuid.UUID, session: DbSession) -> SuiteRead:
    """Return one suite with its scenario count."""
    suite = suite_service.get_suite(session, suite_id)
    return _to_read(suite, scenario_count=suite_service.count_scenarios(session, suite_id))


@router.patch(
    "/{suite_id}",
    response_model=SuiteRead,
    summary="Update a test suite",
    description=(
        "Updates editable metadata. PATCH rather than PUT because both fields "
        "are optional: a caller may change the name without restating the "
        "description. Send `description: null` to clear it; omitting the key "
        "leaves it untouched. Scenarios are never affected."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Name taken"},
    },
)
def update_suite(suite_id: uuid.UUID, payload: SuiteUpdate, session: DbSession) -> SuiteRead:
    """Update a suite's name and/or description."""
    suite = suite_service.update_suite(
        session,
        suite_id,
        name=payload.name,
        description=payload.description,
        # `model_fields_set` records the keys the client actually sent, which
        # is the only way to tell `description: null` (clear it) from an
        # omitted key (leave it alone).
        clear_description=(
            "description" in payload.model_fields_set and payload.description is None
        ),
    )
    return _to_read(suite, scenario_count=suite_service.count_scenarios(session, suite_id))


@router.delete(
    "/{suite_id}",
    response_model=SuiteDeleteResult,
    summary="Delete a test suite",
    description=(
        "Refuses with 409 when the suite still contains scenarios. The "
        "database-level foreign key cascades, so a bare delete would silently "
        "take every scenario with it - the wrong default for an "
        "unrecoverable operation. Pass `cascade=true` to delete the suite and "
        "its scenarios together, which the response then reports."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"},
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Suite is not empty, or a scenario is referenced by call history",
        },
    },
)
def delete_suite(
    suite_id: uuid.UUID,
    session: DbSession,
    cascade: Annotated[
        bool,
        Query(description="Delete the suite's scenarios along with it."),
    ] = False,
) -> SuiteDeleteResult:
    """Delete a suite, with an explicit opt-in for taking its scenarios."""
    deleted = suite_service.delete_suite(session, suite_id, cascade=cascade)
    return SuiteDeleteResult(suite_id=suite_id, scenarios_deleted=deleted)
