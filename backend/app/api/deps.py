"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Injected application settings.

Declared as a dependency rather than imported directly in handlers so that
tests can override it with `app.dependency_overrides`.
"""
