"""Tests for the repository's own tooling configuration.

Not application behaviour, but the thing that decides whether a failure is
seen at all. The suite runs in two places - on the host from the repository
root, and in the Docker container from `backend/` - and those runs read
different configuration files. If they enforce different things, the second
run stops being corroboration and becomes decoration.
"""

from __future__ import annotations

import configparser
import tomllib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PYTEST_INI = BACKEND_ROOT / "pytest.ini"
PYPROJECT = BACKEND_ROOT.parent / "pyproject.toml"

# The two path settings are legitimately different: they are relative to
# different rootdirs. Everything else must agree.
PATH_SETTINGS = frozenset({"testpaths", "pythonpath"})


def _ini_list(raw: str) -> list[str]:
    """Parse an ini value that pytest reads as a line- or space-separated list."""
    return raw.split()


@pytest.fixture(scope="module")
def container_config() -> dict[str, str]:
    """`backend/pytest.ini`, used when rootdir is `backend/` (the container)."""
    parser = configparser.ConfigParser()
    parser.read(PYTEST_INI, encoding="utf-8")
    return dict(parser["pytest"])


@pytest.fixture(scope="module")
def host_config() -> dict[str, object]:
    """`[tool.pytest.ini_options]`, used when rootdir is the repository root."""
    if not PYPROJECT.is_file():  # pragma: no cover
        # Both the host and the container do have it - docker-compose mounts
        # it read-only for exactly this comparison. This guard is for a run
        # from somewhere that does not, where skipping with a reason beats a
        # confusing FileNotFoundError.
        pytest.skip(
            f"{PYPROJECT} is not present, so the host configuration cannot "
            "be compared against this one"
        )
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["tool"]["pytest"]["ini_options"]


class TestContainerPytestConfig:
    """`backend/pytest.ini` must exist and enforce the strict settings."""

    def test_the_file_exists(self) -> None:
        """Its absence is what made the in-container run permissive."""
        assert PYTEST_INI.is_file()

    def test_warnings_are_errors(self, container_config: dict[str, str]) -> None:
        assert _ini_list(container_config["filterwarnings"]) == ["error"]

    def test_collection_is_limited_to_the_test_package(
        self, container_config: dict[str, str]
    ) -> None:
        """Otherwise `app/models/test_run.py` is collected as a test module."""
        assert _ini_list(container_config["testpaths"]) == ["tests"]

    @pytest.mark.parametrize("option", ["--strict-markers", "--strict-config"])
    def test_strict_options_are_present(
        self, container_config: dict[str, str], option: str
    ) -> None:
        assert option in _ini_list(container_config["addopts"])


class TestTheTwoConfigurationsAgree:
    """Drift between them is the failure mode this module exists to catch."""

    def test_the_same_settings_are_configured(
        self, container_config: dict[str, str], host_config: dict[str, object]
    ) -> None:
        assert set(container_config) == set(host_config)

    def test_every_non_path_setting_matches(
        self, container_config: dict[str, str], host_config: dict[str, object]
    ) -> None:
        for key, host_value in host_config.items():
            if key in PATH_SETTINGS:
                continue
            expected = host_value if isinstance(host_value, list) else [str(host_value)]
            assert _ini_list(container_config[key]) == expected, key

    def test_the_path_settings_differ_as_intended(
        self, container_config: dict[str, str], host_config: dict[str, object]
    ) -> None:
        """A guard against "fixing" the comparison by copying the host's paths.

        `testpaths = backend/tests` under a `backend/` rootdir resolves to
        `backend/backend/tests` and collects nothing.
        """
        assert _ini_list(container_config["testpaths"]) == ["tests"]
        assert host_config["testpaths"] == ["backend/tests"]
