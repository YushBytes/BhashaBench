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


def _to_read(suite: TestSuite) -> SuiteRead:
    """Shape a suite for a detail response.

    `scenario_count` is taken from the eagerly loaded relationship, so this
    costs no extra query.
    """
    return SuiteRead(
        id=suite.id,
        name=suite.name,
        description=suite.description,
        created_at=suite.created_at,
        updated_at=suite.updated_at,
        scenario_count=len(suite.scenarios),
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
    return _to_read(suite)


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
    return _to_read(suite_service.get_suite(session, suite_id))
