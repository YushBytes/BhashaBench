"""Test suite: a named collection of scenarios."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.identity import Project
    from app.models.scenario import Scenario
    from app.models.test_run import TestRun


class TestSuite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named group of scenarios that are run together."""

    __tablename__ = "test_suites"
    __table_args__ = (
        # Suite names are the human handle for a suite, so they are unique -
        # within a project since Phase 14, which made tenancy real. Two
        # workspaces may each have a `smoke` suite.
        UniqueConstraint("project_id", "name", name="uq_test_suites_project_id_name"),
    )

    # The tenancy anchor: scenarios, runs, conversations, turns and
    # evaluations all reach their workspace through this column. RESTRICT, so
    # deleting a project can never cascade into recorded runs.
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Never loaded implicitly; declared so a suite and its project created in
    # one flush are inserted in the right order.
    project: Mapped[Project] = relationship(lazy="raise_on_sql")

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Loaded on demand only. No endpoint serialises a suite's scenarios
    # inline - the scenario list is its own paginated endpoint, and the suite
    # detail response reports a SQL COUNT rather than measuring a loaded
    # collection - so eager loading would fetch rows nothing reads.
    #
    # `delete-orphan` with `cascade="all"` means removing a suite removes its
    # scenarios. `passive_deletes=True` lets the database-level ON DELETE
    # CASCADE do that work instead of SQLAlchemy loading every child first,
    # which also keeps statements that bypass the ORM correct.
    scenarios: Mapped[list[Scenario]] = relationship(
        back_populates="suite",
        cascade="all, delete-orphan",
        lazy="select",
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
