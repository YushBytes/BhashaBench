"""Whole conversations driven by the model-backed caller, against PostgreSQL.

The scripted client stands in for a model, so nothing leaves the process. What
is under test is everything around it: that each turn's evidence is persisted,
that `uses_language_model` is derived from what happened rather than from what
was configured, that the per-run limit holds across turns, and that the
scenario's marking scheme never reaches the client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.caller import get_orchestrator_factory
from app.caller.artefacts import AudioArtefactStore
from app.caller.llm.fake import FAKE_MODEL, FAKE_PROVIDER, Reply, ScriptedLlmClient, Step
from app.caller.llm.models import LlmUsage
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.providers.llm import LlmCallerLimits, LlmCallerProvider
from app.caller.service import CallerService
from app.caller.state import CallerState
from app.core.config import Settings, get_settings
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.engine import RunConfig, RunEngine
from app.pipeline.modes import ExecutionMode
from app.repositories import caller_conversations as repo
from app.repositories import pipeline_runs as pipeline_repo
from tests.test_caller_llm_contract import PRICING
from tests.test_caller_orchestrator import CLAIM, TAMIL_SPEC, _make_scenario, _settings

SENTINEL = "ZX-SENTINEL-OUTCOME the bot confirms the claim is approved"
USAGE = LlmUsage(input_tokens=800, output_tokens=60)
TURN_COST = PRICING.cost(input_tokens=800, output_tokens=60)

BOT_REPLIES = [
    "Welcome to the crop insurance helpline.",
    "May I have your claim reference number, please?",
    f"Thank you. Claim {CLAIM} has been approved and payment is scheduled.",
    "Yes, that is correct.",
]


def _turn(message: str, intent: str, next_state: str, *, facts: list[str] | None = None) -> str:
    return json.dumps(
        {
            "message": message,
            "intent": intent,
            "next_state": next_state,
            "termination_reason": None,
            "facts_used": facts or [],
            "explanation": "scripted",
        },
        ensure_ascii=False,
    )


GOOD_TURNS = [
    _turn("வணக்கம், என் பயிர் காப்பீடு பற்றி கேட்க வேண்டும்.", "open", "introducing"),
    _turn("என் claim நிலை என்ன?", "ask", "awaiting_information"),
    _turn(f"என் எண் {CLAIM}.", "provide_fact", "providing_details", facts=["claim_reference"]),
    _turn("அப்படியென்றால் அது ஒப்புதல் ஆகிவிட்டதா?", "confirm", "confirming"),
    _turn("நன்றி.", "close", "goal_achieved"),
]


def _script(turns: list[str]) -> list[Step]:
    return [Reply(text, usage=USAGE) for text in turns]


def _build(
    session: Session,
    settings: Settings,
    script: list[Step],
    *,
    max_cost_per_run: Decimal = Decimal(5),
    max_attempts: int = 2,
) -> tuple[ConversationOrchestrator, ScriptedLlmClient]:
    client = ScriptedLlmClient(script, pricing=PRICING)
    provider = LlmCallerProvider(
        client,
        fallback=DeterministicCallerProvider(max_clarifications=settings.caller_max_clarifications),
        limits=LlmCallerLimits(
            max_output_tokens=400,
            max_prompt_tokens=20_000,
            max_attempts=max_attempts,
            request_timeout_seconds=5.0,
            max_message_chars=settings.caller_max_message_chars,
            max_cost_per_run=max_cost_per_run,
            temperature=0.2,
            seed=11,
        ),
    )
    orchestrator = ConversationOrchestrator(
        session=session, caller=CallerService(provider, settings=settings), settings=settings
    )
    return orchestrator, client


@pytest.fixture
def llm_settings(tmp_path: Path) -> Settings:
    return _settings(tmp_path)


@pytest.fixture
def ids(db_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    spec = {**TAMIL_SPEC, "expected_outcomes": [SENTINEL]}
    suite, scenario = _make_scenario(db_session, spec=spec)
    return suite.id, scenario.id


def _run(orchestrator: ConversationOrchestrator, ids: tuple[uuid.UUID, uuid.UUID]) -> Any:
    return asyncio.run(
        orchestrator.simulate(suite_id=ids[0], scenario_id=ids[1], bot_replies=BOT_REPLIES)
    )


def _caller_turns(session: Session, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    return [
        dict(turn.turn_metadata or {})
        for turn in repo.list_turns(session, conversation_id)
        if turn.speaker.value == "caller"
    ]


class TestGeneratedConversation:
    def test_a_conversation_generated_turn_by_turn_reaches_its_goal(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, client = _build(db_session, llm_settings, _script(GOOD_TURNS))
        report = _run(orchestrator, ids)

        assert report.state is CallerState.GOAL_ACHIEVED
        assert report.goal_achieved is True
        assert report.turns_used == 5
        assert len(client.requests) == 5
        assert client.remaining == 0

    def test_the_report_says_a_model_generated_it_and_which(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        report = _run(orchestrator, ids)

        assert report.uses_language_model is True
        assert report.provider == FAKE_PROVIDER
        assert report.llm is not None
        assert report.llm["models"] == [FAKE_MODEL]
        assert report.llm["turns_generated"] == 5
        assert report.llm["turns_fallback"] == 0
        assert report.llm["requests_sent"] == 5
        assert report.llm["contacts_external_service"] is False

    def test_tokens_and_cost_are_summed_across_the_conversation(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        llm = _run(orchestrator, ids).llm

        assert (llm["input_tokens"], llm["output_tokens"]) == (4000, 300)
        assert Decimal(llm["estimated_cost"]) == TURN_COST * 5
        assert llm["currency"] == "INR"

    def test_every_turn_stores_how_it_was_produced(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        report = _run(orchestrator, ids)

        turns = _caller_turns(db_session, report.conversation_id)
        assert len(turns) == 5
        for metadata in turns:
            generation = metadata["generation"]
            assert metadata["uses_language_model"] is True
            assert generation["generated_by_language_model"] is True
            assert generation["provider"] == FAKE_PROVIDER
            assert generation["model"] == FAKE_MODEL
            assert generation["seed_requested"] == 11
            assert generation["seed_sent"] is True
            assert generation["seed_honoured"] is None
            assert generation["input_tokens"] == 800
            assert Decimal(generation["estimated_cost"]) == TURN_COST
            assert generation["retry_count"] == 0
            assert generation["fallback_used"] is False
            assert generation["latency_ms"] >= 0
            assert metadata["rule_ids"] == ["llm.generated"]


class TestDerivedFromExecution:
    """`uses_language_model` reports what happened, not what was configured."""

    def test_nothing_is_claimed_before_a_turn_exists(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        conversation = orchestrator.start(suite_id=ids[0], scenario_id=ids[1])
        meta = repo.caller_metadata_of(conversation)

        assert meta["provider_declares_language_model"] is True
        assert meta["uses_language_model"] is False
        assert orchestrator.report(conversation.id).uses_language_model is False
        assert orchestrator.report(conversation.id).llm is None

    def test_it_becomes_true_with_the_first_generated_turn(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        conversation = orchestrator.start(suite_id=ids[0], scenario_id=ids[1])
        asyncio.run(orchestrator.next_caller_turn(conversation.id))

        assert orchestrator.report(conversation.id).uses_language_model is True

    def test_a_conversation_where_the_model_never_produced_a_turn_reports_false(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A model provider was configured and asked every time. It never
        delivered, so the rule engine spoke every turn - and the report says
        no model generated this conversation, while still showing what the
        failed requests cost."""
        script = [Reply("not json at all", usage=USAGE)] * 40
        orchestrator, client = _build(db_session, llm_settings, script)
        report = _run(orchestrator, ids)

        assert report.uses_language_model is False
        assert report.provider == FAKE_PROVIDER
        assert report.state is CallerState.GOAL_ACHIEVED
        assert report.llm["turns_generated"] == 0
        assert report.llm["turns_fallback"] == report.turns_used
        assert report.llm["requests_sent"] == len(client.requests) == report.turns_used * 2
        assert Decimal(report.llm["estimated_cost"]) == TURN_COST * len(client.requests)
        for metadata in _caller_turns(db_session, report.conversation_id):
            assert metadata["uses_language_model"] is False
            assert metadata["generation"]["fallback_reason"] == "invalid_output"
            assert "llm.generated" not in metadata["rule_ids"]

    def test_one_generated_turn_is_enough_and_a_later_fallback_does_not_undo_it(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        script = [Reply(GOOD_TURNS[0], usage=USAGE), *[Reply("nope", usage=USAGE)] * 40]
        orchestrator, _ = _build(db_session, llm_settings, script)
        report = _run(orchestrator, ids)

        flags = [
            m["uses_language_model"] for m in _caller_turns(db_session, report.conversation_id)
        ]
        assert flags[0] is True
        assert not any(flags[1:])
        assert report.uses_language_model is True
        assert report.llm["turns_generated"] == 1
        assert report.llm["turns_fallback"] == len(flags) - 1

    def test_a_rule_engine_conversation_has_no_generation_record(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator = ConversationOrchestrator(
            session=db_session,
            caller=CallerService(DeterministicCallerProvider(), settings=llm_settings),
            settings=llm_settings,
        )
        report = _run(orchestrator, ids)

        assert report.uses_language_model is False
        assert report.llm is None
        for metadata in _caller_turns(db_session, report.conversation_id):
            assert metadata["uses_language_model"] is False
            assert "generation" not in metadata

    def test_a_conversation_stored_before_this_field_was_derived_still_reads(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Older rows have no `llm` block and no per-turn evidence."""
        orchestrator = ConversationOrchestrator(
            session=db_session,
            caller=CallerService(DeterministicCallerProvider(), settings=llm_settings),
            settings=llm_settings,
        )
        conversation = orchestrator.start(suite_id=ids[0], scenario_id=ids[1])
        meta = repo.caller_metadata_of(conversation)
        meta.pop("provider_declares_language_model")
        meta["uses_language_model"] = False
        repo.update_caller_metadata(db_session, conversation, meta)

        asyncio.run(orchestrator.next_caller_turn(conversation.id))
        report = orchestrator.report(conversation.id)
        assert report.uses_language_model is False
        assert report.llm is None


class TestPerRunCostLimit:
    def test_the_limit_holds_across_turns_not_just_within_one(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Each turn is told what earlier turns spent. Once the next request's
        worst case no longer fits, the model is not asked again."""
        limit = Decimal("0.1")
        orchestrator, client = _build(
            db_session, llm_settings, _script(GOOD_TURNS), max_cost_per_run=limit
        )
        report = _run(orchestrator, ids)

        turns = _caller_turns(db_session, report.conversation_id)
        reasons = [m["generation"]["fallback_reason"] for m in turns]
        assert reasons[0] is None
        assert "run_cost_limit" in reasons
        first_refusal = reasons.index("run_cost_limit")
        assert all(reason == "run_cost_limit" for reason in reasons[first_refusal:])
        assert len(client.requests) == first_refusal
        assert Decimal(report.llm["estimated_cost"]) <= limit
        assert report.llm["turns_generated"] == first_refusal

    def test_a_refused_request_adds_nothing_to_the_total(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, client = _build(
            db_session, llm_settings, _script(GOOD_TURNS), max_cost_per_run=Decimal("0.000001")
        )
        report = _run(orchestrator, ids)

        assert client.requests == []
        assert report.uses_language_model is False
        assert report.llm["requests_sent"] == 0
        assert Decimal(report.llm["estimated_cost"]) == 0
        assert report.llm["input_tokens"] is None


class TestExpectedOutcomesNeverReachTheModel:
    def test_the_marking_scheme_is_in_no_request(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, client = _build(db_session, llm_settings, _script(GOOD_TURNS))
        report = _run(orchestrator, ids)

        # It is a real part of the scenario and the report surface shows it...
        assert report.outcomes_expected == (SENTINEL,)
        # ...and no request carried it, in a message or in the schema.
        assert len(client.requests) == 5
        for request in client.requests:
            sent = json.dumps(
                {
                    "messages": [m.content for m in request.messages],
                    "schema": request.response_schema,
                    "correlation": request.correlation_id,
                },
                ensure_ascii=False,
            )
            assert "ZX-SENTINEL" not in sent
            assert "expected_outcomes" not in sent

    def test_it_is_in_no_turn_record(
        self, db_session: Session, llm_settings: Settings, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        report = _run(orchestrator, ids)
        stored = json.dumps(_caller_turns(db_session, report.conversation_id), ensure_ascii=False)
        assert "ZX-SENTINEL" not in stored

    def test_it_is_in_no_log_line_and_neither_is_what_the_caller_said(
        self,
        db_session: Session,
        llm_settings: Settings,
        ids: tuple[uuid.UUID, uuid.UUID],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        orchestrator, _ = _build(db_session, llm_settings, _script(GOOD_TURNS))
        with caplog.at_level(logging.DEBUG, logger="bhashabench"):
            _run(orchestrator, ids)

        assert any(record.message == "caller.llm_turn" for record in caplog.records)
        logged = " ".join(
            f"{record.getMessage()} {json.dumps(record.__dict__, default=str, ensure_ascii=False)}"
            for record in caplog.records
        )
        assert "ZX-SENTINEL" not in logged
        assert CLAIM not in logged
        assert "வணக்கம்" not in logged


class TestPipelineRunSummary:
    """The run list reads `uses_language_model` from the run's own metadata."""

    def _engine(
        self, session: Session, settings: Settings, script: list[Step], tmp_path: Path
    ) -> RunEngine:
        orchestrator, _ = _build(session, settings, script)
        return RunEngine(
            session=session,
            orchestrator=orchestrator,
            settings=settings,
            bot_adapter=ManualBotAdapter(),
            artefacts=AudioArtefactStore(tmp_path / "audio"),
            stt_provider=None,
            tts_provider=None,
        )

    def _first_turn(self, engine: RunEngine, ids: tuple[uuid.UUID, uuid.UUID]) -> uuid.UUID:
        run = engine.create(
            suite_id=ids[0],
            scenario_id=ids[1],
            config=RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION, bot_adapter="manual"),
        )
        asyncio.run(engine.run_to_completion(run.id))
        return run.id

    def test_a_created_run_claims_nothing(
        self,
        db_session: Session,
        llm_settings: Settings,
        ids: tuple[uuid.UUID, uuid.UUID],
        tmp_path: Path,
    ) -> None:
        engine = self._engine(db_session, llm_settings, _script(GOOD_TURNS), tmp_path)
        run = engine.create(
            suite_id=ids[0],
            scenario_id=ids[1],
            config=RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION, bot_adapter="manual"),
        )
        assert pipeline_repo.pipeline_metadata_of(run)["uses_language_model"] is False
        assert engine.report(run.id).uses_language_model is False

    def test_a_generated_turn_is_carried_onto_the_run(
        self,
        db_session: Session,
        llm_settings: Settings,
        ids: tuple[uuid.UUID, uuid.UUID],
        tmp_path: Path,
    ) -> None:
        engine = self._engine(db_session, llm_settings, _script(GOOD_TURNS), tmp_path)
        run_id = self._first_turn(engine, ids)
        run = pipeline_repo.get_run(db_session, run_id)
        assert run is not None
        assert pipeline_repo.pipeline_metadata_of(run)["uses_language_model"] is True
        assert engine.report(run_id).uses_language_model is True

    def test_a_fallback_turn_leaves_the_run_saying_no_model(
        self,
        db_session: Session,
        llm_settings: Settings,
        ids: tuple[uuid.UUID, uuid.UUID],
        tmp_path: Path,
    ) -> None:
        engine = self._engine(db_session, llm_settings, [Reply("nope", usage=USAGE)] * 4, tmp_path)
        run_id = self._first_turn(engine, ids)
        run = pipeline_repo.get_run(db_session, run_id)
        assert run is not None
        assert pipeline_repo.pipeline_metadata_of(run)["uses_language_model"] is False
        assert engine.report(run_id).uses_language_model is False


@pytest.fixture
def llm_client(
    api_client: TestClient, test_app: FastAPI, db_session: Session
) -> Iterator[TestClient]:
    """The API with the caller replaced by the scripted model-backed one."""
    settings = test_app.dependency_overrides[get_settings]()
    orchestrator, _ = _build(db_session, settings, _script(GOOD_TURNS))

    def factory() -> Iterator[ConversationOrchestrator]:
        yield orchestrator

    test_app.dependency_overrides[get_orchestrator_factory] = lambda: factory
    yield api_client
    test_app.dependency_overrides.pop(get_orchestrator_factory, None)


class TestApiSurface:
    BASE = "/api/v1/caller"

    def _start(self, client: TestClient, ids: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
        response = client.post(
            f"{self.BASE}/conversations",
            json={"suite_id": str(ids[0]), "scenario_id": str(ids[1])},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_a_new_conversation_reports_no_model_and_no_totals(
        self, llm_client: TestClient, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        body = self._start(llm_client, ids)
        assert body["provider"] == FAKE_PROVIDER
        assert body["uses_language_model"] is False
        assert body["llm"] is None

    def test_a_generated_turn_shows_on_the_conversation_and_the_turn(
        self, llm_client: TestClient, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        conversation_id = self._start(llm_client, ids)["conversation_id"]
        after = llm_client.post(f"{self.BASE}/conversations/{conversation_id}/turns")
        assert after.status_code == 200, after.text
        body = after.json()
        assert body["uses_language_model"] is True
        assert body["llm"]["turns_generated"] == 1
        assert body["llm"]["contacts_external_service"] is False

        turns = llm_client.get(f"{self.BASE}/conversations/{conversation_id}/turns").json()
        turn = turns["turns"][0]
        assert turn["uses_language_model"] is True
        assert turn["generation"]["model"] == FAKE_MODEL
        assert turn["generation"]["fallback_used"] is False

    def test_the_existing_fields_are_all_still_there(
        self, llm_client: TestClient, ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Additive only: a client written before these fields keeps working."""
        body = self._start(llm_client, ids)
        for field in (
            "conversation_id",
            "scenario_name",
            "language",
            "provider",
            "uses_language_model",
            "state",
            "outcome",
            "turns_used",
            "turn_budget",
            "goal_achieved",
            "outcomes_expected",
            "outcomes_observed",
            "rule_ids_fired",
        ):
            assert field in body
