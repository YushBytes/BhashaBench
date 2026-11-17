"""Phase 14 workspaces, members and projects: the role matrix enforced
through the real routes, tenant isolation, and the last-owner rule."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.identity import Role
from tests.auth_helpers import Team, make_team, make_user

API = "/api/v1"


@pytest.fixture(autouse=True)
def _no_default_credential(anonymous: TestClient) -> None:
    """These tests present their own credentials, or deliberately none."""


@pytest.fixture
def team(db_session: Session, settings: Settings, api_client: TestClient) -> Team:
    return make_team(db_session, settings, api_client)


class TestWorkspaces:
    def test_every_route_requires_authentication(self, api_client: TestClient, team: Team) -> None:
        ws = team.workspace.id
        for method, path in [
            ("get", "/workspaces"),
            ("post", "/workspaces"),
            ("get", f"/workspaces/{ws}"),
            ("get", f"/workspaces/{ws}/members"),
            ("get", f"/workspaces/{ws}/projects"),
            ("get", f"/projects/{team.project.id}"),
        ]:
            assert getattr(api_client, method)(API + path).status_code == 401, path

    def test_creating_a_workspace_makes_the_caller_its_owner_with_a_default_project(
        self, api_client: TestClient, team: Team
    ) -> None:
        response = api_client.post(
            f"{API}/workspaces", headers=team.member.headers, json={"name": "Side Project"}
        )
        assert response.status_code == 201
        body = response.json()
        assert (body["slug"], body["role"]) == ("side-project", "owner")
        projects = api_client.get(
            f"{API}/workspaces/{body['id']}/projects", headers=team.member.headers
        ).json()
        assert [p["name"] for p in projects] == ["Default"]
        assert (
            api_client.post(
                f"{API}/workspaces", headers=team.owner.headers, json={"name": "Side Project"}
            ).status_code
            == 409
        )

    def test_the_list_shows_only_the_callers_workspaces(
        self, api_client: TestClient, team: Team
    ) -> None:
        mine = api_client.get(f"{API}/workspaces", headers=team.viewer.headers).json()
        assert [(w["id"], w["role"]) for w in mine] == [(str(team.workspace.id), "viewer")]

    def test_a_foreign_workspace_is_404_not_403(self, api_client: TestClient, team: Team) -> None:
        ws = team.workspace.id
        for path in (
            f"/workspaces/{ws}",
            f"/workspaces/{ws}/members",
            f"/workspaces/{ws}/projects",
        ):
            assert api_client.get(API + path, headers=team.outsider.headers).status_code == 404
        unknown = api_client.get(f"{API}/workspaces/{uuid.uuid4()}", headers=team.owner.headers)
        assert unknown.status_code == 404
        assert (
            api_client.get(
                f"{API}/projects/{team.project.id}", headers=team.outsider.headers
            ).status_code
            == 404
        )


class TestMembers:
    def _add(self, client: TestClient, team: Team, headers: dict, email: str, role: str) -> int:
        return client.post(
            f"{API}/workspaces/{team.workspace.id}/members",
            headers=headers,
            json={"email": email, "role": role},
        ).status_code

    @pytest.mark.parametrize(
        ("actor", "role", "expected"),
        [
            ("owner", "owner", 201),
            ("owner", "admin", 201),
            ("admin", "member", 201),
            ("admin", "viewer", 201),
            ("admin", "admin", 403),
            ("admin", "owner", 403),
            ("member", "viewer", 403),
            ("viewer", "viewer", 403),
        ],
    )
    def test_who_may_add_whom(
        self,
        api_client: TestClient,
        db_session: Session,
        settings: Settings,
        team: Team,
        actor: str,
        role: str,
        expected: int,
    ) -> None:
        newcomer, _ = make_user(db_session, settings, api_client)
        status = self._add(
            api_client, team, getattr(team, actor).headers, newcomer.user.email, role
        )
        assert status == expected

    def test_adding_an_unknown_or_existing_member(self, api_client: TestClient, team: Team) -> None:
        assert (
            self._add(api_client, team, team.owner.headers, "ghost@example.test", "member") == 404
        )
        assert (
            self._add(api_client, team, team.owner.headers, team.viewer.user.email, "member") == 409
        )

    def test_an_added_member_reaches_the_workspace(
        self, api_client: TestClient, team: Team
    ) -> None:
        assert (
            self._add(api_client, team, team.owner.headers, team.outsider.user.email, "viewer")
            == 201
        )
        response = api_client.get(
            f"{API}/workspaces/{team.workspace.id}/projects", headers=team.outsider.headers
        )
        assert response.status_code == 200

    def test_members_are_listed_with_roles(self, api_client: TestClient, team: Team) -> None:
        members = api_client.get(
            f"{API}/workspaces/{team.workspace.id}/members", headers=team.viewer.headers
        ).json()
        assert sorted(m["role"] for m in members) == ["admin", "member", "owner", "viewer"]
        assert all("password" not in str(m) for m in members)

    def test_an_admin_cannot_touch_an_owner_or_another_admin(
        self, api_client: TestClient, db_session: Session, settings: Settings, team: Team
    ) -> None:
        ws = team.workspace.id
        second_admin, _ = make_user(
            db_session, settings, api_client, workspace=team.workspace, role=Role.ADMIN
        )
        for target in (team.owner, second_admin):
            path = f"{API}/workspaces/{ws}/members/{target.user.id}"
            demote = api_client.patch(path, headers=team.admin.headers, json={"role": "viewer"})
            assert demote.status_code == 403
            assert api_client.delete(path, headers=team.admin.headers).status_code == 403

    def test_an_admin_manages_members_but_cannot_promote_to_admin(
        self, api_client: TestClient, team: Team
    ) -> None:
        path = f"{API}/workspaces/{team.workspace.id}/members/{team.member.user.id}"
        demoted = api_client.patch(path, headers=team.admin.headers, json={"role": "viewer"})
        assert demoted.json()["role"] == "viewer"
        promoted = api_client.patch(path, headers=team.admin.headers, json={"role": "admin"})
        assert promoted.status_code == 403

    def test_the_last_owner_cannot_be_demoted_or_removed(
        self, api_client: TestClient, team: Team
    ) -> None:
        path = f"{API}/workspaces/{team.workspace.id}/members/{team.owner.user.id}"
        assert (
            api_client.patch(path, headers=team.owner.headers, json={"role": "admin"}).status_code
            == 409
        )
        assert api_client.delete(path, headers=team.owner.headers).status_code == 409
        promote = f"{API}/workspaces/{team.workspace.id}/members/{team.admin.user.id}"
        assert (
            api_client.patch(
                promote, headers=team.owner.headers, json={"role": "owner"}
            ).status_code
            == 200
        )
        assert api_client.delete(path, headers=team.owner.headers).status_code == 204

    def test_any_member_may_leave(self, api_client: TestClient, team: Team) -> None:
        ws = team.workspace.id
        path = f"{API}/workspaces/{ws}/members/{team.viewer.user.id}"
        assert api_client.delete(path, headers=team.viewer.headers).status_code == 204
        assert (
            api_client.get(f"{API}/workspaces/{ws}", headers=team.viewer.headers).status_code == 404
        )

    def test_an_outsider_cannot_manage_members(self, api_client: TestClient, team: Team) -> None:
        path = f"{API}/workspaces/{team.workspace.id}/members/{team.viewer.user.id}"
        assert api_client.delete(path, headers=team.outsider.headers).status_code == 404


class TestProjects:
    @pytest.mark.parametrize(
        ("actor", "expected"), [("owner", 201), ("admin", 201), ("member", 403), ("viewer", 403)]
    )
    def test_who_may_create_a_project(
        self, api_client: TestClient, team: Team, actor: str, expected: int
    ) -> None:
        response = api_client.post(
            f"{API}/workspaces/{team.workspace.id}/projects",
            headers=getattr(team, actor).headers,
            json={"name": f"P {actor}"},
        )
        assert response.status_code == expected

    def test_project_names_are_unique_within_a_workspace(
        self, api_client: TestClient, team: Team
    ) -> None:
        path = f"{API}/workspaces/{team.workspace.id}/projects"
        assert (
            api_client.post(path, headers=team.owner.headers, json={"name": "Default"}).status_code
            == 409
        )

    def test_rename_and_describe(self, api_client: TestClient, team: Team) -> None:
        path = f"{API}/projects/{team.project.id}"
        body = api_client.patch(
            path, headers=team.admin.headers, json={"name": "Main", "description": "core flows"}
        ).json()
        assert (body["name"], body["description"]) == ("Main", "core flows")
        cleared = api_client.patch(
            path, headers=team.admin.headers, json={"description": None}
        ).json()
        assert (cleared["name"], cleared["description"]) == ("Main", None)
        assert (
            api_client.patch(path, headers=team.member.headers, json={"name": "X"}).status_code
            == 403
        )
        assert api_client.get(path, headers=team.viewer.headers).json()["name"] == "Main"
