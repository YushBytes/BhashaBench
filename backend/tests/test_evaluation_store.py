"""The evaluation and reference tables against real PostgreSQL."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CallSession, ConversationTurn, Scenario, Speaker, Verdict
from app.models import TestRun as RunModel
from app.models import TestSuite as SuiteModel
from app.models.call_session import CallStatus
from app.repositories import evaluations as repo

SPEC = {
    "name": "store_fixture",
    "language": "hi-IN",
    "persona": {"identity": "Caller"},
    "goal": {"objective": "Check something."},
    "expected_outcomes": ["Something is checked"],
}


def _turn(session: Session) -> tuple[RunModel, ConversationTurn]:
    suite = SuiteModel(name=f"eval-store-{uuid.uuid4().hex[:8]}")
    session.add(suite)
    session.flush()
    scenario = Scenario(
        suite_id=suite.id,
        name=f"s_{uuid.uuid4().hex[:6]}",
        language="hi-IN",
        spec=SPEC,
        spec_version=1,
    )
    run = RunModel(suite_id=suite.id)
    session.add_all([scenario, run])
    session.flush()
    call = CallSession(test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.IN_PROGRESS)
    session.add(call)
    session.flush()
    turn = ConversationTurn(call_session_id=call.id, turn_index=1, speaker=Speaker.BOT, content="x")
    session.add(turn)
    session.flush()
    return run, turn


class TestReferences:
    def test_the_latest_reference_wins_and_history_is_kept(self, db_session: Session) -> None:
        _, turn = _turn(db_session)
        repo.add_reference(db_session, conversation_turn_id=turn.id, text="first", reviewer="a")
        repo.add_reference(db_session, conversation_turn_id=turn.id, text="second", reviewer="b")
        latest = repo.latest_references(db_session, [turn.id])
        assert latest[turn.id].text == "second"
        assert [r.text for r in repo.reference_history(db_session, turn.id)] == ["first", "second"]

    def test_an_empty_reference_is_refused_by_the_database(self, db_session: Session) -> None:
        _, turn = _turn(db_session)
        with pytest.raises(IntegrityError, match="reference_text_not_empty"):
            repo.add_reference(db_session, conversation_turn_id=turn.id, text="", reviewer=None)

    def test_references_cascade_with_their_turn(self, db_session: Session) -> None:
        _, turn = _turn(db_session)
        repo.add_reference(db_session, conversation_turn_id=turn.id, text="t", reviewer=None)
        db_session.execute(text("DELETE FROM conversation_turns WHERE id = :id"), {"id": turn.id})
        count = db_session.execute(
            text("SELECT count(*) FROM transcript_references WHERE conversation_turn_id = :id"),
            {"id": turn.id},
        ).scalar_one()
        assert count == 0


class TestEvaluations:
    def _add(self, session: Session, run: RunModel, verdict: Verdict = Verdict.PASS) -> None:
        repo.add_evaluation(
            session,
            test_run_id=run.id,
            evaluator_version="bb-eval-1",
            verdict=verdict,
            evidence_fingerprint="0" * 64,
            results={"criteria": []},
        )

    def test_evaluations_accumulate_newest_first(self, db_session: Session) -> None:
        run, _ = _turn(db_session)
        self._add(db_session, run, Verdict.FAIL)
        self._add(db_session, run, Verdict.PASS)
        rows = repo.list_evaluations(db_session, run.id)
        assert [r.verdict for r in rows] == [Verdict.PASS, Verdict.FAIL]
        assert repo.latest_evaluations(db_session, [run.id])[run.id].verdict is Verdict.PASS

    def test_an_unknown_verdict_is_refused_by_the_database(self, db_session: Session) -> None:
        run, _ = _turn(db_session)
        with pytest.raises(IntegrityError):
            db_session.execute(
                text(
                    "INSERT INTO run_evaluations (id, test_run_id, evaluator_version, verdict, "
                    "evidence_fingerprint, results) VALUES (:id, :run, 'v', 'maybe', 'f', '{}')"
                ),
                {"id": uuid.uuid4(), "run": run.id},
            )
            db_session.flush()

    def test_evaluations_cascade_with_their_run(self, db_session: Session) -> None:
        run, _ = _turn(db_session)
        self._add(db_session, run)
        db_session.execute(
            text("DELETE FROM call_sessions WHERE test_run_id = :id"), {"id": run.id}
        )
        db_session.execute(text("DELETE FROM test_runs WHERE id = :id"), {"id": run.id})
        assert repo.list_evaluations(db_session, run.id) == []
