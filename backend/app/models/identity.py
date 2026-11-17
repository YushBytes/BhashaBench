"""Users, sessions, workspaces, memberships and projects (Phase 14, part 1).

Ownership is a chain: a **project** belongs to one **workspace**, a suite
belongs to one project, and everything else (scenarios, runs, conversations,
turns, evaluations) belongs to a suite. A user reaches a resource only through
a **membership** of its workspace, and the membership's **role** decides what
they may do there. There is no global administrator role: an operator with
database access uses the CLI, which is a different trust boundary.

Two things are deliberately never stored:

- a password, only its scrypt hash in the self-describing format of
  `app.auth.passwords`;
- a session token, only its SHA-256. A copy of the `auth_sessions` table is
  therefore not a set of working credentials.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(StrEnum):
    """A member's role in a workspace, most privileged first.

    `owner` manages members of every role and is the only role that can
    create or remove another owner. `admin` manages projects and the members
    below it and may delete. `member` creates and runs tests. `viewer` reads.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        create_constraint=True,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who can sign in."""

    __tablename__ = "users"
    __table_args__ = (
        # Stored lower-cased by the service; the constraint makes a mixed-case
        # write that bypassed it fail rather than create a second account.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("position('@' in email) > 1", name="email_has_at"),
        CheckConstraint("failed_login_attempts >= 0", name="failed_attempts_non_negative"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class AuthSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One signed-in session. The bearer token itself is never stored."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_is_sha256_hex"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index("ix_auth_sessions_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Absolute expiry; never extended by activity."""
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """Drives the idle timeout. Written at most once a minute per session."""
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Declared so the unit of work orders inserts parent-first within one
    # flush; `raise_on_sql` so nothing is ever loaded implicitly through it.
    user: Mapped[User] = relationship(lazy="raise_on_sql")


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The tenancy boundary. Nothing is shared between workspaces."""

    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'", name="slug_format"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), nullable=False)


class WorkspaceMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's role in a workspace."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"),
        Index("ix_workspace_memberships_user_id", "user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(_enum(Role, "workspace_role"), nullable=False)

    workspace: Mapped[Workspace] = relationship(lazy="raise_on_sql")
    user: Mapped[User] = relationship(lazy="raise_on_sql")


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A group of suites inside a workspace."""

    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_projects_workspace_id_name"),
        CheckConstraint("length(trim(name)) > 0", name="name_not_blank"),
    )

    # RESTRICT, not CASCADE: there is no workspace deletion, and if one is
    # ever added it must not silently take every run and recording with it.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    workspace: Mapped[Workspace] = relationship(lazy="raise_on_sql")


__all__ = ["AuthSession", "Project", "Role", "User", "Workspace", "WorkspaceMembership"]
