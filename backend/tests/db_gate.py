"""Whether an unreachable test database is a skip or a failure.

On a developer machine without PostgreSQL, the database-backed tests skip -
loudly, with the host and port in the reason - so the rest of the suite stays
usable. In CI that same behaviour would be a trap: a misconfigured service
turns several hundred tests into skips and the run still shows green.

`BHASHABENCH_REQUIRE_DATABASE` closes the trap. When it is set to a true
value, an unreachable database fails the session instead of skipping it. CI
sets it; nothing else needs to.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import NoReturn

import pytest

REQUIRE_ENV = "BHASHABENCH_REQUIRE_DATABASE"

_TRUE = frozenset({"1", "true", "yes", "on"})


def database_required(environ: Mapping[str, str] = os.environ) -> bool:
    """True when the environment demands a reachable test database."""
    return environ.get(REQUIRE_ENV, "").strip().casefold() in _TRUE


def database_unreachable(reason: str, *, required: bool) -> NoReturn:
    """Skip, or fail when the database is required. Never returns."""
    if required:
        pytest.fail(
            f"{reason} {REQUIRE_ENV} is set, so this is a failure, not a skip.",
            pytrace=False,
        )
    pytest.skip(reason, allow_module_level=True)
