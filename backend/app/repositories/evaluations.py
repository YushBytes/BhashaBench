"""SQL for evaluations and reference transcripts. Never commits.

Insert and select only: both tables are append-only, and there is no
function here that could update or delete a row.

Rows are stamped with `clock_timestamp()`, not the column default `now()`:
`now()` is fixed for a whole transaction, so two references written in one
transaction would tie and "latest" would fall to UUID order.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.evaluation import RunEvaluation, TranscriptReference, Verdict


def add_evaluation(
    session: Session,
    *,
    test_run_id: uuid.UUID,
    evaluator_version: str,
    verdict: Verdict,
    evidence_fingerprint: str,
    results: dict[str, Any],
) -> RunEvaluation:
    row = RunEvaluation(
        test_run_id=test_run_id,
        evaluator_version=evaluator_version,
        verdict=verdict,
        evidence_fingerprint=evidence_fingerprint,
        results=results,
        created_at=func.clock_timestamp(),
    )
    session.add(row)
    session.flush()
    return row


def list_evaluations(session: Session, test_run_id: uuid.UUID) -> list[RunEvaluation]:
    """Newest first."""
    stmt = (
        select(RunEvaluation)
        .where(RunEvaluation.test_run_id == test_run_id)
        .order_by(RunEvaluation.created_at.desc(), RunEvaluation.id.desc())
    )
    return list(session.scalars(stmt))


def latest_evaluation(session: Session, test_run_id: uuid.UUID) -> RunEvaluation | None:
    rows = list_evaluations(session, test_run_id)
    return rows[0] if rows else None


def latest_evaluations(
    session: Session, test_run_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RunEvaluation]:
    """The newest evaluation of each run that has one, in one query."""
    ids = list(test_run_ids)
    if not ids:
        return {}
    stmt = (
        select(RunEvaluation)
        .where(RunEvaluation.test_run_id.in_(ids))
        .order_by(RunEvaluation.created_at.desc(), RunEvaluation.id.desc())
    )
    latest: dict[uuid.UUID, RunEvaluation] = {}
    for row in session.scalars(stmt):
        latest.setdefault(row.test_run_id, row)
    return latest


def add_reference(
    session: Session, *, conversation_turn_id: uuid.UUID, text: str, reviewer: str | None
) -> TranscriptReference:
    row = TranscriptReference(
        conversation_turn_id=conversation_turn_id,
        text=text,
        reviewer=reviewer,
        created_at=func.clock_timestamp(),
    )
    session.add(row)
    session.flush()
    return row


def latest_references(
    session: Session, turn_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, TranscriptReference]:
    """The newest reference for each turn that has one. A correction is a newer row."""
    ids = list(turn_ids)
    if not ids:
        return {}
    stmt = (
        select(TranscriptReference)
        .where(TranscriptReference.conversation_turn_id.in_(ids))
        .order_by(TranscriptReference.created_at.desc(), TranscriptReference.id.desc())
    )
    latest: dict[uuid.UUID, TranscriptReference] = {}
    for row in session.scalars(stmt):
        latest.setdefault(row.conversation_turn_id, row)
    return latest


def reference_history(session: Session, turn_id: uuid.UUID) -> list[TranscriptReference]:
    stmt = (
        select(TranscriptReference)
        .where(TranscriptReference.conversation_turn_id == turn_id)
        .order_by(TranscriptReference.created_at.asc(), TranscriptReference.id.asc())
    )
    return list(session.scalars(stmt))


__all__ = [
    "add_evaluation",
    "add_reference",
    "latest_evaluation",
    "latest_evaluations",
    "latest_references",
    "list_evaluations",
    "reference_history",
]
