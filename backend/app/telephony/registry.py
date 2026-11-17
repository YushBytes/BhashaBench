"""Which telephony provider a deployment uses: none, or the mock."""

from __future__ import annotations

from app.telephony.base import TelephonyProvider
from app.telephony.mock import MockTelephonyProvider


class TelephonyUnavailableError(Exception):
    pass


_NOT_IMPLEMENTED = {
    "twilio": (
        "no Twilio adapter exists: it needs a paid number and per-minute calls, neither "
        "authorised, and its wire format must be transcribed from Twilio's documentation"
    ),
}


def build_telephony_provider(name: str, *, production: bool) -> TelephonyProvider:
    if name == "":
        raise TelephonyUnavailableError(
            "telephony is not configured (TELEPHONY_PROVIDER is empty); no call can be placed"
        )
    if name == "mock":
        if production:
            raise TelephonyUnavailableError(
                "the mock telephony provider is refused in production: its events are scripted"
            )
        return MockTelephonyProvider()
    raise TelephonyUnavailableError(
        f"TELEPHONY_PROVIDER={name!r} is not available: "
        + _NOT_IMPLEMENTED.get(name, "the only provider is 'mock'")
    )


__all__ = ["TelephonyUnavailableError", "build_telephony_provider"]
