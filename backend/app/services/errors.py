"""Domain errors raised by the service layer.

Services raise these instead of `HTTPException`, so that service code stays
usable outside a request (a CLI, a scheduled job, a test) and so the mapping
from domain failure to HTTP status lives in exactly one place - the exception
handlers in `app.main`.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected, caller-visible failures."""


class NotFoundError(DomainError):
    """A referenced resource does not exist."""

    def __init__(self, resource: str, identifier: object) -> None:
        super().__init__(f"{resource} '{identifier}' does not exist")
        self.resource = resource
        self.identifier = identifier


class ConflictError(DomainError):
    """The request conflicts with existing state, e.g. a duplicate name."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class SuiteNotEmptyError(ConflictError):
    """A suite still holds scenarios and was not asked to take them with it.

    Carries the name and the count as fields rather than only inside a
    message, because the remedy is spelled differently in each front end -
    `?cascade=true` over HTTP, `--cascade` on the command line. A single
    prescriptive message would be wrong in one of them, and telling a CLI user
    to pass `cascade=true` sends them looking for a flag that does not exist.
    """

    def __init__(self, suite_name: str, scenario_count: int, remedy: str) -> None:
        super().__init__(
            f"suite '{suite_name}' still contains {scenario_count} scenario(s). "
            f"Delete them first, or {remedy} to delete the suite and its "
            "scenarios together."
        )
        self.suite_name = suite_name
        self.scenario_count = scenario_count
