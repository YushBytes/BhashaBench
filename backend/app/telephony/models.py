"""What a provider reports, in vendor-neutral terms, and what it means.

`ProviderCallStatus` is the neutral vocabulary an adapter maps its vendor's
statuses into. `CALL_STATUS` maps it onto `CallSession.status`; this mapping
is the only route by which `DIALING`, `NO_ANSWER` or `BUSY` can be set, and
it is reached only from a verified provider event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.models.call_session import CallStatus


class ProviderCallStatus(StrEnum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL = frozenset(
    {
        ProviderCallStatus.COMPLETED,
        ProviderCallStatus.BUSY,
        ProviderCallStatus.NO_ANSWER,
        ProviderCallStatus.FAILED,
        ProviderCallStatus.CANCELED,
    }
)

ORDER = {
    ProviderCallStatus.QUEUED: 0,
    ProviderCallStatus.RINGING: 1,
    ProviderCallStatus.IN_PROGRESS: 2,
}
"""Rank of the non-terminal statuses. An event ranking at or below the call's
current status is stale (webhooks arrive out of order) and is ignored; any
terminal event ends the call, and nothing moves a call out of a terminal one."""

CALL_STATUS: dict[ProviderCallStatus, CallStatus] = {
    ProviderCallStatus.QUEUED: CallStatus.DIALING,
    ProviderCallStatus.RINGING: CallStatus.DIALING,
    ProviderCallStatus.IN_PROGRESS: CallStatus.IN_PROGRESS,
    ProviderCallStatus.COMPLETED: CallStatus.COMPLETED,
    ProviderCallStatus.BUSY: CallStatus.BUSY,
    ProviderCallStatus.NO_ANSWER: CallStatus.NO_ANSWER,
    ProviderCallStatus.FAILED: CallStatus.FAILED,
    ProviderCallStatus.CANCELED: CallStatus.FAILED,
}


@dataclass(frozen=True, slots=True)
class PlacedCall:
    provider: str
    provider_call_id: str
    mocked: bool


@dataclass(frozen=True, slots=True)
class CallEvent:
    """One status report from a provider, after its signature was checked."""

    provider: str
    event_id: str
    provider_call_id: str
    status: ProviderCallStatus
    occurred_at: datetime
    duration_seconds: float | None = None


def advances(current: ProviderCallStatus | None, new: ProviderCallStatus) -> bool:
    """Whether `new` moves a call forward from `current`."""
    if current is None:
        return True
    if current in TERMINAL:
        return False
    if new in TERMINAL:
        return True
    return ORDER[new] > ORDER[current]


__all__ = [
    "CALL_STATUS",
    "TERMINAL",
    "CallEvent",
    "PlacedCall",
    "ProviderCallStatus",
    "advances",
]
