"""One telephony call attempt and the provider events that drove it (Phase 8).

A call belongs to a conversation (`CallSession`); a conversation may make
several attempts, up to `TELEPHONY_MAX_CALLS_PER_RUN` per run. The bot's
number is stored **masked** - nothing downstream needs the full number, so
it is not kept. `mocked` is copied from the provider's capabilities when the
call is placed and never changes: a mocked call stays labelled mocked in
every record and response.

`status` is the last provider status that *advanced* the call; stale and
duplicate events are still kept in `events`, with `applied: false`, so the
order in which a provider actually delivered them stays inspectable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.call_session import CallSession
from app.telephony.models import ProviderCallStatus


class TelephonyCall(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telephony_calls"
    __table_args__ = (
        UniqueConstraint("provider", "provider_call_id", name="uq_telephony_calls_provider_call"),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_non_negative"
        ),
        CheckConstraint(
            "ended_at IS NULL OR answered_at IS NULL OR ended_at >= answered_at",
            name="ended_after_answered",
        ),
        CheckConstraint("position('*' in to_number_masked) > 0", name="number_is_masked"),
        Index("ix_telephony_calls_call_session_id", "call_session_id"),
        Index("ix_telephony_calls_status", "status"),
        Index("ix_telephony_calls_created_at", "created_at"),
    )

    call_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("call_sessions.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    to_number_masked: Mapped[str] = mapped_column(String(20), nullable=False)
    mocked: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[ProviderCallStatus | None] = mapped_column(
        Enum(
            ProviderCallStatus,
            name="telephony_call_status",
            create_constraint=True,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    """`None` until the provider reports anything."""
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    call_session: Mapped[CallSession] = relationship(lazy="raise_on_sql")


__all__ = ["TelephonyCall"]
