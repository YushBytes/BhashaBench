"""Add `telephony_calls` (Phase 8): one row per call attempt and its provider events.

One new table, nothing existing touched. Needed rather than JSONB on the
conversation because the guardrails count calls in progress and sum today's
minutes across every run, which is a query, not a document lookup. The bot's
number is stored masked only (a CHECK insists on it). Rows cascade from their
conversation, so deleting a run deletes its calls.

Revision ID: bcf146f6c696
Revises: b588560f044d
Create Date: 2026-11-17 18:38:01.519700+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bcf146f6c696"
down_revision: str | Sequence[str] | None = "b588560f044d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "telephony_calls",
        sa.Column("call_session_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_call_id", sa.String(length=128), nullable=False),
        sa.Column("to_number_masked", sa.String(length=20), nullable=False),
        sa.Column("mocked", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "ringing",
                "in_progress",
                "completed",
                "busy",
                "no_answer",
                "failed",
                "canceled",
                name="telephony_call_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "events", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "position('*' in to_number_masked) > 0",
            name=op.f("ck_telephony_calls_number_is_masked"),
        ),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name=op.f("ck_telephony_calls_duration_non_negative"),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR answered_at IS NULL OR ended_at >= answered_at",
            name=op.f("ck_telephony_calls_ended_after_answered"),
        ),
        sa.ForeignKeyConstraint(
            ["call_session_id"],
            ["call_sessions.id"],
            name=op.f("fk_telephony_calls_call_session_id_call_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telephony_calls")),
        sa.UniqueConstraint(
            "provider", "provider_call_id", name="uq_telephony_calls_provider_call"
        ),
    )
    op.create_index(
        "ix_telephony_calls_call_session_id", "telephony_calls", ["call_session_id"], unique=False
    )
    op.create_index(
        "ix_telephony_calls_created_at", "telephony_calls", ["created_at"], unique=False
    )
    op.create_index("ix_telephony_calls_status", "telephony_calls", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_telephony_calls_status", table_name="telephony_calls")
    op.drop_index("ix_telephony_calls_created_at", table_name="telephony_calls")
    op.drop_index("ix_telephony_calls_call_session_id", table_name="telephony_calls")
    op.drop_table("telephony_calls")
