"""`text_bot_test` runs end to end: the real caller, the real engine, real
PostgreSQL, and the reference bot on a real localhost socket.

Nothing here is mocked between the caller's decision and the bot's reply:
the rule engine decides, the engine sends the words over HTTP, the reference
bot answers from its script, and the reply is persisted as a bot turn. No
audio moves, and the tests assert the run says so.

Needs PostgreSQL (`docker compose up -d db`); never skips silently.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.service import CallerService
from app.core.config import AppEnv, Settings
from app.core.outbound import OutboundPolicy
from app.models import Scenario
from app.models import TestSuite as SuiteModel
from app.pipeline.bots.http_text import HttpBotConfig, HttpTextBotAdapter
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.engine import RunConfig, RunEngine, RunReport
from app.pipeline.errors import PipelineConfigurationError
from app.pipeline.modes import ExecutionMode, PipelineStatus, RunOutcome
from app.repositories import caller_conversations as caller_repo
from reference_bot.app import BotConfig, create_app
from reference_bot.responder import load
from tests.socket_server import serve, unused_port

TOKEN = "text-bot-engine-test-token-012345"
REFERENCE = "447219"
LOOPBACK = OutboundPolicy.from_setting("127.0.0.1", allow_loopback=True)

SPEC: dict[str, Any] = {
    "name": "english_request_status",
    "description": "A customer checks the status of a service request.",
    "language": "en-IN",
    "persona": {"identity": "Customer", "speaking_style": "polite", "traits": []},
    "goal": {"objective": "Find out the status of my service request.", "max_turns": 8},
    "known_facts": {"request_reference": REFERENCE},
    "expected_outcomes": ["Bot confirms the request"],
    "audio": {"noise_profile": "clean", "snr_db": 30.0, "packet_loss_percent": 0.0},
    "constraints": None,
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "audio"),
        _env_file=None,
    )


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


def _scenario(session: Session) -> tuple[SuiteModel, Scenario]:
    suite = SuiteModel(name=f"text-bot-{uuid.uuid4().hex[:8]}", description="text bot fixture")
    session.add(suite)
    session.flush()
    scenario = Scenario(
        suite_id=suite.id,
        name=f"{SPEC['name']}_{uuid.uuid4().hex[:6]}",
        description=SPEC["description"],
        language=SPEC["language"],
        spec=dict(SPEC),
        spec_version=1,
    )
    session.add(scenario)
    session.flush()
    return suite, scenario


def _http(url: str, *, token: str = TOKEN) -> HttpTextBotAdapter:
    return HttpTextBotAdapter(
        HttpBotConfig(
            base_url=url,
            token=SecretStr(token),
            policy=LOOPBACK,
            timeout_seconds=5.0,
            backoff_seconds=0.0,
        )
    )


def _engine(session: Session, settings: Settings, bot: Any) -> RunEngine:
    caller = CallerService(DeterministicCallerProvider(), settings=settings)
    store = AudioArtefactStore(settings.caller_audio_root)
    orchestrator = ConversationOrchestrator(
        session=session, caller=caller, settings=settings, artefacts=store
    )
    return RunEngine(
        session=session,
        orchestrator=orchestrator,
        settings=settings,
        bot_adapter=bot,
        artefacts=store,
    )


def _run(engine: RunEngine, session: Session, mode: ExecutionMode) -> RunReport:
    suite, scenario = _scenario(session)
    run = engine.create(suite_id=suite.id, scenario_id=scenario.id, config=RunConfig(mode=mode))

    async def go() -> RunReport:
        try:
            return await engine.run_to_completion(run.id)
        finally:
            await engine.close()

    return asyncio.run(go())


class TestAConversationWithTheReferenceBot:
    def test_the_caller_reaches_its_goal_over_http(
        self, db_session: Session, settings: Settings, bot_url: str
    ) -> None:
        report = _run(
            _engine(db_session, settings, _http(bot_url)), db_session, ExecutionMode.TEXT_BOT_TEST
        )
        assert report.status is PipelineStatus.COMPLETED, report.error
        assert report.outcome is RunOutcome.GOAL_ACHIEVED
        assert report.bot_exchange == "text"
        assert report.bot_text_externally_received is True
        assert report.bot_text_replies_received == report.bot_turns >= 2
        # Nothing about audio may be claimed.
        assert report.bot_audio_externally_received is False
        assert report.stt_provider is None and report.tts_provider is None
        assert report.artefacts == ()
        # The session was opened, used and closed.
        assert report.bot_session_id
        stages = [(e.stage, e.status) for e in report.events]
        assert ("bot_session", "ok") in stages
        assert stages[-1] == ("bot_session", "ok")

    def test_each_bot_turn_records_where_it_came_from(
        self, db_session: Session, settings: Settings, bot_url: str
    ) -> None:
        report = _run(
            _engine(db_session, settings, _http(bot_url)), db_session, ExecutionMode.TEXT_BOT_TEST
        )
        assert report.conversation_id is not None
        bot_turns = [
            t
            for t in caller_repo.list_turns(db_session, report.conversation_id)
            if t.speaker.value == "bot"
        ]
        assert bot_turns
        for turn in bot_turns:
            meta = turn.turn_metadata or {}
            assert meta["source"] == "external_text_bot"
            assert meta["received_from_bot"] is True
            assert meta["latency_ms"] > 0
            assert meta["correlation_id"].startswith(str(report.run_id))
        assert any(REFERENCE in (t.content or "") for t in bot_turns)

    def test_the_caller_never_sends_its_expected_outcomes(
        self, db_session: Session, settings: Settings, bot_url: str
    ) -> None:
        report = _run(
            _engine(db_session, settings, _http(bot_url)), db_session, ExecutionMode.TEXT_BOT_TEST
        )
        assert report.conversation_id is not None
        caller_text = " ".join(
            t.content or ""
            for t in caller_repo.list_turns(db_session, report.conversation_id)
            if t.speaker.value == "caller"
        )
        assert "Bot confirms the request" not in caller_text


class TestFailuresKeepTheirOwnNames:
    def test_an_unreachable_bot_fails_the_run_as_unavailable(
        self, db_session: Session, settings: Settings
    ) -> None:
        bot = _http(f"http://127.0.0.1:{unused_port()}")
        report = _run(_engine(db_session, settings, bot), db_session, ExecutionMode.TEXT_BOT_TEST)
        assert report.status is PipelineStatus.FAILED
        assert report.outcome is RunOutcome.EXTERNAL_BOT_UNAVAILABLE
        assert report.bot_text_externally_received is False

    def test_a_rejected_credential_fails_without_revealing_either_token(
        self, db_session: Session, settings: Settings, bot_url: str
    ) -> None:
        wrong = "wrong-token-but-long-enough-000000"
        report = _run(
            _engine(db_session, settings, _http(bot_url, token=wrong)),
            db_session,
            ExecutionMode.TEXT_BOT_TEST,
        )
        assert report.outcome is RunOutcome.EXTERNAL_BOT_UNAVAILABLE
        assert "credential" in (report.error or "")
        evidence = repr(report)
        assert wrong not in evidence and TOKEN not in evidence

    def test_a_bot_that_hangs_up_early_is_recorded_as_such(
        self, db_session: Session, settings: Settings
    ) -> None:
        script = load({"rules": [{"reply": "We are closed. Goodbye.", "end_session": True}]})
        with serve(create_app(BotConfig(token=TOKEN, script=script))) as url:
            report = _run(
                _engine(db_session, settings, _http(url)), db_session, ExecutionMode.TEXT_BOT_TEST
            )
        assert report.status is PipelineStatus.COMPLETED
        assert report.outcome is RunOutcome.BOT_ENDED_SESSION, [
            (e.stage, e.status, e.detail) for e in report.events
        ]
        assert report.outcome is not RunOutcome.GOAL_ACHIEVED


class TestModeAndAdapterMustAgree:
    def test_offline_simulation_refuses_an_adapter_that_contacts_anything(
        self, db_session: Session, settings: Settings, bot_url: str
    ) -> None:
        engine = _engine(db_session, settings, _http(bot_url))
        suite, scenario = _scenario(db_session)
        with pytest.raises(PipelineConfigurationError, match="text_bot_test"):
            engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION),
            )
        asyncio.run(engine.close())

    def test_text_bot_test_refuses_an_offline_adapter(
        self, db_session: Session, settings: Settings
    ) -> None:
        engine = _engine(db_session, settings, ScriptedBotAdapter(()))
        suite, scenario = _scenario(db_session)
        with pytest.raises(PipelineConfigurationError, match="bot_adapter 'http'"):
            engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.TEXT_BOT_TEST),
            )

    @pytest.mark.parametrize(
        "mode", [ExecutionMode.AUDIO_FIXTURE_TEST, ExecutionMode.EXTERNAL_BOT_TEST]
    )
    def test_an_audio_mode_refuses_the_text_only_adapter(
        self, db_session: Session, settings: Settings, bot_url: str, mode: ExecutionMode
    ) -> None:
        engine = _engine(db_session, settings, _http(bot_url))
        suite, scenario = _scenario(db_session)
        with pytest.raises(PipelineConfigurationError, match="carries none"):
            engine.create(suite_id=suite.id, scenario_id=scenario.id, config=RunConfig(mode=mode))
        asyncio.run(engine.close())


class TestThroughTheApi:
    """The real route, the real engine factory and the real registry.

    No engine override: settings alone select the http adapter, which is the
    path an operator takes.
    """

    def test_a_text_bot_run_created_started_and_reported_over_http(
        self,
        api_client: Any,
        test_app: Any,
        db_session: Session,
        settings: Settings,
        bot_url: str,
    ) -> None:
        from app.core.config import get_settings

        configured = settings.model_copy(
            update={
                "bot_http_base_url": bot_url,
                "bot_http_token": SecretStr(TOKEN),
                "bot_http_allowed_hosts": "127.0.0.1",
                "bot_http_allow_loopback": True,
            }
        )
        test_app.dependency_overrides[get_settings] = lambda: configured
        suite, scenario = _scenario(db_session)

        listing = api_client.get("/api/v1/test-runs/bot-adapters/available").json()
        http = next(a for a in listing["adapters"] if a["name"] == "http")
        assert http["available"] is True

        created = api_client.post(
            "/api/v1/test-runs",
            json={
                "suite_id": str(suite.id),
                "scenario_id": str(scenario.id),
                "mode": "text_bot_test",
                "bot_adapter": "http",
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        started = api_client.post(f"/api/v1/test-runs/{run_id}/start")
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["outcome"] == "goal_achieved"
        assert body["bot_exchange"] == "text"
        assert body["bot_text_externally_received"] is True
        assert body["bot_audio_externally_received"] is False
        assert TOKEN not in started.text

        row = next(
            r for r in api_client.get("/api/v1/test-runs").json()["items"] if r["run_id"] == run_id
        )
        assert row["mode"] == "text_bot_test"
        assert row["bot_text_externally_received"] is True

    def test_an_unconfigured_http_adapter_is_refused_with_the_missing_setting(
        self, api_client: Any, db_session: Session
    ) -> None:
        suite, scenario = _scenario(db_session)
        response = api_client.post(
            "/api/v1/test-runs",
            json={
                "suite_id": str(suite.id),
                "scenario_id": str(scenario.id),
                "mode": "text_bot_test",
                "bot_adapter": "http",
            },
        )
        assert response.status_code == 422
        assert "BOT_HTTP_BASE_URL" in response.text
