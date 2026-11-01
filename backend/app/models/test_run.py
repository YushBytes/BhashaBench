"""Test run: one execution of a suite.

Foundational only. Phase 2 creates the table and its relationships so later
phases have a stable schema to write into; nothing in this phase executes a
run, and no endpoint creates a row here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.call_session import CallSession
    from app.models.suite import TestSuite


class RunStatus(StrEnum):
    """Lifecycle of a test run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal states must carry a finish time; non-terminal states must not.
_TERMINAL = ("completed", "failed", "cancelled")


class TestRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of a suite's scenarios."""

    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint(
            "(status IN ('completed', 'failed', 'cancelled') AND finished_at IS NOT NULL)"
            " OR (status NOT IN ('completed', 'failed', 'cancelled') AND finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[RunStatus] = mapped_column(
        # `native_enum=False` stores a VARCHAR with a CHECK constraint instead
        # of a PostgreSQL ENUM type. Postgres enums cannot have a value removed
        # and need DDL to add one, which makes them awkward to migrate; a
        # checked VARCHAR is cheap to evolve.
        Enum(
            RunStatus,
            name="run_status",
            native_enum=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=RunStatus.PENDING,
        index=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set when status is `failed`. Free text, because the cause may come from a
    # provider whose error vocabulary is not ours.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Execution context captured at run time: tool versions, resolved audio
    # profile, seed. A run's result is only reproducible if what produced it is
    # recorded alongside it.
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    suite: Mapped[TestSuite] = relationship(back_populates="test_runs", lazy="joined")

    call_sessions: Mapped[list[CallSession]] = relationship(
        back_populates="test_run",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<TestRun id={self.id} suite_id={self.suite_id} status={self.status}>"
