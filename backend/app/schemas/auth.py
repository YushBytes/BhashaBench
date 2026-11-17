"""Request and response models for authentication, workspaces and projects."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.auth.passwords import MAX_PASSWORD_CHARS
from app.models.identity import Role


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    # SecretStr so the value never appears in a repr, a log line or a
    # validation error; the handler that strips credential inputs is the
    # second layer.
    password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)
    session_type: Literal["cookie", "bearer"] = Field(
        default="cookie",
        description=(
            "`cookie` (browsers): an HttpOnly, SameSite=Strict cookie is set and the "
            "token is NOT returned in the body, so page script cannot read it. "
            "`bearer` (CLI and API clients): the token is returned once, in the body, "
            "and no cookie is set."
        ),
    )


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)
    workspace_name: str = Field(min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)
    new_password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class MembershipRead(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_slug: str
    role: Role


class MeResponse(BaseModel):
    user: UserRead
    workspaces: list[MembershipRead]
    session_expires_at: datetime | None


class LoginResponse(BaseModel):
    user: UserRead
    expires_at: datetime
    session_type: Literal["cookie", "bearer"]
    token: str | None = Field(
        default=None, description="Present only for `session_type=bearer`. Shown once."
    )


class PasswordChangeResponse(BaseModel):
    other_sessions_revoked: int


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


class WorkspaceRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: Role = Field(description="The caller's own role here.")
    created_at: datetime


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    role: Role


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectRead(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
