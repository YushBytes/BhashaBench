"""Aggregate router for the v1 API.

Every v1 route module is mounted here, so `main.py` includes exactly one
router per API version and adding an endpoint does not touch application
setup.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    auth,
    caller,
    evaluation,
    health,
    integrations,
    languages,
    scenario_library,
    scenarios,
    speech,
    suites,
    telephony,
    test_runs,
    transcription,
    workspaces,
)

api_router = APIRouter()
api_router.include_router(health.router)
# Phase 14. Authentication; every other private route depends on it.
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(integrations.router)
api_router.include_router(languages.router)
api_router.include_router(suites.router)

# Order matters: the suite-nested router is mounted before the directly
# addressed one purely for readability of the generated OpenAPI document; the
# prefixes do not overlap, so routing is unambiguous either way.
api_router.include_router(scenarios.suite_scenarios_router)
api_router.include_router(scenarios.scenarios_router)
api_router.include_router(scenario_library.router)

# Phase 4. Mounted last because it is the newest surface, not because of any
# routing constraint - `/transcription` overlaps nothing above.
api_router.include_router(transcription.router)

# Phase 5. Likewise: `/speech` overlaps nothing.
api_router.include_router(speech.router)

# Phase 6. The simulated caller, which drives the two above.
api_router.include_router(caller.router)
# Phase 7. The pipeline, which drives all three.
api_router.include_router(test_runs.router)
# Phase 11. Evaluation reads what the pipeline stored. Its run-scoped routes
# sit under `/test-runs/{id}/...` beside the pipeline's; the paths are
# disjoint, so the two routers never compete for a request.
api_router.include_router(evaluation.router)
api_router.include_router(evaluation.run_router)
# Phase 12. Reporting reads runs and their latest evaluations; read-only.
# `/test-runs/{id}/export` is disjoint from every pipeline and evaluation path.
api_router.include_router(analytics.router)
api_router.include_router(analytics.run_router)
# Phase 8. The provider webhook (signature, not session) and a run's calls.
api_router.include_router(telephony.router)
