"""Aggregate router for the v1 API.

Every v1 route module is mounted here, so `main.py` includes exactly one
router per API version and adding an endpoint does not touch application
setup.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
