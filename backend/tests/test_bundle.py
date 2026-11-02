"""Tests for the scenario bundle format: parsing, validation and building.

No database. The bundle module is pure parsing and serialisation, so these are
unit tests; persistence is covered in `test_api_library.py`.
"""

from __future__ import annotations

import pytest
import yaml

from app.services.bundle import (
    BUNDLE_FORMAT,
    MAX_BUNDLE_SCENARIOS,
    BundleFormatError,
    build_bundle,
    parse_bundle,
)
from app.services.scenario_loader import (
    ScenarioSyntaxError,
    ScenarioTooLargeError,
    spec_from_yaml,
)

ENTRY = """\
  - name: {name}
    language: {language}
    persona:
      identity: Caller
    goal:
      objective: Ask a question.
    expected_outcomes:
      - Bot answers
"""


def bundle_yaml(*entries: str, suite: str | None = None, fmt: str = BUNDLE_FORMAT) -> str:
    """Assemble a bundle document from entry fragments."""
    parts = [f"format: {fmt}\n"]
    if suite is not None:
        parts.append(f"suite:\n  name: {suite}\n")
    parts.append("scenarios:\n")
    parts.extend(entries)
    return "".join(parts)


VALID = bundle_yaml(
    ENTRY.format(name="first", language="hi-IN"),
    ENTRY.format(name="second", language="ta-IN"),
    suite="Two scenarios",
)


class TestBundleFormat:
    """The `format` field is what makes a bundle recognisable."""

    def test_parses_a_valid_bundle(self) -> None:
        parsed = parse_bundle(VALID)

        assert parsed.total == 2
        assert parsed.is_valid
        assert [spec.name for spec in parsed.specs] == ["first", "second"]
        assert parsed.suite.name == "Two scenarios"

    def test_suite_metadata_is_optional(self) -> None:
        parsed = parse_bundle(bundle_yaml(ENTRY.format(name="only", language="hi-IN")))

        assert parsed.suite.name is None
        assert parsed.suite.description is None

    def test_rejects_a_document_with_no_format(self) -> None:
        """The common mistake: posting a single scenario to the import endpoint."""
        single = "name: lonely\nlanguage: hi-IN\n"

        with pytest.raises(BundleFormatError, match="no 'format' field"):
            parse_bundle(single)

    def test_missing_format_error_points_at_the_right_endpoint(self) -> None:
        with pytest.raises(BundleFormatError, match="create-scenario endpoint"):
            parse_bundle("name: lonely\nlanguage: hi-IN\n")

    def test_rejects_an_unknown_format_version(self) -> None:
        with pytest.raises(BundleFormatError, match="unsupported bundle format"):
            parse_bundle(bundle_yaml(ENTRY.format(name="x", language="hi-IN"), fmt="something/v9"))

    def test_rejects_unknown_top_level_fields(self) -> None:
        """A typo at the top level must not be silently ignored."""
        with pytest.raises(BundleFormatError, match="unexpected top-level field"):
            parse_bundle(VALID + "unexpected: true\n")

    def test_rejects_missing_scenarios_key(self) -> None:
        with pytest.raises(BundleFormatError, match="no 'scenarios' field"):
            parse_bundle(f"format: {BUNDLE_FORMAT}\nsuite:\n  name: Empty\n")

    def test_rejects_non_list_scenarios(self) -> None:
        with pytest.raises(BundleFormatError, match="must be a list"):
            parse_bundle(f"format: {BUNDLE_FORMAT}\nscenarios: not-a-list\n")

    def test_rejects_an_empty_scenario_list(self) -> None:
        with pytest.raises(BundleFormatError, match="contains no scenarios"):
            parse_bundle(f"format: {BUNDLE_FORMAT}\nscenarios: []\n")

    def test_rejects_non_mapping_suite_block(self) -> None:
        with pytest.raises(BundleFormatError, match="'suite' must be a mapping"):
            parse_bundle(
                f"format: {BUNDLE_FORMAT}\nsuite: a string\nscenarios:\n"
                + ENTRY.format(name="x", language="hi-IN")
            )

    def test_rejects_unknown_suite_fields(self) -> None:
        with pytest.raises(BundleFormatError, match="unexpected field"):
            parse_bundle(
                f"format: {BUNDLE_FORMAT}\nsuite:\n  name: X\n  owner: me\nscenarios:\n"
                + ENTRY.format(name="x", language="hi-IN")
            )

    def test_rejects_non_string_suite_name(self) -> None:
        with pytest.raises(BundleFormatError, match="must be a string"):
            parse_bundle(
                f"format: {BUNDLE_FORMAT}\nsuite:\n  name: 42\nscenarios:\n"
                + ENTRY.format(name="x", language="hi-IN")
            )

    def test_format_error_is_a_syntax_error_subclass(self) -> None:
        """So the existing 422 handler covers it with no new wiring."""
        assert issubclass(BundleFormatError, ScenarioSyntaxError)


class TestEntryValidation:
    """Every entry is validated, and failures are collected, not raised early."""

    def test_reports_an_invalid_entry_without_losing_the_valid_ones(self) -> None:
        invalid = ENTRY.format(name="bad", language="fr-FR")
        parsed = parse_bundle(bundle_yaml(ENTRY.format(name="good", language="hi-IN"), invalid))

        assert parsed.total == 2
        assert [spec.name for spec in parsed.specs] == ["good"]
        assert len(parsed.entry_errors) == 1
        assert not parsed.is_valid

    def test_entry_error_carries_index_and_name(self) -> None:
        """So an author can find the offending entry in a 40-scenario file."""
        parsed = parse_bundle(
            bundle_yaml(
                ENTRY.format(name="good", language="hi-IN"),
                ENTRY.format(name="broken", language="fr-FR"),
            )
        )

        error = parsed.entry_errors[0]
        assert error.index == 1
        assert error.name == "broken"
        assert any(item.field == "language" for item in error.errors)

    def test_collects_every_failure_not_just_the_first(self) -> None:
        """One run should give the whole list of problems."""
        parsed = parse_bundle(
            bundle_yaml(
                ENTRY.format(name="bad1", language="fr-FR"),
                ENTRY.format(name="bad2", language="de-DE"),
                ENTRY.format(name="bad3", language="ja-JP"),
            )
        )

        assert len(parsed.entry_errors) == 3
        assert [error.index for error in parsed.entry_errors] == [0, 1, 2]

    def test_reports_a_non_mapping_entry(self) -> None:
        document = f"format: {BUNDLE_FORMAT}\nscenarios:\n  - just a string\n"

        parsed = parse_bundle(document)

        assert parsed.total == 1
        assert parsed.entry_errors[0].errors[0].error_type == "bundle_entry_type"

    def test_entry_without_a_readable_name_reports_none(self) -> None:
        document = (
            f"format: {BUNDLE_FORMAT}\nscenarios:\n  - language: hi-IN\n    persona:\n"
            "      identity: Caller\n"
        )

        parsed = parse_bundle(document)

        assert parsed.entry_errors[0].name is None

    def test_as_dict_is_json_serialisable(self) -> None:
        """The API returns these verbatim."""
        parsed = parse_bundle(bundle_yaml(ENTRY.format(name="bad", language="fr-FR")))

        payload = parsed.entry_errors[0].as_dict()

        assert payload["index"] == 0
        assert payload["name"] == "bad"
        assert isinstance(payload["errors"], list)


class TestDuplicateNamesWithinBundle:
    """A bundle cannot carry the same name twice."""

    def test_both_copies_are_reported(self) -> None:
        """Neither is obviously the mistake at authoring time."""
        parsed = parse_bundle(
            bundle_yaml(
                ENTRY.format(name="same", language="hi-IN"),
                ENTRY.format(name="same", language="ta-IN"),
            )
        )

        assert parsed.specs == []
        assert len(parsed.entry_errors) == 2
        assert all(
            error.errors[0].error_type == "bundle_duplicate_name" for error in parsed.entry_errors
        )

    def test_unaffected_entries_still_validate(self) -> None:
        parsed = parse_bundle(
            bundle_yaml(
                ENTRY.format(name="dup", language="hi-IN"),
                ENTRY.format(name="fine", language="ta-IN"),
                ENTRY.format(name="dup", language="te-IN"),
            )
        )

        assert [spec.name for spec in parsed.specs] == ["fine"]
        assert len(parsed.entry_errors) == 2


class TestBundleLimits:
    """The loader's protections must apply to a bundle as a whole."""

    def test_rejects_too_many_entries(self) -> None:
        entries = [
            ENTRY.format(name=f"s{index}", language="hi-IN")
            for index in range(MAX_BUNDLE_SCENARIOS + 1)
        ]

        with pytest.raises(BundleFormatError, match="exceeds the limit"):
            parse_bundle(bundle_yaml(*entries))

    def test_entry_cap_is_a_real_limit(self) -> None:
        assert MAX_BUNDLE_SCENARIOS <= 1000

    def test_rejects_oversized_input(self) -> None:
        oversized = VALID + ("# padding\n" * 40_000)

        with pytest.raises(ScenarioTooLargeError, match="exceeds the"):
            parse_bundle(oversized)

    def test_rejects_unsafe_yaml(self) -> None:
        """The bundle path must not bypass safe loading."""
        payload = f"format: {BUNDLE_FORMAT}\nscenarios: !!python/object/apply:os.system ['x']\n"

        with pytest.raises(ScenarioSyntaxError):
            parse_bundle(payload)

    def test_rejects_recursive_aliases(self) -> None:
        """The Phase 2 cycle guard must still apply inside a bundle."""
        payload = f"format: {BUNDLE_FORMAT}\nscenarios: &s\n  - *s\n"

        with pytest.raises(ScenarioSyntaxError, match="recursive alias"):
            parse_bundle(payload)

    def test_rejects_malformed_yaml(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match="invalid YAML"):
            parse_bundle("format: [unclosed\n")

    def test_rejects_empty_document(self) -> None:
        with pytest.raises(ScenarioSyntaxError, match="empty"):
            parse_bundle("# nothing\n")


class TestBuildBundle:
    """Export must be deterministic and re-importable."""

    def test_emits_the_format_marker(self) -> None:
        specs = parse_bundle(VALID).specs

        document = yaml.safe_load(build_bundle(specs))

        assert document["format"] == BUNDLE_FORMAT

    def test_includes_suite_metadata_when_given(self) -> None:
        specs = parse_bundle(VALID).specs

        document = yaml.safe_load(build_bundle(specs, suite_name="Suite", suite_description="Desc"))

        assert document["suite"] == {"name": "Suite", "description": "Desc"}

    def test_omits_the_suite_block_entirely_when_not_given(self) -> None:
        """A selection may span suites, so there is no single owner to name."""
        document = yaml.safe_load(build_bundle(parse_bundle(VALID).specs))

        assert "suite" not in document

    def test_handles_an_empty_scenario_list(self) -> None:
        """An empty suite is a legitimate thing to export."""
        document = yaml.safe_load(build_bundle([], suite_name="Empty"))

        assert document["scenarios"] == []
        assert document["suite"]["name"] == "Empty"

    def test_output_is_byte_identical_across_calls(self) -> None:
        specs = parse_bundle(VALID).specs

        assert build_bundle(specs) == build_bundle(specs)

    def test_leaks_no_database_fields(self) -> None:
        """A bundle describes scenarios, not rows."""
        output = build_bundle(parse_bundle(VALID).specs, suite_name="S")

        for leaked in ("id:", "suite_id", "created_at", "updated_at", "spec_version"):
            assert leaked not in output

    def test_output_has_no_python_tags(self) -> None:
        assert "!!python" not in build_bundle(parse_bundle(VALID).specs)

    def test_preserves_non_ascii(self) -> None:
        """Indian-language content must stay readable, not escaped."""
        spec = spec_from_yaml(
            "name: devanagari\nlanguage: hi-IN\npersona:\n  identity: ग्राहक\n"
            "goal:\n  objective: पूछताछ करें।\nexpected_outcomes:\n  - उत्तर मिले\n"
        )

        assert "ग्राहक" in build_bundle([spec])


class TestRoundTrip:
    """Export then import must preserve meaning exactly."""

    def test_built_bundle_reparses_identically(self) -> None:
        original = parse_bundle(VALID).specs

        reparsed = parse_bundle(build_bundle(original)).specs

        assert reparsed == original

    def test_round_trip_preserves_tags_and_code_mixing(self) -> None:
        rich = (
            f"format: {BUNDLE_FORMAT}\nscenarios:\n"
            "  - name: hinglish\n"
            "    language: hi-IN\n"
            "    persona:\n"
            "      identity: Commuter\n"
            "    goal:\n"
            "      objective: Reschedule.\n"
            "    expected_outcomes:\n"
            "      - Confirm time\n"
            "    tags:\n"
            "      - code-mixed\n"
            "    code_mixing:\n"
            "      secondary:\n"
            "        - en-IN\n"
            "      switch_triggers:\n"
            "        - numbers\n"
            "      secondary_ratio: 0.3\n"
        )
        original = parse_bundle(rich).specs

        reparsed = parse_bundle(build_bundle(original)).specs

        assert reparsed == original
        assert reparsed[0].tags == ["code-mixed"]
        assert reparsed[0].code_mixing is not None
        assert reparsed[0].code_mixing.secondary_ratio == 0.3

    def test_round_trip_is_stable_over_two_generations(self) -> None:
        """A second round-trip must change nothing."""
        first = build_bundle(parse_bundle(VALID).specs)
        second = build_bundle(parse_bundle(first).specs)

        assert first == second
