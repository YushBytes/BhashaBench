"""Aggregate router for the v1 API.

Every v1 route module is mounted here, so `main.py` includes exactly one
router per API version and adding an endpoint does not touch application
setup.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    caller,
    health,
    languages,
    scenarios,
    speech,
    suites,
    transcription,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(languages.router)
api_router.include_router(suites.router)

# Order matters: the suite-nested router is mounted before the directly
# addressed one purely for readability of the generated OpenAPI document; the
# prefixes do not overlap, so routing is unambiguous either way.
api_router.include_router(scenarios.suite_scenarios_router)
api_router.include_router(scenarios.scenarios_router)

# Phase 4. Mounted last because it is the newest surface, not because of any
# routing constraint - `/transcription` overlaps nothing above.
api_router.include_router(transcription.router)

# Phase 5. Likewise: `/speech` overlaps nothing.
api_router.include_router(speech.router)

# Phase 6. The simulated caller, which drives the two above.
api_router.include_router(caller.router)
