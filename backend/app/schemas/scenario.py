"""Request and response models for scenarios.

A scenario is authored as YAML, so the write endpoints accept YAML text rather
than a JSON mirror of `ScenarioSpec`. Keeping one authoring format avoids two
schemas drifting apart, and means the API validates exactly what a user would
put in a file under `scenarios/`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.scenario_spec import ScenarioName, ScenarioSpec

EXAMPLE_YAML = """\
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

# Bounded at the schema layer as well as in the loader, so an oversized body is
# rejected by request validation before any parsing work happens.
YamlText = Annotated[str, StringConstraints(min_length=1, max_length=256 * 1024)]

# A bundle holds many scenarios, so it gets the same cap as the loader applies
# to a whole document rather than the single-scenario budget.
BundleText = Annotated[str, StringConstraints(min_length=1, max_length=256 * 1024)]

EXAMPLE_BUNDLE_YAML = """\nformat: bhashabench.scenario-bundle/v1
suite:
  name: Hindi appointment flows
scenarios:
  - name: appointment_booking
    language: hi-IN
    persona:
      identity: Working professional
    goal:
      objective: Book an appointment for tomorrow.
    expected_outcomes:
      - Confirm appointment date
"""


class ScenarioCreate(BaseModel):
    """Payload for creating a scenario from YAML."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"yaml": EXAMPLE_YAML}})

    yaml: YamlText = Field(
        description="The scenario definition as YAML. Parsed with safe_load and "
        "validated against the scenario specification."
    )


class ScenarioUpdate(BaseModel):
    """Payload for replacing a scenario's definition.

    A full replacement rather than a patch: a scenario is a single coherent
    document, and partially updating a nested spec would make it easy to leave
    a scenario in a state its author never reviewed.
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"yaml": EXAMPLE_YAML}})

    yaml: YamlText = Field(description="The replacement scenario definition as YAML.")


class ScenarioRead(BaseModel):
    """A scenario as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    description: str | None
    language: str
    spec: ScenarioSpec = Field(description="The validated scenario specification.")
    spec_version: int = Field(description="Revision of the specification schema.")
    created_at: datetime
    updated_at: datetime


class ScenarioSummary(BaseModel):
    """A scenario in a list response, without the full specification."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    description: str | None
    language: str
    created_at: datetime
    updated_at: datetime


class ValidationFieldError(BaseModel):
    """One field-level validation failure."""

    field: str = Field(description="Dotted path to the offending field, e.g. 'audio.snr_db'.")
    message: str = Field(description="What is wrong with it.")
    type: str = Field(description="Machine-readable error category from the validator.")


class ScenarioValidateRequest(BaseModel):
    """Payload for the validation endpoint."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {"yaml": EXAMPLE_YAML}})

    yaml: YamlText = Field(description="YAML to validate. Nothing is persisted.")


class ScenarioValidateResponse(BaseModel):
    """Result of validating YAML.

    Returned with HTTP 200 whether or not the YAML is valid: the request to
    validate succeeded, and `valid` carries the verdict. A 4xx here would make
    "this YAML is wrong" indistinguishable from "the validation endpoint is
    wrong".
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valid": False,
                "errors": [
                    {
                        "field": "audio.snr_db",
                        "message": "Input should be less than or equal to 40",
                        "type": "less_than_equal",
                    }
                ],
                "normalized": None,
                "normalized_yaml": None,
            }
        }
    )

    valid: bool = Field(description="Whether the YAML is a valid scenario.")
    errors: list[ValidationFieldError] = Field(
        default_factory=list, description="Field-level failures. Empty when valid."
    )
    normalized: ScenarioSpec | None = Field(
        default=None,
        description="The parsed specification with defaults applied. Null when invalid.",
    )
    normalized_yaml: str | None = Field(
        default=None,
        description="The specification serialised back to canonical YAML. Null when invalid.",
    )


class ScenarioCopyRequest(BaseModel):
    """Payload for copying a scenario into a suite."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"target_suite_id": "…", "new_name": "appointment_v2"}},
    )

    target_suite_id: uuid.UUID = Field(description="Suite to copy into. Must exist.")
    new_name: ScenarioName | None = Field(
        default=None,
        description="Name for the copy. Required when copying within the same suite, "
        "since the original already holds the name.",
    )


class ScenarioMoveRequest(BaseModel):
    """Payload for moving a scenario between suites."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"target_suite_id": "…"}}
    )

    target_suite_id: uuid.UUID = Field(description="Suite to move into. Must exist.")
    new_name: ScenarioName | None = Field(
        default=None,
        description="Rename while moving, for when the destination already uses the name.",
    )


class BundleImportRequest(BaseModel):
    """Payload for importing a scenario bundle."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "yaml": EXAMPLE_BUNDLE_YAML,
                "dry_run": False,
                "atomic": True,
            }
        },
    )

    yaml: BundleText = Field(description="The bundle document.")
    dry_run: bool = Field(
        default=False,
        description="Validate and report what would happen without writing anything.",
    )
    atomic: bool = Field(
        default=True,
        description="All or nothing. When true (the default) a single failed or "
        "duplicate entry abandons the whole import. Set false to import the "
        "valid, non-colliding entries and have the rest reported.",
    )


class BundleEntryErrorRead(BaseModel):
    """Validation failure for one entry in a bundle."""

    index: int = Field(ge=0, description="Zero-based position in the `scenarios` list.")
    name: str | None = Field(description="The entry's name, when it had a readable one.")
    errors: list[ValidationFieldError] = Field(description="Field-level failures.")


class BundleImportResponse(BaseModel):
    """Result of an import, successful or not."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total": 3,
                "valid": 2,
                "imported": 0,
                "failed": 2,
                "duplicates": ["appointment_booking"],
                "entry_errors": [],
                "dry_run": False,
                "committed": False,
            }
        }
    )

    total: int = Field(ge=0, description="Entries the bundle contained.")
    valid: int = Field(ge=0, description="Entries that passed schema validation.")
    imported: int = Field(ge=0, description="Entries actually written.")
    failed: int = Field(ge=0, description="Entries not imported, for any reason.")
    duplicates: list[str] = Field(
        description="Names already present in the target suite. Never overwritten."
    )
    entry_errors: list[BundleEntryErrorRead] = Field(description="Per-entry validation failures.")
    dry_run: bool = Field(description="Whether this was a dry run.")
    committed: bool = Field(
        description="Whether anything was persisted. False for a dry run and for an "
        "abandoned atomic import, so 'nothing to do' is distinguishable from "
        "'nothing was done'."
    )


class BundleExportResponse(BaseModel):
    """An exported bundle."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"yaml": EXAMPLE_BUNDLE_YAML, "scenario_count": 2}}
    )

    yaml: str = Field(description="The bundle document, ready to re-import.")
    scenario_count: int = Field(ge=0, description="Scenarios included.")
