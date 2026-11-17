"""A telephony provider with no telephone network behind it.

It dials nothing. `place_call` returns an id; `script` produces the event
bodies a provider would send for one of four outcomes - answered, busy, no
answer, failed - which a test or a demo signs and posts to the webhook
receiver like any provider's events. Every call it produces is `mocked`, and
that flag travels into every record, so a mocked call can never be mistaken
for a telephone test.

Refused when `APP_ENV=production` (see the registry): its events are
scripted, and publishing them as call results is exactly what must not
happen.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Literal

from app.telephony.base import TelephonyCapabilities
from app.telephony.models import CallEvent, PlacedCall, ProviderCallStatus

Outcome = Literal["answered", "busy", "no_answer", "failed"]

_SCRIPTS: dict[str, list[ProviderCallStatus]] = {
    "answered": [
        ProviderCallStatus.QUEUED,
        ProviderCallStatus.RINGING,
        ProviderCallStatus.IN_PROGRESS,
        ProviderCallStatus.COMPLETED,
    ],
    "busy": [ProviderCallStatus.QUEUED, ProviderCallStatus.BUSY],
    "no_answer": [
        ProviderCallStatus.QUEUED,
        ProviderCallStatus.RINGING,
        ProviderCallStatus.NO_ANSWER,
    ],
    "failed": [ProviderCallStatus.QUEUED, ProviderCallStatus.FAILED],
}


class MockEventError(ValueError):
    pass


class MockTelephonyProvider:
    def __init__(self) -> None:
        self.placed: list[tuple[str, str]] = []
        self.hung_up: list[str] = []

    @property
    def capabilities(self) -> TelephonyCapabilities:
        return TelephonyCapabilities(
            name="mock", mocked=True, places_real_calls=False, streams_media=False
        )

    def place_call(self, *, to_number: str, call_reference: str) -> PlacedCall:
        provider_call_id = f"mock-{uuid.uuid4().hex}"
        self.placed.append((to_number, call_reference))
        return PlacedCall(provider="mock", provider_call_id=provider_call_id, mocked=True)

    def hang_up(self, provider_call_id: str) -> None:
        self.hung_up.append(provider_call_id)

    def script(
        self,
        provider_call_id: str,
        outcome: Outcome,
        *,
        start: datetime,
        talk_seconds: float = 30.0,
    ) -> list[bytes]:
        """The event bodies for one outcome, in order, one second apart."""
        bodies = []
        for offset, status in enumerate(_SCRIPTS[outcome]):
            duration = talk_seconds if status is ProviderCallStatus.COMPLETED else None
            at = start + timedelta(seconds=offset + (talk_seconds if duration else 0))
            bodies.append(
                json.dumps(
                    {
                        "event_id": f"evt-{uuid.uuid4().hex}",
                        "call_id": provider_call_id,
                        "status": status.value,
                        "occurred_at": at.isoformat(),
                        "duration_seconds": duration,
                        "mocked": True,
                    },
                    separators=(",", ":"),
                ).encode()
            )
        return bodies

    def parse_event(self, body: bytes) -> CallEvent:
        try:
            data = json.loads(body)
            event = CallEvent(
                provider="mock",
                event_id=str(data["event_id"]),
                provider_call_id=str(data["call_id"]),
                status=ProviderCallStatus(data["status"]),
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
                duration_seconds=(
                    None
                    if data.get("duration_seconds") is None
                    else float(data["duration_seconds"])
                ),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise MockEventError(f"the event body is not a valid mock event: {exc}") from exc
        if event.occurred_at.tzinfo is None:
            raise MockEventError("the event time must carry a timezone")
        if event.duration_seconds is not None and event.duration_seconds < 0:
            raise MockEventError("a duration cannot be negative")
        return event


__all__ = ["MockEventError", "MockTelephonyProvider", "Outcome"]
