"""Conversation turn: one utterance within a call session.

Foundational only. Phase 2 creates the table; nothing transcribes or
synthesises speech in this phase.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.call_session import CallSession


class Speaker(StrEnum):
    """Who produced an utterance."""

    CALLER = "caller"
    BOT = "bot"


class ConversationTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One utterance by one party in a call.

    `turn_index` is stored explicitly and made unique per call rather than
    relying on `created_at` ordering: two turns can share a timestamp at the
    resolution the database stores, and a transcript that renders in the wrong
    order is worse than useless. The index is the authority on sequence.
    """

    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint(
            "call_session_id", "turn_index", name="uq_conversation_turns_call_session_id_turn_index"
        ),
        CheckConstraint("turn_index >= 0", name="turn_index_non_negative"),
    )

    call_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("call_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    turn_index: Mapped[int] = mapped_column(nullable=False)

    speaker: Mapped[Speaker] = mapped_column(
        Enum(
            Speaker,
            name="speaker",
            create_constraint=True,
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    # The utterance as text. For the bot this is a transcription and therefore
    # an approximation; for the caller it is the text that was synthesised and
    # so is exact. Nullable because a turn can exist with audio captured but
    # transcription not yet complete.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    spoken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Per-turn detail later phases attach: transcription confidence, latency,
    # the audio artefact reference, the degradation seed actually applied.
    turn_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    call_session: Mapped[CallSession] = relationship(back_populates="turns", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return (
            f"<ConversationTurn id={self.id} call={self.call_session_id} "
            f"index={self.turn_index} speaker={self.speaker}>"
        )
