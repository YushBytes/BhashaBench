"""Create the suite, scenario and execution tables.

Phase 2 initial schema. Creates five tables in dependency order:

* `test_suites`        - named collections of scenarios
* `scenarios`          - validated scenario specifications (JSONB `spec`)
* `test_runs`          - foundational; no run is executed in this phase
* `call_sessions`      - foundational; no call is placed in this phase
* `conversation_turns` - foundational; nothing is transcribed in this phase

Delete behaviour is deliberate: suites cascade to their scenarios, runs and
calls, but `call_sessions.scenario_id` uses ON DELETE RESTRICT so a scenario
with recorded call history cannot be removed and leave those results
uninterpretable.

Status columns are VARCHAR with a CHECK constraint rather than PostgreSQL
ENUM types, so a value can be added or removed without DDL gymnastics. The
CHECK is explicit (`create_constraint=True`); SQLAlchemy omits it by default,
which would leave the allowed values enforced only in Python.

The downgrade drops everything in reverse dependency order and is exercised on
every test run, so this migration is reversible rather than one-way.

Revision ID: 3e3312d5327a
Revises:
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3e3312d5327a"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "test_suites",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suites")),
        sa.UniqueConstraint("name", name="uq_test_suites_name"),
    )
    op.create_index(op.f("ix_test_suites_name"), "test_suites", ["name"], unique=False)
    op.create_table(
        "scenarios",
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=35), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spec_version", sa.Integer(), nullable=False),
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
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_scenarios_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenarios")),
        sa.UniqueConstraint("suite_id", "name", name="uq_scenarios_suite_id_name"),
    )
    op.create_index(op.f("ix_scenarios_language"), "scenarios", ["language"], unique=False)
    op.create_index(op.f("ix_scenarios_name"), "scenarios", ["name"], unique=False)
    op.create_index(op.f("ix_scenarios_suite_id"), "scenarios", ["suite_id"], unique=False)
    op.create_table(
        "test_runs",
        sa.Column("suite_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "run_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
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
            "(status IN ('completed', 'failed', 'cancelled')"
            " AND finished_at IS NOT NULL)"
            " OR (status NOT IN ('completed', 'failed', 'cancelled')"
            " AND finished_at IS NULL)",
            name=op.f("ck_test_runs_finished_at_matches_status"),
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name=op.f("ck_test_runs_finished_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_runs_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_runs")),
    )
    op.create_index(op.f("ix_test_runs_status"), "test_runs", ["status"], unique=False)
    op.create_index(op.f("ix_test_runs_suite_id"), "test_runs", ["suite_id"], unique=False)
    op.create_table(
        "call_sessions",
        sa.Column("test_run_id", sa.UUID(), nullable=False),
        sa.Column("scenario_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "dialing",
                "in_progress",
                "completed",
                "failed",
                "no_answer",
                "busy",
                name="call_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("provider_call_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "call_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
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
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name=op.f("ck_call_sessions_duration_non_negative"),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at",
            name=op.f("ck_call_sessions_ended_after_started"),
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_call_sessions_scenario_id_scenarios"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["test_run_id"],
            ["test_runs.id"],
            name=op.f("fk_call_sessions_test_run_id_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_sessions")),
    )
    op.create_index(
        op.f("ix_call_sessions_provider_call_id"),
        "call_sessions",
        ["provider_call_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_call_sessions_scenario_id"), "call_sessions", ["scenario_id"], unique=False
    )
    op.create_index(op.f("ix_call_sessions_status"), "call_sessions", ["status"], unique=False)
    op.create_index(
        op.f("ix_call_sessions_test_run_id"), "call_sessions", ["test_run_id"], unique=False
    )
    op.create_table(
        "conversation_turns",
        sa.Column("call_session_id", sa.UUID(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column(
            "speaker",
            sa.Enum("caller", "bot", name="speaker", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("spoken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "turn_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
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
            "turn_index >= 0", name=op.f("ck_conversation_turns_turn_index_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["call_session_id"],
            ["call_sessions.id"],
            name=op.f("fk_conversation_turns_call_session_id_call_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_turns")),
        sa.UniqueConstraint(
            "call_session_id", "turn_index", name="uq_conversation_turns_call_session_id_turn_index"
        ),
    )
    op.create_index(
        op.f("ix_conversation_turns_call_session_id"),
        "conversation_turns",
        ["call_session_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_conversation_turns_call_session_id"), table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index(op.f("ix_call_sessions_test_run_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_status"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_scenario_id"), table_name="call_sessions")
    op.drop_index(op.f("ix_call_sessions_provider_call_id"), table_name="call_sessions")
    op.drop_table("call_sessions")
    op.drop_index(op.f("ix_test_runs_suite_id"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_status"), table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_index(op.f("ix_scenarios_suite_id"), table_name="scenarios")
    op.drop_index(op.f("ix_scenarios_name"), table_name="scenarios")
    op.drop_index(op.f("ix_scenarios_language"), table_name="scenarios")
    op.drop_table("scenarios")
    op.drop_index(op.f("ix_test_suites_name"), table_name="test_suites")
    op.drop_table("test_suites")
