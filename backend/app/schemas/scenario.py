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

from app.schemas.scenario_spec import ScenarioSpec

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
