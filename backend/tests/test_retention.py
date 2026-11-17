"""Phase 10 deletion and retention: one run deleted through the API, the
retention sweep through the real CLI, and what neither may touch."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.cli import app as cli_app
from app.core.config import Settings
from app.models import CallSession, ConversationTurn, RunEvaluation, Scenario
from app.models import TestRun as RunModel
from app.models import TestSuite as SuiteModel
from app.models.identity import Role
from app.models.test_run import RunStatus
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.recovery import PROTECTED_RUN_IDS
from app.utils.timing import utc_now
from tests import test_pipeline_api as pipeline_tests
from tests.auth_helpers import make_user
from tests.conftest import default_tenant

pipeline_client = pipeline_tests.pipeline_client
scenario_ids = pipeline_tests.scenario_ids
wav = pipeline_tests.wav
BASE = pipeline_tests.BASE


def _finished_audio_run(client: TestClient, ids: tuple[uuid.UUID, uuid.UUID], audio: bytes) -> str:
    client.pipeline_state["adapter"] = ScriptedBotAdapter([audio] * 4, exhausted_is_error=False)
    run = pipeline_tests._create(client, ids, mode="audio_fixture_test")
    assert client.post(f"{BASE}/{run['run_id']}/start").json()["status"] == "completed"
    client.post(f"{BASE}/{run['run_id']}/evaluations")
    return run["run_id"]


def _count(session: Session, model: type, **where: object) -> int:
    statement = select(func.count()).select_from(model)
    for name, value in where.items():
        statement = statement.where(getattr(model, name) == value)
    return int(session.scalar(statement) or 0)


class TestDeleteRun:
    def test_it_removes_the_run_its_evidence_and_its_audio(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes,
        db_session: Session,
    ) -> None:  # fmt: skip
        run_id = _finished_audio_run(pipeline_client, scenario_ids, wav)
        run_uuid = uuid.UUID(run_id)
        conversation = db_session.scalar(
            select(CallSession.id).where(CallSession.test_run_id == run_uuid)
        )
        store = pipeline_client.artefact_store
        files = list(store.blobs.keys(str(conversation)))
        assert files and any(f.endswith("conversation.wav") for f in files)

        response = pipeline_client.delete(f"{BASE}/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["artefact_files_deleted"] == len(files)
        assert body["artefact_files_not_deleted"] == []

        db_session.expire_all()
        assert db_session.get(RunModel, run_uuid) is None
        assert _count(db_session, CallSession, test_run_id=run_uuid) == 0
        assert _count(db_session, ConversationTurn, call_session_id=conversation) == 0
        assert _count(db_session, RunEvaluation, test_run_id=run_uuid) == 0
        assert list(store.blobs.keys(str(conversation))) == []
        assert pipeline_client.get(f"{BASE}/{run_id}").status_code == 404

    def test_the_suite_and_scenario_survive(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes,
        db_session: Session,
    ) -> None:  # fmt: skip
        run_id = _finished_audio_run(pipeline_client, scenario_ids, wav)
        pipeline_client.delete(f"{BASE}/{run_id}")
        suite_id, scenario_id = scenario_ids
        assert db_session.get(SuiteModel, suite_id) is not None
        assert db_session.get(Scenario, scenario_id) is not None

    def test_a_run_in_flight_is_refused(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = pipeline_tests._create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        response = pipeline_client.delete(f"{BASE}/{run['run_id']}")
        assert response.status_code == 409
        assert "recover-stale" in response.json()["error"]["message"]

    def test_members_cannot_delete_and_outsiders_cannot_see(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes,
        db_session: Session, settings: Settings,
    ) -> None:  # fmt: skip
        run_id = _finished_audio_run(pipeline_client, scenario_ids, wav)
        _, workspace, _ = default_tenant(db_session)
        member, _ = make_user(
            db_session, settings, pipeline_client, workspace=workspace, role=Role.MEMBER
        )
        outsider, _ = make_user(db_session, settings, pipeline_client)
        assert pipeline_client.delete(f"{BASE}/{run_id}", headers=member.headers).status_code == 403
        assert (
            pipeline_client.delete(f"{BASE}/{run_id}", headers=outsider.headers).status_code == 404
        )
        assert pipeline_client.get(f"{BASE}/{run_id}").status_code == 200

    def test_a_protected_historical_run_is_never_deleted(
        self, pipeline_client: TestClient, db_session: Session
    ) -> None:
        protected = sorted(PROTECTED_RUN_IDS, key=str)[0]
        suite = SuiteModel(name=f"history-{uuid.uuid4().hex[:6]}")
        db_session.add(suite)
        db_session.flush()
        db_session.add(
            RunModel(
                id=protected, suite_id=suite.id, status=RunStatus.COMPLETED,
                finished_at=utc_now(), run_metadata={"pipeline": {"mode": "offline_simulation"}},
            )
        )  # fmt: skip
        db_session.flush()
        response = pipeline_client.delete(f"{BASE}/{protected}")
        assert response.status_code == 409
        assert "protected" in response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# The retention sweep, through the real CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def cli(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> Iterator[Settings]:
    configured = settings.model_copy(update={"caller_audio_storage_dir": str(tmp_path / "audio")})

    @contextmanager
    def scoped() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr("app.cli.main.session_scope", scoped)
    monkeypatch.setattr("app.cli.main.get_settings", lambda: configured)
    yield configured


def _run_finished(session: Session, suite: SuiteModel, days_ago: float) -> RunModel:
    finished = utc_now() - timedelta(days=days_ago)
    run = RunModel(
        suite_id=suite.id, status=RunStatus.COMPLETED, started_at=finished - timedelta(minutes=1),
        finished_at=finished, run_metadata={"pipeline": {"mode": "offline_simulation"}},
    )  # fmt: skip
    session.add(run)
    session.flush()
    return run


def _purge(*args: str) -> tuple[int, dict]:
    result = CliRunner().invoke(cli_app, ["runs", "purge", "--json", *args])
    return result.exit_code, (
        json.loads(result.output) if result.exit_code == 0 else {"out": result.output}
    )


class TestRetentionSweep:
    def test_a_dry_run_lists_and_changes_nothing(self, cli: Settings, db_session: Session) -> None:
        suite = SuiteModel(name=f"ret-{uuid.uuid4().hex[:6]}")
        db_session.add(suite)
        db_session.flush()
        old, recent = _run_finished(db_session, suite, 40), _run_finished(db_session, suite, 5)
        code, body = _purge("--older-than", "30d")
        assert code == 0
        assert body["applied"] is False
        listed = {r["run_id"] for r in body["runs"]}
        assert str(old.id) in listed and str(recent.id) not in listed
        assert db_session.get(RunModel, old.id) is not None

    def test_apply_deletes_only_expired_finished_runs(
        self, cli: Settings, db_session: Session
    ) -> None:
        suite = SuiteModel(name=f"ret-{uuid.uuid4().hex[:6]}")
        db_session.add(suite)
        db_session.flush()
        old, recent = _run_finished(db_session, suite, 40), _run_finished(db_session, suite, 5)
        stuck = RunModel(
            suite_id=suite.id, status=RunStatus.RUNNING, started_at=utc_now() - timedelta(days=90)
        )
        db_session.add(stuck)
        db_session.flush()
        code, body = _purge("--older-than", "30d", "--apply")
        assert code == 0
        assert str(old.id) in {d["run_id"] for d in body["deleted"]}
        db_session.expire_all()
        assert db_session.get(RunModel, old.id) is None
        assert db_session.get(RunModel, recent.id) is not None
        assert db_session.get(RunModel, stuck.id) is not None

    def test_retention_days_is_the_default_period(self, cli: Settings, db_session: Session) -> None:
        cli.retention_days = 10
        suite = SuiteModel(name=f"ret-{uuid.uuid4().hex[:6]}")
        db_session.add(suite)
        db_session.flush()
        old = _run_finished(db_session, suite, 11)
        code, body = _purge()
        assert code == 0 and body["retention_days"] == 10
        assert str(old.id) in {r["run_id"] for r in body["runs"]}

    def test_without_a_period_nothing_happens(self, cli: Settings) -> None:
        code, body = _purge("--apply")
        assert code == 2
        assert "Nothing is deleted" in body["out"]

    @pytest.mark.parametrize("value", ["12h", "0d", "1d12h"])
    def test_the_period_must_be_whole_days(self, cli: Settings, value: str) -> None:
        assert _purge("--older-than", value)[0] == 2

    def test_the_protected_runs_are_never_listed(self, cli: Settings, db_session: Session) -> None:
        suite = SuiteModel(name=f"ret-{uuid.uuid4().hex[:6]}")
        db_session.add(suite)
        db_session.flush()
        for run_id in PROTECTED_RUN_IDS:
            finished = utc_now() - timedelta(days=400)
            db_session.add(
                RunModel(id=run_id, suite_id=suite.id, status=RunStatus.COMPLETED,
                         started_at=finished, finished_at=finished)
            )  # fmt: skip
        db_session.flush()
        code, body = _purge("--older-than", "30d", "--apply")
        assert code == 0
        assert {str(r) for r in PROTECTED_RUN_IDS}.isdisjoint({r["run_id"] for r in body["runs"]})
        for run_id in PROTECTED_RUN_IDS:
            assert db_session.get(RunModel, run_id) is not None

    def test_settings_refuse_a_nonsensical_period(self) -> None:
        with pytest.raises(ValueError):
            Settings(retention_days=0, _env_file=None)
        assert Settings(retention_days="", _env_file=None).retention_days is None
