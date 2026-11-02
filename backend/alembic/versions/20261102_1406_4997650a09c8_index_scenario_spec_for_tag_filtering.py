"""Index the scenario specification for tag filtering.

Phase 3 added a `tags` list inside the `scenarios.spec` JSONB document, and
the library search filters on it with JSONB containment:

    WHERE spec @> '{"tags": ["healthcare"]}'

Without an index that predicate is a sequential scan over every scenario. A
GIN index is the right shape for containment.

The index covers the whole `spec` column rather than `spec->'tags'`, so it
also serves any future containment filter on the specification - a search by
`audio.noise_profile`, say - without needing another index.

Data-only change: no column, constraint or foreign key is touched, and no
stored document is rewritten. The downgrade simply drops the index, so this
migration is fully reversible.

Revision ID: 4997650a09c8
Revises: 3e3312d5327a
Create Date: 2026-11-02
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4997650a09c8"
down_revision: str | Sequence[str] | None = "3e3312d5327a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_scenarios_spec_gin", "scenarios", ["spec"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_scenarios_spec_gin", table_name="scenarios", postgresql_using="gin")
