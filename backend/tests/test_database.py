"""Tests for the database schema, relationships and constraints.

These run against a real PostgreSQL created and migrated by the fixtures in
`conftest.py`. If the server is unreachable they are skipped with an explicit
reason and a session-end banner - never silently passed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CallSession,
    CallStatus,
    ConversationTurn,
    RunStatus,
    Scenario,
    Speaker,
)

# Aliased deliberately. pytest collects any module-level class whose name
# starts with `Test`, so importing the `SuiteModel` and `RunModel` ORM models
# under their real names would make pytest try to instantiate them as test
# classes and fail collection. Aliasing keeps the domain models free of
# test-framework markers such as `__test__ = False`.
from app.models import TestRun as RunModel
from app.models import TestSuite as SuiteModel

EXPECTED_TABLES = {
    "alembic_version",
    "call_sessions",
    "conversation_turns",
    "scenarios",
    "test_runs",
    "test_suites",
}

MINIMAL_SPEC = {
    "name": "fixture_scenario",
    "description": None,
    "language": "hi-IN",
    "persona": {"identity": "Caller", "speaking_style": "neutral", "traits": []},
    "goal": {"objective": "Ask a question.", "max_turns": 20},
    "known_facts": {},
    "expected_outcomes": ["Bot answers"],
    "audio": {"noise_profile": "clean", "snr_db": 30.0, "packet_loss_percent": 0.0},
    "constraints": None,
}


def make_suite(session: Session, name: str = "suite") -> SuiteModel:
    """Persist and return a suite."""
    suite = SuiteModel(name=name, description="fixture suite")
    session.add(suite)
    session.flush()
    return suite


def make_scenario(session: Session, suite: SuiteModel, name: str = "scenario") -> Scenario:
    """Persist and return a scenario in the given suite."""
    scenario = Scenario(
        suite_id=suite.id,
        name=name,
        description=None,
        language="hi-IN",
        spec={**MINIMAL_SPEC, "name": name},
        spec_version=1,
    )
    session.add(scenario)
    session.flush()
    return scenario


class TestConnection:
    """The engine must reach the migrated test database."""

    def test_select_one_succeeds(self, db_engine: Engine) -> None:
        with db_engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar() == 1

    def test_connection_probe_reports_reachable(self, db_engine: Engine) -> None:
        """Mirrors what the health endpoint does."""
        with db_engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1


class TestMigrationResult:
    """Alembic's upgrade must produce the schema the models describe."""

    def test_all_tables_exist(self, db_engine: Engine) -> None:
        actual = set(inspect(db_engine).get_table_names())

        assert actual >= EXPECTED_TABLES

    def test_alembic_version_is_stamped(self, db_engine: Engine) -> None:
        """Proves the schema came from a migration, not from create_all()."""
        with db_engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()

        assert revision is not None
        assert len(revision) >= 8

    def test_uuid_primary_keys_are_native(self, db_engine: Engine) -> None:
        """A UUID stored as text would waste 20 bytes per row and index."""
        columns = {c["name"]: c for c in inspect(db_engine).get_columns("scenarios")}

        assert columns["id"]["type"].__class__.__name__ == "UUID"

    def test_timestamps_are_timezone_aware(self, db_engine: Engine) -> None:
        columns = {c["name"]: c for c in inspect(db_engine).get_columns("test_suites")}

        assert columns["created_at"]["type"].timezone is True
        assert columns["updated_at"]["type"].timezone is True

    def test_spec_column_is_jsonb(self, db_engine: Engine) -> None:
        columns = {c["name"]: c for c in inspect(db_engine).get_columns("scenarios")}

        assert columns["spec"]["type"].__class__.__name__ == "JSONB"

    def test_expected_indexes_exist(self, db_engine: Engine) -> None:
        indexes = {i["name"] for i in inspect(db_engine).get_indexes("scenarios")}

        assert "ix_scenarios_suite_id" in indexes
        assert "ix_scenarios_language" in indexes

    def test_foreign_keys_declare_delete_behaviour(self, db_engine: Engine) -> None:
        """Cascade vs restrict is a deliberate decision, so assert it."""
        inspector = inspect(db_engine)

        scenario_fks = {
            fk["referred_table"]: fk["options"].get("ondelete")
            for fk in inspector.get_foreign_keys("scenarios")
        }
        assert scenario_fks["test_suites"] == "CASCADE"

        call_fks = {
            fk["referred_table"]: fk["options"].get("ondelete")
            for fk in inspector.get_foreign_keys("call_sessions")
        }
        assert call_fks["test_runs"] == "CASCADE"
        # A scenario with call history must not vanish.
        assert call_fks["scenarios"] == "RESTRICT"


class TestModelCreation:
    """Each model must persist and read back correctly."""

    def test_creates_a_suite_with_generated_id_and_timestamps(self, db_session: Session) -> None:
        suite = make_suite(db_session, "created-suite")

        assert isinstance(suite.id, uuid.UUID)
        assert suite.created_at is not None
        assert suite.created_at.tzinfo is not None
        assert suite.updated_at is not None

    def test_id_is_generated_in_python_at_flush(self, db_session: Session) -> None:
        """The key is a Python-side default, not a server default.

        It is therefore unset until flush, and is a real uuid4 afterwards -
        which is what lets the INSERT carry the value instead of needing a
        RETURNING round-trip to discover it.
        """
        suite = SuiteModel(name="pre-flush")
        assert suite.id is None

        db_session.add(suite)
        db_session.flush()

        assert isinstance(suite.id, uuid.UUID)
        assert suite.id.version == 4

    def test_creates_a_scenario_with_jsonb_spec(self, db_session: Session) -> None:
        suite = make_suite(db_session, "spec-suite")

        scenario = make_scenario(db_session, suite, "jsonb_scenario")
        db_session.expire(scenario)

        assert scenario.spec["persona"]["identity"] == "Caller"
        assert scenario.spec["audio"]["snr_db"] == 30.0
        assert scenario.spec_version == 1

    def test_jsonb_round_trips_nested_structures(self, db_session: Session) -> None:
        suite = make_suite(db_session, "nested-suite")
        scenario = make_scenario(db_session, suite, "nested")

        db_session.expire(scenario)

        assert scenario.spec["expected_outcomes"] == ["Bot answers"]
        assert scenario.spec["known_facts"] == {}

    def test_creates_a_test_run(self, db_session: Session) -> None:
        suite = make_suite(db_session, "run-suite")

        run = RunModel(suite_id=suite.id, status=RunStatus.PENDING)
        db_session.add(run)
        db_session.flush()

        assert run.status is RunStatus.PENDING
        assert run.run_metadata == {}

    def test_creates_a_call_session(self, db_session: Session) -> None:
        suite = make_suite(db_session, "call-suite")
        scenario = make_scenario(db_session, suite, "call_scenario")
        run = RunModel(suite_id=suite.id, status=RunStatus.RUNNING)
        db_session.add(run)
        db_session.flush()

        call = CallSession(test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.PENDING)
        db_session.add(call)
        db_session.flush()

        assert call.status is CallStatus.PENDING
        assert call.provider_call_id is None

    def test_creates_conversation_turns_in_order(self, db_session: Session) -> None:
        suite = make_suite(db_session, "turn-suite")
        scenario = make_scenario(db_session, suite, "turn_scenario")
        run = RunModel(suite_id=suite.id, status=RunStatus.RUNNING)
        db_session.add(run)
        db_session.flush()
        call = CallSession(
            test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.IN_PROGRESS
        )
        db_session.add(call)
        db_session.flush()

        db_session.add_all(
            [
                ConversationTurn(
                    call_session_id=call.id, turn_index=0, speaker=Speaker.CALLER, content="Hello"
                ),
                ConversationTurn(
                    call_session_id=call.id, turn_index=1, speaker=Speaker.BOT, content="Namaste"
                ),
            ]
        )
        db_session.flush()

        turns = (
            db_session.query(ConversationTurn)
            .filter_by(call_session_id=call.id)
            .order_by(ConversationTurn.turn_index)
            .all()
        )
        assert [turn.speaker for turn in turns] == [Speaker.CALLER, Speaker.BOT]
        assert [turn.content for turn in turns] == ["Hello", "Namaste"]


class TestRelationships:
    """Relationships must traverse in both directions."""

    def test_suite_exposes_its_scenarios(self, db_session: Session) -> None:
        suite = make_suite(db_session, "rel-suite")
        make_scenario(db_session, suite, "one")
        make_scenario(db_session, suite, "two")

        db_session.expire(suite)

        assert {scenario.name for scenario in suite.scenarios} == {"one", "two"}

    def test_scenario_exposes_its_suite(self, db_session: Session) -> None:
        suite = make_suite(db_session, "back-suite")
        scenario = make_scenario(db_session, suite, "child")

        db_session.expire(scenario)

        assert scenario.suite.id == suite.id
        assert scenario.suite.name == "back-suite"


class TestForeignKeys:
    """Referential integrity must be enforced by the database."""

    def test_scenario_requires_an_existing_suite(self, db_session: Session) -> None:
        orphan = Scenario(
            suite_id=uuid.uuid4(),
            name="orphan",
            language="hi-IN",
            spec=MINIMAL_SPEC,
            spec_version=1,
        )
        db_session.add(orphan)

        with pytest.raises(IntegrityError, match=r"foreign key|violates"):
            db_session.flush()

    def test_deleting_a_suite_cascades_to_scenarios(self, db_session: Session) -> None:
        suite = make_suite(db_session, "cascade-suite")
        scenario_id = make_scenario(db_session, suite, "doomed").id

        db_session.delete(suite)
        db_session.flush()

        assert db_session.get(Scenario, scenario_id) is None

    def test_deleting_a_call_cascades_to_turns(self, db_session: Session) -> None:
        suite = make_suite(db_session, "turn-cascade")
        scenario = make_scenario(db_session, suite, "turn_cascade_scenario")
        run = RunModel(suite_id=suite.id, status=RunStatus.RUNNING)
        db_session.add(run)
        db_session.flush()
        call = CallSession(test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.COMPLETED)
        db_session.add(call)
        db_session.flush()
        turn = ConversationTurn(call_session_id=call.id, turn_index=0, speaker=Speaker.BOT)
        db_session.add(turn)
        db_session.flush()
        turn_id = turn.id

        # Delete at SQL level so the database's ON DELETE CASCADE is what acts,
        # rather than the ORM's own cascade bookkeeping.
        db_session.execute(text("DELETE FROM call_sessions WHERE id = :id"), {"id": call.id})
        db_session.flush()
        # The session's identity map still holds the turn, so a plain `get`
        # would return the cached object and the assertion would pass or fail
        # for the wrong reason. Expiring forces a real SELECT.
        db_session.expunge_all()

        assert db_session.get(ConversationTurn, turn_id) is None

    def test_scenario_with_call_history_cannot_be_deleted(self, db_session: Session) -> None:
        """ON DELETE RESTRICT: a result must stay interpretable."""
        suite = make_suite(db_session, "restrict-suite")
        scenario = make_scenario(db_session, suite, "referenced")
        # A terminal run must carry finished_at, per its CHECK constraint.
        run = RunModel(suite_id=suite.id, status=RunStatus.COMPLETED, finished_at=datetime.now(UTC))
        db_session.add(run)
        db_session.flush()
        db_session.add(
            CallSession(test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.COMPLETED)
        )
        db_session.flush()

        # The violation surfaces on execute(), not on a later flush(), so the
        # statement itself has to be inside the raises block.
        with pytest.raises(IntegrityError, match=r"violates foreign key|still referenced"):
            db_session.execute(text("DELETE FROM scenarios WHERE id = :id"), {"id": scenario.id})


class TestConstraints:
    """Declared constraints must actually be enforced."""

    def test_suite_name_is_unique(self, db_session: Session) -> None:
        make_suite(db_session, "duplicate-name")
        db_session.add(SuiteModel(name="duplicate-name"))

        with pytest.raises(IntegrityError, match=r"unique|duplicate key"):
            db_session.flush()

    def test_scenario_name_is_unique_within_a_suite(self, db_session: Session) -> None:
        suite = make_suite(db_session, "unique-suite")
        make_scenario(db_session, suite, "same_name")

        db_session.add(
            Scenario(
                suite_id=suite.id,
                name="same_name",
                language="hi-IN",
                spec=MINIMAL_SPEC,
                spec_version=1,
            )
        )

        with pytest.raises(IntegrityError, match=r"unique|duplicate key"):
            db_session.flush()

    def test_same_scenario_name_is_allowed_in_different_suites(self, db_session: Session) -> None:
        """Uniqueness is per suite, not global."""
        first = make_suite(db_session, "suite-a")
        second = make_suite(db_session, "suite-b")

        make_scenario(db_session, first, "shared_name")
        make_scenario(db_session, second, "shared_name")

        assert db_session.query(Scenario).filter_by(name="shared_name").count() == 2

    def test_turn_index_is_unique_per_call(self, db_session: Session) -> None:
        suite = make_suite(db_session, "turn-unique")
        scenario = make_scenario(db_session, suite, "turn_unique_scenario")
        run = RunModel(suite_id=suite.id, status=RunStatus.RUNNING)
        db_session.add(run)
        db_session.flush()
        call = CallSession(
            test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.IN_PROGRESS
        )
        db_session.add(call)
        db_session.flush()

        db_session.add(
            ConversationTurn(call_session_id=call.id, turn_index=0, speaker=Speaker.CALLER)
        )
        db_session.flush()
        db_session.add(ConversationTurn(call_session_id=call.id, turn_index=0, speaker=Speaker.BOT))

        with pytest.raises(IntegrityError, match=r"unique|duplicate key"):
            db_session.flush()

    def test_negative_turn_index_is_rejected(self, db_session: Session) -> None:
        suite = make_suite(db_session, "negative-turn")
        scenario = make_scenario(db_session, suite, "negative_scenario")
        run = RunModel(suite_id=suite.id, status=RunStatus.RUNNING)
        db_session.add(run)
        db_session.flush()
        call = CallSession(
            test_run_id=run.id, scenario_id=scenario.id, status=CallStatus.IN_PROGRESS
        )
        db_session.add(call)
        db_session.flush()

        db_session.add(
            ConversationTurn(call_session_id=call.id, turn_index=-1, speaker=Speaker.BOT)
        )

        with pytest.raises(IntegrityError, match="check constraint"):
            db_session.flush()

    def test_terminal_run_requires_a_finish_time(self, db_session: Session) -> None:
        """A completed run with no finished_at would be unreportable."""
        suite = make_suite(db_session, "terminal-run")

        db_session.add(RunModel(suite_id=suite.id, status=RunStatus.COMPLETED, finished_at=None))

        with pytest.raises(IntegrityError, match="check constraint"):
            db_session.flush()

    def test_non_terminal_run_must_not_have_a_finish_time(self, db_session: Session) -> None:
        suite = make_suite(db_session, "running-run")

        db_session.add(
            RunModel(suite_id=suite.id, status=RunStatus.RUNNING, finished_at=datetime.now(UTC))
        )

        with pytest.raises(IntegrityError, match="check constraint"):
            db_session.flush()

    def test_completed_run_with_finish_time_is_accepted(self, db_session: Session) -> None:
        suite = make_suite(db_session, "valid-run")
        started = datetime.now(UTC)

        run = RunModel(
            suite_id=suite.id,
            status=RunStatus.COMPLETED,
            started_at=started,
            finished_at=started + timedelta(seconds=30),
        )
        db_session.add(run)
        db_session.flush()

        assert run.finished_at > run.started_at

    def test_finish_before_start_is_rejected(self, db_session: Session) -> None:
        suite = make_suite(db_session, "backwards-run")
        started = datetime.now(UTC)

        db_session.add(
            RunModel(
                suite_id=suite.id,
                status=RunStatus.COMPLETED,
                started_at=started,
                finished_at=started - timedelta(seconds=1),
            )
        )

        with pytest.raises(IntegrityError, match="check constraint"):
            db_session.flush()

    def test_negative_call_duration_is_rejected(self, db_session: Session) -> None:
        suite = make_suite(db_session, "duration-suite")
        scenario = make_scenario(db_session, suite, "duration_scenario")
        run = RunModel(suite_id=suite.id, status=RunStatus.RUNNING)
        db_session.add(run)
        db_session.flush()

        db_session.add(
            CallSession(
                test_run_id=run.id,
                scenario_id=scenario.id,
                status=CallStatus.COMPLETED,
                duration_seconds=-5,
            )
        )

        with pytest.raises(IntegrityError, match="check constraint"):
            db_session.flush()

    def test_invalid_status_value_is_rejected(self, db_session: Session) -> None:
        """Enums are CHECK-constrained VARCHARs, so a bad literal must fail.

        The literal is kept short on purpose. The column is sized to the
        longest valid member ('cancelled', 9 characters), so a longer value
        would be refused by length before the CHECK constraint was consulted
        - and this test is about the CHECK.
        """
        suite = make_suite(db_session, "bad-status")

        with pytest.raises(IntegrityError, match="check constraint"):
            db_session.execute(
                text(
                    "INSERT INTO test_runs (id, suite_id, status, run_metadata) "
                    "VALUES (:id, :suite_id, 'bogus', '{}')"
                ),
                {"id": uuid.uuid4(), "suite_id": suite.id},
            )
            db_session.flush()


class TestTransactions:
    """Rollback must leave no trace."""

    def test_rollback_discards_an_insert(self, db_session: Session) -> None:
        suite = make_suite(db_session, "rollback-suite")
        suite_id = suite.id

        db_session.rollback()

        assert db_session.get(SuiteModel, suite_id) is None

    def test_rollback_after_integrity_error_leaves_session_usable(
        self, db_session: Session
    ) -> None:
        """A failed write must not poison the session for subsequent work."""
        make_suite(db_session, "poison-test")
        db_session.add(SuiteModel(name="poison-test"))

        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

        recovered = make_suite(db_session, "after-rollback")
        assert db_session.get(SuiteModel, recovered.id) is not None

    def test_nested_rollback_to_savepoint(self, db_session: Session) -> None:
        """A savepoint must undo only the work inside it."""
        kept = make_suite(db_session, "kept-suite")

        savepoint = db_session.begin_nested()
        discarded = make_suite(db_session, "discarded-suite")
        discarded_id = discarded.id
        savepoint.rollback()

        assert db_session.get(SuiteModel, kept.id) is not None
        assert db_session.get(SuiteModel, discarded_id) is None

    def test_partial_work_is_not_persisted_on_failure(self, db_session: Session) -> None:
        """Two inserts where the second fails must leave neither."""
        savepoint = db_session.begin_nested()
        first = SuiteModel(name="atomic-one")
        db_session.add(first)
        db_session.flush()
        first_id = first.id

        db_session.add(SuiteModel(name="atomic-one"))
        with pytest.raises(IntegrityError):
            db_session.flush()
        savepoint.rollback()

        assert db_session.get(SuiteModel, first_id) is None
