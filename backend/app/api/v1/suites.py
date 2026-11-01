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

from fastapi import APIRouter, status

from app.api.deps import DbSession, PaginationParams
from app.models.suite import TestSuite
from app.schemas.common import ErrorResponse
from app.schemas.suite import Page, SuiteCreate, SuiteRead, SuiteSummary
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
