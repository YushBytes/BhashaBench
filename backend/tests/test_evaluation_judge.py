"""The LLM judge contract, driven by the scripted client. No request leaves the process."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from typing import Any

import pytest

from app.caller.llm.errors import (
    LiveCallsDisabledError,
    LlmAuthenticationError,
    LlmTimeoutError,
)
from app.caller.llm.fake import Fail, Reply, ScriptedLlmClient
from app.evaluation.judge import (
    DEFAULT_RUBRIC,
    JudgeInput,
    JudgeOutputError,
    JudgeTurn,
    build_messages,
    judge,
    parse,
)

INPUT = JudgeInput(
    language="en-IN",
    objective="Find out the status of my service request.",
    expected_outcomes=("Bot confirms the request",),
    turns=(
        JudgeTurn(0, "caller", "Hello, I am calling about my request."),
        JudgeTurn(1, "bot", "Could you tell me your reference number?"),
        JudgeTurn(2, "caller", "It is 447219."),
        JudgeTurn(3, "bot", "Your request 447219 is confirmed."),
    ),
)


def _reply(**overrides: Any) -> str:
    items = [
        {"criterion_id": c.id, "score": "pass", "evidence_turns": [3], "explanation": "ok"}
        for c in DEFAULT_RUBRIC.criteria
    ]
    for item in items:
        item.update(overrides.get(item["criterion_id"], {}))
    return json.dumps({"judgements": items})


def _run(script: list[Any], **kwargs: Any) -> Any:
    client = ScriptedLlmClient(script)
    return asyncio.run(judge(client, INPUT, **kwargs)), client


class TestParsing:
    def test_a_valid_reply_parses_in_rubric_order(self) -> None:
        judgements = parse(_reply(), DEFAULT_RUBRIC, INPUT)
        assert [j.criterion_id for j in judgements] == [c.id for c in DEFAULT_RUBRIC.criteria]

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("not json", "not JSON"),
            ("{}", "no 'judgements'"),
            (_reply(answered_objective={"evidence_turns": [99]}), "do not exist"),
            (_reply(answered_objective={"score": "great"}), "is not one of"),
            (_reply(answered_objective={"evidence_turns": []}), "no evidence cited"),
            (_reply(answered_objective={"explanation": " "}), "no explanation"),
            (
                json.dumps({"judgements": json.loads(_reply())["judgements"][:1]}),
                "not judged",
            ),
        ],
    )
    def test_any_defect_rejects_the_whole_reply(self, text: str, message: str) -> None:
        with pytest.raises(JudgeOutputError, match=message):
            parse(text, DEFAULT_RUBRIC, INPUT)

    def test_uncertain_may_cite_nothing(self) -> None:
        text = _reply(appropriate_refusal={"score": "uncertain", "evidence_turns": []})
        judgements = parse(text, DEFAULT_RUBRIC, INPUT)
        assert judgements[2].score == "uncertain"


class TestJudging:
    def test_a_judgement_records_its_versions_and_is_supplementary(self) -> None:
        result, client = _run([Reply(_reply())])
        assert result.status == "judged"
        out = result.as_dict()
        assert out["supplementary"] is True
        assert (out["rubric_version"], out["prompt_version"]) == ("1", "bb-judge-prompt-1")
        assert client.requests[0].temperature == 0.0
        assert client.requests[0].response_schema is not None

    def test_invalid_output_is_retried_within_bounds_then_fails(self) -> None:
        bad = _reply(answered_objective={"evidence_turns": [42]})
        result, client = _run([Reply(bad), Reply(bad)], max_attempts=2)
        assert result.status == "failed"
        assert result.judgements == ()
        assert [a["outcome"] for a in result.attempt_log] == ["invalid_output", "invalid_output"]
        assert len(client.requests) == 2

    def test_a_retryable_failure_then_success(self) -> None:
        result, _ = _run([Fail(LlmTimeoutError("slow", provider="x")), Reply(_reply())])
        assert (result.status, result.attempts) == ("judged", 2)

    def test_a_non_retryable_failure_stops_immediately(self) -> None:
        result, client = _run(
            [Fail(LlmAuthenticationError("no", provider="x")), Reply(_reply())], max_attempts=3
        )
        assert result.status == "failed"
        assert len(client.requests) == 1

    def test_the_live_gate_is_recorded_as_no_request_sent(self) -> None:
        result, _ = _run([Fail(LiveCallsDisabledError("live calls are off", provider="sarvam"))])
        assert result.status == "failed"
        assert result.attempt_log[0]["request_sent"] is False

    def test_attempts_are_capped(self) -> None:
        with pytest.raises(ValueError, match="between 1 and 3"):
            _run([], max_attempts=10)


class TestInformationBoundary:
    def test_the_judge_input_has_no_verdict_or_facts_fields(self) -> None:
        fields = {f.name for f in dataclasses.fields(JudgeInput)}
        assert fields == {"language", "objective", "expected_outcomes", "turns"}

    def test_the_prompt_carries_the_transcript_and_the_rubric(self) -> None:
        user = build_messages(INPUT, DEFAULT_RUBRIC)[1].content
        payload = json.loads(user)
        assert "[3] bot: Your request 447219 is confirmed." in payload["transcript"]
        assert [r["id"] for r in payload["rubric"]] == [c.id for c in DEFAULT_RUBRIC.criteria]
        assert "verdict" not in user
