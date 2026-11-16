"""The run evaluator: verdict rules on synthetic evidence, and real runs end to end."""

from __future__ import annotations

import asyncio
import copy
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
from app.evaluation.evaluator import evaluate_evidence, evaluate_run, gather_evidence
from app.evaluation.registry import BY_NAME, EVALUATOR_VERSION
from app.models import Scenario, Verdict
from app.models import TestSuite as SuiteModel
from app.pipeline.bots.http_text import HttpBotConfig, HttpTextBotAdapter
from app.pipeline.engine import RunConfig, RunEngine
from app.pipeline.modes import ExecutionMode
from app.repositories import caller_conversations as caller_repo
from app.repositories import evaluations as eval_repo
from app.repositories import pipeline_runs as pipeline_repo
from reference_bot.app import BotConfig, create_app
from tests.socket_server import serve

BASE: dict[str, Any] = {
    "run_id": "r",
    "mode": "text_bot_test",
    "status": "completed",
    "outcome": "goal_achieved",
    "language": "en-IN",
    "expected_outcomes": [],
    "required_phrases": [],
    "forbidden_phrases": [],
    "caller_turns": 3,
    "bot_turns": [
        {
            "turn_index": 1,
            "text": "Your request 447219 is confirmed.",
            "latency_ms": 12.0,
            "transcription_failed": False,
            "reference": None,
        },
        {
            "turn_index": 3,
            "text": "Goodbye.",
            "latency_ms": 30.0,
            "transcription_failed": False,
            "reference": None,
        },
    ],
}


def _with(**changes: Any) -> dict[str, Any]:
    evidence = copy.deepcopy(BASE)
    evidence.update(changes)
    return evidence


class TestVerdict:
    def test_goal_achieved_with_no_declared_phrases_passes(self) -> None:
        result = evaluate_evidence(BASE)
        assert result.verdict is Verdict.PASS
        names = {c["name"]: c["status"] for c in result.results["criteria"]}
        assert names == {
            "task_completion": "pass",
            "required_phrases": "not_evaluated",
            "forbidden_phrases": "not_evaluated",
        }

    @pytest.mark.parametrize("outcome", ["bot_refused", "no_progress", "bot_ended_session"])
    def test_a_bot_outcome_short_of_the_goal_fails(self, outcome: str) -> None:
        result = evaluate_evidence(_with(outcome=outcome))
        assert result.verdict is Verdict.FAIL
        assert result.results["metrics"]["task_completion"]["value"] == 0

    @pytest.mark.parametrize(
        "outcome",
        ["provider_error", "audio_validation_failed", "external_bot_unavailable", "cancelled"],
    )
    def test_our_faults_are_undetermined_never_failed(self, outcome: str) -> None:
        result = evaluate_evidence(_with(outcome=outcome, status="failed"))
        assert result.verdict is Verdict.UNDETERMINED
        assert result.results["metrics"]["task_completion"]["value"] is None

    def test_an_unfinished_run_is_undetermined(self) -> None:
        result = evaluate_evidence(_with(status="running", outcome=None))
        assert result.verdict is Verdict.UNDETERMINED

    def test_a_missing_required_phrase_fails_and_names_it(self) -> None:
        result = evaluate_evidence(_with(required_phrases=["is confirmed", "reference number"]))
        assert result.verdict is Verdict.FAIL
        assert result.results["metrics"]["required_phrases"]["missing"] == ["reference number"]

    def test_required_phrases_match_after_normalisation(self) -> None:
        result = evaluate_evidence(_with(required_phrases=["IS CONFIRMED!"]))
        assert result.verdict is Verdict.PASS

    def test_a_forbidden_phrase_fails(self) -> None:
        result = evaluate_evidence(_with(forbidden_phrases=["goodbye"]))
        assert result.verdict is Verdict.FAIL
        assert result.results["metrics"]["forbidden_phrases"]["found"] == ["goodbye"]

    def test_keyword_coverage_never_moves_the_verdict(self) -> None:
        result = evaluate_evidence(_with(expected_outcomes=["Bot states the refund amount"]))
        assert result.verdict is Verdict.PASS
        coverage = result.results["metrics"]["expected_outcome_keyword_coverage"]
        assert (coverage["value"], coverage["declared"]) == (0.0, 1)


class TestMetrics:
    def test_error_rates_are_null_without_references(self) -> None:
        metrics = evaluate_evidence(BASE).results["metrics"]
        assert metrics["wer"]["value"] is None and metrics["cer"]["value"] is None

    def test_error_rates_pool_over_referenced_turns(self) -> None:
        evidence = copy.deepcopy(BASE)
        evidence["bot_turns"][0]["reference"] = "your request 447219 is now confirmed"
        evidence["bot_turns"][1]["reference"] = "goodbye"
        wer = evaluate_evidence(evidence).results["metrics"]["wer"]
        assert (wer["errors"], wer["reference_length"], wer["scored_turns"]) == (1, 7, 2)
        assert wer["value"] == pytest.approx(1 / 7, abs=1e-6)

    def test_a_failed_transcription_is_excluded_not_scored_as_deletions(self) -> None:
        evidence = _with(mode="audio_fixture_test")
        evidence["bot_turns"][0].update(text=None, transcription_failed=True, reference="hello")
        metrics = evaluate_evidence(evidence).results["metrics"]
        assert metrics["wer"]["value"] is None
        assert metrics["transcription_failure_rate"]["value"] == 0.5

    def test_latency_percentiles_use_nearest_rank(self) -> None:
        latency = evaluate_evidence(BASE).results["metrics"]["bot_response_latency_ms"]
        assert (latency["p50"], latency["p90"], latency["max"], latency["samples"]) == (
            12.0,
            30.0,
            30.0,
            2,
        )

    def test_latency_is_null_when_nothing_was_measured(self) -> None:
        evidence = copy.deepcopy(BASE)
        for turn in evidence["bot_turns"]:
            turn["latency_ms"] = None
        assert (
            evaluate_evidence(evidence).results["metrics"]["bot_response_latency_ms"]["value"]
            is None
        )

    def test_every_reported_metric_is_registered(self) -> None:
        assert set(evaluate_evidence(BASE).results["metrics"]) <= set(BY_NAME)


class TestReproducibility:
    def test_the_same_evidence_gives_identical_results_and_fingerprint(self) -> None:
        a, b = evaluate_evidence(BASE), evaluate_evidence(copy.deepcopy(BASE))
        assert (a.results, a.fingerprint) == (b.results, b.fingerprint)

    def test_any_change_to_the_evidence_changes_the_fingerprint(self) -> None:
        changed = copy.deepcopy(BASE)
        changed["bot_turns"][0]["reference"] = "x"
        assert evaluate_evidence(changed).fingerprint != evaluate_evidence(BASE).fingerprint


# ---------------------------------------------------------------------------
# A real run, evaluated from what it stored
# ---------------------------------------------------------------------------

TOKEN = "evaluator-test-token-0123456789ab"
SPEC: dict[str, Any] = {
    "name": "english_request_status",
    "language": "en-IN",
    "persona": {"identity": "Customer", "speaking_style": "polite", "traits": []},
    "goal": {"objective": "Find out the status of my service request.", "max_turns": 8},
    "known_facts": {"request_reference": "447219"},
    "expected_outcomes": ["Bot confirms the request"],
    "constraints": {"required_phrases": ["is confirmed"], "forbidden_phrases": ["password"]},
}


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


def _real_run(session: Session, tmp_path: Path, url: str) -> uuid.UUID:
    settings = Settings(
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "audio"),
        _env_file=None,
    )
    suite = SuiteModel(name=f"eval-{uuid.uuid4().hex[:8]}")
    session.add(suite)
    session.flush()
    scenario = Scenario(
        suite_id=suite.id,
        name=f"s_{uuid.uuid4().hex[:6]}",
        language="en-IN",
        spec=SPEC,
        spec_version=1,
    )
    session.add(scenario)
    session.flush()
    store = AudioArtefactStore(settings.caller_audio_root)
    engine = RunEngine(
        session=session,
        orchestrator=ConversationOrchestrator(
            session=session,
            caller=CallerService(DeterministicCallerProvider(), settings=settings),
            settings=settings,
            artefacts=store,
        ),
        settings=settings,
        bot_adapter=HttpTextBotAdapter(
            HttpBotConfig(
                base_url=url,
                token=SecretStr(TOKEN),
                policy=OutboundPolicy.from_setting("127.0.0.1", allow_loopback=True),
                backoff_seconds=0.0,
            )
        ),
        artefacts=store,
    )
    run = engine.create(
        suite_id=suite.id,
        scenario_id=scenario.id,
        config=RunConfig(mode=ExecutionMode.TEXT_BOT_TEST),
    )
    asyncio.run(engine.run_to_completion(run.id))
    return run.id


class TestARealRun:
    def test_a_completed_text_bot_run_passes_with_measured_latency(
        self, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        evaluation = evaluate_run(db_session, run_id)
        assert evaluation.verdict is Verdict.PASS, evaluation.results["criteria"]
        assert evaluation.evaluator_version == EVALUATOR_VERSION
        metrics = evaluation.results["metrics"]
        assert metrics["forbidden_phrases"]["status"] == "pass"
        assert metrics["bot_response_latency_ms"]["samples"] >= 2
        assert metrics["transcription_failure_rate"]["status"] == "not_evaluated"
        assert evaluation.results["measures_audio"] is False

    def test_re_evaluating_unchanged_evidence_agrees_and_appends(
        self, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        first = evaluate_run(db_session, run_id)
        second = evaluate_run(db_session, run_id)
        assert first.id != second.id
        assert first.evidence_fingerprint == second.evidence_fingerprint
        assert first.results == second.results
        assert len(eval_repo.list_evaluations(db_session, run_id)) == 2

    def test_a_reference_adds_an_error_rate_and_changes_the_fingerprint(
        self, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        before = evaluate_run(db_session, run_id)
        conversation = pipeline_repo.conversation_of(db_session, run_id)
        assert conversation is not None
        bot_turn = next(
            t
            for t in caller_repo.list_turns(db_session, conversation.id)
            if t.speaker.value == "bot"
        )
        eval_repo.add_reference(
            db_session, conversation_turn_id=bot_turn.id, text=bot_turn.content or "", reviewer="qa"
        )
        after = evaluate_run(db_session, run_id)
        assert after.evidence_fingerprint != before.evidence_fingerprint
        assert after.results["metrics"]["wer"]["value"] == 0.0
        assert after.results["metrics"]["wer"]["scored_turns"] == 1

    def test_the_evaluator_never_sees_its_own_output(
        self, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        """Evidence is the run's, not a previous evaluation's."""
        run_id = _real_run(db_session, tmp_path, bot_url)
        evaluate_run(db_session, run_id)
        assert "verdict" not in gather_evidence(db_session, run_id)
