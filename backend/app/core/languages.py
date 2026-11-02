"""The Indian-language catalogue.

The single source of truth for which languages BhashaBench supports. Schemas,
services, routers and the CLI all resolve language questions here, so a tag can
never be accepted in one layer and rejected in another.

Phase 1 and 2 kept a bare `frozenset` of tags inside
`app.schemas.scenario_spec`. That was enough to validate, but it carried no
display name or locale and could not answer "what can I author in?". This
module replaces it; `scenario_spec` re-exports `SUPPORTED_LANGUAGES` from here
so existing imports keep working.

**Scope honesty.** Listing a language here means a scenario may be *authored*
and *validated* in it. It does not mean speech recognition or synthesis exists
for it - no provider is integrated until Phases 4-5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# BCP 47, restricted to the `language` or `language-REGION` shapes this project
# uses. Deliberately not the full RFC 5646 grammar: accepting extensions and
# private-use subtags that cannot be routed to a speech provider would be
# accepting input we cannot honour.
LANGUAGE_TAG_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


@dataclass(frozen=True, slots=True)
class Language:
    """One supported language."""

    code: str
    """Canonical BCP 47 tag, e.g. `hi-IN`. This is what a scenario stores."""
    name: str
    """English display name, e.g. `Hindi`."""
    endonym: str
    """The language's name in its own script, for UI that shows a native label."""
    script: str
    """ISO 15924 script code, e.g. `Deva`. Useful when rendering or
    normalising text, and for telling `ur-IN` (Arab) from `hi-IN` (Deva)."""
    locale: str
    """Underscore locale form, e.g. `hi_IN`. Some providers and ICU-based
    libraries expect this spelling rather than the hyphenated tag."""


# Ordered by number of speakers in India, which makes the `languages` command
# and the API listing read sensibly rather than alphabetically.
CATALOGUE: tuple[Language, ...] = (
    Language("hi-IN", "Hindi", "हिन्दी", "Deva", "hi_IN"),
    Language("bn-IN", "Bengali", "বাংলা", "Beng", "bn_IN"),
    Language("mr-IN", "Marathi", "मराठी", "Deva", "mr_IN"),
    Language("te-IN", "Telugu", "తెలుగు", "Telu", "te_IN"),
    Language("ta-IN", "Tamil", "தமிழ்", "Taml", "ta_IN"),
    Language("gu-IN", "Gujarati", "ગુજરાતી", "Gujr", "gu_IN"),
    Language("ur-IN", "Urdu", "اردو", "Arab", "ur_IN"),
    Language("kn-IN", "Kannada", "ಕನ್ನಡ", "Knda", "kn_IN"),
    Language("or-IN", "Odia", "ଓଡ଼ିଆ", "Orya", "or_IN"),
    Language("ml-IN", "Malayalam", "മലയാളം", "Mlym", "ml_IN"),
    Language("pa-IN", "Punjabi", "ਪੰਜਾਬੀ", "Guru", "pa_IN"),
    Language("as-IN", "Assamese", "অসমীয়া", "Beng", "as_IN"),
    Language("en-IN", "Indian English", "Indian English", "Latn", "en_IN"),
)

BY_CODE: dict[str, Language] = {language.code: language for language in CATALOGUE}

SUPPORTED_LANGUAGES: frozenset[str] = frozenset(BY_CODE)
"""Every supported tag. Re-exported by `app.schemas.scenario_spec`."""

SUPPORTED_CODES: tuple[str, ...] = tuple(language.code for language in CATALOGUE)
"""Supported tags in catalogue order, for stable listings and error messages."""


class UnsupportedLanguageError(ValueError):
    """A language tag is well-formed but not in the catalogue, or malformed.

    A `ValueError` subclass so Pydantic field validators can raise it directly
    and have it surface as a normal validation error.
    """


def is_supported(code: str) -> bool:
    """Return whether a tag is in the catalogue."""
    return code in BY_CODE


def get(code: str) -> Language:
    """Return the catalogue entry for a tag.

    Raises `UnsupportedLanguageError` with the supported list in the message,
    so an author learns the options instead of guessing.
    """
    language = BY_CODE.get(code)
    if language is None:
        raise UnsupportedLanguageError(
            f"'{code}' is not a supported language; supported tags are {list(SUPPORTED_CODES)}"
        )
    return language


def validate_tag(code: str) -> str:
    """Validate and normalise a language tag, returning it unchanged.

    Checks shape before membership so a malformed tag gets a message about its
    *form* rather than a list it could never have matched.
    """
    tag = code.strip()
    if not LANGUAGE_TAG_PATTERN.match(tag):
        raise UnsupportedLanguageError(
            f"'{tag}' is not a well-formed language tag; expected a form like 'hi-IN' or 'hi'"
        )
    get(tag)
    return tag


__all__ = [
    "BY_CODE",
    "CATALOGUE",
    "LANGUAGE_TAG_PATTERN",
    "SUPPORTED_CODES",
    "SUPPORTED_LANGUAGES",
    "Language",
    "UnsupportedLanguageError",
    "get",
    "is_supported",
    "validate_tag",
]
