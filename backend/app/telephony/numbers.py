"""Telephone numbers in E.164, and only E.164.

A number is `+`, a country code that does not start with 0, and up to 15
digits in all (ITU-T E.164). Spaces, dashes, dots and brackets are removed
before checking, because people paste numbers formatted; anything else -
letters, a missing `+`, a trunk `0` after the country code's place - is
refused rather than repaired, so the allowlist compares one canonical form.
"""

from __future__ import annotations

import re

_E164 = re.compile(r"^\+[1-9]\d{1,14}$")
_PUNCTUATION = re.compile(r"[\s\-.()]")


class InvalidNumberError(ValueError):
    pass


def normalise(raw: str) -> str:
    candidate = _PUNCTUATION.sub("", raw.strip())
    if not _E164.fullmatch(candidate):
        raise InvalidNumberError(
            f"{raw!r} is not an E.164 number: '+', a country code, then at most 15 digits in all"
        )
    return candidate


def masked(number: str) -> str:
    """For logs and evidence: the country code and last two digits only."""
    return number[:3] + "*" * max(len(number) - 5, 0) + number[-2:]


__all__ = ["InvalidNumberError", "masked", "normalise"]
