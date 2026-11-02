"""Request and response models for test suites."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SuiteName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


# PEP 695 type parameter syntax, which the project's Python 3.12 target
# supports and Pydantic resolves the same way as the older `Generic[T]` form.
class Page[T](BaseModel):
    """A page of results plus the metadata needed to request the next one.

    `total` is the unfiltered count, so a client can show "showing 20 of 134"
    and know when to stop paging without requesting an empty page.
    """

    items: list[T] = Field(description="The results on this page.")
    total: int = Field(ge=0, description="Total matching records, across all pages.")
    limit: int = Field(ge=1, description="Maximum items requested per page.")
    offset: int = Field(ge=0, description="Number of items skipped.")


class SuiteCreate(BaseModel):
    """Payload for creating a suite."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "name": "Hindi appointment flows",
                "description": "Appointment booking scenarios in Hindi.",
            }
        },
    )

    name: SuiteName = Field(description="Human-readable suite name. Must be unique.")
    description: str | None = Field(
        default=None, max_length=2000, description="What this suite covers."
    )


class SuiteRead(BaseModel):
    """A suite as returned by the API."""

    # `from_attributes` lets the router hand an ORM object straight to this
    # model; without it the mapping would have to be written out by hand.
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    scenario_count: int = Field(ge=0, description="Number of scenarios in this suite.")


class SuiteSummary(BaseModel):
    """A suite in a list response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class SuiteUpdate(BaseModel):
    """Payload for updating a suite's editable metadata.

    Both fields are optional so a caller can change one without restating the
    other. `description` uses a sentinel rather than plain `None`, because
    `None` cannot distinguish "leave it alone" from "clear it" - and a partial
    update that silently erased a description would be a data-loss bug.
    Send `description: null` to clear it explicitly; the router reads
    `model_fields_set` to tell the two cases apart.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"name": "Hindi appointment flows", "description": "Updated scope."}
        },
    )

    name: SuiteName | None = Field(default=None, description="New name. Must be unique.")
    description: str | None = Field(
        default=None, max_length=2000, description="New description; null clears it."
    )


class SuiteDeleteResult(BaseModel):
    """What a suite deletion removed."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"suite_id": "…", "scenarios_deleted": 3}}
    )

    suite_id: uuid.UUID
    scenarios_deleted: int = Field(
        ge=0, description="Scenarios removed with the suite. Zero unless cascade was used."
    )
