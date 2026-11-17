"""Attach every suite to a project (Phase 14, part 1).

Adds `test_suites.project_id` (NOT NULL, ON DELETE RESTRICT) and makes suite
names unique per project instead of globally.

**Existing data is kept, not discarded.** If any suite exists when this runs,
one workspace with slug `legacy` and one project `Default` are created and
every suite is assigned to it. The workspace has no members, so nobody can
see those suites until an operator grants access:

    bhashabench users create --email you@example.com --workspace legacy

A fresh database has no suites and gets no legacy workspace.

Downgrade drops the column and restores the global unique constraint. It
fails, deliberately, if two projects now hold suites with the same name: the
old schema cannot represent that, and silently renaming or deleting one would
lose data. The legacy workspace and project rows are left in place.

Revision ID: b588560f044d
Revises: 05f303520380
Create Date: 2026-11-17 16:51:00+00:00

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b588560f044d"
down_revision: str | Sequence[str] | None = "05f303520380"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_SLUG = "legacy"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("test_suites", sa.Column("project_id", sa.UUID(), nullable=True))

    connection = op.get_bind()
    has_suites = connection.execute(sa.text("SELECT EXISTS (SELECT 1 FROM test_suites)")).scalar()
    if has_suites:
        workspace_id = connection.execute(
            sa.text("SELECT id FROM workspaces WHERE slug = :slug"), {"slug": LEGACY_SLUG}
        ).scalar()
        if workspace_id is None:
            workspace_id = uuid.uuid4()
            connection.execute(
                sa.text("INSERT INTO workspaces (id, name, slug) VALUES (:id, :name, :slug)"),
                {"id": workspace_id, "name": "Legacy (pre-tenancy data)", "slug": LEGACY_SLUG},
            )
        project_id = connection.execute(
            sa.text("SELECT id FROM projects WHERE workspace_id = :w AND name = 'Default'"),
            {"w": workspace_id},
        ).scalar()
        if project_id is None:
            project_id = uuid.uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO projects (id, workspace_id, name, description) "
                    "VALUES (:id, :w, 'Default', :d)"
                ),
                {
                    "id": project_id,
                    "w": workspace_id,
                    "d": "Suites that existed before workspaces were introduced.",
                },
            )
        connection.execute(
            sa.text("UPDATE test_suites SET project_id = :p WHERE project_id IS NULL"),
            {"p": project_id},
        )

    op.alter_column("test_suites", "project_id", nullable=False)
    op.drop_constraint(op.f("uq_test_suites_name"), "test_suites", type_="unique")
    op.create_index(op.f("ix_test_suites_project_id"), "test_suites", ["project_id"], unique=False)
    op.create_unique_constraint(
        "uq_test_suites_project_id_name", "test_suites", ["project_id", "name"]
    )
    op.create_foreign_key(
        op.f("fk_test_suites_project_id_projects"),
        "test_suites",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_test_suites_project_id_projects"), "test_suites", type_="foreignkey"
    )
    op.drop_constraint("uq_test_suites_project_id_name", "test_suites", type_="unique")
    op.drop_index(op.f("ix_test_suites_project_id"), table_name="test_suites")
    op.create_unique_constraint(op.f("uq_test_suites_name"), "test_suites", ["name"])
    op.drop_column("test_suites", "project_id")
