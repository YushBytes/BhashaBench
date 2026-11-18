"""The CI regression gate (Phase 14 exit criterion: a deliberately introduced
regression fails CI).

Every committed reference scenario in `scenarios/` runs as a
`text_bot_test` against the scripted reference bot on a real localhost
socket, is evaluated, and its verdict is compared with
`benchmarks/baseline.json`. A verdict that got worse fails this test - and
so the build. Deterministic end to end: the rule-based caller and the
scripted bot produce the same verdicts for the same code.

To accept an intended change, regenerate the baseline and commit it with
the change that explains it:

    BENCHMARK_UPDATE_BASELINE=1 pytest backend/tests/test_benchmark_gate.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.caller.errors import ScenarioNotUsableError
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.service import CallerService
from app.core.config import AppEnv, Settings
from app.core.outbound import OutboundPolicy
from app.evaluation.evaluator import evaluate_run
from app.evaluation.regression_gate import compare
from app.models import TestSuite as SuiteModel
from app.pipeline.bots.http_text import HttpBotConfig, HttpTextBotAdapter
from app.pipeline.engine import RunConfig, RunEngine
from app.pipeline.modes import ExecutionMode
from app.services import scenario_service
from reference_bot.app import BotConfig, create_app
from reference_bot.responder import load, load_path
from tests.socket_server import serve

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = sorted((REPO / "scenarios").glob("*.yaml"))
BASELINE = REPO / "benchmarks" / "baseline.json"
TOKEN = "benchmark-reference-token-0123456789"

BENCHMARK_SCRIPT = load_path(REPO / "benchmarks" / "reference_bot_script.json")
"""The reference bot as the benchmark runs it: scripted to satisfy the
reference scenarios' required phrases. It measures this pipeline, not any
real bot - a regression here is a regression in our code."""

REFUSING = load(
    {"rules": [{"reply": "I am sorry, I cannot help you with that.", "end_session": True}]}
)
"""A deliberately broken bot: it refuses every request and hangs up."""


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN, script=BENCHMARK_SCRIPT))) as url:
        yield url


@pytest.fixture(scope="module")
def broken_bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN, script=REFUSING))) as url:
        yield url


def run_benchmark(session: Session, tmp_path: Path, url: str) -> dict[str, str]:
    """Each reference scenario's verdict against the bot at `url`."""
    settings = Settings(
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "audio"),
        _env_file=None,
    )
    suite = SuiteModel(name=f"benchmark-{uuid.uuid4().hex[:8]}")
    session.add(suite)
    session.flush()
    store = AudioArtefactStore(settings.caller_audio_root)
    verdicts: dict[str, str] = {}
    for path in SCENARIOS:
        scenario = scenario_service.create_scenario(
            session, suite_id=suite.id, content=path.read_text(encoding="utf-8")
        )
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
        try:
            run = engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.TEXT_BOT_TEST),
            )
        except ScenarioNotUsableError:
            # The caller has no reviewed phrase table for this language.
            verdicts[path.stem] = "not_runnable"
            continue
        asyncio.run(engine.run_to_completion(run.id))
        asyncio.run(engine.close())
        verdicts[path.stem] = evaluate_run(session, run.id).verdict.value
    return verdicts


def test_the_benchmark_has_not_regressed(db_session: Session, tmp_path: Path, bot_url: str) -> None:
    current = run_benchmark(db_session, tmp_path, bot_url)
    if os.environ.get("BENCHMARK_UPDATE_BASELINE") == "1":
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"baseline rewritten: {current}")
    assert BASELINE.exists(), (
        "no benchmarks/baseline.json; generate it (see this module's docstring)"
    )
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = compare(baseline, current)
    assert report.passed, "the benchmark regressed:\n" + report.summary()


def test_the_baseline_is_worth_guarding(db_session: Session) -> None:
    """A gate over a baseline in which nothing passes would catch nothing."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert set(baseline) == {p.stem for p in SCENARIOS}, "baseline and scenarios/ disagree"
    assert "pass" in baseline.values()


def test_a_deliberately_broken_bot_fails_the_gate(
    db_session: Session, tmp_path: Path, broken_bot_url: str
) -> None:
    """The exit criterion itself: introduce a regression, and the gate fails."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    report = compare(baseline, run_benchmark(db_session, tmp_path, broken_bot_url))
    assert not report.passed
    passing = [name for name, verdict in baseline.items() if verdict == "pass"]
    assert all(any(r.startswith(f"{name}:") for r in report.regressions) for name in passing)


class TestCompare:
    def test_a_worse_verdict_is_a_regression(self) -> None:
        report = compare({"a": "pass", "b": "fail"}, {"a": "fail", "b": "pass"})
        assert report.regressions == ["a: pass -> fail"]
        assert report.improvements == ["b: fail -> pass"]

    def test_a_missing_scenario_is_a_regression_and_a_new_one_is_not(self) -> None:
        report = compare({"a": "pass"}, {"b": "pass"})
        assert report.regressions == ["a: pass -> missing from the benchmark"]
        assert report.new == ["b: pass"]

    def test_unknown_verdicts_are_refused(self) -> None:
        with pytest.raises(ValueError):
            compare({"a": "great"}, {"a": "pass"})
