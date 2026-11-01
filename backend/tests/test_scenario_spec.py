"""Tests for YAML loading and scenario specification validation.

No database is needed here: the loader and the spec are pure functions.
"""

from __future__ import annotations

import pytest

from app.schemas.scenario_spec import (
    SUPPORTED_LANGUAGES,
    AudioConfig,
    NoiseProfile,
    ScenarioSpec,
    SpeakingStyle,
)
from app.services.scenario_loader import (
    MAX_YAML_BYTES,
    MAX_YAML_NODES,
    ScenarioSyntaxError,
    ScenarioTooLargeError,
    ScenarioValidationError,
    spec_from_file,
    spec_from_yaml,
    spec_to_yaml,
)

VALID_YAML = """\
name: appointment_booking
description: Test whether a voice bot can book a doctor appointment.
language: hi-IN

persona:
  identity: Working professional
  speaking_style: polite
  traits:
    - impatient
    - prefers short responses

goal:
  objective: Book an appointment for tomorrow.
  max_turns: 15

known_facts:
  patient_name: Rahul
  preferred_time: "10 AM"

expected_outcomes:
  - Confirm appointment date
  - Confirm appointment time
  - Confirm patient name

audio:
  noise_profile: clean
  snr_db: 30
"""

MINIMAL_YAML = """\
name: minimal
language: en-IN
persona:
  identity: Caller
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
"""


def _error_fields(exc: ScenarioValidationError) -> set[str]:
    """Field paths reported by a validation failure."""
    return {error.field for error in exc.errors}


class TestValidYaml:
    """A well-formed scenario parses into a fully populated spec."""

    def test_parses_all_fields(self) -> None:
        spec = spec_from_yaml(VALID_YAML)

        assert spec.name == "appointment_booking"
        assert spec.language == "hi-IN"
        assert spec.persona.identity == "Working professional"
        assert spec.persona.speaking_style is SpeakingStyle.POLITE
        assert spec.persona.traits == ["impatient", "prefers short responses"]
        assert spec.goal.objective == "Book an appointment for tomorrow."
        assert spec.goal.max_turns == 15
        assert spec.known_facts == {"patient_name": "Rahul", "preferred_time": "10 AM"}
        assert len(spec.expected_outcomes) == 3
        assert spec.audio.noise_profile is NoiseProfile.CLEAN
        assert spec.audio.snr_db == 30.0

    def test_applies_defaults_for_omitted_optionals(self) -> None:
        spec = spec_from_yaml(MINIMAL_YAML)

        assert spec.description is None
        assert spec.persona.speaking_style is SpeakingStyle.NEUTRAL
        assert spec.persona.traits == []
        assert spec.goal.max_turns == 20
        assert spec.known_facts == {}
        assert spec.audio == AudioConfig()
        assert spec.constraints is None

    def test_accepts_optional_constraints_block(self) -> None:
        spec = spec_from_yaml(
            MINIMAL_YAML
            + """
constraints:
  max_silence_seconds: 3.5
  allow_interruptions: false
  required_phrases:
    - my name is
"""
        )

        assert spec.constraints is not None
        assert spec.constraints.max_silence_seconds == 3.5
        assert spec.constraints.allow_interruptions is False
        assert spec.constraints.required_phrases == ["my name is"]

    def test_spec_is_immutable(self) -> None:
        """A validated spec must not be mutable after the fact."""
        spec = spec_from_yaml(MINIMAL_YAML)

        with pytest.raises(Exception, match=r"frozen|Instance is frozen"):
            spec.name = "something-else"  # type: ignore[misc]

    def test_strips_surrounding_whitespace(self) -> None:
        spec = spec_from_yaml(MINIMAL_YAML.replace("identity: Caller", 'identity: "  Caller  "'))

        assert spec.persona.identity == "Caller"


class TestYamlSyntax:
    """Malformed YAML must fail with a locatable message."""

    def test_rejects_unparseable_yaml(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match="invalid YAML"):
            spec_from_yaml("name: test\n  bad: indentation\n   worse: here\n")

    def test_reports_line_and_column(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match=r"line \d+, column \d+"):
            spec_from_yaml("name: [unclosed\n")

    def test_rejects_empty_document(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match="empty"):
            spec_from_yaml("")

    def test_rejects_comments_only_document(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match="empty"):
            spec_from_yaml("# just a comment\n")

    @pytest.mark.parametrize(
        "content", ["- a\n- b\n", "just a string\n", "42\n"], ids=["list", "scalar", "int"]
    )
    def test_rejects_non_mapping_document(self, content: str) -> None:
        with pytest.raises(ScenarioSyntaxError, match="must be a mapping"):
            spec_from_yaml(content)

    def test_rejects_invalid_utf8(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match="not valid UTF-8"):
            spec_from_yaml(b"name: \xff\xfe invalid\n")


class TestUnsafeYaml:
    """`safe_load` must refuse Python object construction."""

    def test_rejects_python_object_tag(self) -> None:
        """The payload that would be remote code execution under yaml.load."""
        payload = "name: !!python/object/apply:os.system ['echo pwned']\n"

        with pytest.raises(ScenarioSyntaxError):
            spec_from_yaml(payload)

    def test_rejects_python_name_tag(self) -> None:
        with pytest.raises(ScenarioSyntaxError):
            spec_from_yaml("name: !!python/name:os.system\n")

    def test_rejects_arbitrary_unknown_tag(self) -> None:
        with pytest.raises(ScenarioSyntaxError):
            spec_from_yaml("name: !!python/module:subprocess\n")

    def test_does_not_execute_payload(self) -> None:
        """Belt and braces: the marker file must not be created."""
        import tempfile
        from pathlib import Path as _Path

        marker = _Path(tempfile.gettempdir()) / "bhashabench_yaml_rce_marker"
        marker.unlink(missing_ok=True)

        payload = (
            "name: !!python/object/apply:pathlib.Path.touch"
            " [!!python/object/apply:pathlib.Path"
            f" ['{marker.as_posix()}']]\n"
        )

        with pytest.raises(ScenarioSyntaxError):
            spec_from_yaml(payload)

        assert not marker.exists()


class TestSizeLimits:
    """Oversized and expansion-bomb input must be refused."""

    def test_rejects_oversized_input(self) -> None:
        oversized = "name: x\n" + ("# padding\n" * (MAX_YAML_BYTES // 10 + 100))

        with pytest.raises(ScenarioTooLargeError, match="exceeds the"):
            spec_from_yaml(oversized)

    def test_accepts_input_just_under_the_cap(self) -> None:
        """The limit must not be off by one against legitimate input."""
        padding_needed = MAX_YAML_BYTES - len(MINIMAL_YAML.encode()) - 200
        padded = MINIMAL_YAML + "# " + ("p" * padding_needed) + "\n"
        assert len(padded.encode()) < MAX_YAML_BYTES

        assert spec_from_yaml(padded).name == "minimal"

    def test_rejects_billion_laughs_expansion(self) -> None:
        """Anchors and aliases expanding past the node cap must be refused.

        The source text is tiny, so the byte cap alone would let this through;
        the node count after parsing is what catches it.
        """
        bomb = (
            "name: bomb\n"
            "a: &a [x, x, x, x, x, x, x, x, x, x]\n"
            "b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a]\n"
            "c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b]\n"
            "d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c, *c]\n"
            "e: [*d, *d, *d, *d, *d, *d, *d, *d, *d, *d]\n"
        )
        assert len(bomb.encode()) < MAX_YAML_BYTES

        with pytest.raises(ScenarioTooLargeError, match="nodes"):
            spec_from_yaml(bomb)

    def test_rejects_excessive_nesting(self) -> None:
        deep = "name: deep\n"
        for level in range(40):
            deep += "  " * level + f"k{level}:\n"
        deep += "  " * 40 + "leaf: value\n"

        with pytest.raises(ScenarioTooLargeError, match=r"depth|nodes"):
            spec_from_yaml(deep)

    def test_node_cap_is_a_real_limit(self) -> None:
        """Sanity check that the configured cap is meaningful, not enormous."""
        assert MAX_YAML_NODES < 100_000


class TestRequiredFields:
    """Omitting a required field must name it."""

    @pytest.mark.parametrize(
        ("field", "removal"),
        [
            ("name", "name: minimal\n"),
            ("language", "language: en-IN\n"),
            ("persona", "persona:\n  identity: Caller\n"),
            ("goal", "goal:\n  objective: Ask a question.\n"),
            ("expected_outcomes", "expected_outcomes:\n  - Bot answers\n"),
        ],
    )
    def test_missing_required_field_is_reported(self, field: str, removal: str) -> None:
        content = MINIMAL_YAML.replace(removal, "")

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert field in _error_fields(exc_info.value)

    def test_nested_required_field_path_is_reported(self) -> None:
        content = MINIMAL_YAML.replace("  identity: Caller\n", "  speaking_style: polite\n")

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "persona.identity" in _error_fields(exc_info.value)

    def test_empty_expected_outcomes_is_rejected(self) -> None:
        """A scenario with nothing to check can neither pass nor fail."""
        content = MINIMAL_YAML.replace("  - Bot answers\n", "")

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "expected_outcomes" in _error_fields(exc_info.value)


class TestLanguageValidation:
    """Language tags must be well-formed and supported."""

    @pytest.mark.parametrize("tag", sorted(SUPPORTED_LANGUAGES))
    def test_accepts_every_supported_tag(self, tag: str) -> None:
        spec = spec_from_yaml(MINIMAL_YAML.replace("language: en-IN", f"language: {tag}"))

        assert spec.language == tag

    @pytest.mark.parametrize(
        "tag", ["english", "HI-in", "hi_IN", "h", "toolongtag", "123", "hi-IND"]
    )
    def test_rejects_malformed_tag(self, tag: str) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(MINIMAL_YAML.replace("language: en-IN", f"language: {tag}"))

        assert "language" in _error_fields(exc_info.value)

    @pytest.mark.parametrize("tag", ["fr-FR", "de-DE", "ja-JP", "zh-CN"])
    def test_rejects_well_formed_but_unsupported_tag(self, tag: str) -> None:
        """Rejected with the supported list, so the author learns the options."""
        with pytest.raises(ScenarioValidationError, match="not a supported language"):
            spec_from_yaml(MINIMAL_YAML.replace("language: en-IN", f"language: {tag}"))


class TestAudioValidation:
    """Audio settings must stay inside physically sensible ranges."""

    @pytest.mark.parametrize("snr", [-1, -0.5, 41, 100, 1e9])
    def test_rejects_out_of_range_snr(self, snr: float) -> None:
        content = MINIMAL_YAML + f"audio:\n  snr_db: {snr}\n"

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "audio.snr_db" in _error_fields(exc_info.value)

    @pytest.mark.parametrize("snr", [0, 20, 30, 40])
    def test_accepts_in_range_snr(self, snr: float) -> None:
        spec = spec_from_yaml(MINIMAL_YAML + f"audio:\n  snr_db: {snr}\n")

        assert spec.audio.snr_db == float(snr)

    @pytest.mark.parametrize("value", [".nan", ".inf", "-.inf"])
    def test_rejects_non_finite_snr(self, value: str) -> None:
        """YAML accepts these literals; a range check must still refuse them."""
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(MINIMAL_YAML + f"audio:\n  snr_db: {value}\n")

        assert "audio.snr_db" in _error_fields(exc_info.value)

    def test_rejects_unknown_noise_profile(self) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(MINIMAL_YAML + "audio:\n  noise_profile: hurricane\n")

        assert "audio.noise_profile" in _error_fields(exc_info.value)

    @pytest.mark.parametrize("loss", [-1, 31, 100])
    def test_rejects_out_of_range_packet_loss(self, loss: float) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(MINIMAL_YAML + f"audio:\n  packet_loss_percent: {loss}\n")

        assert "audio.packet_loss_percent" in _error_fields(exc_info.value)


class TestTypeValidation:
    """Wrong types must be rejected, not coerced."""

    def test_rejects_string_where_mapping_expected(self) -> None:
        content = MINIMAL_YAML.replace("persona:\n  identity: Caller\n", "persona: a person\n")

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "persona" in _error_fields(exc_info.value)

    def test_rejects_scalar_where_list_expected(self) -> None:
        content = MINIMAL_YAML.replace(
            "expected_outcomes:\n  - Bot answers\n", "expected_outcomes: Bot answers\n"
        )

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "expected_outcomes" in _error_fields(exc_info.value)

    def test_rejects_non_integer_max_turns(self) -> None:
        content = MINIMAL_YAML.replace(
            "  objective: Ask a question.\n", "  objective: Ask a question.\n  max_turns: many\n"
        )

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "goal.max_turns" in _error_fields(exc_info.value)

    @pytest.mark.parametrize("turns", [0, -5, 101])
    def test_rejects_out_of_range_max_turns(self, turns: int) -> None:
        content = MINIMAL_YAML.replace(
            "  objective: Ask a question.\n",
            f"  objective: Ask a question.\n  max_turns: {turns}\n",
        )

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "goal.max_turns" in _error_fields(exc_info.value)

    def test_rejects_non_string_known_fact_value(self) -> None:
        """Values are spoken aloud; YAML would read `0123` as 123."""
        content = MINIMAL_YAML + "known_facts:\n  account: 0123\n"

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "known_facts.account" in _error_fields(exc_info.value)

    def test_quoted_numeric_fact_is_preserved_exactly(self) -> None:
        spec = spec_from_yaml(MINIMAL_YAML + 'known_facts:\n  account: "0123"\n')

        assert spec.known_facts["account"] == "0123"

    def test_rejects_invalid_fact_key(self) -> None:
        content = MINIMAL_YAML + 'known_facts:\n  "bad key!": value\n'

        with pytest.raises(ScenarioValidationError):
            spec_from_yaml(content)


class TestUnexpectedFields:
    """Unknown keys must be errors, not silently ignored."""

    def test_rejects_unknown_top_level_field(self) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(MINIMAL_YAML + "unexpected_field: value\n")

        assert "unexpected_field" in _error_fields(exc_info.value)

    def test_rejects_misspelled_field(self) -> None:
        """The case this rule exists for: a typo must not change behaviour silently."""
        content = MINIMAL_YAML.replace("persona:", "persoan:")

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        fields = _error_fields(exc_info.value)
        assert "persoan" in fields
        assert "persona" in fields

    def test_rejects_unknown_nested_field(self) -> None:
        content = MINIMAL_YAML.replace("  identity: Caller\n", "  identity: Caller\n  age: 42\n")

        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(content)

        assert "persona.age" in _error_fields(exc_info.value)

    def test_rejects_unknown_audio_field(self) -> None:
        with pytest.raises(ScenarioValidationError) as exc_info:
            spec_from_yaml(MINIMAL_YAML + "audio:\n  reverb: 0.5\n")

        assert "audio.reverb" in _error_fields(exc_info.value)


class TestDuplicateDetection:
    """Repeated list entries are authoring errors."""

    def test_rejects_duplicate_expected_outcomes(self) -> None:
        content = MINIMAL_YAML.replace("  - Bot answers\n", "  - Bot answers\n  - bot answers\n")

        with pytest.raises(ScenarioValidationError, match="duplicate expected outcomes"):
            spec_from_yaml(content)

    def test_rejects_duplicate_traits(self) -> None:
        content = MINIMAL_YAML.replace(
            "  identity: Caller\n",
            "  identity: Caller\n  traits:\n    - impatient\n    - Impatient\n",
        )

        with pytest.raises(ScenarioValidationError, match="duplicate traits"):
            spec_from_yaml(content)


class TestSerialization:
    """A spec must round-trip through YAML without loss."""

    def test_round_trip_preserves_every_value(self) -> None:
        original = spec_from_yaml(VALID_YAML)

        reparsed = spec_from_yaml(spec_to_yaml(original))

        assert reparsed == original

    def test_round_trip_is_stable(self) -> None:
        """Serialising twice must produce identical text."""
        spec = spec_from_yaml(VALID_YAML)

        first = spec_to_yaml(spec)
        second = spec_to_yaml(spec_from_yaml(first))

        assert first == second

    def test_output_contains_no_python_tags(self) -> None:
        """Enums must serialise as plain strings, not Python object tags."""
        output = spec_to_yaml(spec_from_yaml(VALID_YAML))

        assert "!!python" not in output
        assert "noise_profile: clean" in output
        assert "speaking_style: polite" in output

    def test_output_preserves_declared_field_order(self) -> None:
        """Alphabetising would make a round-tripped file harder to read."""
        output = spec_to_yaml(spec_from_yaml(VALID_YAML))

        assert output.index("name:") < output.index("language:")
        assert output.index("language:") < output.index("persona:")
        assert output.index("persona:") < output.index("goal:")

    def test_defaults_are_materialised_on_output(self) -> None:
        """A round-tripped minimal scenario gains its defaults explicitly."""
        output = spec_to_yaml(spec_from_yaml(MINIMAL_YAML))

        assert "max_turns: 20" in output
        assert "snr_db: 30" in output

    def test_unicode_is_not_escaped(self) -> None:
        """Indian-language text must stay readable in the output."""
        spec = spec_from_yaml(MINIMAL_YAML.replace("identity: Caller", "identity: ग्राहक"))

        assert "ग्राहक" in spec_to_yaml(spec)


class TestFileLoading:
    """Loading from disk mirrors loading from a string."""

    def test_loads_a_valid_file(self, tmp_path) -> None:
        path = tmp_path / "scenario.yaml"
        path.write_text(VALID_YAML, encoding="utf-8")

        assert spec_from_file(path).name == "appointment_booking"

    def test_reports_a_missing_file(self, tmp_path) -> None:
        with pytest.raises(Exception, match="cannot read scenario file"):
            spec_from_file(tmp_path / "absent.yaml")

    def test_rejects_an_oversized_file_without_reading_it(self, tmp_path) -> None:
        path = tmp_path / "huge.yaml"
        path.write_bytes(b"#" * (MAX_YAML_BYTES + 1))

        with pytest.raises(ScenarioTooLargeError, match="exceeds the"):
            spec_from_file(path)


class TestModelDirectly:
    """A few checks against the model itself, bypassing YAML."""

    def test_spec_json_schema_is_generable(self) -> None:
        """FastAPI needs this to build the OpenAPI document."""
        schema = ScenarioSpec.model_json_schema()

        assert schema["title"] == "ScenarioSpec"
        assert "name" in schema["required"]

    def test_model_dump_json_round_trips(self) -> None:
        spec = spec_from_yaml(VALID_YAML)

        assert ScenarioSpec.model_validate(spec.model_dump(mode="json")) == spec
