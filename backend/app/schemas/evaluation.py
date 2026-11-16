"""HTTP models for the evaluation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.languages import validate_tag
from app.models.evaluation import Verdict

MAX_TEXT = 20_000


class MetricDefinitionResponse(BaseModel):
    name: str
    title: str
    definition: str
    formula: str
    evidence: str
    normalisation: str
    better: str = Field(description="`lower`, `higher`, or `pass` for a boolean criterion.")
    missing_data: str
    limitations: list[str]
    unit: str


class MetricCatalogueResponse(BaseModel):
    evaluator_version: str
    normalisation_version: str
    composite_score: None = Field(
        default=None,
        description="Always null. There is no composite score; see docs/EVALUATION.md.",
    )
    metrics: list[MetricDefinitionResponse]


class ErrorRateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(max_length=MAX_TEXT, description="Reviewed ground-truth text.")
    hypothesis: str = Field(max_length=MAX_TEXT, description="The text to score.")
    language: str | None = Field(
        default=None, description="BCP 47 tag from the catalogue. Affects Urdu ZWNJ handling."
    )

    @field_validator("language")
    @classmethod
    def _known(cls, value: str | None) -> str | None:
        if value is not None:
            validate_tag(value)
        return value


class ErrorRateBreakdown(BaseModel):
    metric: str
    value: float | None = Field(description="Null when the reference is empty.")
    substitutions: int
    deletions: int
    insertions: int
    hits: int
    reference_length: int
    hypothesis_length: int
    normalisation: str


class ErrorRateResponse(BaseModel):
    wer: ErrorRateBreakdown
    cer: ErrorRateBreakdown


class EvaluationResponse(BaseModel):
    evaluation_id: uuid.UUID
    run_id: uuid.UUID
    evaluator_version: str
    verdict: Verdict
    evidence_fingerprint: str = Field(
        description="SHA-256 of the evidence read. Same fingerprint and version, same results."
    )
    created_at: datetime
    criteria: list[dict[str, Any]]
    metrics: dict[str, Any]
    measures_audio: bool = Field(
        description="False for text and offline modes: nothing here describes audio."
    )


class EvaluationListResponse(BaseModel):
    run_id: uuid.UUID
    evaluations: list[EvaluationResponse] = Field(description="Newest first.")


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=MAX_TEXT, description="Reviewed transcript.")
    reviewer: str | None = Field(
        default=None, max_length=200, description="Who reviewed it. Free text until Phase 14."
    )

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a reference transcript cannot be blank")
        return value


class ReferenceResponse(BaseModel):
    reference_id: uuid.UUID
    run_id: uuid.UUID
    turn_index: int
    text: str
    reviewer: str | None
    created_at: datetime


class ReferenceHistoryResponse(BaseModel):
    run_id: uuid.UUID
    turn_index: int
    references: list[ReferenceResponse] = Field(description="Oldest first; the last one is used.")
