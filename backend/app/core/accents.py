"""Accent profiles: a second dimension beside language.

A language says what is spoken; an accent says how a particular speaker
sounds - which region or first language shapes their pronunciation. Indian
voice bots fail on accent as often as on language, so a scenario may name
the accent its caller should have (`persona.accent`).

**A profile is a label for a speaker population, not a sound.** Nothing in
this module makes audio sound like anything. An accent is *applied* only
when the audio source that speaks the caller's lines can genuinely produce
it: a speech provider declares the profiles it renders
(`SpeechCapabilities.accents`), and the run records the requested accent,
the applied one (or `None`) and the reason. Today no configured provider
documents an accent for any voice - Gnani Timbre's catalogue gives each
voice a gender and an intended use, nothing regional - so every run
reports the accent as requested and not applied. That is the honest state,
and the run page shows it.

Like `app.core.languages`, this is the single source of truth: the scenario
validator, the language catalogue endpoint and the run evidence all read
it. Add a profile here, with a description that says who it describes;
never add one to make a run look covered.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccentProfile:
    key: str
    """Stable identifier, unique across all languages, e.g. `en-IN.south`."""
    language: str
    """The catalogue language this accent is a variety of."""
    name: str
    description: str


def _p(language: str, slug: str, name: str, description: str) -> AccentProfile:
    return AccentProfile(f"{language}.{slug}", language, name, description)


CATALOGUE: tuple[AccentProfile, ...] = (
    _p(
        "en-IN",
        "south",
        "South Indian English",
        "Indian English of speakers whose first language is Tamil, Telugu, Kannada or Malayalam.",
    ),
    _p(
        "en-IN",
        "north",
        "North Indian English",
        "Indian English of speakers whose first language is Hindi, Punjabi or a related language.",
    ),
    _p(
        "en-IN",
        "east",
        "East Indian English",
        "Indian English of speakers whose first language is Bengali, Odia or Assamese.",
    ),
    _p(
        "en-IN",
        "west",
        "West Indian English",
        "Indian English of speakers whose first language is Marathi or Gujarati.",
    ),
    _p(
        "hi-IN",
        "standard",
        "Standard Hindi",
        "The Khari Boli-based standard heard in broadcast and formal speech.",
    ),
    _p(
        "hi-IN",
        "eastern",
        "Eastern Hindi (Bhojpuri-influenced)",
        "Hindi of speakers from Bihar and eastern Uttar Pradesh, shaped by Bhojpuri or Awadhi.",
    ),
    _p(
        "hi-IN",
        "haryanvi",
        "Haryanvi-influenced Hindi",
        "Hindi of speakers from Haryana and the surrounding region.",
    ),
    _p(
        "hi-IN",
        "mumbai",
        "Mumbai Hindi",
        "The Hindi of Mumbai, with Marathi and Gujarati influence.",
    ),
    _p("ta-IN", "chennai", "Chennai Tamil", "The urban Tamil of Chennai and its surroundings."),
    _p(
        "ta-IN",
        "kongu",
        "Kongu Tamil",
        "Tamil of the western region around Coimbatore, Erode and Tiruppur.",
    ),
    _p("ta-IN", "madurai", "Madurai Tamil", "Tamil of the southern region around Madurai."),
    _p("te-IN", "telangana", "Telangana Telugu", "Telugu of Telangana, including Hyderabad."),
    _p(
        "te-IN",
        "coastal",
        "Coastal Andhra Telugu",
        "Telugu of the coastal districts of Andhra Pradesh.",
    ),
    _p(
        "te-IN",
        "rayalaseema",
        "Rayalaseema Telugu",
        "Telugu of the Rayalaseema region of Andhra Pradesh.",
    ),
    _p(
        "kn-IN",
        "mysuru",
        "Bengaluru-Mysuru Kannada",
        "Kannada of the southern region around Bengaluru and Mysuru.",
    ),
    _p(
        "kn-IN",
        "north",
        "North Karnataka Kannada",
        "Kannada of the northern districts around Dharwad, Hubballi and Belagavi.",
    ),
    _p(
        "ml-IN",
        "south",
        "Southern Malayalam",
        "Malayalam of the southern districts around Thiruvananthapuram.",
    ),
    _p(
        "ml-IN",
        "malabar",
        "Malabar Malayalam",
        "Malayalam of the northern Malabar region around Kozhikode and Kannur.",
    ),
    _p("bn-IN", "kolkata", "Kolkata Bengali", "The Bengali of Kolkata and its surroundings."),
    _p("mr-IN", "pune", "Pune Marathi", "The Marathi of Pune, close to the written standard."),
    _p(
        "mr-IN",
        "vidarbha",
        "Vidarbha Marathi (Varhadi)",
        "Marathi of the Vidarbha region around Nagpur and Amravati.",
    ),
)

BY_KEY: dict[str, AccentProfile] = {profile.key: profile for profile in CATALOGUE}


def for_language(language: str) -> tuple[AccentProfile, ...]:
    return tuple(profile for profile in CATALOGUE if profile.language == language)


class UnknownAccentError(ValueError):
    """Not in the catalogue, or a variety of a different language."""


def validate(key: str, language: str) -> AccentProfile:
    """The profile for `key`, which must be a variety of `language`."""
    profile = BY_KEY.get(key)
    if profile is None:
        known = ", ".join(p.key for p in for_language(language)) or "none yet"
        raise UnknownAccentError(f"unknown accent '{key}'; for {language}: {known}")
    if profile.language != language:
        raise UnknownAccentError(
            f"accent '{key}' is a variety of {profile.language}, not of the scenario's {language}"
        )
    return profile


__all__ = [
    "BY_KEY",
    "CATALOGUE",
    "AccentProfile",
    "UnknownAccentError",
    "for_language",
    "validate",
]
