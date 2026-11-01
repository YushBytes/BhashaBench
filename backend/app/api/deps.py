"""Shared FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db

SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Injected application settings.

Declared as a dependency rather than imported directly in handlers so that
tests can override it with `app.dependency_overrides`.
"""

DbSession = Annotated[Session, Depends(get_db)]
"""Injected request-scoped database session.

The underlying dependency rolls back and closes in a `finally`, so a handler
that raises cannot leak a connection or leave a transaction open. Tests
override `get_db` to bind a session to their own transaction.
"""


@dataclass(frozen=True, slots=True)
class Pagination:
    """Validated page window."""

    limit: int
    offset: int


def pagination_params(
    limit: Annotated[
        int,
        Query(
            ge=1,
            # Capped so a client cannot ask for the whole table in one request
            # and turn a list endpoint into an accidental denial of service.
            le=100,
            description="Maximum items to return.",
        ),
    ] = 20,
    offset: Annotated[int, Query(ge=0, description="Items to skip.")] = 0,
) -> Pagination:
    """Parse and validate `limit`/`offset` query parameters."""
    return Pagination(limit=limit, offset=offset)


PaginationParams = Annotated[Pagination, Depends(pagination_params)]
"""Injected pagination window, shared by every list endpoint."""
