"""A chatbot a workspace has connected so it can be tested ("bring your own bot").

One row is one external bot: which of the two published protocols it speaks
(`docs/BOT_PROTOCOL.md`), where it lives, and the bearer token BhashaBench
sends it. The bot itself is never built or hosted here.

- **The token is stored encrypted** (`app/core/secretbox.py`), bound to this
  row's id, and is never returned by any route: responses carry only
  `credential_hint`, the last four characters.
- **"Connected" is earned, not declared.** `check_status` starts
  `unverified`, becomes `connected` only when a real connection check through
  the adapter succeeded, and falls back to `unverified` whenever the URL or
  the credential changes. Runs may use only a `connected` integration.
- **The integration belongs to a project**, like a suite, so tenancy is the
  project's: a run may use an integration only from its own suite's project.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationProtocol(StrEnum):
    """The two protocols a connected bot can speak. Named as the adapters are."""

    HTTP = "http"
    """`bhashabench-text-bot/1`: text over HTTPS. Tests what a bot says, not audio."""
    WS_VOICE = "ws_voice"
    """`bhashabench-voice-bot/1`: streaming 16 kHz PCM over a WebSocket."""


class CheckStatus(StrEnum):
    UNVERIFIED = "unverified"
    """Saved, never checked - or changed since the last check."""
    CONNECTED = "connected"
    """The last connection check through the real adapter succeeded."""
    FAILED = "failed"
    """The last connection check failed; `last_check` says why."""


def _enum(cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        cls,
        name=name,
        create_constraint=True,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
    )


class BotIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_integrations"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_bot_integrations_project_name"),
        Index("ix_bot_integrations_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    protocol: Mapped[IntegrationProtocol] = mapped_column(
        _enum(IntegrationProtocol, "bot_integration_protocol"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    credential_sealed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    """AES-GCM ciphertext of the bearer token, bound to `id`. Never returned."""
    credential_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    default_language: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    check_status: Mapped[CheckStatus] = mapped_column(
        _enum(CheckStatus, "bot_integration_check_status"),
        nullable=False,
        default=CheckStatus.UNVERIFIED,
        server_default=CheckStatus.UNVERIFIED.value,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """The last check's outcome, message, latency and verified capabilities."""


__all__ = ["BotIntegration", "CheckStatus", "IntegrationProtocol"]
