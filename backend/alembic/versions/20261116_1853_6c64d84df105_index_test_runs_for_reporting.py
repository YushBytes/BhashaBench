"""Index test runs for the Phase 12 reporting queries.

Two indexes, no data change: a btree on `created_at`, which the run listing,
the exports and the trend buckets order or group by, and a GIN index on
`run_metadata`, which serves the `has_key('pipeline')` test every report and
listing applies. Chosen from the queries in `app/repositories/analytics.py`.

Not served, and stated: the value filters (`->'pipeline'->>'language' = ...`)
are text equality on an extracted field, which a default GIN index does not
index. They are evaluated on the rows the other predicates leave. Rewriting
them as containment (`@>`) or adding expression indexes would serve them;
neither is done until a measured query plan says it is needed.

Fully reversible.

Revision ID: 6c64d84df105
Revises: 1c40c48f72cf
Create Date: 2026-11-16 18:53:02.423484+00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6c64d84df105"
down_revision: str | Sequence[str] | None = "1c40c48f72cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_test_runs_created_at", "test_runs", ["created_at"], unique=False)
    op.create_index(
        "ix_test_runs_run_metadata_gin",
        "test_runs",
        ["run_metadata"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_test_runs_run_metadata_gin", table_name="test_runs", postgresql_using="gin")
    op.drop_index("ix_test_runs_created_at", table_name="test_runs")
