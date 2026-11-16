"""Evaluation endpoints (Phase 11): metric definitions, scoring, references.

Thin by design: every rule is in `app/evaluation/` and
`app/services/evaluation_service.py`. Nothing here calls a provider.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Path, status

from app.api.deps import DbSession
from app.evaluation.metrics import character_error_rate, word_error_rate
from app.evaluation.registry import EVALUATOR_VERSION, METRICS
from app.evaluation.text import NORMALISATION_VERSION
from app.models.evaluation import RunEvaluation, TranscriptReference
from app.schemas.common import ErrorResponse
from app.schemas.evaluation import (
    ErrorRateBreakdown,
    ErrorRateRequest,
    ErrorRateResponse,
    EvaluationListResponse,
    EvaluationResponse,
    MetricCatalogueResponse,
    MetricDefinitionResponse,
    ReferenceHistoryResponse,
    ReferenceRequest,
    ReferenceResponse,
)
from app.services import evaluation_service as service

router = APIRouter(prefix="/evaluation", tags=["evaluation"])
run_router = APIRouter(prefix="/test-runs", tags=["evaluation"])

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "No such run."}}
TurnIndex = Path(ge=0, le=10_000)


def _evaluation(row: RunEvaluation) -> EvaluationResponse:
    return EvaluationResponse(
        evaluation_id=row.id,
        run_id=row.test_run_id,
        evaluator_version=row.evaluator_version,
        verdict=row.verdict,
        evidence_fingerprint=row.evidence_fingerprint,
        created_at=row.created_at,
        criteria=list(row.results.get("criteria", [])),
        metrics=dict(row.results.get("metrics", {})),
        measures_audio=bool(row.results.get("measures_audio", False)),
    )


def _reference(row: TranscriptReference, run_id: uuid.UUID, turn_index: int) -> ReferenceResponse:
    return ReferenceResponse(
        reference_id=row.id,
        run_id=run_id,
        turn_index=turn_index,
        text=row.text,
        reviewer=row.reviewer,
        created_at=row.created_at,
    )


@router.get(
    "/metrics",
    response_model=MetricCatalogueResponse,
    summary="List every metric and how it is computed",
    description=(
        "The registry, verbatim: definition, formula, evidence, normalisation, "
        "direction, missing-data behaviour and limitations for every metric an "
        "evaluation can report. There is no composite score."
    ),
)
def list_metrics() -> MetricCatalogueResponse:
    return MetricCatalogueResponse(
        evaluator_version=EVALUATOR_VERSION,
        normalisation_version=NORMALISATION_VERSION,
        metrics=[MetricDefinitionResponse(**m.as_dict()) for m in METRICS],  # type: ignore[arg-type]
    )


@router.post(
    "/error-rate",
    response_model=ErrorRateResponse,
    summary="Score a transcript against a reference",
    description=(
        "WER and CER under normalisation bb-norm-1, with the full breakdown. "
        "Stateless: nothing is stored."
    ),
)
def error_rate(payload: ErrorRateRequest) -> ErrorRateResponse:
    wer = word_error_rate(payload.reference, payload.hypothesis, language=payload.language)
    cer = character_error_rate(payload.reference, payload.hypothesis, language=payload.language)
    return ErrorRateResponse(
        wer=ErrorRateBreakdown(**wer.as_dict()),  # type: ignore[arg-type]
        cer=ErrorRateBreakdown(**cer.as_dict()),  # type: ignore[arg-type]
    )


@run_router.post(
    "/{run_id}/evaluations",
    response_model=EvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Evaluate a run",
    description=(
        "Computes every metric from the run's stored evidence and appends an "
        "evaluation. Never replaces an earlier one. An unfinished run, or one "
        "that ended by our fault, is `undetermined` - not failed."
    ),
    responses=_NOT_FOUND,
)
def evaluate_run(run_id: uuid.UUID, session: DbSession) -> EvaluationResponse:
    return _evaluation(service.evaluate(session, run_id))


@run_router.get(
    "/{run_id}/evaluations",
    response_model=EvaluationListResponse,
    summary="List a run's evaluations",
    responses=_NOT_FOUND,
)
def list_run_evaluations(run_id: uuid.UUID, session: DbSession) -> EvaluationListResponse:
    rows = service.list_evaluations(session, run_id)
    return EvaluationListResponse(run_id=run_id, evaluations=[_evaluation(r) for r in rows])


@run_router.post(
    "/{run_id}/turns/{turn_index}/reference",
    response_model=ReferenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a reviewed reference transcript for a bot turn",
    description=(
        "Ground truth for WER and CER. Append-only: a correction is a new "
        "reference and the newest is used; earlier ones stay in the history. "
        "Refused for a caller turn, whose text is already exact."
    ),
    responses={
        **_NOT_FOUND,
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "A caller turn."},
    },
)
def add_reference(
    run_id: uuid.UUID,
    payload: ReferenceRequest,
    session: DbSession,
    turn_index: int = TurnIndex,
) -> ReferenceResponse:
    row = service.add_reference(
        session, run_id, turn_index, text=payload.text, reviewer=payload.reviewer
    )
    return _reference(row, run_id, turn_index)


@run_router.get(
    "/{run_id}/turns/{turn_index}/reference",
    response_model=ReferenceHistoryResponse,
    summary="A bot turn's reference transcripts, oldest first",
    responses=_NOT_FOUND,
)
def reference_history(
    run_id: uuid.UUID, session: DbSession, turn_index: int = TurnIndex
) -> ReferenceHistoryResponse:
    rows = service.reference_history(session, run_id, turn_index)
    return ReferenceHistoryResponse(
        run_id=run_id,
        turn_index=turn_index,
        references=[_reference(r, run_id, turn_index) for r in rows],
    )
