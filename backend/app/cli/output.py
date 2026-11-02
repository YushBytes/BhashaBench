"""Shared output and exit-code helpers for the CLI.

Kept separate so every command formats errors the same way, and so the exit
codes live in one place rather than as scattered magic numbers.
"""

from __future__ import annotations

import contextlib
import json
import sys
from enum import IntEnum
from pathlib import Path
from typing import Any

import typer

from app.services.scenario_loader import (
    MAX_YAML_BYTES,
    FieldError,
    ScenarioLoadError,
    ScenarioValidationError,
)


class ExitCode(IntEnum):
    """Process exit codes.

    Distinguished rather than collapsed into 1, because a shell script wants
    to retry a database outage and not a malformed file.
    """

    OK = 0
    FAILED = 1
    """The operation was understood but could not be completed: not found,
    name conflict, deletion refused."""
    INVALID_INPUT = 2
    """The input was rejected: unparseable YAML, failed validation, bad
    arguments."""
    DATABASE_UNAVAILABLE = 3
    """The database could not be reached."""


def fail(message: str, code: ExitCode = ExitCode.FAILED) -> None:
    """Print an error to stderr and exit with `code`.

    stderr rather than stdout so that `--json` output stays machine-parsable
    even when a command fails.
    """
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(int(code))


def emit_json(payload: Any) -> None:
    """Print a payload as JSON on stdout.

    `default=str` so UUIDs and datetimes serialise without each caller having
    to convert them.
    """
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def print_field_errors(errors: list[FieldError], *, prefix: str = "  ") -> None:
    """Print validation failures as `field: message`, one per line."""
    for error in errors:
        typer.echo(f"{prefix}{error.field}: {error.message}", err=True)


def read_yaml_file(path: Path) -> str:
    """Read a YAML file for the parser, with the checks a CLI owes its user.

    Resolves the path and confirms it is a regular file before reading, so a
    directory or a dangling symlink produces a clear message rather than an
    opaque OSError. The size is checked via `stat` first so an oversized file
    is refused without being pulled into memory.

    No path restriction is applied: this is a local tool run by the person who
    owns the shell, and refusing to read a file they named would be wrong. The
    API, where input *is* untrusted, never takes a path at all - it accepts
    the document in the request body.
    """
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        fail(f"cannot resolve {path}: {exc.strerror}", ExitCode.INVALID_INPUT)
        raise AssertionError("unreachable") from exc  # pragma: no cover

    if not resolved.exists():
        fail(f"{resolved} does not exist", ExitCode.INVALID_INPUT)
    if resolved.is_dir():
        fail(f"{resolved} is a directory, not a file", ExitCode.INVALID_INPUT)
    if not resolved.is_file():
        fail(f"{resolved} is not a regular file", ExitCode.INVALID_INPUT)

    size = resolved.stat().st_size
    if size > MAX_YAML_BYTES:
        fail(
            f"{resolved.name} is {size} bytes, which exceeds the {MAX_YAML_BYTES}-byte limit",
            ExitCode.INVALID_INPUT,
        )

    try:
        return resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        fail(f"{resolved.name} is not valid UTF-8", ExitCode.INVALID_INPUT)
        raise AssertionError("unreachable") from exc  # pragma: no cover
    except OSError as exc:
        fail(f"cannot read {resolved.name}: {exc.strerror}", ExitCode.INVALID_INPUT)
        raise AssertionError("unreachable") from exc  # pragma: no cover


def write_output(content: str, destination: Path | None) -> None:
    """Write content to a file, or to stdout when no destination is given.

    Defaulting to stdout makes the command pipeable; `--output` is for when
    the user wants a file. The parent directory must already exist - creating
    directories implicitly on the strength of a typo is not helpful.
    """
    if destination is None:
        typer.echo(content)
        return

    resolved = destination.expanduser().resolve()
    if not resolved.parent.is_dir():
        fail(f"{resolved.parent} is not an existing directory", ExitCode.INVALID_INPUT)

    try:
        resolved.write_text(content, encoding="utf-8")
    except OSError as exc:
        fail(f"cannot write {resolved}: {exc.strerror}", ExitCode.FAILED)

    typer.echo(f"wrote {resolved}", err=True)


def handle_load_error(exc: ScenarioLoadError) -> None:
    """Report a parser or validation failure and exit with code 2.

    A `ScenarioValidationError` already embeds the first few field errors in
    its message, for consumers that have nothing but a message to show. The
    CLI has room for the whole list, so here the headline is printed alone and
    every failure listed beneath it - printing the message as-is and then the
    list showed the first five twice.
    """
    if isinstance(exc, ScenarioValidationError):
        typer.echo(f"error: {ScenarioValidationError.HEADLINE}:", err=True)
        print_field_errors(exc.errors)
    else:
        typer.echo(f"error: {exc}", err=True)

    raise typer.Exit(int(ExitCode.INVALID_INPUT))


def stdin_text() -> str:
    """Read the whole of stdin, for `-` as a filename."""
    return sys.stdin.read()


def configure_streams() -> None:
    """Make stdout/stderr able to carry non-ASCII text.

    The catalogue prints endonyms in Devanagari, Tamil, Bengali and Arabic
    script. On a Windows console the default encoding is still a legacy
    code page (cp1252 here), and writing `हिन्दी` to it raises
    UnicodeEncodeError - the command crashed with a traceback rather than
    printing a language list.

    Reconfiguring to UTF-8 fixes it where the terminal supports UTF-8, and
    `errors="replace"` degrades to placeholder characters rather than an
    exception where it does not. Printing a `?` is a cosmetic problem;
    crashing is not.

    Only called from the console entry point, so a test harness that captures
    output keeps its own streams.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # An exotic stream may refuse; a cosmetic encoding tweak must never
            # be the reason a command fails.
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")
