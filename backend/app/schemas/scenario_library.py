"""Responses of `GET /api/v1/scenario-library`."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LibraryScenarioRead(BaseModel):
    key: str = Field(description="Path under scenarios/ without .yaml.")
    name: str
    language: str = Field(description="BhashaBench language tag.")
    description: str | None
    objective: str
    yaml: str = Field(description="The file as shipped, comments included.")


class ScenarioLibraryResponse(BaseModel):
    scenarios: list[LibraryScenarioRead]
    total: int
