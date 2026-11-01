"""Time helpers.

Centralised so that every timestamp the API emits is timezone-aware UTC, and
so that tests have a single place to patch the clock.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def monotonic_seconds() -> float:
    """Return a monotonic clock reading, safe for measuring elapsed time."""
    return time.monotonic()
