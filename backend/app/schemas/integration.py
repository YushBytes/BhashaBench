"""Request and response shapes for connected bots ("bring your own bot").

No response model has a token field. `credential_hint` is all that is ever
returned, and the request models take the token as a `SecretStr` named
`token`, which the 422 handler never echoes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from app.models.bot_integration import CheckStatus, IntegrationProtocol


class IntegrationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, description="A label for this bot.")
    protocol: IntegrationProtocol = Field(
        description="`http` for a text bot speaking `bhashabench-text-bot/1`, `ws_voice` "
        "for a streaming voice bot speaking `bhashabench-voice-bot/1` (docs/BOT_PROTOCOL.md)."
    )
    url: str = Field(
        max_length=2048,
        description="`https://...` base URL for `http`; `wss://...` voice endpoint for "
        "`ws_voice`. Plain http/ws is accepted only for a loopback bot in development.",
    )
    token: SecretStr = Field(
        description="Bearer token BhashaBench sends the bot. Stored encrypted; never returned."
    )
    default_language: str = Field(
        default="hi-IN", description="BCP 47 tag used by connection checks."
    )


class IntegrationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=2048)
    token: SecretStr | None = Field(
        default=None, description="A replacement token. Omit to keep the stored one."
    )
    default_language: str | None = None


class IntegrationCheckRequest(BaseModel):
    language: str | None = Field(
        default=None, description="Language for the check; defaults to the integration's."
    )


class CapabilityRead(BaseModel):
    """What the adapter declares, separate from what a check verified."""

    contacts_external_system: bool
    supports_sessions: bool
    requires_credentials: bool
    accepts_containers: list[str]
    supports_caller_barge_in: bool
    execution_mode: str = Field(description="The run mode this protocol is tested in.")
    notes: list[str]


class LastCheckRead(BaseModel):
    outcome: str = Field(
        description="`connected`, `authentication_failed`, `target_refused`, `unreachable`, "
        "`timeout`, `protocol_error` or `session_rejected`."
    )
    message: str
    protocol: str
    latency_ms: float | None
    verified: dict[str, bool | None] = Field(
        description="Per capability: `true` seen working, `false` seen failing or not "
        "carried by the protocol, `null` not exercised by a check (a run measures it)."
    )
    detail: dict[str, Any]


class IntegrationRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    protocol: IntegrationProtocol
    url: str
    credential_hint: str = Field(description="The token's last four characters, never more.")
    default_language: str
    check_status: CheckStatus = Field(
        description="`connected` only after a successful check; `unverified` after any "
        "change to the URL or token."
    )
    last_checked_at: datetime | None
    last_check: LastCheckRead | None
    declared: CapabilityRead
    created_at: datetime
    updated_at: datetime


class IntegrationCheckResponse(BaseModel):
    integration: IntegrationRead
    ok: bool


__all__ = [
    "CapabilityRead",
    "IntegrationCheckRequest",
    "IntegrationCheckResponse",
    "IntegrationCreate",
    "IntegrationRead",
    "IntegrationUpdate",
    "LastCheckRead",
]
