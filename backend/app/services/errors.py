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
