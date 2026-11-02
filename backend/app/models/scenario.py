"""Scenario: one test case, defined by a validated specification."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.suite import TestSuite


class Scenario(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single test case belonging to a suite.

    **Why the specification is one JSONB column rather than many tables.**
    The scenario specification is a nested document - persona, goal, known
    facts, expected outcomes, audio settings - that is always read and written
    whole, is never queried field-by-field, and will keep gaining fields as
    later phases add capabilities. Normalising it would mean five more tables
    and a migration for every new scenario option, with no query benefit.

    It is emphatically not an unvalidated bag of values: every write passes
    through `ScenarioSpec` (see `app.schemas.scenario_spec`), which rejects
    unknown keys and range-checks every number. JSONB is the storage format;
    Pydantic is the schema. `spec_version` records which revision of that
    schema produced the stored document, so a future schema change can migrate
    old rows instead of guessing at their shape.
    """

    __tablename__ = "scenarios"
    __table_args__ = (
        # Scenario names are unique per suite, not globally: two suites may
        # each reasonably contain an "appointment_booking" scenario.
        UniqueConstraint("suite_id", "name", name="uq_scenarios_suite_id_name"),
        # GIN index for JSONB containment, which is how tag filtering is
        # expressed: `spec @> '{"tags": ["healthcare"]}'`. Without it that
        # predicate is a sequential scan over every scenario. Indexing the
        # whole `spec` document rather than `spec->'tags'` keeps the index
        # usable for any future containment filter on the specification.
        Index(
            "ix_scenarios_spec_gin",
            "spec",
            postgresql_using="gin",
        ),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        # ON DELETE CASCADE at the database level, so deleting a suite cannot
        # leave orphaned scenarios even via raw SQL.
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # BCP 47 language tag, e.g. `hi-IN`. Indexed because filtering scenarios
    # by language is the one query a multilingual benchmark suite will need.
    language: Mapped[str] = mapped_column(String(35), nullable=False, index=True)

    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    spec_version: Mapped[int] = mapped_column(nullable=False, default=1)

    suite: Mapped[TestSuite] = relationship(back_populates="scenarios", lazy="joined")

    def __repr__(self) -> str:
        return f"<Scenario id={self.id} suite_id={self.suite_id} name={self.name!r}>"
