"""YAML loading and validation for scenario definitions.

This module does three things and nothing else: read YAML safely, validate it
against `ScenarioSpec`, and serialise a spec back to YAML. It has no database
or HTTP awareness, so the same code path serves the API, a future CLI and the
test suite.

**Security.** YAML is parsed only with `yaml.safe_load`. `yaml.load` with the
default loader can construct arbitrary Python objects from tags such as
`!!python/object/apply:os.system`, which turns a scenario file into remote code
execution. `safe_load` restricts construction to plain scalars, lists and
dicts, and raises on any unknown tag.

**Resource limits.** Input is size-capped before parsing, because a parser is
happy to build a structure far larger than its input (the "billion laughs"
pattern uses YAML anchors and aliases to expand a few hundred bytes into
gigabytes). Node count and nesting depth are checked after parsing, which
bounds alias expansion that stays under the byte cap.

**Cyclic aliases.** `safe_load` is safe from code execution but will still
build a *cyclic* object graph from a recursive alias, which naive traversal
walks forever. `_measure` therefore tracks object identity along its active
recursion path and rejects a cycle explicitly, rather than relying on the
depth limit to trip first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas.scenario_spec import ScenarioSpec

# 256 KiB. A legitimate scenario is a few kilobytes; this leaves generous room
# for a heavily commented one while refusing anything pathological.
MAX_YAML_BYTES = 256 * 1024

# Guards against anchor/alias expansion that slips under the byte cap.
MAX_YAML_NODES = 10_000
MAX_YAML_DEPTH = 20


class ScenarioLoadError(Exception):
    """Base class for every failure in this module."""


class ScenarioTooLargeError(ScenarioLoadError):
    """Input exceeded a size, node-count or nesting limit."""


class ScenarioSyntaxError(ScenarioLoadError):
    """Input was not well-formed YAML, or used an unsafe construct."""


class ScenarioRecursionError(ScenarioSyntaxError):
    """Input contained a recursive (cyclic) alias.

    A subclass of `ScenarioSyntaxError` rather than a new top-level error: a
    cycle is a malformed document, and inheriting means the existing
    `ScenarioSyntaxError` exception handler already maps it to HTTP 422
    `yaml_syntax_error`. Callers that want to distinguish a cycle can catch
    this specific type; the public API shape is unchanged.
    """


class ScenarioValidationError(ScenarioLoadError):
    """Input parsed as YAML but did not satisfy `ScenarioSpec`."""

    def __init__(self, message: str, errors: list[FieldError]) -> None:
        super().__init__(message)
        self.errors = errors


@dataclass(frozen=True, slots=True)
class FieldError:
    """One validation failure, with the path to the offending field."""

    field: str
    """Dotted path, e.g. `persona.traits.0` or `audio.snr_db`."""
    message: str
    error_type: str

    def as_dict(self) -> dict[str, str]:
        """Render for a JSON response."""
        return {"field": self.field, "message": self.message, "type": self.error_type}


def _format_location(location: tuple[Any, ...]) -> str:
    """Render a Pydantic error location as a dotted path.

    Pydantic reports locations as tuples mixing field names and list indices;
    `('persona', 'traits', 0)` becomes `persona.traits.0`, which matches how an
    author reads their own YAML.
    """
    return ".".join(str(part) for part in location) or "<root>"


def _collect_errors(exc: ValidationError) -> list[FieldError]:
    """Convert a Pydantic `ValidationError` into field-addressed errors."""
    return [
        FieldError(
            field=_format_location(error["loc"]),
            message=error["msg"],
            error_type=error["type"],
        )
        for error in exc.errors()
    ]


def _measure(node: Any, depth: int = 0, active: set[int] | None = None) -> tuple[int, int]:
    """Return `(node_count, max_depth)` for a parsed YAML structure.

    Counted after parsing so that alias expansion is measured as realised, not
    as written.

    **Cycle detection.** `yaml.safe_load` happily builds genuinely cyclic
    objects from a recursive alias:

        persona: &persona
          identity: *persona

    produces a dict whose own value is itself. `active` holds the `id()` of
    every container currently on the recursion path, so re-entering one is
    detected and reported as a cycle.

    It is an *active path* set, not a "seen anywhere" set, on purpose. A
    non-cyclic document may legitimately reference one anchor from several
    places; each container is discarded from `active` once its subtree is
    finished, so sibling references to a shared anchor are measured normally
    rather than being mistaken for a cycle. Shared subtrees are deliberately
    counted once per reference, because the node cap bounds *realised*
    expansion.

    `id()` is unique only among live objects, which is sufficient here: the
    whole document is held alive by the caller for the duration of the walk.

    Without this, the only thing standing between a cyclic document and an
    uncontrolled `RecursionError` is `MAX_YAML_DEPTH` happening to be smaller
    than Python's recursion limit - protection by coincidence, which breaks
    the moment that limit is raised.
    """
    if depth > MAX_YAML_DEPTH:
        raise ScenarioTooLargeError(f"YAML nesting exceeds the maximum depth of {MAX_YAML_DEPTH}")

    if active is None:
        active = set()

    count = 1
    deepest = depth

    is_container = isinstance(node, (dict, list, tuple))
    marker = id(node) if is_container else None

    if is_container:
        if marker in active:
            raise ScenarioRecursionError(
                "scenario YAML contains a recursive alias: an anchor refers to a "
                "structure that contains itself. Remove the self-reference - a "
                "scenario must be a finite document."
            )
        active.add(marker)

    try:
        if isinstance(node, dict):
            for key, value in node.items():
                key_count, key_depth = _measure(key, depth + 1, active)
                value_count, value_depth = _measure(value, depth + 1, active)
                count += key_count + value_count
                deepest = max(deepest, key_depth, value_depth)
        elif isinstance(node, (list, tuple)):
            for item in node:
                item_count, item_depth = _measure(item, depth + 1, active)
                count += item_count
                deepest = max(deepest, item_depth)
    finally:
        # Discarded in `finally` so an exception raised deeper in the walk
        # cannot leave a stale id behind and make a later sibling reference
        # look like a cycle.
        if is_container:
            active.discard(marker)

    if count > MAX_YAML_NODES:
        raise ScenarioTooLargeError(
            f"YAML expands to more than {MAX_YAML_NODES} nodes; "
            "this usually means anchors and aliases are being expanded"
        )

    return count, deepest


def parse_yaml(content: str | bytes) -> dict[str, Any]:
    """Parse YAML into a mapping, safely and within limits.

    Raises `ScenarioTooLargeError`, `ScenarioSyntaxError` (including its
    `ScenarioRecursionError` subclass for a cyclic alias).
    """
    raw = content.encode("utf-8") if isinstance(content, str) else content

    if len(raw) > MAX_YAML_BYTES:
        raise ScenarioTooLargeError(
            f"scenario YAML is {len(raw)} bytes, which exceeds the {MAX_YAML_BYTES}-byte limit"
        )

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScenarioSyntaxError(f"scenario YAML is not valid UTF-8: {exc}") from exc

    try:
        # safe_load, never load: see the module docstring.
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # Surface the line/column mark when PyYAML provides one.
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        raise ScenarioSyntaxError(f"invalid YAML{location}: {problem}") from exc

    if document is None:
        raise ScenarioSyntaxError("scenario YAML is empty")

    if not isinstance(document, dict):
        raise ScenarioSyntaxError(
            f"scenario YAML must be a mapping of fields, got {type(document).__name__}"
        )

    try:
        _measure(document)
    except RecursionError as exc:
        # Defence in depth. The depth limit and the cycle check above should
        # make this unreachable, but a RecursionError escaping to the API
        # would surface as an opaque 500, and exhausting the stack can leave
        # the interpreter in a fragile state. Converting it here keeps every
        # malformed-input path inside the module's documented error contract.
        raise ScenarioRecursionError(
            "scenario YAML is too deeply or recursively structured to analyse safely"
        ) from exc

    return document


def spec_from_yaml(content: str | bytes) -> ScenarioSpec:
    """Parse and validate YAML into a `ScenarioSpec`.

    Raises `ScenarioTooLargeError`, `ScenarioSyntaxError` (including
    `ScenarioRecursionError`), `ScenarioValidationError`.
    """
    document = parse_yaml(content)

    try:
        return ScenarioSpec.model_validate(document)
    except ValidationError as exc:
        errors = _collect_errors(exc)
        summary = "; ".join(f"{error.field}: {error.message}" for error in errors[:5])
        if len(errors) > 5:
            summary += f" (and {len(errors) - 5} more)"
        raise ScenarioValidationError(f"scenario failed validation - {summary}", errors) from exc


def spec_from_file(path: Path) -> ScenarioSpec:
    """Load and validate a scenario from a file on disk.

    The file is stat-checked before reading so an oversized file is rejected
    without being pulled into memory first.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ScenarioLoadError(f"cannot read scenario file {path.name}: {exc.strerror}") from exc

    if size > MAX_YAML_BYTES:
        raise ScenarioTooLargeError(
            f"{path.name} is {size} bytes, which exceeds the {MAX_YAML_BYTES}-byte limit"
        )

    return spec_from_yaml(path.read_bytes())


def spec_to_yaml(spec: ScenarioSpec) -> str:
    """Serialise a validated spec back to YAML.

    `sort_keys=False` preserves the field order declared on the model, so a
    round-tripped file stays readable rather than being alphabetised.
    Enum members are dumped via `mode="json"`, which yields their string
    values instead of Python object tags.
    """
    document = spec.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=88,
    )
