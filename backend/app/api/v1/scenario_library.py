"""`GET /api/v1/scenario-library`: the scenarios that ship with BhashaBench.

A starting point for authoring: the UI offers them in the scenario editor,
and adding one to a suite is the ordinary validated create in the caller's
own workspace. Read-only, and signed-in only like every non-public route,
although the content is the repository's own.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.access import Authenticated
from app.schemas.scenario_library import LibraryScenarioRead, ScenarioLibraryResponse
from app.services.scenario_library import reference_scenarios

router = APIRouter(prefix="/scenario-library", tags=["scenarios"])


@router.get(
    "",
    response_model=ScenarioLibraryResponse,
    summary="List the reference scenarios that ship with BhashaBench",
    description=(
        "The one-per-language reference survey and the demonstration scenario, "
        "each validated by the same loader as an upload. Adding one to a suite "
        "is `POST /suites/{suite_id}/scenarios` with its `yaml`."
    ),
    dependencies=[Authenticated],
)
def list_reference_scenarios() -> ScenarioLibraryResponse:
    entries = [
        LibraryScenarioRead(
            key=s.key,
            name=s.name,
            language=s.language,
            description=s.description,
            objective=s.objective,
            yaml=s.yaml,
        )
        for s in reference_scenarios()
    ]
    return ScenarioLibraryResponse(scenarios=entries, total=len(entries))
