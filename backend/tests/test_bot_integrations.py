"""Bring your own bot: connect, check and test a workspace's own chatbot.

Everything runs against the reference bot (`backend/reference_bot`) on a real
loopback socket, through the real routes, service, adapters, outbound guard
and pinned transports. Loopback is reachable only because these tests opt in
with `BOT_HTTP_ALLOW_LOOPBACK`, exactly as a developer's machine would; the
settings refuse that flag in staging and production.

The journey tested end to end: save an integration (unverified), check it
(connected, with verified capabilities), create a run that names it, start
the run, and read back a conversation whose bot replies really came from the
connected bot.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.secretbox import CredentialUnreadableError, open_sealed
from app.models import BotIntegration, Project, Scenario
from app.models.identity import Role
from app.models.suite import TestSuite as SuiteModel
from reference_bot.app import BotConfig, create_app
from tests.auth_helpers import make_user
from tests.conftest import default_tenant
from tests.socket_server import serve, unused_port
from tests.test_pipeline_api import SPEC

API = "/api/v1"
TOKEN = "byo-reference-bot-token-0123456789"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """The suite's settings, with loopback reachable for the reference bot."""
    return settings.model_copy(update={"bot_http_allow_loopback": True})


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


def _create(client: TestClient, project_id: uuid.UUID, **body: Any) -> Any:
    payload = {
        "name": "Reference text bot",
        "protocol": "http",
        "url": "http://127.0.0.1:9",
        "token": TOKEN,
        "default_language": "ta-IN",
        **body,
    }
    return client.post(f"{API}/projects/{project_id}/bot-integrations", json=payload)


@pytest.fixture
def project(api_client: TestClient, db_session: Session) -> Project:
    return default_tenant(db_session)[2]


@pytest.fixture
def connected(api_client: TestClient, project: Project, bot_url: str) -> dict[str, Any]:
    created = _create(api_client, project.id, url=bot_url)
    assert created.status_code == 201, created.text
    checked = api_client.post(f"{API}/bot-integrations/{created.json()['id']}/check")
    assert checked.status_code == 200, checked.text
    assert checked.json()["ok"] is True, checked.json()
    return checked.json()["integration"]


def _suite_and_scenario(session: Session, project: Project) -> tuple[SuiteModel, Scenario]:
    suite = SuiteModel(name=f"byo-{uuid.uuid4().hex[:6]}", project_id=project.id)
    session.add(suite)
    session.flush()
    scenario = Scenario(
        suite_id=suite.id,
        name=f"byo_{SPEC['name']}_{uuid.uuid4().hex[:6]}",
        description=SPEC["description"],
        language=SPEC["language"],
        spec=dict(SPEC),
        spec_version=1,
    )
    session.add(scenario)
    session.flush()
    return suite, scenario


class TestSavingIsNotConnecting:
    def test_a_saved_integration_is_unverified_and_never_returns_its_token(
        self, api_client: TestClient, project: Project
    ) -> None:
        response = _create(api_client, project.id)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["check_status"] == "unverified"
        assert body["last_check"] is None
        assert body["credential_hint"] == "…6789"
        assert TOKEN not in response.text
        assert "token" not in body
        listed = api_client.get(f"{API}/projects/{project.id}/bot-integrations")
        assert TOKEN not in listed.text
        assert [i["id"] for i in listed.json()] == [body["id"]]

    def test_the_declared_capabilities_follow_the_protocol(
        self, api_client: TestClient, project: Project
    ) -> None:
        text = _create(api_client, project.id).json()["declared"]
        voice = _create(
            api_client, project.id, name="voice", protocol="ws_voice", url="ws://127.0.0.1:9/v1"
        ).json()["declared"]
        assert text["accepts_containers"] == [] and text["execution_mode"] == "text_bot_test"
        assert voice["accepts_containers"] == ["wav"]
        assert voice["execution_mode"] == "external_bot_test"
        assert voice["supports_caller_barge_in"] is True
        assert text["supports_caller_barge_in"] is False

    def test_the_token_is_sealed_and_bound_to_its_row(
        self, api_client: TestClient, project: Project, db_session: Session, settings: Settings
    ) -> None:
        integration_id = uuid.UUID(_create(api_client, project.id).json()["id"])
        row = db_session.get(BotIntegration, integration_id)
        assert row is not None
        assert TOKEN.encode() not in row.credential_sealed
        key = settings.secret_key
        assert open_sealed(row.credential_sealed, secret_key=key, bound_to=row.id.bytes) == TOKEN
        with pytest.raises(CredentialUnreadableError):
            open_sealed(row.credential_sealed, secret_key=key, bound_to=uuid.uuid4().bytes)
        with pytest.raises(CredentialUnreadableError):
            open_sealed(row.credential_sealed, secret_key="another-key", bound_to=row.id.bytes)

    @pytest.mark.parametrize(
        ("body", "fragment"),
        [
            ({"url": "wss://bot.example.com/v1"}, "must start with https:// or http://"),
            ({"protocol": "ws_voice", "url": "https://bot.example.com"}, "wss:// or ws://"),
            ({"url": "https://admin:pw@bot.example.com"}, "username or password"),
            ({"url": "https://bot.example.com/#frag"}, "fragment"),
            ({"url": "https://bot.example.com:99999"}, "malformed"),
            ({"token": "short"}, "16 to 4096"),
            ({"token": "has a space in it, long enough"}, "whitespace"),
            ({"default_language": "fr-FR"}, "not a supported language"),
        ],
    )
    def test_a_configuration_no_adapter_can_use_is_refused(
        self, api_client: TestClient, project: Project, body: dict[str, Any], fragment: str
    ) -> None:
        response = _create(api_client, project.id, **body)
        assert response.status_code == 422, response.text
        assert fragment in response.text
        if "token" in body:
            assert body["token"] not in response.text  # a refused token is not echoed

    def test_a_duplicate_name_is_a_conflict(self, api_client: TestClient, project: Project) -> None:
        assert _create(api_client, project.id).status_code == 201
        assert _create(api_client, project.id).status_code == 409

    def test_the_operator_can_forbid_user_supplied_bots(
        self, api_client: TestClient, project: Project, test_app: FastAPI, settings: Settings
    ) -> None:
        from app.core.config import get_settings

        test_app.dependency_overrides[get_settings] = lambda: settings.model_copy(
            update={"bot_integrations_enabled": False}
        )
        response = _create(api_client, project.id)
        assert response.status_code == 409
        assert "BOT_INTEGRATIONS_ENABLED" in response.text


class TestTheConnectionCheck:
    def test_a_reachable_text_bot_is_connected_with_what_was_verified(
        self, connected: dict[str, Any]
    ) -> None:
        check = connected["last_check"]
        assert connected["check_status"] == "connected"
        assert check["outcome"] == "connected"
        assert check["verified"] == {
            "reachable": True,
            "authenticated": True,
            "session_lifecycle": True,
            "text_exchange": True,
            "audio_input": False,
            "audio_output": False,
        }
        assert check["latency_ms"] > 0
        assert check["detail"]["reply_chars"] > 0

    def test_a_wrong_token_is_an_authentication_failure_and_never_logged(
        self,
        api_client: TestClient,
        project: Project,
        bot_url: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        wrong = "wrong-token-for-the-reference-bot-xyz"
        created = _create(api_client, project.id, url=bot_url, token=wrong).json()
        with caplog.at_level(logging.DEBUG):
            response = api_client.post(f"{API}/bot-integrations/{created['id']}/check")
        body = response.json()
        assert response.status_code == 200
        assert body["ok"] is False
        assert body["integration"]["check_status"] == "failed"
        assert body["integration"]["last_check"]["outcome"] == "authentication_failed"
        assert body["integration"]["last_check"]["verified"]["authenticated"] is False
        assert wrong not in response.text
        assert wrong not in caplog.text

    def test_nothing_listening_is_unreachable(
        self, api_client: TestClient, project: Project
    ) -> None:
        created = _create(api_client, project.id, url=f"http://127.0.0.1:{unused_port()}").json()
        check = api_client.post(f"{API}/bot-integrations/{created['id']}/check").json()
        assert check["integration"]["last_check"]["outcome"] == "unreachable"
        assert check["integration"]["check_status"] == "failed"

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data",
            "http://[::ffff:169.254.169.254]/",
            "http://10.0.0.5/",
            "https://0.0.0.0/",
        ],
    )
    def test_a_forbidden_destination_is_refused_before_any_connection(
        self, api_client: TestClient, project: Project, url: str
    ) -> None:
        created = _create(api_client, project.id, url=url).json()
        check = api_client.post(f"{API}/bot-integrations/{created['id']}/check").json()
        assert check["ok"] is False
        assert check["integration"]["last_check"]["outcome"] == "target_refused"

    def test_a_voice_bot_is_checked_in_the_format_a_run_streams(
        self, api_client: TestClient, project: Project, bot_url: str
    ) -> None:
        voice_url = bot_url.replace("http://", "ws://") + "/v1/voice"
        created = _create(
            api_client, project.id, name="voice", protocol="ws_voice", url=voice_url
        ).json()
        check = api_client.post(f"{API}/bot-integrations/{created['id']}/check").json()
        assert check["ok"] is True, check
        verified = check["integration"]["last_check"]["verified"]
        assert verified["audio_format_accepted"] is True
        # A handshake proves neither of these; only a run measures them.
        assert verified["audio_output"] is None
        assert verified["caller_barge_in"] is None
        assert check["integration"]["last_check"]["detail"]["format"]["sample_rate_hz"] == 16000

    def test_a_voice_bot_with_a_wrong_token_fails_the_handshake(
        self, api_client: TestClient, project: Project, bot_url: str
    ) -> None:
        voice_url = bot_url.replace("http://", "ws://") + "/v1/voice"
        created = _create(
            api_client, project.id, name="voice", protocol="ws_voice", url=voice_url,
            token="wrong-token-for-the-reference-bot-xyz",
        ).json()  # fmt: skip
        check = api_client.post(f"{API}/bot-integrations/{created['id']}/check").json()
        assert check["integration"]["last_check"]["outcome"] == "authentication_failed"

    def test_changing_the_url_or_token_demotes_to_unverified(
        self, api_client: TestClient, connected: dict[str, Any], bot_url: str
    ) -> None:
        path = f"{API}/bot-integrations/{connected['id']}"
        renamed = api_client.patch(path, json={"name": "Renamed"}).json()
        assert renamed["check_status"] == "connected"
        moved = api_client.patch(path, json={"url": bot_url + "/"}).json()
        assert moved["check_status"] == "unverified" and moved["last_check"] is None
        api_client.post(f"{path}/check")
        rekeyed = api_client.patch(path, json={"token": TOKEN + "-rotated"}).json()
        assert rekeyed["check_status"] == "unverified"
        assert rekeyed["credential_hint"] == "…ated"


class TestRunningAScenarioAgainstAConnectedBot:
    def test_the_whole_journey_records_replies_from_the_connected_bot(
        self,
        api_client: TestClient,
        db_session: Session,
        project: Project,
        connected: dict[str, Any],
    ) -> None:
        suite, scenario = _suite_and_scenario(db_session, project)
        created = api_client.post(
            f"{API}/test-runs",
            json={
                "suite_id": str(suite.id),
                "scenario_id": str(scenario.id),
                "mode": "text_bot_test",
                "bot_integration_id": connected["id"],
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        assert created.json()["bot_adapter"] == "http"
        started = api_client.post(f"{API}/test-runs/{run_id}/start")
        assert started.status_code == 200, started.text
        report = started.json()
        assert report["status"] == "completed", report
        assert report["bot_text_externally_received"] is True, report
        turns = api_client.get(f"{API}/test-runs/{run_id}/turns").json()["turns"]
        bot_turns = [t for t in turns if t["speaker"] == "bot"]
        assert bot_turns and all(t["text"] for t in bot_turns)
        row = _run_row(db_session, run_id)
        integration = (row.run_metadata or {})["pipeline"]["bot_integration"]
        assert integration["id"] == connected["id"]
        assert integration["host"] == "127.0.0.1"
        assert TOKEN not in str(row.run_metadata)

    def test_an_unverified_integration_cannot_be_tested(
        self, api_client: TestClient, db_session: Session, project: Project, bot_url: str
    ) -> None:
        integration = _create(api_client, project.id, url=bot_url).json()
        suite, scenario = _suite_and_scenario(db_session, project)
        response = api_client.post(
            f"{API}/test-runs",
            json={
                "suite_id": str(suite.id), "scenario_id": str(scenario.id),
                "mode": "text_bot_test", "bot_integration_id": integration["id"],
            },
        )  # fmt: skip
        assert response.status_code == 409
        assert "connection check" in response.text

    @pytest.mark.parametrize(
        ("mode", "adapter", "fragment"),
        [
            ("external_bot_test", None, "carries none"),
            ("offline_simulation", None, "contacts nothing"),
            ("text_bot_test", "ws_voice", "contradicts"),
        ],
    )
    def test_a_mode_or_adapter_the_protocol_cannot_honour_is_refused(
        self,
        api_client: TestClient,
        db_session: Session,
        project: Project,
        connected: dict[str, Any],
        mode: str,
        adapter: str | None,
        fragment: str,
    ) -> None:
        suite, scenario = _suite_and_scenario(db_session, project)
        body: dict[str, Any] = {
            "suite_id": str(suite.id), "scenario_id": str(scenario.id),
            "mode": mode, "bot_integration_id": connected["id"],
        }  # fmt: skip
        if adapter:
            body["bot_adapter"] = adapter
        response = api_client.post(f"{API}/test-runs", json=body)
        assert response.status_code == 422, response.text
        assert fragment in response.text

    def test_another_projects_integration_is_refused(
        self,
        api_client: TestClient,
        db_session: Session,
        connected: dict[str, Any],
    ) -> None:
        _, workspace, _ = default_tenant(db_session)
        other = api_client.post(
            f"{API}/workspaces/{workspace.id}/projects", json={"name": "Other"}
        ).json()
        other_project = db_session.get(Project, uuid.UUID(other["id"]))
        assert other_project is not None
        suite, scenario = _suite_and_scenario(db_session, other_project)
        response = api_client.post(
            f"{API}/test-runs",
            json={
                "suite_id": str(suite.id), "scenario_id": str(scenario.id),
                "mode": "text_bot_test", "bot_integration_id": connected["id"],
            },
        )  # fmt: skip
        assert response.status_code == 422
        assert "another project" in response.text

    def test_a_deleted_integration_stops_its_runs_but_not_their_evidence(
        self,
        api_client: TestClient,
        db_session: Session,
        project: Project,
        connected: dict[str, Any],
    ) -> None:
        suite, scenario = _suite_and_scenario(db_session, project)
        run_id = api_client.post(
            f"{API}/test-runs",
            json={
                "suite_id": str(suite.id), "scenario_id": str(scenario.id),
                "mode": "text_bot_test", "bot_integration_id": connected["id"],
            },
        ).json()["run_id"]  # fmt: skip
        assert api_client.delete(f"{API}/bot-integrations/{connected['id']}").status_code == 204
        refused = api_client.post(f"{API}/test-runs/{run_id}/start")
        assert refused.status_code == 409
        assert "deleted" in refused.text
        assert api_client.get(f"{API}/test-runs/{run_id}").status_code == 200


class TestTenancy:
    def test_an_outsider_sees_a_404_and_a_viewer_cannot_write(
        self,
        api_client: TestClient,
        db_session: Session,
        settings: Settings,
        project: Project,
        connected: dict[str, Any],
    ) -> None:
        _, workspace, _ = default_tenant(db_session)
        viewer, _ = make_user(
            db_session, settings, api_client, workspace=workspace, role=Role.VIEWER
        )
        outsider, _ = make_user(db_session, settings, api_client)
        path = f"{API}/bot-integrations/{connected['id']}"
        assert api_client.get(path, headers=outsider.headers).status_code == 404
        assert api_client.post(f"{path}/check", headers=outsider.headers).status_code == 404
        assert (
            api_client.get(
                f"{API}/projects/{project.id}/bot-integrations", headers=outsider.headers
            ).status_code
            == 404
        )
        assert api_client.get(path, headers=viewer.headers).status_code == 200
        assert api_client.post(f"{path}/check", headers=viewer.headers).status_code == 403
        assert api_client.delete(path, headers=viewer.headers).status_code == 403
        with TestClient(api_client.app) as anonymous:
            assert _create(anonymous, project.id).status_code == 401


def _run_row(session: Session, run_id: str) -> Any:
    from app.models import TestRun as RunModel

    row = session.get(RunModel, uuid.UUID(run_id))
    assert row is not None
    return row
