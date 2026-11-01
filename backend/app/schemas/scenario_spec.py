"""The scenario specification: the validated schema behind every YAML file.

This module is the authority on what a scenario may contain. It is pure
Pydantic with no I/O, no YAML and no database awareness, so it can be reasoned
about and tested on its own.

Design rules applied throughout:

* **`extra="forbid"` everywhere.** A typo such as `persoan:` must be a loud
  error, not a silently ignored key that makes a scenario behave differently
  from what its author wrote.
* **Every number is range-checked.** An SNR of 10000 dB or a negative turn
  budget is a mistake worth catching at authoring time rather than hours into
  a benchmark run.
* **No speculative fields.** Everything here is referenced by the roadmap's
  named phases. Fields a later phase will need but cannot yet specify are
  absent rather than guessed at.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SPEC_VERSION = 1
"""Revision of this schema. Stored on every persisted scenario.

Bump this when a change to the models below would alter the meaning of an
already-stored document, so old rows can be identified and migrated.
"""

# BCP 47, restricted to the `language` or `language-REGION` shapes this project
# actually uses (`hi`, `hi-IN`, `en-IN`). Deliberately not the full RFC 5646
# grammar: accepting extensions and private-use subtags we cannot route to a
# speech provider would be accepting input we cannot honour.
_LANGUAGE_TAG = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")

# Languages the platform targets. A tag outside this set is rejected with the
# list in the message, so an author learns what is available rather than
# discovering mid-run that nothing supports their choice.
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {
        "hi-IN",  # Hindi
        "ta-IN",  # Tamil
        "te-IN",  # Telugu
        "kn-IN",  # Kannada
        "ml-IN",  # Malayalam
        "mr-IN",  # Marathi
        "bn-IN",  # Bengali
        "gu-IN",  # Gujarati
        "pa-IN",  # Punjabi
        "or-IN",  # Odia
        "as-IN",  # Assamese
        "ur-IN",  # Urdu
        "en-IN",  # Indian English
    }
)

# A short machine-friendly identifier: lowercase, digits, underscore, hyphen.
ScenarioName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=200,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    ),
]

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
FactKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$"
    ),
]


class SpecModel(BaseModel):
    """Base for every specification model: strict, immutable, trimmed."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class SpeakingStyle(StrEnum):
    """How the simulated caller speaks."""

    POLITE = "polite"
    NEUTRAL = "neutral"
    BRUSQUE = "brusque"
    CONFUSED = "confused"
    HURRIED = "hurried"
    ELDERLY = "elderly"


class NoiseProfile(StrEnum):
    """Named acoustic environment.

    Phase 7 implements these. Naming them here lets a scenario author declare
    intent now; until then the value is recorded and not acted upon.
    """

    CLEAN = "clean"
    URBAN = "urban"
    RURAL = "rural"
    MARKET = "market"
    INDOOR_FAN = "indoor_fan"
    WORST_CASE = "worst_case"


class Persona(SpecModel):
    """Who the simulated caller is."""

    identity: ShortText = Field(description="Who the caller is, e.g. 'Working professional'.")
    speaking_style: SpeakingStyle = Field(
        default=SpeakingStyle.NEUTRAL, description="How the caller speaks."
    )
    traits: list[ShortText] = Field(
        default_factory=list,
        max_length=10,
        description="Behavioural traits, e.g. 'impatient'. Capped to keep personas coherent.",
    )

    @field_validator("traits")
    @classmethod
    def _reject_duplicate_traits(cls, value: list[str]) -> list[str]:
        """A repeated trait is a copy-paste error, not emphasis."""
        lowered = [item.lower() for item in value]
        duplicates = {item for item in lowered if lowered.count(item) > 1}
        if duplicates:
            raise ValueError(f"duplicate traits: {sorted(duplicates)}")
        return value


class Goal(SpecModel):
    """What the caller is trying to achieve."""

    objective: LongText = Field(description="The caller's aim, in one or two sentences.")
    # A call that never ends costs money and blocks the run. The cap is part of
    # the scenario so a complex negotiation can be given more room explicitly.
    max_turns: int = Field(
        default=20, ge=1, le=100, description="Hard limit on conversation turns."
    )


class AudioConfig(SpecModel):
    """Acoustic conditions to simulate."""

    noise_profile: NoiseProfile = Field(
        default=NoiseProfile.CLEAN, description="Named acoustic environment."
    )
    # 40 dB is effectively studio-clean; 0 dB means noise as loud as speech.
    # Below 0 the speech is quieter than the noise, which no real deployment
    # would consider a fair test. The bounds also reject YAML's `.nan` and
    # `.inf`, since neither compares inside a range.
    snr_db: float = Field(
        default=30.0,
        ge=0.0,
        le=40.0,
        description="Signal-to-noise ratio in dB. Higher is cleaner.",
    )
    packet_loss_percent: float = Field(
        default=0.0, ge=0.0, le=30.0, description="Simulated packet loss, percent."
    )


class ConversationConstraints(SpecModel):
    """Optional limits on how the conversation may proceed."""

    max_silence_seconds: float = Field(
        default=5.0, gt=0.0, le=60.0, description="Silence before the caller re-prompts."
    )
    allow_interruptions: bool = Field(
        default=True, description="Whether the caller may talk over the bot."
    )
    required_phrases: list[ShortText] = Field(
        default_factory=list,
        max_length=20,
        description="Phrases the caller must say at some point.",
    )
    forbidden_phrases: list[ShortText] = Field(
        default_factory=list,
        max_length=20,
        description="Phrases the caller must never say.",
    )


class ScenarioSpec(SpecModel):
    """A complete, validated scenario definition.

    This is what a YAML file deserialises into, and what is stored as the
    `scenarios.spec` JSONB document.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "name": "appointment_booking",
                "description": "Test whether a voice bot can book a doctor appointment.",
                "language": "hi-IN",
                "persona": {
                    "identity": "Working professional",
                    "speaking_style": "polite",
                    "traits": ["impatient", "prefers short responses"],
                },
                "goal": {"objective": "Book an appointment for tomorrow.", "max_turns": 15},
                "known_facts": {"patient_name": "Rahul", "preferred_time": "10 AM"},
                "expected_outcomes": [
                    "Confirm appointment date",
                    "Confirm appointment time",
                    "Confirm patient name",
                ],
                "audio": {"noise_profile": "clean", "snr_db": 30},
            }
        },
    )

    name: ScenarioName = Field(description="Machine-friendly identifier, unique within its suite.")
    description: LongText | None = Field(default=None, description="What this scenario tests.")
    language: str = Field(description="BCP 47 tag, e.g. 'hi-IN'.")

    persona: Persona = Field(description="Who the simulated caller is.")
    goal: Goal = Field(description="What the caller is trying to achieve.")

    # Facts the caller knows and may volunteer when asked. Values must be
    # strings, and non-strings are rejected rather than coerced: these values
    # get spoken aloud, and YAML's implicit typing would otherwise read
    # `account: 0123` as the integer 123 and lose the leading zero. Requiring
    # the author to quote such a value keeps it exactly as written.
    known_facts: dict[FactKey, ShortText] = Field(
        default_factory=dict,
        max_length=50,
        description="Facts the caller can supply, e.g. patient_name: Rahul.",
    )

    expected_outcomes: list[ShortText] = Field(
        min_length=1,
        max_length=20,
        description="What the bot must achieve. At least one is required - a "
        "scenario with nothing to check cannot pass or fail.",
    )

    audio: AudioConfig = Field(
        default_factory=AudioConfig, description="Acoustic conditions to simulate."
    )
    constraints: ConversationConstraints | None = Field(
        default=None, description="Optional conversation limits."
    )

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        """Require a well-formed tag drawn from the supported set."""
        tag = value.strip()
        if not _LANGUAGE_TAG.match(tag):
            raise ValueError(
                f"'{tag}' is not a well-formed language tag; expected a form like 'hi-IN' or 'hi'"
            )
        if tag not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"'{tag}' is not a supported language; supported tags are "
                f"{sorted(SUPPORTED_LANGUAGES)}"
            )
        return tag

    @field_validator("expected_outcomes")
    @classmethod
    def _reject_duplicate_outcomes(cls, value: list[str]) -> list[str]:
        """Two identical outcomes would be scored twice and weight the result."""
        lowered = [item.lower() for item in value]
        duplicates = {item for item in lowered if lowered.count(item) > 1}
        if duplicates:
            raise ValueError(f"duplicate expected outcomes: {sorted(duplicates)}")
        return value
