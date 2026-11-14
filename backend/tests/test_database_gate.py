"""The database gate: skip locally, fail in CI.

The end-to-end cases run a real pytest subprocess against a closed port, so
they prove the behaviour CI depends on - a non-zero exit when the database is
required and unreachable - rather than only the helper's logic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.db_gate import REQUIRE_ENV, database_required, database_unreachable

REPO_ROOT = Path(__file__).resolve().parents[2]

# A port nothing listens on: connection refused immediately, no timeout wait.
UNREACHABLE_URL = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"


class TestDatabaseRequired:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
    def test_true_values_require_the_database(self, value: str) -> None:
        assert database_required({REQUIRE_ENV: value}) is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
    def test_anything_else_does_not(self, value: str) -> None:
        assert database_required({REQUIRE_ENV: value}) is False

    def test_unset_does_not(self) -> None:
        assert database_required({}) is False


class TestDatabaseUnreachable:
    def test_skips_when_not_required(self) -> None:
        with pytest.raises(pytest.skip.Exception, match="no database here"):
            database_unreachable("no database here.", required=False)

    def test_fails_when_required(self) -> None:
        with pytest.raises(pytest.fail.Exception, match="failure, not a skip"):
            database_unreachable("no database here.", required=True)


def _run_database_tests(*, require: bool) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "BHASHABENCH_TEST_DATABASE_URL": UNREACHABLE_URL}
    env.pop(REQUIRE_ENV, None)
    if require:
        env[REQUIRE_ENV] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "backend/tests/test_database.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "-x",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.mark.skipif(
    not (REPO_ROOT / "backend" / "tests" / "test_database.py").is_file(),
    reason="repository layout not present (e.g. inside the backend-only container)",
)
class TestEndToEnd:
    def test_unreachable_database_skips_by_default(self) -> None:
        result = _run_database_tests(require=False)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "skipped" in result.stdout

    def test_unreachable_database_fails_when_required(self) -> None:
        result = _run_database_tests(require=True)

        assert result.returncode != 0
        assert "failure, not a skip" in result.stdout + result.stderr
