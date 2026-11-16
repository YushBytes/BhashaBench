"""Evaluation use cases. Owns the transaction; raises domain errors only."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.evaluation.evaluator import evaluate_run
from app.models.evaluation import RunEvaluation, TranscriptReference
from app.repositories import caller_conversations as caller_repo
from app.repositories import evaluations as eval_repo
from app.repositories import pipeline_runs as pipeline_repo
from app.services.errors import ConflictError, NotFoundError

MAX_REFERENCE_CHARS = 20_000


class ReferenceNotAllowedError(ConflictError):
    """A reference was offered for a turn that cannot have one."""


def _bot_turn(session: Session, run_id: uuid.UUID, turn_index: int):  # noqa: ANN202 - ORM row
    if pipeline_repo.get_run(session, run_id) is None:
        raise NotFoundError("TestRun", run_id)
    conversation = pipeline_repo.conversation_of(session, run_id)
    if conversation is None:
        raise NotFoundError("ConversationTurn", f"{run_id}:{turn_index}")
    turn = next(
        (t for t in caller_repo.list_turns(session, conversation.id) if t.turn_index == turn_index),
        None,
    )
    if turn is None:
        raise NotFoundError("ConversationTurn", f"{run_id}:{turn_index}")
    if turn.speaker.value != "bot":
        raise ReferenceNotAllowedError(
            f"turn {turn_index} is the caller's. A reference transcript is ground truth for "
            "what the bot said; the caller's text is already exact"
        )
    return turn


def evaluate(session: Session, run_id: uuid.UUID) -> RunEvaluation:
    evaluation = evaluate_run(session, run_id)
    session.commit()
    return evaluation


def list_evaluations(session: Session, run_id: uuid.UUID) -> list[RunEvaluation]:
    if pipeline_repo.get_run(session, run_id) is None:
        raise NotFoundError("TestRun", run_id)
    return eval_repo.list_evaluations(session, run_id)


def add_reference(
    session: Session, run_id: uuid.UUID, turn_index: int, *, text: str, reviewer: str | None
) -> TranscriptReference:
    turn = _bot_turn(session, run_id, turn_index)
    reference = eval_repo.add_reference(
        session, conversation_turn_id=turn.id, text=text, reviewer=reviewer
    )
    session.commit()
    return reference


def reference_history(
    session: Session, run_id: uuid.UUID, turn_index: int
) -> list[TranscriptReference]:
    turn = _bot_turn(session, run_id, turn_index)
    return eval_repo.reference_history(session, turn.id)


__all__ = [
    "MAX_REFERENCE_CHARS",
    "ReferenceNotAllowedError",
    "add_reference",
    "evaluate",
    "list_evaluations",
    "reference_history",
]
