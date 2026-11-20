"""Phase 14 authorisation, swept across the whole API.

Two sweeps read the generated OpenAPI document, so a route added later is
covered without anyone remembering to add it here:

1. every operation outside a short public allowlist answers **401** to a
   caller with no credential;
2. every operation addressing a tenant's resource answers **404** to a
   member of another workspace - indistinguishable from a resource that does
   not exist - and **403** to a member whose role is too low.

The rest checks what a sweep cannot: listings and aggregates never include
another tenant's rows, a run cannot borrow another tenant's scenario, suite
creation picks its project only when unambiguous, the WebSocket handshake is
authenticated, and the migration keeps pre-tenancy data.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.models import Scenario
from app.models.identity import Role
from tests.auth_helpers import make_user
from tests.conftest import BACKEND_ROOT, _admin_url, _source_url, default_tenant
from tests.test_pipeline_api import SPEC, pipeline_client  # noqa: F401 - fixture

API = "/api/v1"
PUBLIC = {
    ("get", "/"),
    ("get", "/health"),
    ("get", "/api/v1/health"),
    ("get", "/api/v1/languages"),
    ("get", "/api/v1/evaluation/metrics"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/signup"),
    ("get", "/api/v1/auth/options"),
    ("post", "/api/v1/telephony/events/{provider}"),
}
"""Public on purpose: liveness, the language and metric catalogues (static
reference data), the two routes that exist to obtain a credential, and the
telephony webhook, whose credential is the provider's signature over the
body rather than a session (tested in test_telephony_calls.py)."""


INTEGRATION_BODY = {
    "name": "sweep bot",
    "protocol": "http",
    "url": "https://bot.example.com",
    "token": "sweep-token-0123456789abcdef",
}
"""A connected bot for the sweep. Saving contacts nothing, so no bot is needed."""


READ_ONLY_POSTS = {("post", "/api/v1/test-runs/{run_id}/audio-links")}
"""POSTs that need only `view` and change nothing: minting a signed link to
audio the caller can already play. Compared against the owner like a GET."""


def _operations(client: TestClient) -> list[tuple[str, str]]:
    schema = client.app.openapi()  # type: ignore[attr-defined]
    methods = {"get", "post", "put", "patch", "delete"}
    return sorted(
        (method, path)
        for path, item in schema["paths"].items()
        for method in item
        if method in methods
    )


def _fill(path: str, ids: dict[str, Any]) -> str:
    for name, value in ids.items():
        path = path.replace("{" + name + "}", str(value))
    assert "{" not in path, f"no id for a parameter in {path}"
    return path


def _call(client: TestClient, method: str, path: str, headers: dict[str, str], body: Any) -> int:
    kwargs: dict[str, Any] = {"headers": headers}
    if method in {"post", "put", "patch"}:
        kwargs["json"] = body
    return getattr(client, method)(path, **kwargs).status_code


# ---------------------------------------------------------------------------
# 1. Authentication on every private route
# ---------------------------------------------------------------------------


class TestEveryPrivateRouteNeedsACredential:
    def test_the_public_allowlist_is_exact(self, anonymous: TestClient) -> None:
        operations = set(_operations(anonymous))
        assert operations >= PUBLIC, PUBLIC - operations

    def test_no_credential_is_401_everywhere_else(self, anonymous: TestClient) -> None:
        ids = {
            name: uuid.uuid4()
            for name in ("suite_id", "scenario_id", "run_id", "conversation_id",
                         "workspace_id", "user_id", "project_id", "integration_id")
        }  # fmt: skip
        ids["turn_index"] = 0
        ids["provider"] = "mock"
        refused = []
        for method, path in _operations(anonymous):
            if (method, path) in PUBLIC:
                continue
            status = _call(anonymous, method, _fill(path, ids), {}, {})
            if status != 401:
                refused.append((method, path, status))
        assert refused == []

    def test_a_revoked_or_forged_token_is_401(self, anonymous: TestClient) -> None:
        from app.auth import tokens

        forged = {"Authorization": f"Bearer {tokens.new_token()}"}
        assert anonymous.get(f"{API}/suites", headers=forged).status_code == 401


# ---------------------------------------------------------------------------
# 2. Tenant isolation and the role matrix on every resource route
# ---------------------------------------------------------------------------


@pytest.fixture
def world(
    pipeline_client: TestClient,  # noqa: F811 - the imported fixture
    db_session: Session,
    settings: Settings,
) -> dict[str, Any]:
    """A real suite, scenario, run, conversation and evaluation, owned by the
    default tenant; a viewer and a member there; an outsider elsewhere."""
    owner, workspace, project = default_tenant(db_session)
    suite = pipeline_client.post(f"{API}/suites", json={"name": "isolated"}).json()
    scenario = Scenario(
        suite_id=uuid.UUID(suite["id"]),
        name=f"{SPEC['name']}_iso",
        description=SPEC["description"],
        language="ta-IN",
        spec=SPEC,
        spec_version=1,
    )
    db_session.add(scenario)
    db_session.flush()
    run = pipeline_client.post(
        f"{API}/test-runs",
        json={
            "suite_id": suite["id"],
            "scenario_id": str(scenario.id),
            "mode": "offline_simulation",
        },
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["run_id"]
    assert pipeline_client.post(f"{API}/test-runs/{run_id}/start").status_code == 200
    pipeline_client.post(f"{API}/test-runs/{run_id}/evaluations")
    conversation = pipeline_client.post(
        f"{API}/caller/conversations",
        json={"suite_id": suite["id"], "scenario_id": str(scenario.id)},
    )
    assert conversation.status_code == 201, conversation.text
    viewer, _ = make_user(
        db_session, settings, pipeline_client, workspace=workspace, role=Role.VIEWER
    )
    member, _ = make_user(
        db_session, settings, pipeline_client, workspace=workspace, role=Role.MEMBER
    )
    outsider, _ = make_user(db_session, settings, pipeline_client)
    integration = pipeline_client.post(
        f"{API}/projects/{project.id}/bot-integrations", json=INTEGRATION_BODY
    )
    assert integration.status_code == 201, integration.text
    return {
        "client": pipeline_client,
        "ids": {
            "suite_id": suite["id"],
            "scenario_id": scenario.id,
            "run_id": run_id,
            "conversation_id": conversation.json()["conversation_id"],
            "workspace_id": workspace.id,
            "project_id": project.id,
            "integration_id": integration.json()["id"],
            "user_id": owner.id,
            "turn_index": 1,
            "provider": "mock",
        },
        "viewer": viewer,
        "member": member,
        "outsider": outsider,
    }


def _bodies(ids: dict[str, Any]) -> dict[tuple[str, str], Any]:
    """Valid bodies where validation would otherwise answer before access."""
    target = str(ids["suite_id"])
    ws, scenario = "/api/v1/workspaces/{workspace_id}", "/api/v1/scenarios/{scenario_id}"
    return {
        ("post", f"{ws}/members"): {"email": "x@example.test", "role": "viewer"},
        ("patch", f"{ws}/members/{{user_id}}"): {"role": "viewer"},
        ("post", f"{ws}/projects"): {"name": "intruder"},
        ("post", "/api/v1/projects/{project_id}/bot-integrations"): {
            **INTEGRATION_BODY,
            "name": "intruder",
        },
        ("patch", "/api/v1/projects/{project_id}"): {"name": "renamed"},
        ("post", f"{scenario}/copy"): {"target_suite_id": target, "new_name": "c"},
        ("post", f"{scenario}/move"): {"target_suite_id": target},
    }


def _addressed(operations: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Operations whose path names a tenant resource."""
    return [(m, p) for m, p in operations if "{" in p and (m, p) not in PUBLIC]


class TestTenantIsolation:
    def test_an_outsider_gets_404_on_every_resource_route(self, world: dict[str, Any]) -> None:
        client, ids, outsider = world["client"], world["ids"], world["outsider"]
        bodies = _bodies(ids)
        leaked = []
        for method, path in _addressed(_operations(client)):
            status = _call(
                client, method, _fill(path, ids), outsider.headers, bodies.get((method, path), {})
            )
            if status != 404:
                leaked.append((method, path, status))
        assert leaked == []

    def test_the_404_is_identical_to_a_missing_resource(self, world: dict[str, Any]) -> None:
        client, ids, outsider = world["client"], world["ids"], world["outsider"]
        foreign = client.get(f"{API}/test-runs/{ids['run_id']}", headers=outsider.headers).json()
        missing_id = uuid.uuid4()
        missing = client.get(f"{API}/test-runs/{missing_id}", headers=outsider.headers).json()
        assert foreign["error"]["message"].replace(str(ids["run_id"]), "ID") == missing["error"][
            "message"
        ].replace(str(missing_id), "ID")

    def test_a_viewer_reads_everything_and_writes_nothing(self, world: dict[str, Any]) -> None:
        """A viewer's read answers exactly as the owner's does (a turn with no
        audio is 404 to both); every write is 403."""
        client, ids, viewer = world["client"], world["ids"], world["viewer"]
        bodies = _bodies(ids)
        wrong = []
        for method, path in _addressed(_operations(client)):
            url, body = _fill(path, ids), bodies.get((method, path), {})
            status = _call(client, method, url, viewer.headers, body)
            if method == "get" or (method, path) in READ_ONLY_POSTS:
                owner_status = _call(client, method, url, {}, body)
                if status != owner_status:
                    wrong.append((method, path, status, owner_status))
            elif status != 403:
                wrong.append((method, path, status))
        assert wrong == []

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/suites/{suite_id}",
            "/api/v1/scenarios/{scenario_id}",
            "/api/v1/projects/{project_id}",
        ],
    )
    def test_a_member_cannot_delete(self, world: dict[str, Any], path: str) -> None:
        client, ids, member = world["client"], world["ids"], world["member"]
        assert client.delete(_fill(path, ids), headers=member.headers).status_code == 403

    def test_a_member_can_drive_a_run(self, world: dict[str, Any]) -> None:
        client, ids, member = world["client"], world["ids"], world["member"]
        evaluated = client.post(
            f"{API}/test-runs/{ids['run_id']}/evaluations", headers=member.headers
        )
        assert evaluated.status_code == 201

    def test_listings_and_aggregates_show_an_outsider_nothing(self, world: dict[str, Any]) -> None:
        client, outsider = world["client"], world["outsider"]
        h = outsider.headers
        assert client.get(f"{API}/suites", headers=h).json()["total"] == 0
        assert client.get(f"{API}/scenarios", headers=h).json()["total"] == 0
        assert client.get(f"{API}/test-runs", headers=h).json()["total"] == 0
        assert client.get(f"{API}/analytics/summary", headers=h).json()["overall"]["runs"] == 0
        assert client.get(f"{API}/analytics/trend", headers=h).json()["periods"] == []
        csv_rows = client.get(f"{API}/analytics/runs.csv", headers=h).text.strip().splitlines()
        assert len(csv_rows) == 1  # the header only

    def test_the_owners_own_listing_includes_them(self, world: dict[str, Any]) -> None:
        client, ids = world["client"], world["ids"]
        runs = client.get(f"{API}/test-runs").json()
        assert ids["run_id"] in [r["run_id"] for r in runs["items"]]
        assert client.get(f"{API}/analytics/summary").json()["overall"]["runs"] >= 1

    def test_filtering_by_a_foreign_suite_is_404_not_an_empty_page(
        self, world: dict[str, Any]
    ) -> None:
        client, ids, h = world["client"], world["ids"], world["outsider"].headers
        for path in ("/test-runs", "/scenarios", "/analytics/summary", "/analytics/runs.csv"):
            response = client.get(API + path, headers=h, params={"suite_id": str(ids["suite_id"])})
            assert response.status_code == 404, path

    def test_comparing_against_a_foreign_run_is_404(
        self, world: dict[str, Any], db_session: Session, settings: Settings
    ) -> None:
        client, ids, outsider = world["client"], world["ids"], world["outsider"]
        params = {"baseline": str(ids["run_id"]), "candidate": str(ids["run_id"])}
        assert (
            client.get(
                f"{API}/analytics/compare", headers=outsider.headers, params=params
            ).status_code
            == 404
        )


class TestRunTargets:
    def test_a_run_cannot_borrow_another_tenants_scenario(
        self, world: dict[str, Any], db_session: Session, settings: Settings
    ) -> None:
        client, ids, outsider = world["client"], world["ids"], world["outsider"]
        own_suite = client.post(
            f"{API}/suites", headers=outsider.headers, json={"name": "mine"}
        ).json()
        for path in ("/test-runs", "/caller/conversations"):
            body = {
                "suite_id": own_suite["id"],
                "scenario_id": str(ids["scenario_id"]),
                "mode": "offline_simulation",
            }
            if path != "/test-runs":
                body.pop("mode")
            response = client.post(API + path, headers=outsider.headers, json=body)
            assert response.status_code == 404, (path, response.text)

    def test_a_scenario_from_another_suite_of_the_same_tenant_is_422(
        self, world: dict[str, Any]
    ) -> None:
        client, ids = world["client"], world["ids"]
        other = client.post(f"{API}/suites", json={"name": "other"}).json()
        response = client.post(
            f"{API}/test-runs",
            json={
                "suite_id": other["id"],
                "scenario_id": str(ids["scenario_id"]),
                "mode": "offline_simulation",
            },
        )
        assert response.status_code == 422
        assert "another suite" in response.json()["error"]["message"]

    def test_copying_into_a_foreign_suite_is_404(self, world: dict[str, Any]) -> None:
        client, ids, outsider = world["client"], world["ids"], world["outsider"]
        foreign = client.post(
            f"{API}/suites", headers=outsider.headers, json={"name": "dest"}
        ).json()
        response = client.post(
            f"{API}/scenarios/{ids['scenario_id']}/copy",
            json={"target_suite_id": foreign["id"], "new_name": "stolen"},
        )
        assert response.status_code == 404


class TestSuiteCreation:
    def test_the_project_is_inferred_only_when_unambiguous(
        self, anonymous: TestClient, db_session: Session, settings: Settings
    ) -> None:
        owner, workspace = make_user(db_session, settings, anonymous)
        made = anonymous.post(f"{API}/suites", headers=owner.headers, json={"name": "s"})
        assert made.status_code == 201
        anonymous.post(
            f"{API}/workspaces/{workspace.id}/projects", headers=owner.headers, json={"name": "Two"}
        )
        ambiguous = anonymous.post(f"{API}/suites", headers=owner.headers, json={"name": "t"})
        assert ambiguous.status_code == 422
        assert "project_id is required" in ambiguous.json()["error"]["message"]

    def test_a_viewer_cannot_create_a_suite_anywhere(
        self, anonymous: TestClient, db_session: Session, settings: Settings
    ) -> None:
        owner, workspace = make_user(db_session, settings, anonymous)
        viewer, _ = make_user(
            db_session, settings, anonymous, workspace=workspace, role=Role.VIEWER
        )
        project = anonymous.get(
            f"{API}/workspaces/{workspace.id}/projects", headers=owner.headers
        ).json()[0]
        inferred = anonymous.post(f"{API}/suites", headers=viewer.headers, json={"name": "v"})
        assert inferred.status_code == 422
        named = anonymous.post(
            f"{API}/suites", headers=viewer.headers, json={"name": "v", "project_id": project["id"]}
        )
        assert named.status_code == 403

    def test_names_are_unique_per_project_not_globally(
        self, anonymous: TestClient, db_session: Session, settings: Settings
    ) -> None:
        a, _ = make_user(db_session, settings, anonymous)
        b, _ = make_user(db_session, settings, anonymous)
        for actor in (a, b):
            assert (
                anonymous.post(
                    f"{API}/suites", headers=actor.headers, json={"name": "smoke"}
                ).status_code
                == 201
            )
        assert (
            anonymous.post(f"{API}/suites", headers=a.headers, json={"name": "smoke"}).status_code
            == 409
        )

    def test_a_project_with_suites_cannot_be_deleted(
        self, anonymous: TestClient, db_session: Session, settings: Settings
    ) -> None:
        owner, _ = make_user(db_session, settings, anonymous)
        suite = anonymous.post(f"{API}/suites", headers=owner.headers, json={"name": "keep"}).json()
        path = f"{API}/projects/{suite['project_id']}"
        assert anonymous.delete(path, headers=owner.headers).status_code == 409
        assert (
            anonymous.delete(f"{API}/suites/{suite['id']}", headers=owner.headers).status_code
            == 200
        )
        assert anonymous.delete(path, headers=owner.headers).status_code == 204


# ---------------------------------------------------------------------------
# The WebSocket handshake
# ---------------------------------------------------------------------------


class TestWebSocketAuthentication:
    PATH = "/api/v1/transcription/stream?language=hi-IN"

    def test_no_credential_closes_with_1008(self, anonymous: TestClient) -> None:
        with pytest.raises(WebSocketDisconnect) as closed, anonymous.websocket_connect(self.PATH):
            pass
        assert closed.value.code == 1008

    def test_a_bearer_token_is_accepted(self, api_client: TestClient) -> None:
        with api_client.websocket_connect(self.PATH) as socket:
            socket.send_text("EOS")
            events = []
            while True:
                event = socket.receive_json()
                events.append(event["type"])
                if event["type"] in ("completed", "failed"):
                    break
        assert events[0] == "started"

    def test_a_foreign_origin_with_the_cookie_is_refused(
        self, anonymous: TestClient, db_session: Session, settings: Settings
    ) -> None:
        actor, _ = make_user(db_session, settings, anonymous)
        anonymous.post(
            f"{API}/auth/login",
            json={"email": actor.user.email, "password": "a long enough passphrase"},
        )
        evil = {"Origin": "https://evil.example"}
        with (
            pytest.raises(WebSocketDisconnect) as closed,
            anonymous.websocket_connect(self.PATH, headers=evil),
        ):
            pass
        assert closed.value.code == 1008


# ---------------------------------------------------------------------------
# The migration keeps pre-tenancy data
# ---------------------------------------------------------------------------

MIGRATION_DB = "bhashabench_test_tenancy_migration"


@pytest.fixture
def scratch_database(database_url: str) -> Iterator[str]:
    """A throwaway database, separate from the shared test database."""
    from urllib.parse import urlsplit, urlunsplit

    del database_url  # only for its skip-when-unreachable behaviour
    base = _source_url()
    admin = create_engine(_admin_url(base), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}"'))
        connection.execute(text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    yield urlunsplit(urlsplit(base)._replace(path=f"/{MIGRATION_DB}"))
    with admin.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :n AND pid <> pg_backend_pid()"
            ),
            {"n": MIGRATION_DB},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}"'))
    admin.dispose()


def _alembic(url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class TestTenancyMigration:
    def test_existing_suites_are_kept_in_a_legacy_workspace(self, scratch_database: str) -> None:
        _alembic(scratch_database, "upgrade", "05f303520380")
        engine = create_engine(scratch_database)
        suite_id = uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO test_suites (id, name) VALUES (:id, 'pre-tenancy')"),
                {"id": suite_id},
            )
        _alembic(scratch_database, "upgrade", "head")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT w.slug, p.name FROM test_suites s "
                    "JOIN projects p ON p.id = s.project_id "
                    "JOIN workspaces w ON w.id = p.workspace_id WHERE s.id = :id"
                ),
                {"id": suite_id},
            ).one()
            members = connection.execute(
                text("SELECT count(*) FROM workspace_memberships")
            ).scalar()
        assert tuple(row) == ("legacy", "Default")
        assert members == 0  # nobody sees it until an operator grants access
        _alembic(scratch_database, "downgrade", "-1")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM test_suites")).scalar() == 1
        engine.dispose()

    def test_a_fresh_database_gets_no_legacy_workspace(self, db_session: Session) -> None:
        from sqlalchemy import select

        from app.models.identity import Workspace

        assert db_session.scalar(select(Workspace).where(Workspace.slug == "legacy")) is None
