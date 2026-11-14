"""CLI command definitions.

Every command delegates to the same service functions the API routes call.
Where a command needs a database it borrows `session_scope` from
`app.db.session`, so configuration and connection handling have exactly one
implementation.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typer.core import TyperGroup

from app.cli.output import (
    ExitCode,
    configure_streams,
    emit_json,
    fail,
    handle_load_error,
    print_field_errors,
    read_yaml_file,
    stdin_text,
    write_output,
)
from app.core import languages
from app.core.config import get_settings
from app.db.session import session_scope
from app.pipeline import recovery
from app.schemas.scenario_spec import SPEC_VERSION, ScenarioSpec
from app.services import scenario_service, suite_service
from app.services.bundle import BUNDLE_FORMAT, parse_bundle
from app.services.errors import ConflictError, NotFoundError
from app.services.scenario_loader import ScenarioLoadError, spec_from_yaml, spec_to_yaml
from app.utils.timing import utc_now


class DomainErrorGroup(TyperGroup):
    """Translate service-layer domain errors into a message and an exit code.

    This lives in the command group rather than in `main` so the translation
    applies however the CLI is entered - the console script, `python -m
    app.cli`, or a harness driving the Click object directly. Doing it only in
    `main` meant the exit codes a shell script sees could differ from the ones
    exercised in tests, which is exactly the gap that makes exit codes
    untrustworthy.

    Only errors a user can act on are caught. Anything else keeps its
    traceback, because a bug should look like a bug.
    """

    def invoke(self, ctx: typer.Context) -> Any:
        try:
            return super().invoke(ctx)
        except (NotFoundError, ConflictError) as exc:
            fail(str(exc), ExitCode.FAILED)
        except ScenarioLoadError as exc:
            fail(str(exc), ExitCode.INVALID_INPUT)


app = typer.Typer(
    name="bhashabench",
    help=(
        "BhashaBench - Indian-language voice bot test bench.\n\n"
        "Scenario validation and the language catalogue work offline. Suite and "
        "scenario commands need the configured PostgreSQL."
    ),
    no_args_is_help=True,
    add_completion=False,
    cls=DomainErrorGroup,
)

suite_app = typer.Typer(help="Manage test suites.", no_args_is_help=True)
scenario_app = typer.Typer(help="Manage scenarios.", no_args_is_help=True)
runs_app = typer.Typer(help="Inspect and maintain test runs.", no_args_is_help=True)
app.add_typer(suite_app, name="suite")
app.add_typer(scenario_app, name="scenario")
app.add_typer(runs_app, name="runs")

JsonFlag = Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")]


@contextmanager
def _session() -> Iterator[Session]:
    """Open a database session, reporting an outage as exit code 3.

    A connection failure is not the user's mistake, so it gets its own exit
    code and a message that says what to do - rather than a SQLAlchemy
    traceback. The driver's message is deliberately not echoed: it can contain
    the connection URL, and therefore the password.
    """
    try:
        with session_scope() as session:
            yield session
    except (NotFoundError, ConflictError, ScenarioLoadError, typer.Exit):
        raise
    except SQLAlchemyError as exc:
        fail(
            f"cannot reach the database ({type(exc).__name__}). Check DATABASE_URL, "
            "or start it with: docker compose up -d db",
            ExitCode.DATABASE_UNAVAILABLE,
        )


def _read_source(source: str) -> str:
    """Read YAML from a path, or from stdin when `source` is `-`."""
    return stdin_text() if source == "-" else read_yaml_file(Path(source))


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    """Parse a UUID argument, failing with exit code 2 rather than a traceback."""
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        fail(f"{label} '{value}' is not a valid UUID", ExitCode.INVALID_INPUT)
        raise AssertionError("unreachable") from exc  # pragma: no cover


# ---------------------------------------------------------------------------
# Offline commands
# ---------------------------------------------------------------------------


@app.command("validate")
def validate_scenario(
    source: Annotated[str, typer.Argument(help="Scenario YAML file, or '-' to read stdin.")],
    as_json: JsonFlag = False,
    show_normalized: Annotated[
        bool,
        typer.Option("--show-normalized", help="Print the canonical YAML on success."),
    ] = False,
) -> None:
    """Validate one scenario file. Needs no database."""
    content = _read_source(source)

    try:
        spec = spec_from_yaml(content)
    except ScenarioLoadError as exc:
        if as_json:
            errors = getattr(exc, "errors", [])
            emit_json(
                {
                    "valid": False,
                    "error": str(exc),
                    "errors": [error.as_dict() for error in errors],
                }
            )
            raise typer.Exit(int(ExitCode.INVALID_INPUT)) from exc
        handle_load_error(exc)

    if as_json:
        emit_json({"valid": True, "scenario": spec.model_dump(mode="json")})
        return

    typer.echo(f"valid: {spec.name}")
    typer.echo(f"  language: {spec.language} ({languages.get(spec.language).name})")
    typer.echo(f"  outcomes: {len(spec.expected_outcomes)}")
    if spec.tags:
        typer.echo(f"  tags:     {', '.join(spec.tags)}")
    if spec.code_mixing is not None:
        secondary = ", ".join(spec.code_mixing.secondary)
        # `expected: false` asserts the caller stays monolingual, so printing
        # "hi-IN + en-IN" there would state the opposite of what the scenario
        # checks. The secondary languages are still named, because they are
        # the ones being asserted absent.
        if spec.code_mixing.expected:
            typer.echo(f"  mixing:   {spec.language} + {secondary}")
        else:
            typer.echo(f"  mixing:   none expected ({secondary} asserted absent)")
    if show_normalized:
        typer.echo("")
        typer.echo(spec_to_yaml(spec))


@app.command("validate-bundle")
def validate_bundle(
    source: Annotated[str, typer.Argument(help="Bundle YAML file, or '-' for stdin.")],
    as_json: JsonFlag = False,
) -> None:
    """Validate a scenario bundle. Needs no database.

    Reports every invalid entry rather than stopping at the first, so one run
    gives the whole list of problems.
    """
    content = _read_source(source)

    try:
        parsed = parse_bundle(content)
    except ScenarioLoadError as exc:
        handle_load_error(exc)
        return

    payload = {
        "format": BUNDLE_FORMAT,
        "total": parsed.total,
        "valid": len(parsed.specs),
        "invalid": len(parsed.entry_errors),
        "suite": {"name": parsed.suite.name, "description": parsed.suite.description},
        "entry_errors": [error.as_dict() for error in parsed.entry_errors],
    }

    if as_json:
        emit_json(payload)
    else:
        typer.echo(f"bundle: {parsed.total} entr{'y' if parsed.total == 1 else 'ies'}")
        typer.echo(f"  valid:   {len(parsed.specs)}")
        typer.echo(f"  invalid: {len(parsed.entry_errors)}")
        if parsed.suite.name:
            typer.echo(f"  suite:   {parsed.suite.name}")
        for entry in parsed.entry_errors:
            label = entry.name or "<unnamed>"
            typer.echo(f"\n  entry {entry.index} ({label}):", err=True)
            print_field_errors(entry.errors, prefix="    ")

    if parsed.entry_errors:
        raise typer.Exit(int(ExitCode.INVALID_INPUT))


@app.command("languages")
def list_languages(as_json: JsonFlag = False) -> None:
    """List the supported Indian languages. Needs no database."""
    if as_json:
        emit_json(
            [
                {
                    "code": language.code,
                    "name": language.name,
                    "endonym": language.endonym,
                    "script": language.script,
                    "locale": language.locale,
                }
                for language in languages.CATALOGUE
            ]
        )
        return

    typer.echo(f"{len(languages.CATALOGUE)} supported languages:")
    for language in languages.CATALOGUE:
        typer.echo(f"  {language.code:7} {language.name:16} {language.endonym}")
    typer.echo("")
    typer.echo(f"scenario schema version: {SPEC_VERSION}")


# ---------------------------------------------------------------------------
# Suite commands
# ---------------------------------------------------------------------------


@suite_app.command("list")
def suite_list(
    limit: Annotated[int, typer.Option(min=1, max=100, help="Page size.")] = 20,
    offset: Annotated[int, typer.Option(min=0, help="Items to skip.")] = 0,
    as_json: JsonFlag = False,
) -> None:
    """List test suites."""
    with _session() as session:
        suites, total = suite_service.list_suites(session, limit=limit, offset=offset)
        rows = [
            {
                "id": str(suite.id),
                "name": suite.name,
                "description": suite.description,
                "scenarios": suite_service.count_scenarios(session, suite.id),
            }
            for suite in suites
        ]

    if as_json:
        emit_json({"total": total, "limit": limit, "offset": offset, "suites": rows})
        return

    typer.echo(f"{total} suite(s), showing {len(rows)}:")
    for row in rows:
        typer.echo(f"  {row['id']}  {row['name']}  ({row['scenarios']} scenario(s))")


@suite_app.command("show")
def suite_show(
    suite_id: Annotated[str, typer.Argument(help="Suite UUID.")],
    as_json: JsonFlag = False,
) -> None:
    """Show one suite."""
    identifier = _parse_uuid(suite_id, "suite id")

    with _session() as session:
        suite = suite_service.get_suite(session, identifier)
        count = suite_service.count_scenarios(session, identifier)
        row = {
            "id": str(suite.id),
            "name": suite.name,
            "description": suite.description,
            "scenarios": count,
            "created_at": suite.created_at,
            "updated_at": suite.updated_at,
        }

    if as_json:
        emit_json(row)
        return

    typer.echo(f"{row['name']}  ({row['id']})")
    typer.echo(f"  description: {row['description'] or '-'}")
    typer.echo(f"  scenarios:   {row['scenarios']}")
    typer.echo(f"  created:     {row['created_at']}")


@suite_app.command("create")
def suite_create(
    name: Annotated[str, typer.Argument(help="Suite name. Must be unique.")],
    description: Annotated[str | None, typer.Option(help="Optional description.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Create a suite."""
    with _session() as session:
        suite = suite_service.create_suite(session, name=name, description=description)
        row = {"id": str(suite.id), "name": suite.name, "description": suite.description}

    if as_json:
        emit_json(row)
    else:
        typer.echo(f"created suite {row['id']}  {row['name']}")


@suite_app.command("update")
def suite_update(
    suite_id: Annotated[str, typer.Argument(help="Suite UUID.")],
    name: Annotated[str | None, typer.Option(help="New name.")] = None,
    description: Annotated[str | None, typer.Option(help="New description.")] = None,
    clear_description: Annotated[
        bool, typer.Option("--clear-description", help="Remove the description.")
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """Update a suite's name or description."""
    identifier = _parse_uuid(suite_id, "suite id")

    if name is None and description is None and not clear_description:
        fail(
            "nothing to update: pass --name, --description or --clear-description",
            ExitCode.INVALID_INPUT,
        )
    if description is not None and clear_description:
        fail(
            "--description and --clear-description are contradictory",
            ExitCode.INVALID_INPUT,
        )

    with _session() as session:
        suite = suite_service.update_suite(
            session,
            identifier,
            name=name,
            description=description,
            clear_description=clear_description,
        )
        row = {"id": str(suite.id), "name": suite.name, "description": suite.description}

    if as_json:
        emit_json(row)
    else:
        typer.echo(f"updated suite {row['id']}  {row['name']}")


@suite_app.command("delete")
def suite_delete(
    suite_id: Annotated[str, typer.Argument(help="Suite UUID.")],
    cascade: Annotated[
        bool,
        typer.Option("--cascade", help="Also delete the suite's scenarios."),
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """Delete a suite.

    Refuses a non-empty suite unless `--cascade` is given, because the
    database-level cascade would otherwise remove every scenario in it
    silently.
    """
    identifier = _parse_uuid(suite_id, "suite id")

    with _session() as session:
        deleted = suite_service.delete_suite(
            session, identifier, cascade=cascade, cascade_remedy="pass --cascade"
        )

    if as_json:
        emit_json({"suite_id": str(identifier), "scenarios_deleted": deleted})
    else:
        typer.echo(f"deleted suite {identifier} ({deleted} scenario(s) removed)")


# ---------------------------------------------------------------------------
# Scenario commands
# ---------------------------------------------------------------------------


@scenario_app.command("list")
def scenario_list(
    suite: Annotated[str | None, typer.Option(help="Restrict to this suite UUID.")] = None,
    language: Annotated[str | None, typer.Option(help="Exact language tag.")] = None,
    name: Annotated[str | None, typer.Option(help="Substring of the name.")] = None,
    tag: Annotated[list[str] | None, typer.Option(help="Require this tag. Repeatable.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=100, help="Page size.")] = 20,
    offset: Annotated[int, typer.Option(min=0, help="Items to skip.")] = 0,
    as_json: JsonFlag = False,
) -> None:
    """Search the scenario library."""
    suite_identifier = _parse_uuid(suite, "suite id") if suite else None

    if language is not None and not languages.is_supported(language):
        fail(
            f"'{language}' is not a supported language; see 'bhashabench languages'",
            ExitCode.INVALID_INPUT,
        )

    with _session() as session:
        scenarios, total = scenario_service.search_scenarios(
            session,
            suite_id=suite_identifier,
            language=language,
            name_contains=name,
            tags=tag,
            limit=limit,
            offset=offset,
        )
        rows = [
            {
                "id": str(scenario.id),
                "suite_id": str(scenario.suite_id),
                "name": scenario.name,
                "language": scenario.language,
            }
            for scenario in scenarios
        ]

    if as_json:
        emit_json({"total": total, "limit": limit, "offset": offset, "scenarios": rows})
        return

    typer.echo(f"{total} scenario(s) matched, showing {len(rows)}:")
    for row in rows:
        typer.echo(f"  {row['id']}  {row['language']:7} {row['name']}")


@scenario_app.command("show")
def scenario_show(
    scenario_id: Annotated[str, typer.Argument(help="Scenario UUID.")],
    as_yaml: Annotated[
        bool, typer.Option("--yaml", help="Print the scenario as canonical YAML.")
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """Show one scenario."""
    identifier = _parse_uuid(scenario_id, "scenario id")

    with _session() as session:
        scenario = scenario_service.get_scenario(session, identifier)
        spec = ScenarioSpec.model_validate(scenario.spec)
        meta = {
            "id": str(scenario.id),
            "suite_id": str(scenario.suite_id),
            "spec_version": scenario.spec_version,
        }

    if as_yaml:
        typer.echo(spec_to_yaml(spec))
        return
    if as_json:
        emit_json({**meta, "scenario": spec.model_dump(mode="json")})
        return

    typer.echo(f"{spec.name}  ({meta['id']})")
    typer.echo(f"  suite:    {meta['suite_id']}")
    typer.echo(f"  language: {spec.language}")
    typer.echo(f"  version:  spec v{meta['spec_version']}")
    typer.echo(f"  tags:     {', '.join(spec.tags) or '-'}")


@scenario_app.command("copy")
def scenario_copy(
    scenario_id: Annotated[str, typer.Argument(help="Scenario UUID.")],
    to_suite: Annotated[str, typer.Option("--to-suite", help="Destination suite UUID.")],
    new_name: Annotated[str | None, typer.Option(help="Name for the copy.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Copy a scenario into another suite."""
    identifier = _parse_uuid(scenario_id, "scenario id")
    target = _parse_uuid(to_suite, "suite id")

    with _session() as session:
        copy = scenario_service.copy_scenario(
            session, identifier, target_suite_id=target, new_name=new_name
        )
        row = {"id": str(copy.id), "suite_id": str(copy.suite_id), "name": copy.name}

    if as_json:
        emit_json(row)
    else:
        typer.echo(f"copied to {row['id']}  {row['name']}  in suite {row['suite_id']}")


@scenario_app.command("move")
def scenario_move(
    scenario_id: Annotated[str, typer.Argument(help="Scenario UUID.")],
    to_suite: Annotated[str, typer.Option("--to-suite", help="Destination suite UUID.")],
    new_name: Annotated[str | None, typer.Option(help="Rename while moving.")] = None,
    as_json: JsonFlag = False,
) -> None:
    """Move a scenario to another suite, keeping its id."""
    identifier = _parse_uuid(scenario_id, "scenario id")
    target = _parse_uuid(to_suite, "suite id")

    with _session() as session:
        moved = scenario_service.move_scenario(
            session, identifier, target_suite_id=target, new_name=new_name
        )
        row = {"id": str(moved.id), "suite_id": str(moved.suite_id), "name": moved.name}

    if as_json:
        emit_json(row)
    else:
        typer.echo(f"moved {row['id']}  {row['name']}  to suite {row['suite_id']}")


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------


@app.command("import")
def import_bundle(
    source: Annotated[str, typer.Argument(help="Bundle YAML file, or '-' for stdin.")],
    suite: Annotated[str, typer.Option("--suite", help="Destination suite UUID.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would happen without writing."),
    ] = False,
    non_atomic: Annotated[
        bool,
        typer.Option(
            "--non-atomic",
            help="Import the valid entries instead of abandoning the whole batch.",
        ),
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """Import a scenario bundle into a suite.

    Atomic by default: one bad or duplicate entry abandons the import.
    """
    target = _parse_uuid(suite, "suite id")
    content = _read_source(source)

    with _session() as session:
        result = scenario_service.import_bundle(
            session,
            suite_id=target,
            content=content,
            dry_run=dry_run,
            atomic=not non_atomic,
        )

    payload = {
        "total": result.total,
        "valid": result.valid,
        "imported": result.imported,
        "failed": result.failed,
        "duplicates": result.duplicates,
        "entry_errors": [error.as_dict() for error in result.entry_errors],
        "dry_run": result.dry_run,
        "committed": result.committed,
    }

    if as_json:
        emit_json(payload)
    else:
        mode = "dry run" if result.dry_run else "import"
        typer.echo(f"{mode}: {result.total} entr{'y' if result.total == 1 else 'ies'}")
        typer.echo(f"  valid:      {result.valid}")
        typer.echo(f"  imported:   {result.imported}")
        typer.echo(f"  failed:     {result.failed}")
        typer.echo(f"  committed:  {result.committed}")
        if result.duplicates:
            typer.echo(f"  duplicates: {', '.join(result.duplicates)}", err=True)
        for entry in result.entry_errors:
            typer.echo(f"\n  entry {entry.index} ({entry.name or '<unnamed>'}):", err=True)
            print_field_errors(entry.errors, prefix="    ")

    # A dry run that found problems, or an atomic import that was abandoned,
    # is a failure from a script's point of view even though the command ran.
    if result.failed:
        raise typer.Exit(int(ExitCode.INVALID_INPUT))


@app.command("export")
def export_suite(
    suite: Annotated[str, typer.Argument(help="Suite UUID to export.")],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write here instead of stdout.")
    ] = None,
) -> None:
    """Export a suite as a re-importable scenario bundle."""
    identifier = _parse_uuid(suite, "suite id")

    with _session() as session:
        document = scenario_service.export_suite(session, identifier)

    write_output(document, output)


# ---------------------------------------------------------------------------
# Run maintenance
# ---------------------------------------------------------------------------

_DURATION = re.compile(r"^\s*(\d+)\s*([smhd])\s*$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _parse_duration(value: str) -> timedelta:
    """Parse `90s`, `30m`, `6h` or `2d`, failing with exit code 2."""
    match = _DURATION.match(value.lower())
    if match is None:
        fail(
            f"--older-than '{value}' is not a duration; use a number and a unit, "
            "e.g. 30m, 6h or 2d",
            ExitCode.INVALID_INPUT,
        )
        raise AssertionError("unreachable")  # pragma: no cover
    return timedelta(seconds=int(match.group(1)) * _UNIT_SECONDS[match.group(2)])


@runs_app.command("recover-stale")
def runs_recover_stale(
    older_than: Annotated[
        str,
        typer.Option(
            "--older-than",
            help="Idle time before a run counts as abandoned, e.g. 6h or 2d. "
            "May not be shorter than PIPELINE_RUN_TIMEOUT_SECONDS.",
        ),
    ],
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Close the runs listed. Without it nothing changes."),
    ] = False,
    as_json: JsonFlag = False,
) -> None:
    """List runs left in flight with nothing executing them; close them with --apply.

    A dry run by default: it reads and reports, and changes nothing. Runs
    waiting for an operator are never listed. With --apply each listed run is
    finished as `failed` with outcome `abandoned`; its turns, events and
    artefacts are kept untouched and a `recovery` event records what happened.
    """
    threshold = _parse_duration(older_than)
    ceiling = get_settings().pipeline_run_timeout_seconds
    if threshold.total_seconds() < ceiling:
        fail(
            f"--older-than must be at least PIPELINE_RUN_TIMEOUT_SECONDS ({ceiling:g}s): "
            "a run quieter than that may still be executing inside a request",
            ExitCode.INVALID_INPUT,
        )

    now = utc_now()
    with _session() as session:
        stale = recovery.find_stale_runs(session, older_than=threshold, now=now)
        rows = [
            {
                "run_id": str(item.run.id),
                "scenario": item.scenario_name,
                "mode": item.mode,
                "status": item.pipeline_status,
                "last_activity_at": item.last_activity_at.isoformat(),
                "idle_hours": round(item.idle.total_seconds() / 3600, 1),
            }
            for item in stale
        ]
        if apply:
            for item in stale:
                recovery.abandon(session, item, now=now)
        elif session.new or session.dirty or session.deleted:
            # A dry run must not persist anything. If a later change ever made
            # the read path touch a row, fail loudly before the scope commits
            # rather than quietly writing.
            raise RuntimeError("recover-stale dry run attempted to modify the database")

    if as_json:
        emit_json({"applied": apply, "older_than_seconds": threshold.total_seconds(), "runs": rows})
        return
    if not rows:
        typer.echo("no abandoned runs found")
        return
    for row in rows:
        typer.echo(
            f"{row['run_id']}  {row['scenario']}  {row['mode']}  {row['status']}  "
            f"idle {row['idle_hours']}h since {row['last_activity_at']}"
        )
    if apply:
        typer.echo(f"closed {len(rows)} run(s) as abandoned")
    else:
        typer.echo(
            f"DRY RUN: {len(rows)} run(s) would be closed. "
            "Nothing was changed; re-run with --apply."
        )


def main() -> None:
    """Console-script entry point.

    Does nothing but prepare the output streams: domain errors are translated
    by `DomainErrorGroup`, inside the app, so this wrapper and a test harness
    behave identically.
    """
    configure_streams()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
