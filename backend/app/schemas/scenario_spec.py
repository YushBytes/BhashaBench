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

from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.core import languages

SPEC_VERSION = 2
"""Revision of this schema. Stored on every persisted scenario.

Bump this when a change to the models below would alter the meaning of an
already-stored document, so old rows can be identified and migrated.

v1 -> v2 (Phase 3) added the optional `tags` and `code_mixing` fields. Both
are optional with defaults, so a stored v1 document still validates against
this schema unchanged - no data migration is needed, and a v1 row keeps its
recorded `spec_version` until it is next written.
"""

# Language validation is delegated to `app.core.languages`, the single source
# of truth. `SUPPORTED_LANGUAGES` is re-exported here so that code importing it
# from this module - as Phases 1 and 2 did - keeps working unchanged.
SUPPORTED_LANGUAGES = languages.SUPPORTED_LANGUAGES

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
# The pattern accepts either case and `to_lower` normalises afterwards.
# Pydantic applies `pattern` to the *raw* input, before `to_lower`, so a
# lowercase-only pattern would reject `Healthcare` instead of accepting and
# folding it - which is the opposite of the intent.
Tag = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]

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


class SwitchTrigger(StrEnum):
    """When the caller is expected to switch language mid-conversation.

    Named triggers rather than free text, so a Phase 6 caller agent can act on
    the value instead of having to interpret prose.
    """

    NUMBERS = "numbers"
    """Digits, amounts and dates - very commonly spoken in English."""
    TECHNICAL_TERMS = "technical_terms"
    """Domain or product vocabulary with no settled local equivalent."""
    PROPER_NOUNS = "proper_nouns"
    """Names of people, places, brands."""
    FRUSTRATION = "frustration"
    """A caller who gives up on the regional language when the bot struggles."""
    CLARIFICATION = "clarification"
    """Repeating a misheard phrase in the other language."""
    THROUGHOUT = "throughout"
    """Habitual mixing with no particular trigger - ordinary urban speech."""


class CodeMixing(SpecModel):
    """How the caller mixes languages within the conversation.

    Indian callers routinely switch language inside a single sentence -
    Hinglish, Tanglish and their regional equivalents are ordinary speech, not
    an edge case. A bot tested only on monolingual input will pass a benchmark
    and still fail a real call.

    The whole block is optional, so every Phase 2 scenario remains valid
    unchanged. When present it records *intent*: which languages appear, how
    often, and what prompts a switch. Nothing here detects language from audio
    - that belongs to the speech phases. This is the authored expectation that
    a caller agent will later perform and an evaluator will later score
    against.
    """

    primary: str | None = Field(
        default=None,
        description="The dominant language. Defaults to the scenario's `language`; "
        "if given it must match it.",
    )
    secondary: list[str] = Field(
        min_length=1,
        max_length=3,
        description="Languages mixed into the primary one, most prominent first. "
        "At least one - a code-mixing block with nothing to mix is meaningless.",
    )
    expected: bool = Field(
        default=True,
        description="Whether mixing is expected. Set false to assert the caller "
        "stays monolingual, which is how a regression in a bot's regional-language "
        "handling gets caught.",
    )
    switch_triggers: list[SwitchTrigger] = Field(
        default_factory=list,
        max_length=6,
        description="What prompts a switch. Empty means unconstrained.",
    )
    secondary_ratio: float | None = Field(
        default=None,
        ge=0.0,
        le=0.9,
        description="Rough share of words expected in the secondary languages. "
        "Capped below 1.0 because at that point the primary language is "
        "mislabelled rather than mixed.",
    )
    sample_utterances: list[ShortText] = Field(
        default_factory=list,
        max_length=10,
        description="Example mixed utterances, e.g. 'Mujhe kal ka appointment "
        "chahiye at 10 AM'. Illustrative for authors and useful as few-shot "
        "material later; not assertions.",
    )

    @field_validator("secondary")
    @classmethod
    def _validate_secondary(cls, value: list[str]) -> list[str]:
        """Every secondary language must be in the catalogue, with no repeats."""
        validated = [languages.validate_tag(tag) for tag in value]
        duplicates = {tag for tag in validated if validated.count(tag) > 1}
        if duplicates:
            raise ValueError(f"duplicate secondary languages: {sorted(duplicates)}")
        return validated

    @field_validator("primary")
    @classmethod
    def _validate_primary(cls, value: str | None) -> str | None:
        """Validate the tag when one is supplied."""
        return None if value is None else languages.validate_tag(value)

    @model_validator(mode="after")
    def _primary_not_in_secondary(self) -> CodeMixing:
        """A language cannot be mixed into itself."""
        if self.primary is not None and self.primary in self.secondary:
            raise ValueError(f"'{self.primary}' is both the primary and a secondary language")
        return self

    @model_validator(mode="after")
    def _ratio_requires_expected_mixing(self) -> CodeMixing:
        """A ratio above zero contradicts `expected: false`."""
        if not self.expected and self.secondary_ratio:
            raise ValueError("secondary_ratio must be 0 or omitted when expected is false")
        return self


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

    # Free-form labels for organising a growing library: a release name, a
    # domain ("healthcare"), a risk level. Kept as a flat list rather than a
    # separate table because they are only ever read with the scenario and
    # filtered on exact match.
    tags: list[Tag] = Field(
        default_factory=list,
        max_length=20,
        description="Lowercase labels for filtering, e.g. ['healthcare', 'smoke'].",
    )

    code_mixing: CodeMixing | None = Field(
        default=None,
        description="How the caller mixes languages. Omit for a monolingual scenario.",
    )

    @field_validator("tags")
    @classmethod
    def _normalise_tags(cls, value: list[str]) -> list[str]:
        """Lowercase, de-duplicate and sort, so filtering is predictable.

        Sorted because two scenarios tagged the same way should serialise
        identically regardless of the order their author typed them in - which
        is what makes export deterministic.
        """
        lowered = sorted({tag.strip().lower() for tag in value})
        return lowered

    @field_validator("known_facts")
    @classmethod
    def _sort_known_facts(cls, value: dict[str, str]) -> dict[str, str]:
        """Order the facts by key, so the canonical form is provenance-free.

        `known_facts` is looked up by name, so its order carries no meaning.
        But PostgreSQL `jsonb` does not preserve insertion order - it stores
        keys sorted by length, then bytewise - so a scenario exported from the
        database came back with its facts in a different order from the file it
        was imported from. Both documents were valid and semantically equal,
        and the diff between them was pure noise.

        Sorting here, at validation, means the canonical serialisation of a
        scenario depends only on the scenario and not on where it was read
        from: a bundle built from files and the same bundle exported from the
        database are byte-identical. That is the whole point of having a
        canonical form.
        """
        return dict(sorted(value.items()))

    @field_validator("language")
    @classmethod
    def _validate_language(cls, value: str) -> str:
        """Require a well-formed tag drawn from the catalogue."""
        return languages.validate_tag(value)

    @model_validator(mode="after")
    def _check_code_mixing_against_primary(self) -> ScenarioSpec:
        """Keep `code_mixing.primary` consistent with the scenario language.

        Two fields naming a primary language could disagree, and a scenario
        whose top-level language says Tamil while its code-mixing block says
        Hindi has no single correct interpretation. Rather than silently
        preferring one, `primary` may be omitted - in which case it defaults to
        the scenario language - but if given it must match.
        """
        mixing = self.code_mixing
        if mixing is not None and mixing.primary is not None and mixing.primary != self.language:
            raise ValueError(
                f"code_mixing.primary ('{mixing.primary}') must match the scenario "
                f"language ('{self.language}'), or be omitted to default to it"
            )
        return self

    @field_validator("expected_outcomes")
    @classmethod
    def _reject_duplicate_outcomes(cls, value: list[str]) -> list[str]:
        """Two identical outcomes would be scored twice and weight the result."""
        lowered = [item.lower() for item in value]
        duplicates = {item for item in lowered if lowered.count(item) > 1}
        if duplicates:
            raise ValueError(f"duplicate expected outcomes: {sorted(duplicates)}")
        return value
