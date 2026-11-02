"""Tests for the `bhashabench` CLI.

Invoked through Typer's `CliRunner`, which exercises the real argument
parsing, the real commands and the real exit codes rather than calling the
underlying functions directly.

The offline commands need no database. The database-backed ones are driven
against the migrated test database by overriding the session factory, so they
run inside the same rolled-back transaction as the rest of the suite.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.cli.main import app
from app.cli.output import ExitCode
from app.core import languages
from app.services.bundle import BUNDLE_FORMAT

runner = CliRunner()

SCENARIO = """\
name: cli_scenario
language: hi-IN
persona:
  identity: Caller
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
"""

BUNDLE = yaml.safe_dump(
    {
        "format": BUNDLE_FORMAT,
        "suite": {"name": "CLI bundle"},
        "scenarios": [
            {
                "name": f"cli_entry_{index}",
                "language": "hi-IN",
                "persona": {"identity": "Caller"},
                "goal": {"objective": "Ask a question."},
                "expected_outcomes": ["Bot answers"],
            }
            for index in range(2)
        ],
    },
    sort_keys=False,
)


TWO_BAD_FIELDS = """name: two_bad
language: fr-FR
persona:
  identity: Caller
  speaking_style: shouty
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
"""


MONOLINGUAL_BLOCK = """\ncode_mixing:
  secondary:
    - en-IN
  expected: false
"""


@pytest.fixture
def scenario_file(tmp_path: Path) -> Path:
    """A valid scenario on disk."""
    path = tmp_path / "scenario.yaml"
    path.write_text(SCENARIO, encoding="utf-8")
    return path


@pytest.fixture
def bundle_file(tmp_path: Path) -> Path:
    """A valid two-entry bundle on disk."""
    path = tmp_path / "bundle.yaml"
    path.write_text(BUNDLE, encoding="utf-8")
    return path


@pytest.fixture
def cli_db(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Point the CLI's `session_scope` at the test's transaction.

    The CLI opens its own session through `session_scope`, which would commit
    to the real database. Replacing it with a scope bound to `db_session`
    keeps CLI tests inside the same rolled-back transaction as every other
    test, so they leave nothing behind.
    """
    from contextlib import contextmanager

    @contextmanager
    def scoped() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr("app.cli.main.session_scope", scoped)
    yield db_session


def invoke(*args: str) -> tuple[int, str]:
    """Run the CLI and return `(exit_code, combined_output)`."""
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


# ---------------------------------------------------------------------------
# Help and argument parsing
# ---------------------------------------------------------------------------


class TestHelp:
    """`--help` is the first thing a user runs."""

    def test_top_level_help_succeeds(self) -> None:
        code, output = invoke("--help")

        assert code == ExitCode.OK
        assert "bhashabench" in output.lower()

    def test_help_lists_every_command_group(self) -> None:
        _, output = invoke("--help")

        for command in ("validate", "validate-bundle", "languages", "import", "export"):
            assert command in output
        assert "suite" in output
        assert "scenario" in output

    def test_help_says_which_commands_need_no_database(self) -> None:
        """A user should not have to start Postgres to check a file."""
        _, output = invoke("--help")

        assert "offline" in output.lower()

    @pytest.mark.parametrize("group", ["suite", "scenario"])
    def test_subcommand_help_succeeds(self, group: str) -> None:
        code, output = invoke(group, "--help")

        assert code == ExitCode.OK
        assert "list" in output

    @pytest.mark.parametrize("group", ["suite", "scenario"])
    def test_bare_group_shows_help_rather_than_failing_obscurely(self, group: str) -> None:
        _, output = invoke(group)

        assert "Usage" in output

    def test_unknown_command_is_a_usage_error(self) -> None:
        code, _ = invoke("teleport")

        assert code != ExitCode.OK


# ---------------------------------------------------------------------------
# Offline: validate
# ---------------------------------------------------------------------------


class TestValidateCommand:
    """`validate` must work with no database."""

    def test_accepts_a_valid_scenario(self, scenario_file: Path) -> None:
        code, output = invoke("validate", str(scenario_file))

        assert code == ExitCode.OK
        assert "valid: cli_scenario" in output
        assert "hi-IN" in output

    def test_shows_the_language_display_name(self, scenario_file: Path) -> None:
        _, output = invoke("validate", str(scenario_file))

        assert "Hindi" in output

    def test_json_output_is_parsable(self, scenario_file: Path) -> None:
        code, output = invoke("validate", str(scenario_file), "--json")

        assert code == ExitCode.OK
        payload = json.loads(output)
        assert payload["valid"] is True
        assert payload["scenario"]["name"] == "cli_scenario"

    def test_show_normalized_prints_canonical_yaml(self, scenario_file: Path) -> None:
        _, output = invoke("validate", str(scenario_file), "--show-normalized")

        assert "max_turns: 20" in output

    def test_invalid_scenario_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(SCENARIO.replace("language: hi-IN", "language: fr-FR"), encoding="utf-8")

        code, output = invoke("validate", str(path))

        assert code == ExitCode.INVALID_INPUT
        assert "not a supported language" in output

    def test_invalid_scenario_json_output_reports_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text(SCENARIO.replace("language: hi-IN", "language: fr-FR"), encoding="utf-8")

        code, output = invoke("validate", str(path), "--json")

        assert code == ExitCode.INVALID_INPUT
        payload = json.loads(output)
        assert payload["valid"] is False
        assert any(error["field"] == "language" for error in payload["errors"])

    def test_asserted_monolingual_is_not_shown_as_mixing(self, tmp_path: Path) -> None:
        """`expected: false` is the opposite claim and must not read as mixing."""
        path = tmp_path / "mono.yaml"
        path.write_text(
            SCENARIO + MONOLINGUAL_BLOCK,
            encoding="utf-8",
        )

        code, output = invoke("validate", str(path))

        assert code == ExitCode.OK
        assert "none expected" in output
        assert "hi-IN + en-IN" not in output

    def test_each_failure_is_reported_once(self, tmp_path: Path) -> None:
        """The embedded message summary must not be printed alongside the list.

        `ScenarioValidationError` carries the first few failures inside its
        message for consumers that have only a message to show. The CLI renders
        `.errors` itself, so echoing the raw message too showed each failure
        twice.
        """
        path = tmp_path / "two_bad.yaml"
        path.write_text(TWO_BAD_FIELDS, encoding="utf-8")

        _, output = invoke("validate", str(path))

        assert output.count("fr-FR") == 1
        assert output.count("persona.speaking_style") == 1
        assert output.count("language:") == 1

    def test_malformed_yaml_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.yaml"
        path.write_text("name: [unclosed\n", encoding="utf-8")

        code, output = invoke("validate", str(path))

        assert code == ExitCode.INVALID_INPUT
        assert "invalid YAML" in output

    def test_unsafe_yaml_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "unsafe.yaml"
        path.write_text("name: !!python/object/apply:os.system ['x']\n", encoding="utf-8")

        code, _ = invoke("validate", str(path))

        assert code == ExitCode.INVALID_INPUT

    def test_recursive_alias_exits_two(self, tmp_path: Path) -> None:
        """The Phase 2 cycle guard must apply through the CLI too."""
        path = tmp_path / "cyclic.yaml"
        path.write_text("name: r\nlanguage: hi-IN\npersona: &p\n  identity: *p\n", encoding="utf-8")

        code, output = invoke("validate", str(path))

        assert code == ExitCode.INVALID_INPUT
        assert "recursive alias" in output

    def test_missing_file_exits_two(self, tmp_path: Path) -> None:
        code, output = invoke("validate", str(tmp_path / "absent.yaml"))

        assert code == ExitCode.INVALID_INPUT
        assert "does not exist" in output

    def test_directory_argument_exits_two(self, tmp_path: Path) -> None:
        """A clear message rather than an opaque OSError."""
        code, output = invoke("validate", str(tmp_path))

        assert code == ExitCode.INVALID_INPUT
        assert "is a directory" in output

    def test_oversized_file_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "huge.yaml"
        path.write_bytes(b"#" * (256 * 1024 + 10))

        code, output = invoke("validate", str(path))

        assert code == ExitCode.INVALID_INPUT
        assert "exceeds the" in output

    def test_non_utf8_file_exits_two(self, tmp_path: Path) -> None:
        path = tmp_path / "latin.yaml"
        path.write_bytes(b"name: \xff\xfe\n")

        code, output = invoke("validate", str(path))

        assert code == ExitCode.INVALID_INPUT
        assert "UTF-8" in output

    def test_path_traversal_string_is_not_special_cased(self, tmp_path: Path) -> None:
        """A traversal path is treated as a path: it simply does not exist.

        The CLI deliberately does not restrict paths - it is a local tool. The
        point here is that it fails cleanly rather than crashing or reading
        something unexpected.
        """
        code, output = invoke("validate", str(tmp_path / ".." / ".." / "etc" / "passwd"))

        assert code == ExitCode.INVALID_INPUT
        assert "does not exist" in output or "is a directory" in output


# ---------------------------------------------------------------------------
# Offline: validate-bundle and languages
# ---------------------------------------------------------------------------


class TestValidateBundleCommand:
    """`validate-bundle` reports every bad entry at once."""

    def test_accepts_a_valid_bundle(self, bundle_file: Path) -> None:
        code, output = invoke("validate-bundle", str(bundle_file))

        assert code == ExitCode.OK
        assert "valid:   2" in output

    def test_reports_the_suite_name(self, bundle_file: Path) -> None:
        _, output = invoke("validate-bundle", str(bundle_file))

        assert "CLI bundle" in output

    def test_json_output_is_parsable(self, bundle_file: Path) -> None:
        code, output = invoke("validate-bundle", str(bundle_file), "--json")

        assert code == ExitCode.OK
        payload = json.loads(output)
        assert payload["total"] == 2
        assert payload["valid"] == 2
        assert payload["format"] == BUNDLE_FORMAT

    def test_invalid_entries_exit_two_and_are_all_listed(self, tmp_path: Path) -> None:
        document = yaml.safe_dump(
            {
                "format": BUNDLE_FORMAT,
                "scenarios": [
                    {
                        "name": f"bad_{index}",
                        "language": bad,
                        "persona": {"identity": "C"},
                        "goal": {"objective": "O"},
                        "expected_outcomes": ["E"],
                    }
                    for index, bad in enumerate(("fr-FR", "de-DE"))
                ],
            },
            sort_keys=False,
        )
        path = tmp_path / "bad_bundle.yaml"
        path.write_text(document, encoding="utf-8")

        code, output = invoke("validate-bundle", str(path))

        assert code == ExitCode.INVALID_INPUT
        assert "invalid: 2" in output
        assert "bad_0" in output
        assert "bad_1" in output

    def test_non_bundle_document_exits_two(self, scenario_file: Path) -> None:
        """A single scenario is not a bundle, and the message says so."""
        code, output = invoke("validate-bundle", str(scenario_file))

        assert code == ExitCode.INVALID_INPUT
        assert "format" in output


class TestLanguagesCommand:
    """`languages` must work offline and list the whole catalogue."""

    def test_lists_all_thirteen(self) -> None:
        code, output = invoke("languages")

        assert code == ExitCode.OK
        assert "13 supported languages" in output

    def test_includes_every_code(self) -> None:
        _, output = invoke("languages")

        for code in languages.SUPPORTED_CODES:
            assert code in output

    def test_reports_the_schema_version(self) -> None:
        _, output = invoke("languages")

        assert "scenario schema version" in output

    def test_json_output_is_parsable_and_complete(self) -> None:
        code, output = invoke("languages", "--json")

        assert code == ExitCode.OK
        payload = json.loads(output)
        assert len(payload) == 13
        assert {entry["code"] for entry in payload} == set(languages.SUPPORTED_CODES)
        assert all(entry["endonym"] for entry in payload)


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    """Bad arguments must exit 2, never traceback."""

    def test_invalid_suite_uuid_exits_two(self) -> None:
        code, output = invoke("suite", "show", "not-a-uuid")

        assert code == ExitCode.INVALID_INPUT
        assert "not a valid UUID" in output

    def test_invalid_scenario_uuid_exits_two(self) -> None:
        code, output = invoke("scenario", "show", "12345")

        assert code == ExitCode.INVALID_INPUT
        assert "not a valid UUID" in output

    def test_update_with_no_fields_exits_two(self) -> None:
        """Nothing to do is a usage mistake worth reporting."""
        code, output = invoke("suite", "update", str(uuid.uuid4()))

        assert code == ExitCode.INVALID_INPUT
        assert "nothing to update" in output

    def test_contradictory_description_flags_exit_two(self) -> None:
        code, output = invoke(
            "suite",
            "update",
            str(uuid.uuid4()),
            "--description",
            "x",
            "--clear-description",
        )

        assert code == ExitCode.INVALID_INPUT
        assert "contradictory" in output

    def test_unsupported_language_filter_exits_two(self) -> None:
        code, output = invoke("scenario", "list", "--language", "fr-FR")

        assert code == ExitCode.INVALID_INPUT
        assert "not a supported language" in output

    def test_out_of_range_limit_is_rejected(self) -> None:
        code, _ = invoke("scenario", "list", "--limit", "500")

        assert code != ExitCode.OK


# ---------------------------------------------------------------------------
# Database-backed commands
# ---------------------------------------------------------------------------


class TestSuiteCommands:
    """`suite` commands against the test database."""

    def test_create_then_show(self, cli_db: Session) -> None:
        code, output = invoke("suite", "create", "CLI created", "--json")
        assert code == ExitCode.OK
        suite_id = json.loads(output)["id"]

        code, output = invoke("suite", "show", suite_id, "--json")

        assert code == ExitCode.OK
        assert json.loads(output)["name"] == "CLI created"

    def test_list_reports_scenario_counts(self, cli_db: Session) -> None:
        suite_id = json.loads(invoke("suite", "create", "Counted", "--json")[1])["id"]
        invoke("import", "-", "--suite", suite_id)  # no stdin; just ensure no crash

        code, output = invoke("suite", "list", "--json")

        assert code == ExitCode.OK
        payload = json.loads(output)
        row = next(item for item in payload["suites"] if item["id"] == suite_id)
        assert row["scenarios"] == 0

    def test_duplicate_name_exits_one(self, cli_db: Session) -> None:
        invoke("suite", "create", "Duplicated")

        code, output = invoke("suite", "create", "Duplicated")

        assert code == ExitCode.FAILED
        assert "already exists" in output

    def test_unknown_suite_exits_one(self, cli_db: Session) -> None:
        code, output = invoke("suite", "show", str(uuid.uuid4()))

        assert code == ExitCode.FAILED
        assert "does not exist" in output

    def test_update_renames(self, cli_db: Session) -> None:
        suite_id = json.loads(invoke("suite", "create", "Before", "--json")[1])["id"]

        code, output = invoke("suite", "update", suite_id, "--name", "After", "--json")

        assert code == ExitCode.OK
        assert json.loads(output)["name"] == "After"

    def test_clear_description_removes_it(self, cli_db: Session) -> None:
        suite_id = json.loads(
            invoke("suite", "create", "Described", "--description", "Gone soon", "--json")[1]
        )["id"]

        code, output = invoke("suite", "update", suite_id, "--clear-description", "--json")

        assert code == ExitCode.OK
        assert json.loads(output)["description"] is None

    def test_delete_empty_suite_succeeds(self, cli_db: Session) -> None:
        suite_id = json.loads(invoke("suite", "create", "Disposable", "--json")[1])["id"]

        code, output = invoke("suite", "delete", suite_id)

        assert code == ExitCode.OK
        assert "deleted suite" in output

    def test_delete_non_empty_suite_is_refused(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Occupied", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)

        code, output = invoke("suite", "delete", suite_id)

        assert code == ExitCode.FAILED
        assert "still contains" in output

    def test_refusal_names_the_flag_and_not_the_query_parameter(
        self, cli_db: Session, bundle_file: Path
    ) -> None:
        """The remedy has to be the one this front end actually accepts.

        The same service refusal is surfaced over HTTP, where the opt-in is
        `?cascade=true`. Printing that here would send a shell user looking for
        a flag the CLI does not have.
        """
        suite_id = json.loads(invoke("suite", "create", "Worded", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)

        _, output = invoke("suite", "delete", suite_id)

        assert "--cascade" in output
        assert "cascade=true" not in output

    def test_cascade_delete_removes_scenarios(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Cascaded", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)

        code, output = invoke("suite", "delete", suite_id, "--cascade", "--json")

        assert code == ExitCode.OK
        assert json.loads(output)["scenarios_deleted"] == 2


class TestImportExportCommands:
    """`import` and `export` round-trip through the database."""

    def test_dry_run_writes_nothing(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Dry", "--json")[1])["id"]

        code, output = invoke(
            "import", str(bundle_file), "--suite", suite_id, "--dry-run", "--json"
        )

        assert code == ExitCode.OK
        payload = json.loads(output)
        assert payload["valid"] == 2
        assert payload["imported"] == 0
        assert payload["committed"] is False

    def test_import_persists(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Importing", "--json")[1])["id"]

        code, output = invoke("import", str(bundle_file), "--suite", suite_id, "--json")

        assert code == ExitCode.OK
        payload = json.loads(output)
        assert payload["imported"] == 2
        assert payload["committed"] is True

    def test_duplicate_import_exits_two_and_imports_nothing(
        self, cli_db: Session, bundle_file: Path
    ) -> None:
        suite_id = json.loads(invoke("suite", "create", "Twice", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)

        code, output = invoke("import", str(bundle_file), "--suite", suite_id, "--json")

        assert code == ExitCode.INVALID_INPUT
        payload = json.loads(output)
        assert payload["imported"] == 0
        assert len(payload["duplicates"]) == 2

    def test_export_to_stdout_is_a_valid_bundle(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Exporting", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)

        code, output = invoke("export", suite_id)

        assert code == ExitCode.OK
        document = yaml.safe_load(output)
        assert document["format"] == BUNDLE_FORMAT
        assert len(document["scenarios"]) == 2

    def test_export_to_a_file(self, cli_db: Session, bundle_file: Path, tmp_path: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "File export", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)
        destination = tmp_path / "out.yaml"

        code, _ = invoke("export", suite_id, "--output", str(destination))

        assert code == ExitCode.OK
        assert yaml.safe_load(destination.read_text(encoding="utf-8"))["format"] == BUNDLE_FORMAT

    def test_export_to_a_missing_directory_exits_two(self, cli_db: Session, tmp_path: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Bad dest", "--json")[1])["id"]

        code, output = invoke("export", suite_id, "--output", str(tmp_path / "nope" / "out.yaml"))

        assert code == ExitCode.INVALID_INPUT
        assert "not an existing directory" in output

    def test_round_trip_through_the_cli(
        self, cli_db: Session, bundle_file: Path, tmp_path: Path
    ) -> None:
        """Export then import into a fresh suite must preserve meaning."""
        source = json.loads(invoke("suite", "create", "RT source", "--json")[1])["id"]
        target = json.loads(invoke("suite", "create", "RT target", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", source)
        exported = tmp_path / "rt.yaml"
        invoke("export", source, "--output", str(exported))

        code, _ = invoke("import", str(exported), "--suite", target)

        assert code == ExitCode.OK
        again = tmp_path / "rt2.yaml"
        invoke("export", target, "--output", str(again))
        first = yaml.safe_load(exported.read_text(encoding="utf-8"))["scenarios"]
        second = yaml.safe_load(again.read_text(encoding="utf-8"))["scenarios"]
        assert first == second

    def test_import_into_unknown_suite_exits_one(self, cli_db: Session, bundle_file: Path) -> None:
        code, output = invoke("import", str(bundle_file), "--suite", str(uuid.uuid4()))

        assert code == ExitCode.FAILED
        assert "does not exist" in output


class TestScenarioCommands:
    """`scenario` list / show / copy / move."""

    def test_list_filters_by_suite(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Listing", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)

        code, output = invoke("scenario", "list", "--suite", suite_id, "--json")

        assert code == ExitCode.OK
        assert json.loads(output)["total"] == 2

    def test_show_as_yaml_is_reimportable(self, cli_db: Session, bundle_file: Path) -> None:
        suite_id = json.loads(invoke("suite", "create", "Showing", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", suite_id)
        listing = json.loads(invoke("scenario", "list", "--suite", suite_id, "--json")[1])
        scenario_id = listing["scenarios"][0]["id"]

        code, output = invoke("scenario", "show", scenario_id, "--yaml")

        assert code == ExitCode.OK
        assert yaml.safe_load(output)["name"].startswith("cli_entry_")

    def test_copy_creates_a_new_id(self, cli_db: Session, bundle_file: Path) -> None:
        source = json.loads(invoke("suite", "create", "Copy src", "--json")[1])["id"]
        target = json.loads(invoke("suite", "create", "Copy dst", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", source)
        listing = json.loads(invoke("scenario", "list", "--suite", source, "--json")[1])
        scenario_id = listing["scenarios"][0]["id"]

        code, output = invoke("scenario", "copy", scenario_id, "--to-suite", target, "--json")

        assert code == ExitCode.OK
        copy = json.loads(output)
        assert copy["id"] != scenario_id
        assert copy["suite_id"] == target

    def test_move_preserves_the_id(self, cli_db: Session, bundle_file: Path) -> None:
        source = json.loads(invoke("suite", "create", "Move src", "--json")[1])["id"]
        target = json.loads(invoke("suite", "create", "Move dst", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", source)
        listing = json.loads(invoke("scenario", "list", "--suite", source, "--json")[1])
        scenario_id = listing["scenarios"][0]["id"]

        code, output = invoke("scenario", "move", scenario_id, "--to-suite", target, "--json")

        assert code == ExitCode.OK
        moved = json.loads(output)
        assert moved["id"] == scenario_id
        assert moved["suite_id"] == target

    def test_copy_name_clash_exits_one(self, cli_db: Session, bundle_file: Path) -> None:
        source = json.loads(invoke("suite", "create", "Clash src", "--json")[1])["id"]
        target = json.loads(invoke("suite", "create", "Clash dst", "--json")[1])["id"]
        invoke("import", str(bundle_file), "--suite", source)
        invoke("import", str(bundle_file), "--suite", target)
        listing = json.loads(invoke("scenario", "list", "--suite", source, "--json")[1])
        scenario_id = listing["scenarios"][0]["id"]

        code, output = invoke("scenario", "copy", scenario_id, "--to-suite", target)

        assert code == ExitCode.FAILED
        assert "already exists" in output

    def test_unknown_scenario_exits_one(self, cli_db: Session) -> None:
        code, output = invoke("scenario", "show", str(uuid.uuid4()))

        assert code == ExitCode.FAILED
        assert "does not exist" in output


class TestNoSecretsInOutput:
    """The CLI must never print a credential."""

    def test_database_url_is_not_echoed_on_success(
        self, cli_db: Session, bundle_file: Path
    ) -> None:
        suite_id = json.loads(invoke("suite", "create", "Quiet", "--json")[1])["id"]

        _, output = invoke("import", str(bundle_file), "--suite", suite_id)

        assert "postgresql" not in output.lower()
        assert "password" not in output.lower()

    def test_connection_failure_message_names_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The driver's own message can contain the DSN; ours must not."""
        from sqlalchemy.exc import OperationalError

        def exploding_scope() -> Iterator[Session]:
            raise OperationalError(
                "SELECT 1", {}, Exception("password authentication failed for secret-user")
            )

        from contextlib import contextmanager

        monkeypatch.setattr("app.cli.main.session_scope", contextmanager(exploding_scope))

        code, output = invoke("suite", "list")

        assert code == ExitCode.DATABASE_UNAVAILABLE
        assert "cannot reach the database" in output
        assert "secret-user" not in output
