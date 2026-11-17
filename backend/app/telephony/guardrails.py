"""Limits checked before a call is placed - every one of them, every time.

A call is refused before the provider is contacted when:

- the number is not E.164, or is not on `TELEPHONY_ALLOWED_NUMBERS`
  (an empty allowlist allows nothing);
- the run already has `TELEPHONY_MAX_CALLS_PER_RUN` calls;
- `TELEPHONY_MAX_CONCURRENT_CALLS` calls are already in progress;
- calls today (UTC) already total `TELEPHONY_MAX_MINUTES_PER_DAY` minutes.

The counts are supplied by the caller (the service reads them from the
database), so this module is pure and every refusal is unit-testable. A
refusal names the limit and its value, never the bot's full number.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.telephony.numbers import InvalidNumberError, masked, normalise


class GuardrailError(Exception):
    """A call was refused before dialling."""


@dataclass(frozen=True, slots=True)
class Limits:
    allowed_numbers: frozenset[str]
    max_calls_per_run: int
    max_concurrent_calls: int
    max_minutes_per_day: float


@dataclass(frozen=True, slots=True)
class Usage:
    calls_in_run: int
    calls_in_progress: int
    minutes_today: float


def parse_allowlist(raw: str) -> frozenset[str]:
    """Comma-separated E.164 numbers. One malformed entry fails the whole list."""
    entries = [entry.strip() for entry in raw.split(",") if entry.strip()]
    try:
        return frozenset(normalise(entry) for entry in entries)
    except InvalidNumberError as exc:
        raise ValueError(f"TELEPHONY_ALLOWED_NUMBERS: {exc}") from exc


def check(to_number: str, limits: Limits, usage: Usage) -> str:
    """The normalised number if the call may be placed; `GuardrailError` if not."""
    try:
        number = normalise(to_number)
    except InvalidNumberError as exc:
        raise GuardrailError(str(exc)) from exc
    if number not in limits.allowed_numbers:
        raise GuardrailError(
            f"{masked(number)} is not on TELEPHONY_ALLOWED_NUMBERS; only allow-listed bot "
            "numbers are ever dialled"
        )
    if usage.calls_in_run >= limits.max_calls_per_run:
        raise GuardrailError(
            f"this run already has {usage.calls_in_run} call(s); "
            f"TELEPHONY_MAX_CALLS_PER_RUN is {limits.max_calls_per_run}"
        )
    if usage.calls_in_progress >= limits.max_concurrent_calls:
        raise GuardrailError(
            f"{usage.calls_in_progress} call(s) are in progress; "
            f"TELEPHONY_MAX_CONCURRENT_CALLS is {limits.max_concurrent_calls}"
        )
    if usage.minutes_today >= limits.max_minutes_per_day:
        raise GuardrailError(
            f"calls today total {usage.minutes_today:.1f} minutes; "
            f"TELEPHONY_MAX_MINUTES_PER_DAY is {limits.max_minutes_per_day:g}"
        )
    return number


__all__ = ["GuardrailError", "Limits", "Usage", "check", "parse_allowlist"]
