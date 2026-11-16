"""Add run evaluations and reviewed transcript references (Phase 11).

Two new tables and nothing else: no existing column, constraint or row is
touched, so every recorded run keeps its evidence exactly. Both tables are
append-only by design (see `app/models/evaluation.py`): an evaluation is
re-run by adding a row, and a reference is corrected by adding a row.

Cascades from their parents, so deleting a run removes its evaluations and
deleting a turn removes its references - neither outlives the evidence it
describes. Fully reversible.

Revision ID: 1c40c48f72cf
Revises: 4997650a09c8
Create Date: 2026-11-16 18:09:47.037182+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c40c48f72cf"
down_revision: str | Sequence[str] | None = "4997650a09c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "run_evaluations",
        sa.Column("test_run_id", sa.UUID(), nullable=False),
        sa.Column("evaluator_version", sa.String(length=32), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                "pass",
                "fail",
                "undetermined",
                name="verdict",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            "length(evaluator_version) > 0",
            name=op.f("ck_run_evaluations_evaluator_version_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["test_run_id"],
            ["test_runs.id"],
            name=op.f("fk_run_evaluations_test_run_id_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_evaluations")),
    )
    op.create_index(
        "ix_run_evaluations_test_run_id_created_at",
        "run_evaluations",
        ["test_run_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "transcript_references",
        sa.Column("conversation_turn_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=200), nullable=True),
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
            "length(text) > 0", name=op.f("ck_transcript_references_reference_text_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_turn_id"],
            ["conversation_turns.id"],
            name=op.f("fk_transcript_references_conversation_turn_id_conversation_turns"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcript_references")),
    )
    op.create_index(
        "ix_transcript_references_turn_id_created_at",
        "transcript_references",
        ["conversation_turn_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_transcript_references_turn_id_created_at", table_name="transcript_references")
    op.drop_table("transcript_references")
    op.drop_index("ix_run_evaluations_test_run_id_created_at", table_name="run_evaluations")
    op.drop_table("run_evaluations")
