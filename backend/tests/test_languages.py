"""Tests for the language catalogue and the code-mixing / tag metadata.

No database: the catalogue is a module constant and the spec is pure Pydantic.
"""

from __future__ import annotations

import pytest

from app.core import languages
from app.schemas.scenario_spec import (
    CodeMixing,
    ScenarioSpec,
    SwitchTrigger,
)
from app.services.scenario_loader import (
    ScenarioValidationError,
    spec_from_yaml,
    spec_to_yaml,
)

# The 13 codes Phase 3 is required to support.
REQUIRED_CODES = (
    "hi-IN",
    "ta-IN",
    "te-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "bn-IN",
    "gu-IN",
    "pa-IN",
    "or-IN",
    "as-IN",
    "ur-IN",
    "en-IN",
)

BASE_YAML = """\
name: base
language: hi-IN
persona:
  identity: Caller
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
"""


def _error_fields(exc: ScenarioValidationError) -> set[str]:
    return {error.field for error in exc.errors}


class TestCatalogue:
    """The catalogue must cover exactly the required languages."""

    def test_contains_every_required_code(self) -> None:
        assert set(REQUIRED_CODES) <= languages.SUPPORTED_LANGUAGES

    def test_contains_no_extra_codes(self) -> None:
        """Claiming support for a language we have not listed would be a lie."""
        assert set(REQUIRED_CODES) == languages.SUPPORTED_LANGUAGES

    def test_has_thirteen_entries(self) -> None:
        assert len(languages.CATALOGUE) == 13

    @pytest.mark.parametrize("code", REQUIRED_CODES)
    def test_every_entry_is_fully_populated(self, code: str) -> None:
        """A half-filled entry would render as a blank label in a picker."""
        language = languages.get(code)

        assert language.code == code
        assert language.name
        assert language.endonym
        assert len(language.script) == 4
        assert language.locale == code.replace("-", "_")

    def test_codes_are_unique(self) -> None:
        codes = [language.code for language in languages.CATALOGUE]

        assert len(codes) == len(set(codes))

    def test_display_names_are_unique(self) -> None:
        """Two languages sharing a label would be indistinguishable in a UI."""
        names = [language.name for language in languages.CATALOGUE]

        assert len(names) == len(set(names))

    def test_supported_codes_matches_catalogue_order(self) -> None:
        """Order is part of the contract: listings must be stable."""
        assert tuple(language.code for language in languages.CATALOGUE) == languages.SUPPORTED_CODES

    def test_urdu_and_hindi_have_different_scripts(self) -> None:
        """A real distinction the catalogue exists to record."""
        assert languages.get("ur-IN").script == "Arab"
        assert languages.get("hi-IN").script == "Deva"


class TestLanguageValidation:
    """`validate_tag` is the one gate every layer goes through."""

    @pytest.mark.parametrize("code", REQUIRED_CODES)
    def test_accepts_supported_tags(self, code: str) -> None:
        assert languages.validate_tag(code) == code

    def test_strips_surrounding_whitespace(self) -> None:
        assert languages.validate_tag("  hi-IN  ") == "hi-IN"

    @pytest.mark.parametrize("code", ["english", "HI-in", "hi_IN", "h", "123", "hi-IND"])
    def test_rejects_malformed_tags(self, code: str) -> None:
        """A malformed tag gets a message about its *form*."""
        with pytest.raises(languages.UnsupportedLanguageError, match="well-formed"):
            languages.validate_tag(code)

    @pytest.mark.parametrize("code", ["fr-FR", "de-DE", "ja-JP", "zh-CN", "en-US"])
    def test_rejects_well_formed_but_unsupported_tags(self, code: str) -> None:
        """A well-formed tag gets the supported list, not a grammar lecture."""
        with pytest.raises(languages.UnsupportedLanguageError, match="not a supported"):
            languages.validate_tag(code)

    def test_error_lists_the_supported_codes(self) -> None:
        """So an author learns the options instead of guessing."""
        with pytest.raises(languages.UnsupportedLanguageError) as exc_info:
            languages.validate_tag("fr-FR")

        message = str(exc_info.value)
        assert "hi-IN" in message
        assert "ta-IN" in message

    def test_is_supported_matches_get(self) -> None:
        assert languages.is_supported("hi-IN")
        assert not languages.is_supported("fr-FR")

    def test_unsupported_error_is_a_value_error(self) -> None:
        """So Pydantic field validators can raise it directly."""
        assert issubclass(languages.UnsupportedLanguageError, ValueError)


class TestCatalogueIsTheSingleSource:
    """The schema must not keep its own copy of the language list."""

    def test_scenario_spec_reexports_the_catalogue(self) -> None:
        from app.schemas import scenario_spec

        assert scenario_spec.SUPPORTED_LANGUAGES is languages.SUPPORTED_LANGUAGES

    def test_scenario_validation_uses_the_catalogue(self) -> None:
        """A tag the catalogue rejects must be rejected by the scenario too."""
        with pytest.raises(ScenarioValidationError, match="not a supported language"):
            spec_from_yaml(BASE_YAML.replace("language: hi-IN", "language: fr-FR"))


class TestTags:
    """Tags organise a growing library and must normalise predictably."""

    def test_absent_by_default(self) -> None:
        assert spec_from_yaml(BASE_YAML).tags == []

    def test_lowercased_deduplicated_and_sorted(self) -> None:
        """Deterministic order is what makes export byte-stable."""
        spec = spec_from_yaml(BASE_YAML + "tags:\n  - Zebra\n  - alpha\n  - ALPHA\n")

        assert spec.tags == ["alpha", "zebra"]

    def test_mixed_case_is_folded_not_rejected(self) -> None:
        """Pydantic applies `pattern` before `to_lower`, which this pins."""
        assert spec_from_yaml(BASE_YAML + "tags:\n  - Healthcare\n").tags == ["healthcare"]

    @pytest.mark.parametrize("tag", ["bad tag", "has!", "-leading", "_leading", ""])
    def test_rejects_malformed_tags(self, tag: str) -> None:
        with pytest.raises(ScenarioValidationError):
            spec_from_yaml(BASE_YAML + f'tags:\n  - "{tag}"\n')

    def test_rejects_too_many_tags(self) -> None:
        many = "".join(f"  - tag{index}\n" for index in range(21))

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(BASE_YAML + "tags:\n" + many)

        assert "tags" in _error_fields(exc_info.value)


class TestCodeMixing:
    """Code-mixing metadata: optional, structured, and consistent."""

    def test_absent_by_default(self) -> None:
        """Every Phase 2 scenario stays valid."""
        assert spec_from_yaml(BASE_YAML).code_mixing is None

    def test_minimal_block_accepted(self) -> None:
        spec = spec_from_yaml(BASE_YAML + "code_mixing:\n  secondary:\n    - en-IN\n")

        assert spec.code_mixing is not None
        assert spec.code_mixing.secondary == ["en-IN"]
        assert spec.code_mixing.expected is True
        assert spec.code_mixing.primary is None

    def test_secondary_is_required(self) -> None:
        """A mixing block with nothing to mix is meaningless."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(BASE_YAML + "code_mixing:\n  expected: true\n")

        assert "code_mixing.secondary" in _error_fields(exc_info.value)

    def test_secondary_validated_against_the_catalogue(self) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(BASE_YAML + "code_mixing:\n  secondary:\n    - fr-FR\n")

        assert "code_mixing.secondary" in _error_fields(exc_info.value)

    def test_rejects_duplicate_secondary_languages(self) -> None:
        with pytest.raises(ScenarioValidationError, match="duplicate secondary"):
            spec_from_yaml(BASE_YAML + "code_mixing:\n  secondary:\n    - en-IN\n    - en-IN\n")

    def test_primary_may_be_omitted(self) -> None:
        """It then defaults to the scenario language."""
        spec = spec_from_yaml(BASE_YAML + "code_mixing:\n  secondary:\n    - en-IN\n")

        assert spec.code_mixing is not None
        assert spec.code_mixing.primary is None
        assert spec.language == "hi-IN"

    def test_primary_matching_the_language_is_accepted(self) -> None:
        spec = spec_from_yaml(
            BASE_YAML + "code_mixing:\n  primary: hi-IN\n  secondary:\n    - en-IN\n"
        )

        assert spec.code_mixing is not None
        assert spec.code_mixing.primary == "hi-IN"

    def test_primary_contradicting_the_language_is_rejected(self) -> None:
        """Two fields naming a primary language must not disagree."""
        with pytest.raises(ScenarioValidationError, match="must match the scenario language"):
            spec_from_yaml(
                BASE_YAML + "code_mixing:\n  primary: ta-IN\n  secondary:\n    - en-IN\n"
            )

    def test_primary_cannot_also_be_secondary(self) -> None:
        """A language cannot be mixed into itself."""
        with pytest.raises(ScenarioValidationError, match="both the primary and a secondary"):
            spec_from_yaml(
                BASE_YAML + "code_mixing:\n  primary: hi-IN\n  secondary:\n    - hi-IN\n"
            )

    @pytest.mark.parametrize("ratio", [-0.1, 0.95, 1.0, 2.0])
    def test_rejects_out_of_range_ratio(self, ratio: float) -> None:
        """Above 0.9 the primary language is mislabelled rather than mixed."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(
                BASE_YAML + f"code_mixing:\n  secondary:\n    - en-IN\n  secondary_ratio: {ratio}\n"
            )

        assert "code_mixing.secondary_ratio" in _error_fields(exc_info.value)

    def test_ratio_contradicting_expected_false_is_rejected(self) -> None:
        with pytest.raises(ScenarioValidationError, match="must be 0 or omitted"):
            spec_from_yaml(
                BASE_YAML + "code_mixing:\n  expected: false\n  secondary:\n    - en-IN\n"
                "  secondary_ratio: 0.4\n"
            )

    def test_expected_false_asserts_monolingual_behaviour(self) -> None:
        """How a regression in regional-language handling gets caught."""
        spec = spec_from_yaml(
            BASE_YAML + "code_mixing:\n  expected: false\n  secondary:\n    - en-IN\n"
        )

        assert spec.code_mixing is not None
        assert spec.code_mixing.expected is False

    @pytest.mark.parametrize("trigger", [t.value for t in SwitchTrigger])
    def test_accepts_every_declared_switch_trigger(self, trigger: str) -> None:
        spec = spec_from_yaml(
            BASE_YAML
            + f"code_mixing:\n  secondary:\n    - en-IN\n  switch_triggers:\n    - {trigger}\n"
        )

        assert spec.code_mixing is not None
        assert spec.code_mixing.switch_triggers == [SwitchTrigger(trigger)]

    def test_rejects_unknown_switch_trigger(self) -> None:
        """Structured rather than free text, so an agent can act on the value."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(
                BASE_YAML
                + "code_mixing:\n  secondary:\n    - en-IN\n  switch_triggers:\n    - shouting\n"
            )

        assert "code_mixing.switch_triggers.0" in _error_fields(exc_info.value)

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(
                BASE_YAML + "code_mixing:\n  secondary:\n    - en-IN\n  dialect: urban\n"
            )

        assert "code_mixing.dialect" in _error_fields(exc_info.value)

    def test_rejects_too_many_secondary_languages(self) -> None:
        with pytest.raises(ScenarioValidationError):
            spec_from_yaml(
                BASE_YAML
                + "code_mixing:\n  secondary:\n    - en-IN\n    - ta-IN\n    - te-IN\n    - kn-IN\n"
            )

    def test_is_immutable(self) -> None:
        mixing = CodeMixing(secondary=["en-IN"])

        with pytest.raises(Exception, match=r"frozen|Instance is frozen"):
            mixing.expected = False  # type: ignore[misc]


class TestCodeMixedScenarioRoundTrip:
    """A code-mixed scenario must survive serialisation unchanged."""

    HINGLISH = """\
name: hinglish_reschedule
language: hi-IN
persona:
  identity: Urban commuter
  speaking_style: hurried
goal:
  objective: Move the appointment to the afternoon.
expected_outcomes:
  - Confirm the new time
tags:
  - code-mixed
  - healthcare
code_mixing:
  secondary:
    - en-IN
  switch_triggers:
    - numbers
    - technical_terms
  secondary_ratio: 0.35
  sample_utterances:
    - Mujhe kal ka appointment afternoon mein shift karna hai
"""

    TANGLISH = """\
name: tanglish_balance
language: ta-IN
persona:
  identity: Small business owner
goal:
  objective: Check the account balance.
expected_outcomes:
  - State the balance
code_mixing:
  primary: ta-IN
  secondary:
    - en-IN
  switch_triggers:
    - numbers
"""

    @pytest.mark.parametrize("content", [HINGLISH, TANGLISH], ids=["hinglish", "tanglish"])
    def test_round_trip_preserves_everything(self, content: str) -> None:
        original = spec_from_yaml(content)

        assert spec_from_yaml(spec_to_yaml(original)) == original

    def test_serialisation_is_stable(self) -> None:
        """Two serialisations of the same spec must be byte-identical."""
        spec = spec_from_yaml(self.HINGLISH)

        first = spec_to_yaml(spec)
        second = spec_to_yaml(spec_from_yaml(first))

        assert first == second

    def test_output_has_no_python_tags(self) -> None:
        output = spec_to_yaml(spec_from_yaml(self.HINGLISH))

        assert "!!python" not in output
        assert "switch_triggers" in output

    def test_json_schema_includes_the_new_models(self) -> None:
        """FastAPI needs these to document the API."""
        schema = ScenarioSpec.model_json_schema()

        assert "CodeMixing" in schema["$defs"]
        assert "SwitchTrigger" in schema["$defs"]
