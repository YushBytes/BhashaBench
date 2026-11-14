"""Stale-run recovery: `bhashabench runs recover-stale`.

Driven through the real Typer app with `CliRunner`, against the migrated test
database, so argument parsing, exit codes and the transaction are real. The
stale run is produced the way the two historical ones arose - one caller turn
of an offline run, then nothing - rather than by inventing a row shape.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.caller.artefacts import AudioArtefactStore
from app.cli.main import app
from app.cli.output import ExitCode
from app.core.config import AppEnv, Settings
from app.models import TestRun as RunModel
from app.models.test_run import RunStatus
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.engine import RunConfig
from app.pipeline.modes import OUR_FAULT_OUTCOMES, ExecutionMode, RunOutcome
from app.repositories import caller_conversations as caller_repo
from app.repositories import pipeline_runs as repo
from app.utils.timing import utc_now
from tests.test_pipeline_engine import SPEC, _engine, _make_scenario

runner = CliRunner()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "audio"),
        caller_synthesise_audio=True,
        _env_file=None,
    )


@pytest.fixture
def cli_db(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    """Point the CLI's session at the test's rolled-back transaction."""

    @contextmanager
    def scoped() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr("app.cli.main.session_scope", scoped)
    yield db_session


def _offline_run(session: Session, settings: Settings, tmp_path: Path) -> uuid.UUID:
    """An offline manual run after its first caller turn, waiting for text."""
    store = AudioArtefactStore(Path(tmp_path / "audio"))
    suite, scenario = _make_scenario(session, spec=SPEC)
    engine = _engine(session, settings, store, bot=ManualBotAdapter())
    run = engine.create(
        suite_id=suite.id,
        scenario_id=scenario.id,
        config=RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION, bot_adapter="manual"),
    )
    asyncio.run(engine.run_to_completion(run.id))
    return run.id


def _make_stuck(session: Session, run_id: uuid.UUID, *, idle: timedelta) -> None:
    """Remove the waiting marker - the pre-Phase-0 shape - and backdate it."""
    run = repo.get_run(session, run_id)
    assert run is not None
    meta = dict(repo.pipeline_metadata_of(run))
    meta.pop("awaiting_bot_text_for_turn", None)
    repo.update_pipeline_metadata(session, run, meta)
    session.flush()
    _backdate(session, run_id, idle=idle)


def _backdate(session: Session, run_id: uuid.UUID, *, idle: timedelta) -> None:
    session.execute(
        update(RunModel).where(RunModel.id == run_id).values(updated_at=utc_now() - idle)
    )
    session.flush()
    session.expire_all()


def _snapshot(session: Session, run_id: uuid.UUID) -> dict[str, Any]:
    run = repo.get_run(session, run_id)
    assert run is not None
    conversation = repo.conversation_of(session, run_id)
    assert conversation is not None
    turns = caller_repo.list_turns(session, conversation.id)
    meta = repo.pipeline_metadata_of(run)
    return {
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "meta_status": meta.get("status"),
        "outcome": meta.get("outcome"),
        "events": list(meta.get("events", [])),
        "artefacts": list(meta.get("artefacts", [])),
        "turns": [(t.turn_index, t.speaker.value, t.content) for t in turns],
    }


def _invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["runs", "recover-stale", *args])
    return result.exit_code, result.output


class TestEligibility:
    def test_a_stuck_run_is_listed(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(days=3))

        code, output = _invoke("--older-than", "1h", "--json")

        assert code == ExitCode.OK, output
        listed = [row["run_id"] for row in json.loads(output)["runs"]]
        assert str(run_id) in listed

    def test_a_run_waiting_for_an_operator_is_never_listed(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        """Waiting is healthy however long it lasts."""
        run_id = _offline_run(cli_db, settings, tmp_path)
        _backdate(cli_db, run_id, idle=timedelta(days=30))

        code, output = _invoke("--older-than", "1h", "--json")

        assert code == ExitCode.OK, output
        assert str(run_id) not in [row["run_id"] for row in json.loads(output)["runs"]]

    def test_a_recently_active_run_is_not_listed(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(minutes=5))

        code, output = _invoke("--older-than", "1h", "--json")

        assert code == ExitCode.OK, output
        assert str(run_id) not in [row["run_id"] for row in json.loads(output)["runs"]]

    def test_a_threshold_below_the_run_timeout_is_refused(self, cli_db: Session) -> None:
        """A run quieter than its own wall-clock ceiling may still be executing."""
        code, output = _invoke("--older-than", "1m")

        assert code == ExitCode.INVALID_INPUT
        assert "PIPELINE_RUN_TIMEOUT_SECONDS" in output

    def test_a_malformed_duration_is_refused(self, cli_db: Session) -> None:
        code, output = _invoke("--older-than", "soon")

        assert code == ExitCode.INVALID_INPUT
        assert "not a duration" in output

    def test_the_threshold_is_required(self, cli_db: Session) -> None:
        code, _ = _invoke()

        assert code != ExitCode.OK


class TestDryRun:
    def test_the_default_changes_nothing(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(days=3))
        before = _snapshot(cli_db, run_id)

        code, output = _invoke("--older-than", "1h")

        assert code == ExitCode.OK, output
        assert "DRY RUN" in output
        assert str(run_id) in output
        cli_db.expire_all()
        assert _snapshot(cli_db, run_id) == before
        assert before["status"] is RunStatus.RUNNING


class TestApply:
    def test_apply_marks_the_run_abandoned(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(days=3))

        code, output = _invoke("--older-than", "1h", "--apply")

        assert code == ExitCode.OK, output
        cli_db.expire_all()
        after = _snapshot(cli_db, run_id)
        assert after["status"] is RunStatus.FAILED
        assert after["meta_status"] == "failed"
        assert after["outcome"] == RunOutcome.ABANDONED.value
        assert after["finished_at"] is not None
        run = repo.get_run(cli_db, run_id)
        assert run is not None
        assert (run.error_message or "").startswith("abandoned: no activity since")
        meta = repo.pipeline_metadata_of(run)
        assert meta["recovered"]["finished_at_is_recovery_time"] is True

    def test_apply_keeps_every_turn_event_and_artefact(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(days=3))
        before = _snapshot(cli_db, run_id)

        _invoke("--older-than", "1h", "--apply")
        cli_db.expire_all()
        after = _snapshot(cli_db, run_id)

        assert after["turns"] == before["turns"]
        assert after["turns"]  # the caller's opening turn survives
        assert after["artefacts"] == before["artefacts"]
        assert after["started_at"] == before["started_at"]
        assert after["events"][: len(before["events"])] == before["events"]
        assert [e["stage"] for e in after["events"][len(before["events"]) :]] == ["recovery"]

    def test_apply_closes_the_open_conversation(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(days=3))

        _invoke("--older-than", "1h", "--apply")
        cli_db.expire_all()

        conversation = repo.conversation_of(cli_db, run_id)
        assert conversation is not None
        caller_meta = caller_repo.caller_metadata_of(conversation)
        assert caller_meta["state"] == "terminated"
        assert caller_meta["termination_reason"] == "operator_terminated"

    def test_apply_leaves_a_waiting_run_alone(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        stuck = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, stuck, idle=timedelta(days=3))
        waiting = _offline_run(cli_db, settings, tmp_path)
        _backdate(cli_db, waiting, idle=timedelta(days=3))
        before = _snapshot(cli_db, waiting)

        _invoke("--older-than", "1h", "--apply")
        cli_db.expire_all()

        assert _snapshot(cli_db, waiting)["status"] is before["status"] is RunStatus.RUNNING
        assert _snapshot(cli_db, waiting)["outcome"] is None

    def test_a_closed_run_is_not_closed_twice(
        self, cli_db: Session, settings: Settings, tmp_path: Path
    ) -> None:
        run_id = _offline_run(cli_db, settings, tmp_path)
        _make_stuck(cli_db, run_id, idle=timedelta(days=3))
        _invoke("--older-than", "1h", "--apply")
        cli_db.expire_all()

        code, output = _invoke("--older-than", "1h", "--json")

        assert code == ExitCode.OK
        assert str(run_id) not in [row["run_id"] for row in json.loads(output)["runs"]]


def test_abandoned_is_never_a_statement_about_the_bot() -> None:
    assert RunOutcome.ABANDONED in OUR_FAULT_OUTCOMES
