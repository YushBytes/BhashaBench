"""Declarative base, naming conventions and shared column mixins.

Every model inherits from `Base`, so `Base.metadata` is the single source of
truth that Alembic autogenerates against.

The application never calls `Base.metadata.create_all()`. Schema changes go
through Alembic migrations only, so that what runs in development is the same
thing that will run anywhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit, deterministic constraint names. Without this, PostgreSQL invents
# names for unnamed constraints and Alembic cannot reliably drop them in a
# downgrade - the usual cause of irreversible migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """A UUID primary key, generated application-side.

    Generated in Python rather than by a database default so that code holds
    the identifier before the row is flushed - which keeps a caller from
    needing a round-trip to learn the id of something it just created. The
    column is a native PostgreSQL `uuid`, not a string, so comparisons and
    indexes use 16 bytes rather than 36 characters.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Timezone-aware creation and update timestamps.

    `DateTime(timezone=True)` maps to `timestamptz`, so values are stored as
    absolute instants rather than ambiguous wall-clock readings. Both defaults
    are evaluated by the database (`now()`), which keeps timestamps consistent
    even if application servers disagree about the time.

    `onupdate` fires on ORM-issued UPDATEs. A bulk `UPDATE` statement that
    bypasses the ORM will not touch it; no such statement exists in this phase.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
