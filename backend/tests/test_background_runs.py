"""Phase 9 background execution and recovery without an operator: a run
started with `background=true` outlives its request, a crash finishes the run
instead of leaving it `running`, and the recovery loop closes runs whose
worker died."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.test_runs import get_background_executor, get_engine_factory
from app.models import TestRun as RunModel
from app.models import TestSuite as SuiteModel
from app.models.test_run import RunStatus
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.recovery import PROTECTED_RUN_IDS
from app.pipeline.worker import RecoveryLoop, run_worker
from app.utils.timing import utc_now
from tests import test_pipeline_api as pipeline_tests

pipeline_client = pipeline_tests.pipeline_client
scenario_ids = pipeline_tests.scenario_ids
wav = pipeline_tests.wav
BASE = pipeline_tests.BASE


class _Borrowed:
    """The test's session, with `close` made harmless: the worker closes the
    sessions it opens, and this one belongs to the test's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


class _TestExecutor:
    def __init__(self, test_app: FastAPI, session: Session, *, crash: bool = False) -> None:
        self._factory = test_app.dependency_overrides[get_engine_factory]()
        self._session = session
        self._crash = crash
        self.session_factory = lambda: _Borrowed(session)

    async def execute(self, run_id: uuid.UUID) -> None:
        if self._crash:
            raise RuntimeError("worker died mid-run with token=bbs_secret")
        built = self._factory(None)
        engine = next(built)
        await engine.run_to_completion(run_id)
        self._session.commit()


def _drain(client: TestClient) -> None:
    client.portal.call(run_worker().drain)  # type: ignore[attr-defined]


@pytest.fixture
def audio_run(
    pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes
) -> str:
    pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
        [wav] * 4, exhausted_is_error=False
    )
    return pipeline_tests._create(pipeline_client, scenario_ids, mode="audio_fixture_test")[
        "run_id"
    ]


class TestBackgroundExecution:
    def test_the_run_outlives_its_request(
        self, pipeline_client: TestClient, test_app: FastAPI, db_session: Session, audio_run: str
    ) -> None:
        test_app.dependency_overrides[get_background_executor] = lambda: _TestExecutor(
            test_app, db_session
        )
        response = pipeline_client.post(f"{BASE}/{audio_run}/start", params={"background": "true"})
        assert response.status_code == 202, response.text
        assert response.json()["status"] in ("created", "initializing", "running")
        _drain(pipeline_client)
        finished = pipeline_client.get(f"{BASE}/{audio_run}").json()
        assert finished["status"] == "completed"
        assert finished["outcome"] == "goal_achieved"

    def test_a_crash_finishes_the_run_instead_of_leaving_it_running(
        self, pipeline_client: TestClient, test_app: FastAPI, db_session: Session, audio_run: str
    ) -> None:
        test_app.dependency_overrides[get_background_executor] = lambda: _TestExecutor(
            test_app, db_session, crash=True
        )
        assert (
            pipeline_client.post(
                f"{BASE}/{audio_run}/start", params={"background": "true"}
            ).status_code
            == 202
        )
        _drain(pipeline_client)
        run = db_session.get(RunModel, uuid.UUID(audio_run))
        db_session.refresh(run)
        assert run.status is RunStatus.FAILED
        meta = run.run_metadata["pipeline"]
        assert meta["outcome"] == "abandoned"
        assert meta["recovered"]["by"] == "background worker"
        assert "RuntimeError" in meta["recovered"]["reason"]
        assert "bbs_secret" not in str(run.run_metadata) and "bbs_secret" not in (
            run.error_message or ""
        )

    def test_a_finished_run_is_refused_before_the_202(
        self, pipeline_client: TestClient, test_app: FastAPI, db_session: Session, audio_run: str
    ) -> None:
        assert pipeline_client.post(f"{BASE}/{audio_run}/start").json()["status"] == "completed"
        test_app.dependency_overrides[get_background_executor] = lambda: _TestExecutor(
            test_app, db_session
        )
        assert (
            pipeline_client.post(
                f"{BASE}/{audio_run}/start", params={"background": "true"}
            ).status_code
            == 409
        )

    def test_without_a_free_slot_it_is_503_and_nothing_starts(
        self,
        pipeline_client: TestClient,
        test_app: FastAPI,
        db_session: Session,
        audio_run: str,
        settings,
    ) -> None:
        from app.pipeline.concurrency import get_run_slots

        test_app.dependency_overrides[get_background_executor] = lambda: _TestExecutor(
            test_app, db_session
        )
        slots = get_run_slots(settings)
        held = [slots.hold_sync() for _ in range(slots.limit)]
        for hold in held:
            hold.__enter__()
        try:
            response = pipeline_client.post(
                f"{BASE}/{audio_run}/start", params={"background": "true"}
            )
            assert response.status_code == 503
        finally:
            for hold in held:
                hold.__exit__(None, None, None)
        assert not run_worker().running(uuid.UUID(audio_run))
        assert pipeline_client.get(f"{BASE}/{audio_run}").json()["status"] == "created"


class TestRecoveryLoop:
    def _stuck(
        self,
        session: Session,
        run_id: uuid.UUID | None = None,
        idle: timedelta = timedelta(hours=2),
    ) -> RunModel:
        suite = SuiteModel(name=f"stuck-{uuid.uuid4().hex[:6]}")
        session.add(suite)
        session.flush()
        run = RunModel(
            id=run_id or uuid.uuid4(), suite_id=suite.id, status=RunStatus.RUNNING,
            started_at=utc_now() - idle,
            run_metadata={
                "pipeline": {"mode": "offline_simulation", "status": "running", "events": []}
            },
        )  # fmt: skip
        session.add(run)
        session.flush()
        session.execute(
            RunModel.__table__.update()
            .where(RunModel.id == run.id)
            .values(updated_at=utc_now() - idle)
        )
        session.flush()
        session.expire(run)  # the Core update bypassed the identity map
        return run

    def test_a_sweep_closes_runs_whose_worker_died(self, db_session: Session) -> None:
        stuck = self._stuck(db_session)
        recent = self._stuck(db_session, idle=timedelta(seconds=30))
        loop = RecoveryLoop(
            lambda: _Borrowed(db_session), interval_seconds=0, threshold_seconds=660
        )
        assert loop.sweep_once() >= 1
        db_session.expire_all()
        assert db_session.get(RunModel, stuck.id).status is RunStatus.FAILED
        assert (
            db_session.get(RunModel, stuck.id).run_metadata["pipeline"]["recovered"]["by"]
            == "automatic recovery"
        )
        assert db_session.get(RunModel, recent.id).status is RunStatus.RUNNING

    def test_the_protected_runs_are_never_swept(self, db_session: Session) -> None:
        protected = self._stuck(db_session, run_id=sorted(PROTECTED_RUN_IDS, key=str)[0])
        RecoveryLoop(
            lambda: _Borrowed(db_session), interval_seconds=0, threshold_seconds=660
        ).sweep_once()
        db_session.expire_all()
        assert db_session.get(RunModel, protected.id).status is RunStatus.RUNNING

    def test_a_zero_interval_starts_nothing(self) -> None:
        import asyncio

        async def check() -> None:
            loop = RecoveryLoop(lambda: None, interval_seconds=0, threshold_seconds=660)  # type: ignore[arg-type,return-value]
            loop.start()
            assert loop._task is None
            await loop.stop()

        asyncio.run(check())

    def test_the_app_never_sweeps_with_the_global_settings(
        self, test_app: FastAPI, settings
    ) -> None:
        assert test_app.state.settings is settings
        assert settings.pipeline_recovery_interval_seconds == 0
