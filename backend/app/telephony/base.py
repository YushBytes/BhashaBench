"""The contract a telephony provider adapter meets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.telephony.models import CallEvent, PlacedCall


@dataclass(frozen=True, slots=True)
class TelephonyCapabilities:
    name: str
    mocked: bool
    """True when no telephone network is involved. Recorded on every call."""
    places_real_calls: bool
    streams_media: bool


class TelephonyProvider(Protocol):
    @property
    def capabilities(self) -> TelephonyCapabilities: ...

    def place_call(self, *, to_number: str, call_reference: str) -> PlacedCall:
        """Ask the provider to dial. Called only after every guardrail passed."""
        ...

    def hang_up(self, provider_call_id: str) -> None: ...

    def parse_event(self, body: bytes) -> CallEvent:
        """Decode a webhook body whose signature has already been verified."""
        ...


__all__ = ["TelephonyCapabilities", "TelephonyProvider"]
