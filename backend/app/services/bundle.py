"""Scenario bundles: the bulk import and export format.

A *bundle* is one YAML document holding many scenarios plus optional suite
metadata. It exists because a scenario library is moved, reviewed and
version-controlled as a set, not one file at a time.

The format is deliberately a thin wrapper around the existing scenario schema
rather than a second dialect: each entry under `scenarios:` is exactly a
`ScenarioSpec`, so anything that validates standalone validates inside a
bundle, and the whole document goes through the same safe loader with the same
size, node-count, depth and cycle limits.

    format: bhashabench.scenario-bundle/v1
    suite:
      name: Hindi appointment flows
      description: Optional.
    scenarios:
      - name: appointment_booking
        language: hi-IN
        ...
      - name: reschedule
        language: hi-IN
        ...

`format` is required and checked, so a plain single-scenario file submitted to
the import endpoint by mistake gets a message saying so instead of a confusing
list of missing-field errors.

Nothing here touches the database; persistence is `scenario_service`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas.scenario_spec import ScenarioSpec
from app.services.scenario_loader import (
    FieldError,
    ScenarioSyntaxError,
    collect_validation_errors,
    parse_yaml,
)

BUNDLE_FORMAT = "bhashabench.scenario-bundle/v1"
"""The only format identifier this version accepts.

Versioned in the document itself so a future v2 can be introduced without
guessing at an unmarked file's shape.
"""

MAX_BUNDLE_SCENARIOS = 500
"""Cap on entries per bundle.

The loader's node limit already bounds total size, but a bundle of 10,000
scenarios would be a single enormous transaction holding locks for a long
time. 500 is far above any realistic hand-authored library and keeps one
import bounded.
"""


class BundleFormatError(ScenarioSyntaxError):
    """The document is not a recognisable scenario bundle.

    A `ScenarioSyntaxError` subclass so the existing exception handler maps it
    to HTTP 422 without new wiring.
    """


@dataclass(frozen=True, slots=True)
class BundleEntryError:
    """Validation failure for one scenario inside a bundle."""

    index: int
    """Zero-based position in the `scenarios:` list, so an author can find it."""
    name: str | None
    """The entry's `name` if it had a readable one, else None."""
    errors: list[FieldError]

    def as_dict(self) -> dict[str, Any]:
        """Render for a JSON response."""
        return {
            "index": self.index,
            "name": self.name,
            "errors": [error.as_dict() for error in self.errors],
        }


@dataclass(frozen=True, slots=True)
class SuiteMetadata:
    """Optional suite details carried by a bundle."""

    name: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedBundle:
    """The result of parsing a bundle: what was valid and what was not."""

    suite: SuiteMetadata
    specs: list[ScenarioSpec] = field(default_factory=list)
    """Entries that validated, in document order."""
    entry_errors: list[BundleEntryError] = field(default_factory=list)
    """Entries that did not. Never silently dropped."""

    @property
    def total(self) -> int:
        """Number of entries the document contained."""
        return len(self.specs) + len(self.entry_errors)

    @property
    def is_valid(self) -> bool:
        """True when every entry validated."""
        return not self.entry_errors


def parse_bundle(content: str | bytes) -> ParsedBundle:
    """Parse and validate a bundle document.

    Every entry is validated, and failures are collected rather than raised on
    the first one: an author fixing a 40-scenario library wants the whole list
    of problems, not one per round-trip.

    Raises `BundleFormatError` for a document that is not a bundle at all, and
    the usual `ScenarioTooLargeError` / `ScenarioSyntaxError` from the shared
    loader for unsafe or oversized input.
    """
    document = parse_yaml(content)

    declared = document.get("format")
    if declared is None:
        raise BundleFormatError(
            f"not a scenario bundle: the document has no 'format' field. "
            f"A bundle must begin with 'format: {BUNDLE_FORMAT}'. To import a "
            "single scenario, use the create-scenario endpoint instead."
        )
    if declared != BUNDLE_FORMAT:
        raise BundleFormatError(
            f"unsupported bundle format '{declared}'; this version accepts '{BUNDLE_FORMAT}'"
        )

    unknown = set(document) - {"format", "suite", "scenarios"}
    if unknown:
        raise BundleFormatError(
            f"unexpected top-level field(s) in bundle: {sorted(unknown)}; "
            "expected only 'format', 'suite' and 'scenarios'"
        )

    suite = _parse_suite_metadata(document.get("suite"))
    entries = document.get("scenarios")

    if entries is None:
        raise BundleFormatError("bundle has no 'scenarios' field")
    if not isinstance(entries, list):
        raise BundleFormatError(f"bundle 'scenarios' must be a list, got {type(entries).__name__}")
    if not entries:
        raise BundleFormatError("bundle contains no scenarios")
    if len(entries) > MAX_BUNDLE_SCENARIOS:
        raise BundleFormatError(
            f"bundle contains {len(entries)} scenarios, which exceeds the "
            f"limit of {MAX_BUNDLE_SCENARIOS}"
        )

    specs: list[ScenarioSpec] = []
    entry_errors: list[BundleEntryError] = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            entry_errors.append(
                BundleEntryError(
                    index=index,
                    name=None,
                    errors=[
                        FieldError(
                            field="<entry>",
                            message=(
                                f"each scenario entry must be a mapping, got {type(entry).__name__}"
                            ),
                            error_type="bundle_entry_type",
                        )
                    ],
                )
            )
            continue

        try:
            specs.append(ScenarioSpec.model_validate(entry))
        except ValidationError as exc:
            raw_name = entry.get("name")
            entry_errors.append(
                BundleEntryError(
                    index=index,
                    name=raw_name if isinstance(raw_name, str) else None,
                    errors=collect_validation_errors(exc),
                )
            )

    _reject_duplicate_names_within_bundle(specs, entry_errors)

    return ParsedBundle(suite=suite, specs=specs, entry_errors=entry_errors)


def _parse_suite_metadata(raw: Any) -> SuiteMetadata:
    """Validate the optional `suite:` block."""
    if raw is None:
        return SuiteMetadata()
    if not isinstance(raw, dict):
        raise BundleFormatError(f"bundle 'suite' must be a mapping, got {type(raw).__name__}")

    unknown = set(raw) - {"name", "description"}
    if unknown:
        raise BundleFormatError(
            f"unexpected field(s) in bundle 'suite': {sorted(unknown)}; "
            "expected only 'name' and 'description'"
        )

    for key in ("name", "description"):
        value = raw.get(key)
        if value is not None and not isinstance(value, str):
            raise BundleFormatError(
                f"bundle 'suite.{key}' must be a string, got {type(value).__name__}"
            )

    return SuiteMetadata(name=raw.get("name"), description=raw.get("description"))


def _reject_duplicate_names_within_bundle(
    specs: list[ScenarioSpec], entry_errors: list[BundleEntryError]
) -> None:
    """Move entries whose name repeats inside the bundle into the error list.

    A bundle carrying the same name twice cannot be imported into one suite -
    the `(suite_id, name)` constraint forbids it - and guessing which one the
    author meant would be wrong. Both are reported, because at authoring time
    neither is obviously the mistake.

    Mutates its arguments so the caller's lists stay the single record of what
    succeeded and what did not.
    """
    seen: dict[str, int] = {}
    duplicate_names: set[str] = set()
    for index, spec in enumerate(specs):
        if spec.name in seen:
            duplicate_names.add(spec.name)
        else:
            seen[spec.name] = index

    if not duplicate_names:
        return

    kept: list[ScenarioSpec] = []
    for spec in specs:
        if spec.name in duplicate_names:
            entry_errors.append(
                BundleEntryError(
                    index=seen[spec.name],
                    name=spec.name,
                    errors=[
                        FieldError(
                            field="name",
                            message=(
                                f"'{spec.name}' appears more than once in this bundle; "
                                "scenario names must be unique within a suite"
                            ),
                            error_type="bundle_duplicate_name",
                        )
                    ],
                )
            )
        else:
            kept.append(spec)

    specs[:] = kept
    entry_errors.sort(key=lambda error: error.index)


def build_bundle(
    specs: list[ScenarioSpec],
    *,
    suite_name: str | None = None,
    suite_description: str | None = None,
) -> str:
    """Serialise scenarios into a bundle document.

    Output is deterministic: entries are emitted in the order given (callers
    pass them ordered by name), field order follows the model declaration
    rather than being alphabetised, and no timestamps or ids are included - so
    exporting the same suite twice produces byte-identical YAML, and a diff
    between two exports shows only real changes.

    Database identifiers are deliberately omitted. A bundle describes
    scenarios, not rows; re-importing one creates new records rather than
    trying to resurrect old primary keys.
    """
    document: dict[str, Any] = {"format": BUNDLE_FORMAT}

    suite: dict[str, Any] = {}
    if suite_name is not None:
        suite["name"] = suite_name
    if suite_description is not None:
        suite["description"] = suite_description
    if suite:
        document["suite"] = suite

    document["scenarios"] = [spec.model_dump(mode="json", exclude_none=True) for spec in specs]

    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=88,
    )
