"""Test suite: a named collection of scenarios."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.scenario import Scenario
    from app.models.test_run import TestRun


class TestSuite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named group of scenarios that are run together."""

    __tablename__ = "test_suites"
    __table_args__ = (
        # Suite names are the human handle for a suite, so they are unique
        # globally. There is no tenant or owner concept yet; when one arrives
        # this becomes a composite constraint rather than a new column.
        UniqueConstraint("name", name="uq_test_suites_name"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # `selectin` avoids the N+1 queries that lazy loading causes when a list
    # endpoint serialises many suites. `delete-orphan` with `cascade="all"`
    # means removing a suite removes its scenarios; the database-level
    # ON DELETE CASCADE on the child column enforces the same thing for
    # statements that bypass the ORM.
    scenarios: Mapped[list[Scenario]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        lazy="selectin",
        passive_deletes=True,
    )

    # Runs are deliberately NOT eagerly loaded: a suite accumulates runs
    # without bound, and no endpoint in this phase needs them inline.
    test_runs: Mapped[list[TestRun]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<TestSuite id={self.id} name={self.name!r}>"
