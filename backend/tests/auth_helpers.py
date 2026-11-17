"""Signed-in users for tests, through the real login route.

Not a fixture module: tests import `Actors`/`make_user` so each test states
which users and roles it needs. Sessions are real - created by POST
/auth/login against the test database - so these helpers exercise the same
path a client does.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.identity import Project, Role, User, Workspace
from app.repositories import identity as repo
from app.services import auth_service

PASSWORD = "a long enough passphrase"


@dataclass
class Actor:
    user: User
    headers: dict[str, str]


def login_headers(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "session_type": "bearer"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def make_user(
    session: Session,
    settings: Settings,
    client: TestClient,
    *,
    workspace: Workspace | None = None,
    role: Role = Role.OWNER,
) -> tuple[Actor, Workspace]:
    """A new user with `role` in `workspace` (a fresh one when omitted)."""
    tag = uuid.uuid4().hex[:10]
    user, ws = auth_service.create_user(
        session,
        settings,
        email=f"user-{tag}@example.test",
        display_name=f"User {tag}",
        password=PASSWORD,
        workspace_name=None if workspace else f"ws-{tag}",
        workspace_slug=workspace.slug if workspace else f"ws-{tag}",
        role=role,
    )
    return Actor(user, login_headers(client, user.email)), ws


def default_project(session: Session, workspace: Workspace) -> Project:
    project = repo.get_project_by_name(session, workspace.id, auth_service.DEFAULT_PROJECT_NAME)
    assert project is not None
    return project


@dataclass
class Team:
    """One workspace with a user at each role, and an outsider elsewhere."""

    workspace: Workspace
    project: Project
    owner: Actor
    admin: Actor
    member: Actor
    viewer: Actor
    outsider: Actor


def make_team(session: Session, settings: Settings, client: TestClient) -> Team:
    owner, ws = make_user(session, settings, client)
    admin, _ = make_user(session, settings, client, workspace=ws, role=Role.ADMIN)
    member, _ = make_user(session, settings, client, workspace=ws, role=Role.MEMBER)
    viewer, _ = make_user(session, settings, client, workspace=ws, role=Role.VIEWER)
    outsider, _ = make_user(session, settings, client)
    return Team(ws, default_project(session, ws), owner, admin, member, viewer, outsider)


__all__ = [
    "PASSWORD",
    "Actor",
    "Team",
    "default_project",
    "login_headers",
    "make_team",
    "make_user",
]
