"""The evaluation endpoints through the real routes and PostgreSQL."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import caller_conversations as caller_repo
from app.repositories import pipeline_runs as pipeline_repo
from reference_bot.app import BotConfig, create_app
from tests.socket_server import serve
from tests.test_evaluation_evaluator import TOKEN, _real_run

BASE = "/api/v1"


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


def _bot_turn_index(session: Session, run_id: uuid.UUID) -> int:
    conversation = pipeline_repo.conversation_of(session, run_id)
    assert conversation is not None
    return next(
        t.turn_index
        for t in caller_repo.list_turns(session, conversation.id)
        if t.speaker.value == "bot"
    )


class TestCatalogue:
    def test_every_metric_is_served_with_its_definition(self, api_client: TestClient) -> None:
        body = api_client.get(f"{BASE}/evaluation/metrics").json()
        assert body["evaluator_version"] == "bb-eval-2"
        assert body["normalisation_version"] == "bb-norm-1"
        assert body["composite_score"] is None
        names = {m["name"] for m in body["metrics"]}
        assert {"task_completion", "wer", "cer", "bot_response_latency_ms"} <= names
        assert all(m["limitations"] for m in body["metrics"])


class TestErrorRate:
    def test_a_breakdown_is_returned(self, api_client: TestClient) -> None:
        response = api_client.post(
            f"{BASE}/evaluation/error-rate",
            json={"reference": "मेरा दावा मंजूर हुआ", "hypothesis": "मेरा दावा हुआ", "language": "hi-IN"},
        )
        assert response.status_code == 200
        wer = response.json()["wer"]
        assert (wer["value"], wer["deletions"], wer["reference_length"]) == (0.25, 1, 4)

    def test_an_empty_reference_has_a_null_rate(self, api_client: TestClient) -> None:
        body = api_client.post(
            f"{BASE}/evaluation/error-rate", json={"reference": "", "hypothesis": "x"}
        ).json()
        assert body["wer"]["value"] is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"reference": "a", "hypothesis": "b", "language": "fr-FR"},
            {"reference": "a", "hypothesis": "b", "extra": 1},
            {"reference": "a" * 20_001, "hypothesis": "b"},
        ],
    )
    def test_a_bad_request_is_422(self, api_client: TestClient, payload: dict) -> None:
        assert api_client.post(f"{BASE}/evaluation/error-rate", json=payload).status_code == 422


class TestRunEvaluations:
    def test_evaluate_list_and_re_evaluate_after_a_reference(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        first = api_client.post(f"{BASE}/test-runs/{run_id}/evaluations")
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["verdict"] == "pass"
        assert body["measures_audio"] is False
        assert body["metrics"]["wer"]["value"] is None

        turn = _bot_turn_index(db_session, run_id)
        text = next(
            t.content
            for t in caller_repo.list_turns(
                db_session, pipeline_repo.conversation_of(db_session, run_id).id
            )
            if t.turn_index == turn
        )
        added = api_client.post(
            f"{BASE}/test-runs/{run_id}/turns/{turn}/reference",
            json={"text": text, "reviewer": "qa"},
        )
        assert added.status_code == 201, added.text

        second = api_client.post(f"{BASE}/test-runs/{run_id}/evaluations").json()
        assert second["metrics"]["wer"]["value"] == 0.0
        assert second["evidence_fingerprint"] != body["evidence_fingerprint"]

        listing = api_client.get(f"{BASE}/test-runs/{run_id}/evaluations").json()
        assert [e["evaluation_id"] for e in listing["evaluations"]] == [
            second["evaluation_id"],
            body["evaluation_id"],
        ]

    def test_a_correction_is_appended_and_the_history_kept(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        turn = _bot_turn_index(db_session, run_id)
        url = f"{BASE}/test-runs/{run_id}/turns/{turn}/reference"
        api_client.post(url, json={"text": "first draft"})
        api_client.post(url, json={"text": "corrected"})
        history = api_client.get(url).json()["references"]
        assert [r["text"] for r in history] == ["first draft", "corrected"]

    def test_a_caller_turn_cannot_have_a_reference(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        response = api_client.post(
            f"{BASE}/test-runs/{run_id}/turns/0/reference", json={"text": "x"}
        )
        assert response.status_code == 409
        assert "caller" in response.text

    @pytest.mark.parametrize("body", [{"text": ""}, {"text": "   "}, {"text": "x", "other": 1}])
    def test_a_blank_or_malformed_reference_is_422(
        self, api_client: TestClient, db_session: Session, tmp_path: Path, bot_url: str, body: dict
    ) -> None:
        run_id = _real_run(db_session, tmp_path, bot_url)
        turn = _bot_turn_index(db_session, run_id)
        response = api_client.post(f"{BASE}/test-runs/{run_id}/turns/{turn}/reference", json=body)
        assert response.status_code == 422

    def test_unknown_runs_and_turns_are_404(self, api_client: TestClient) -> None:
        missing = uuid.uuid4()
        assert api_client.post(f"{BASE}/test-runs/{missing}/evaluations").status_code == 404
        assert api_client.get(f"{BASE}/test-runs/{missing}/evaluations").status_code == 404
        assert (
            api_client.post(
                f"{BASE}/test-runs/{missing}/turns/1/reference", json={"text": "x"}
            ).status_code
            == 404
        )
