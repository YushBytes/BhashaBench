"""Call session: one telephony call made during a test run.

Foundational only. Phase 2 creates the table; no call is placed in this phase.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.conversation_turn import ConversationTurn
    from app.models.scenario import Scenario
    from app.models.test_run import TestRun


class CallStatus(StrEnum):
    """Lifecycle of a single call."""

    PENDING = "pending"
    DIALING = "dialing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"


class CallSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One call placed against the bot under test.

    A run executes many scenarios, and each scenario execution is one call, so
    this table carries both references. `scenario_id` uses `ON DELETE
    RESTRICT`: a scenario that has been exercised by a call cannot simply
    vanish, or the call's result becomes uninterpretable. Deleting such a
    scenario is a deliberate act that must deal with its history first.
    """

    __tablename__ = "call_sessions"
    __table_args__ = (
        CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name="ended_after_started",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="duration_non_negative",
        ),
    )

    test_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("scenarios.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[CallStatus] = mapped_column(
        Enum(
            CallStatus,
            name="call_status",
            create_constraint=True,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CallStatus.PENDING,
        index=True,
    )

    # Identifier assigned by the telephony provider. Nullable because it does
    # not exist until the call is actually placed. Indexed so a provider
    # webhook can find its session without scanning.
    provider_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Stored rather than always derived from the timestamps: the provider
    # reports a billable duration that may differ from wall-clock, and that is
    # the figure cost accounting needs.
    duration_seconds: Mapped[int | None] = mapped_column(nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    call_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    test_run: Mapped[TestRun] = relationship(back_populates="call_sessions", lazy="raise_on_sql")
    scenario: Mapped[Scenario] = relationship(lazy="raise_on_sql")

    turns: Mapped[list[ConversationTurn]] = relationship(
        back_populates="call_session",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
        passive_deletes=True,
        order_by="ConversationTurn.turn_index",
    )

    def __repr__(self) -> str:
        return f"<CallSession id={self.id} run_id={self.test_run_id} status={self.status}>"
