"""Evaluation results and the reviewed references they are scored against.

Both tables are **append-only**. An evaluation is never updated: re-running
one adds a row, so a report can always show what a run scored under each
evaluator version and when. A reference transcript is never edited either:
a correction is a new row, the latest wins, and the history of what was
reviewed stays. Neither has a code path that issues an UPDATE.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Verdict(StrEnum):
    """A run's overall result under one evaluator version."""

    PASS = "pass"
    FAIL = "fail"
    UNDETERMINED = "undetermined"
    """The evidence cannot support a verdict: the run is unfinished, or it
    ended for a reason that says nothing about the bot. Never a failure."""


class RunEvaluation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One evaluation of one run."""

    __tablename__ = "run_evaluations"
    __table_args__ = (
        Index("ix_run_evaluations_test_run_id_created_at", "test_run_id", "created_at"),
        CheckConstraint("length(evaluator_version) > 0", name="evaluator_version_not_empty"),
    )

    test_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    verdict: Mapped[Verdict] = mapped_column(
        Enum(
            Verdict,
            name="verdict",
            create_constraint=True,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    evidence_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    """SHA-256 of the evidence the evaluation read. Two evaluations with the
    same fingerprint and version must agree; a test asserts it."""
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return f"<RunEvaluation id={self.id} run={self.test_run_id} verdict={self.verdict}>"


class TranscriptReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reviewed, ground-truth transcript of one bot turn."""

    __tablename__ = "transcript_references"
    __table_args__ = (
        Index(
            "ix_transcript_references_turn_id_created_at",
            "conversation_turn_id",
            "created_at",
        ),
        CheckConstraint("length(text) > 0", name="reference_text_not_empty"),
    )

    conversation_turn_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    """Who reviewed it, as they named themselves. Becomes a user id once
    authentication exists (Phase 14)."""

    def __repr__(self) -> str:
        return f"<TranscriptReference id={self.id} turn={self.conversation_turn_id}>"
