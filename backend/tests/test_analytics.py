"""Phase 12 reporting: statistics, exports, and SQL aggregation through the API."""

from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.analytics.export import safe_cell, to_csv
from app.analytics.stats import fisher_exact, nearest_rank, wilson
from app.models import TestRun as RunModel
from app.models import TestSuite as SuiteModel
from app.models import Verdict
from app.repositories import evaluations as eval_repo
from app.utils.timing import utc_now
from reference_bot.app import BotConfig, create_app
from tests.socket_server import serve
from tests.test_evaluation_evaluator import TOKEN, _real_run

BASE = "/api/v1/analytics"


class TestStatistics:
    def test_wilson_matches_published_values(self) -> None:
        interval = wilson(8, 10)
        assert (interval.low, interval.high) == pytest.approx((0.4902, 0.9433), abs=1e-4)
        assert wilson(0, 10).high == pytest.approx(0.2775, abs=1e-4)
        assert wilson(10, 10).low == pytest.approx(0.7225, abs=1e-4)

    def test_wilson_with_no_decided_runs_is_null_not_zero(self) -> None:
        assert wilson(0, 0).as_dict()["rate"] is None

    @pytest.mark.parametrize(
        ("table", "expected"),
        [((3, 1, 1, 3), 0.485714), ((1, 9, 11, 3), 0.002759), ((8, 2, 1, 5), 0.034965)],
    )
    def test_fisher_matches_published_values(self, table: tuple, expected: float) -> None:
        assert fisher_exact(*table) == pytest.approx(expected, abs=1e-6)

    def test_fisher_is_one_for_identical_groups(self) -> None:
        assert fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)

    def test_nearest_rank(self) -> None:
        assert nearest_rank([3.0, 1.0, 2.0], 50) == 2.0
        assert nearest_rank([], 50) is None

    def test_invalid_inputs_are_refused(self) -> None:
        with pytest.raises(ValueError):
            wilson(3, 2)
        with pytest.raises(ValueError):
            fisher_exact(-1, 0, 0, 0)


class TestCsvSafety:
    @pytest.mark.parametrize("value", ["=1+1", "+cmd", "-2", "@SUM(A1)", "\tx", "\rx"])
    def test_formula_like_cells_are_neutralised(self, value: str) -> None:
        assert safe_cell(value) == "'" + value

    def test_ordinary_text_is_untouched(self) -> None:
        assert safe_cell("मेरा दावा") == "मेरा दावा"
        assert safe_cell(None) == ""

    def test_quotes_and_newlines_round_trip(self) -> None:
        text = to_csv(["a"], [['he said "hi",\nthen left']])
        assert list(csv.reader(io.StringIO(text)))[1] == ['he said "hi",\nthen left']


# ---------------------------------------------------------------------------
# Aggregation over constructed runs
# ---------------------------------------------------------------------------


def _suite(session: Session) -> SuiteModel:
    suite = SuiteModel(name=f"analytics-{uuid.uuid4().hex[:8]}")
    session.add(suite)
    session.flush()
    return suite


def _run(
    session: Session,
    suite: SuiteModel,
    *,
    verdicts: list[Verdict] | None,
    language: str = "hi-IN",
    scenario: str = "s1",
    adapter: str = "http",
    version: str = "bb-eval-1",
    metrics: dict[str, Any] | None = None,
    age_days: int = 0,
) -> RunModel:
    run = RunModel(
        suite_id=suite.id,
        run_metadata={
            "pipeline": {
                "mode": "text_bot_test",
                "language": language,
                "scenario_name": scenario,
                "bot_adapter": adapter,
                "status": "completed",
                "outcome": "goal_achieved",
            }
        },
    )
    session.add(run)
    session.flush()
    if age_days:
        run.created_at = utc_now() - timedelta(days=age_days)
        session.flush()
    for verdict in verdicts or []:
        eval_repo.add_evaluation(
            session,
            test_run_id=run.id,
            evaluator_version=version,
            verdict=verdict,
            evidence_fingerprint="f" * 64,
            results={"metrics": metrics or {}, "criteria": []},
        )
    return run


class TestSummary:
    def test_pass_rate_counts_decided_runs_only(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite = _suite(db_session)
        for v in [Verdict.PASS, Verdict.PASS, Verdict.FAIL, Verdict.UNDETERMINED]:
            _run(db_session, suite, verdicts=[v])
        _run(db_session, suite, verdicts=None)
        body = api_client.get(f"{BASE}/summary", params={"suite_id": str(suite.id)}).json()
        overall = body["overall"]
        assert overall["runs"] == 5
        assert overall["verdicts"] == {
            "pass": 2,
            "fail": 1,
            "undetermined": 1,
            "not_evaluated": 1,
        }
        assert overall["pass_rate"]["n"] == 3
        assert overall["pass_rate"]["rate"] == pytest.approx(2 / 3, abs=1e-6)

    def test_a_re_evaluated_run_counts_once_with_its_latest_verdict(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite = _suite(db_session)
        _run(db_session, suite, verdicts=[Verdict.FAIL, Verdict.PASS])
        body = api_client.get(f"{BASE}/summary", params={"suite_id": str(suite.id)}).json()
        assert body["overall"]["verdicts"]["pass"] == 1
        assert body["overall"]["runs"] == 1

    def test_grouping_by_language(self, api_client: TestClient, db_session: Session) -> None:
        suite = _suite(db_session)
        _run(db_session, suite, verdicts=[Verdict.PASS], language="hi-IN")
        _run(db_session, suite, verdicts=[Verdict.FAIL], language="ta-IN")
        body = api_client.get(
            f"{BASE}/summary", params={"suite_id": str(suite.id), "group_by": "language"}
        ).json()
        rates = {g["key"]: g["pass_rate"]["rate"] for g in body["groups"]}
        assert rates == {"hi-IN": 1.0, "ta-IN": 0.0}

    def test_an_unknown_dimension_is_422(self, api_client: TestClient) -> None:
        assert api_client.get(f"{BASE}/summary", params={"group_by": "password"}).status_code == 422

    def test_mixed_evaluator_versions_are_flagged(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite = _suite(db_session)
        _run(db_session, suite, verdicts=[Verdict.PASS], version="bb-eval-1")
        _run(db_session, suite, verdicts=[Verdict.PASS], version="bb-eval-0")
        body = api_client.get(f"{BASE}/summary", params={"suite_id": str(suite.id)}).json()
        assert body["evaluator_versions"] == ["bb-eval-0", "bb-eval-1"]
        assert "not comparable" in body["warnings"][0]

    def test_wer_is_pooled_across_runs(self, api_client: TestClient, db_session: Session) -> None:
        suite = _suite(db_session)
        _run(
            db_session,
            suite,
            verdicts=[Verdict.PASS],
            metrics={"wer": {"value": 0.5, "errors": 1, "reference_length": 2}},
        )
        _run(
            db_session,
            suite,
            verdicts=[Verdict.PASS],
            metrics={"wer": {"value": 0.125, "errors": 1, "reference_length": 8}},
        )
        body = api_client.get(f"{BASE}/summary", params={"suite_id": str(suite.id)}).json()
        # (1 + 1) / (2 + 8), not the mean of 0.5 and 0.125.
        assert body["metrics"]["wer_pooled"]["value"] == pytest.approx(0.2)

    def test_runs_the_pipeline_did_not_create_are_excluded(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite = _suite(db_session)
        db_session.add(RunModel(suite_id=suite.id, run_metadata={}))
        db_session.flush()
        body = api_client.get(f"{BASE}/summary", params={"suite_id": str(suite.id)}).json()
        assert body["overall"]["runs"] == 0


class TestRegressions:
    def _params(self, base: SuiteModel, cand: SuiteModel) -> dict[str, str]:
        return {"baseline_suite_id": str(base.id), "candidate_suite_id": str(cand.id)}

    def test_a_large_drop_is_a_regression(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        base, cand = _suite(db_session), _suite(db_session)
        for _ in range(10):
            _run(db_session, base, verdicts=[Verdict.PASS])
        for i in range(10):
            _run(db_session, cand, verdicts=[Verdict.PASS if i < 2 else Verdict.FAIL])
        body = api_client.get(f"{BASE}/regressions", params=self._params(base, cand)).json()
        assert body["conclusion"] == "regression"
        assert body["p_value"] < 0.05
        assert body["pass_rate_difference"] == pytest.approx(-0.8)

    def test_a_small_sample_is_insufficient_however_extreme(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        base, cand = _suite(db_session), _suite(db_session)
        for _ in range(3):
            _run(db_session, base, verdicts=[Verdict.PASS])
            _run(db_session, cand, verdicts=[Verdict.FAIL])
        body = api_client.get(f"{BASE}/regressions", params=self._params(base, cand)).json()
        assert body["conclusion"] == "insufficient_evidence"
        assert "at least 5" in body["reason"]

    def test_a_small_difference_is_not_significant(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        base, cand = _suite(db_session), _suite(db_session)
        for i in range(10):
            _run(db_session, base, verdicts=[Verdict.PASS if i < 8 else Verdict.FAIL])
            _run(db_session, cand, verdicts=[Verdict.PASS if i < 7 else Verdict.FAIL])
        body = api_client.get(f"{BASE}/regressions", params=self._params(base, cand)).json()
        assert body["conclusion"] == "no_significant_difference"

    def test_undetermined_runs_do_not_count_as_failures(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        base, cand = _suite(db_session), _suite(db_session)
        for _ in range(6):
            _run(db_session, base, verdicts=[Verdict.PASS])
            _run(db_session, cand, verdicts=[Verdict.PASS])
            _run(db_session, cand, verdicts=[Verdict.UNDETERMINED])
        body = api_client.get(f"{BASE}/regressions", params=self._params(base, cand)).json()
        assert body["candidate"]["pass_rate"]["rate"] == 1.0
        assert body["conclusion"] == "no_significant_difference"


class TestTrendAndExport:
    def test_trend_buckets_by_day(self, api_client: TestClient, db_session: Session) -> None:
        suite = _suite(db_session)
        _run(db_session, suite, verdicts=[Verdict.PASS], age_days=2)
        _run(db_session, suite, verdicts=[Verdict.FAIL])
        body = api_client.get(f"{BASE}/trend", params={"suite_id": str(suite.id)}).json()
        assert len(body["periods"]) == 2
        assert [p["verdicts"]["pass"] for p in body["periods"]] == [1, 0]

    def test_runs_csv_neutralises_formula_cells(
        self, api_client: TestClient, db_session: Session
    ) -> None:
        suite = _suite(db_session)
        _run(db_session, suite, verdicts=[Verdict.PASS], scenario="=HYPERLINK(evil)")
        response = api_client.get(f"{BASE}/runs.csv", params={"suite_id": str(suite.id)})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(response.text)))
        assert rows[0][0] == "run_id"
        assert rows[1][3] == "'=HYPERLINK(evil)"
        assert rows[1][9] == "pass"


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


class TestRealRuns:
    def test_compare_two_evaluated_runs(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        a = _real_run(db_session, tmp_path, bot_url)
        b = _real_run(db_session, tmp_path, bot_url)
        for run_id in (a, b):
            api_client.post(f"/api/v1/test-runs/{run_id}/evaluations")
        body = api_client.get(
            f"{BASE}/compare", params={"baseline": str(a), "candidate": str(b)}
        ).json()
        assert body["verdict_change"] == "unchanged"
        assert body["comparable"] is True
        assert "not a significant result" in body["statistical_note"]
        latency = next(
            d for d in body["metric_deltas"] if d["metric"] == "bot_response_latency_p50_ms"
        )
        assert latency["change"] in {"better", "worse", "unchanged"}
        wer = next(d for d in body["metric_deltas"] if d["metric"] == "wer")
        assert wer["change"] == "not_comparable"

    def test_comparing_an_unevaluated_run_is_refused(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        a = _real_run(db_session, tmp_path, bot_url)
        response = api_client.get(
            f"{BASE}/compare", params={"baseline": str(a), "candidate": str(a)}
        )
        assert response.status_code == 409
        missing = api_client.get(
            f"{BASE}/compare", params={"baseline": str(uuid.uuid4()), "candidate": str(a)}
        )
        assert missing.status_code == 404

    def test_a_run_exports_as_json_and_csv(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        api_client.post(f"/api/v1/test-runs/{run_id}/evaluations")
        exported = api_client.get(f"/api/v1/test-runs/{run_id}/export")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
        document = json.loads(exported.text)
        assert document["export"]["format"] == "bhashabench.run-export/v1"
        assert document["evaluation"]["verdict"] == "pass"
        assert len(document["evaluation"]["evidence_fingerprint"]) == 64
        assert document["turns"][0]["speaker"] == "caller"
        assert TOKEN not in exported.text

        as_csv = api_client.get(f"/api/v1/test-runs/{run_id}/export", params={"format": "csv"})
        rows = list(csv.reader(io.StringIO(as_csv.text)))
        assert rows[0] == [
            "turn_index",
            "speaker",
            "text",
            "source",
            "latency_ms",
            "transcription_error",
            "reference",
        ]
        assert len(rows) == len(document["turns"]) + 1

    def test_exporting_an_unknown_run_is_404(self, api_client: TestClient) -> None:
        assert api_client.get(f"/api/v1/test-runs/{uuid.uuid4()}/export").status_code == 404
