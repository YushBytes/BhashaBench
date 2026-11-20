"""Add `bot_integrations`: a chatbot a workspace connected so it can be tested.

One new table, nothing existing touched. A row holds the bot's protocol, URL
and AES-GCM-sealed bearer token (never the token in clear), and the outcome
of the last connection check. Rows cascade from their project, so deleting a
project deletes its integrations; runs that used one keep its id and name in
their own metadata as evidence.

Revision ID: 59b9983c8f1e
Revises: 92a1fdd146b8
Create Date: 2026-11-20 09:22:09.463010+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "59b9983c8f1e"
down_revision: str | Sequence[str] | None = "92a1fdd146b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "bot_integrations",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "protocol",
            sa.Enum(
                "http",
                "ws_voice",
                name="bot_integration_protocol",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("credential_sealed", sa.LargeBinary(), nullable=False),
        sa.Column("credential_hint", sa.String(length=8), nullable=False),
        sa.Column("default_language", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "check_status",
            sa.Enum(
                "unverified",
                "connected",
                "failed",
                name="bot_integration_check_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_bot_integrations_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_bot_integrations_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_integrations")),
        sa.UniqueConstraint("project_id", "name", name="uq_bot_integrations_project_name"),
    )
    op.create_index(
        "ix_bot_integrations_project_id", "bot_integrations", ["project_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_bot_integrations_project_id", table_name="bot_integrations")
    op.drop_table("bot_integrations")
