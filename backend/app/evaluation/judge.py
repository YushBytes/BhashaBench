"""A language-model judge: supplementary, versioned, and never the verdict.

Deterministic metrics decide a run's verdict (`evaluator.py`). A judge adds
what keyword rules cannot - "did the bot actually answer the question?" -
and is treated as an *opinion with evidence*: every criterion it scores must
cite the turns it rests on, and a citation of a turn that does not exist
invalidates the whole judgement rather than being quietly dropped.

It speaks to a model through the same vendor-neutral `LlmClient` the caller
uses, so it inherits every control that layer has: the code-level live gate
(`LIVE_CALLS_AUTHORISED`, which is False), worst-case costing of unknown
usage, and no retry inside a client. Retrying is here, bounded by
`max_attempts`, and every attempt is recorded.

**What the judge may see:** the conversation's turns, the scenario's
objective and its expected outcomes - judging against expected outcomes is
the point. **What it may not:** the deterministic verdict (so it cannot
anchor on it), known facts beyond what the turns contain, or anything from
the database row. `build_messages` takes a `JudgeInput` and nothing else,
which is the boundary that enforces this.

No judge is wired into the API: the only model client this project has is
Sarvam's, and live calls are not authorised. The interface is tested end to
end with the scripted client.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.caller.llm.errors import LlmError
from app.caller.llm.models import LlmMessage, LlmRequest, LlmRole
from app.caller.llm.protocol import LlmClient

JUDGE_PROMPT_VERSION = "bb-judge-prompt-1"
SCORES = ("pass", "fail", "uncertain")


@dataclass(frozen=True, slots=True)
class RubricCriterion:
    id: str
    question: str


@dataclass(frozen=True, slots=True)
class Rubric:
    """A versioned rubric. Two judgements are comparable only on the same version."""

    name: str
    version: str
    criteria: tuple[RubricCriterion, ...]

    def __post_init__(self) -> None:
        ids = [c.id for c in self.criteria]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("a rubric needs at least one criterion, with unique ids")


DEFAULT_RUBRIC = Rubric(
    name="task-conversation",
    version="1",
    criteria=(
        RubricCriterion("answered_objective", "Did the bot address the caller's objective?"),
        RubricCriterion(
            "factually_consistent", "Are the bot's statements consistent with each other?"
        ),
        RubricCriterion("appropriate_refusal", "If the bot refused, was the refusal appropriate?"),
    ),
)


@dataclass(frozen=True, slots=True)
class JudgeTurn:
    turn_index: int
    speaker: str
    text: str


@dataclass(frozen=True, slots=True)
class JudgeInput:
    """Everything the judge is allowed to read."""

    language: str
    objective: str
    expected_outcomes: tuple[str, ...]
    turns: tuple[JudgeTurn, ...]


@dataclass(frozen=True, slots=True)
class CriterionJudgement:
    criterion_id: str
    score: str
    evidence_turns: tuple[int, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class JudgeResult:
    status: str
    """`judged` or `failed`. A failed judgement carries no scores."""
    rubric: str
    rubric_version: str
    prompt_version: str
    model_requested: str | None
    model_reported: str | None
    attempts: int
    judgements: tuple[CriterionJudgement, ...] = ()
    failure: str | None = None
    attempt_log: tuple[dict[str, Any], ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["supplementary"] = True
        return out


def response_schema(rubric: Rubric) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["judgements"],
        "properties": {
            "judgements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion_id", "score", "evidence_turns", "explanation"],
                    "properties": {
                        "criterion_id": {"enum": [c.id for c in rubric.criteria]},
                        "score": {"enum": list(SCORES)},
                        "evidence_turns": {"type": "array", "items": {"type": "integer"}},
                        "explanation": {"type": "string", "maxLength": 600},
                    },
                },
            }
        },
    }


def build_messages(judge_input: JudgeInput, rubric: Rubric) -> tuple[LlmMessage, ...]:
    system = (
        "You are evaluating a conversation between a simulated caller and a customer-service "
        "bot. Score each rubric criterion as pass, fail or uncertain. For every criterion, cite "
        "the turn_index values your judgement rests on and explain briefly. Use 'uncertain' "
        "when the conversation does not show enough. Reply with JSON only."
    )
    transcript = "\n".join(f"[{t.turn_index}] {t.speaker}: {t.text}" for t in judge_input.turns)
    user = json.dumps(
        {
            "language": judge_input.language,
            "caller_objective": judge_input.objective,
            "expected_outcomes": list(judge_input.expected_outcomes),
            "rubric": [{"id": c.id, "question": c.question} for c in rubric.criteria],
            "transcript": transcript,
        },
        ensure_ascii=False,
    )
    return (LlmMessage(LlmRole.SYSTEM, system), LlmMessage(LlmRole.USER, user))


class JudgeOutputError(ValueError):
    """The model's reply does not satisfy the judge contract."""


def parse(text: str, rubric: Rubric, judge_input: JudgeInput) -> tuple[CriterionJudgement, ...]:
    """Validate strictly. Any defect rejects the whole reply."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JudgeOutputError("the reply is not JSON") from exc
    items = data.get("judgements") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise JudgeOutputError("the reply has no 'judgements' list")
    wanted = {c.id for c in rubric.criteria}
    known_turns = {t.turn_index for t in judge_input.turns}
    seen: dict[str, CriterionJudgement] = {}
    for item in items:
        if not isinstance(item, dict):
            raise JudgeOutputError("a judgement is not an object")
        cid, score = item.get("criterion_id"), item.get("score")
        turns, explanation = item.get("evidence_turns"), item.get("explanation")
        if cid not in wanted:
            raise JudgeOutputError(f"unknown criterion {cid!r}")
        if cid in seen:
            raise JudgeOutputError(f"criterion {cid!r} judged twice")
        if score not in SCORES:
            raise JudgeOutputError(f"score {score!r} is not one of {SCORES}")
        if not isinstance(turns, list) or not all(isinstance(i, int) for i in turns):
            raise JudgeOutputError("evidence_turns must be a list of integers")
        invented = sorted(set(turns) - known_turns)
        if invented:
            raise JudgeOutputError(f"cites turns that do not exist: {invented}")
        if score != "uncertain" and not turns:
            raise JudgeOutputError(f"criterion {cid!r} is scored {score} with no evidence cited")
        if not isinstance(explanation, str) or not explanation.strip():
            raise JudgeOutputError(f"criterion {cid!r} has no explanation")
        seen[cid] = CriterionJudgement(cid, score, tuple(turns), explanation.strip()[:600])
    missing = wanted - set(seen)
    if missing:
        raise JudgeOutputError(f"criteria not judged: {sorted(missing)}")
    return tuple(seen[c.id] for c in rubric.criteria)


async def judge(
    client: LlmClient,
    judge_input: JudgeInput,
    *,
    rubric: Rubric = DEFAULT_RUBRIC,
    max_attempts: int = 2,
    max_output_tokens: int = 800,
    seed: int | None = 7,
) -> JudgeResult:
    """Ask the model, validate, retry within bounds, and record every attempt."""
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    caps = client.capabilities
    request = LlmRequest(
        messages=build_messages(judge_input, rubric),
        max_output_tokens=max_output_tokens,
        temperature=0.0,
        seed=seed,
        response_schema=response_schema(rubric) if caps.supports_json_schema else None,
        schema_name="judge_result",
    )
    log: list[dict[str, Any]] = []
    model_reported = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.complete(request)
        except LlmError as exc:
            log.append({"attempt": attempt, "outcome": exc.code, "request_sent": exc.request_sent})
            if not exc.retryable:
                break
            continue
        model_reported = response.model_reported
        try:
            judgements = parse(response.text, rubric, judge_input)
        except JudgeOutputError as exc:
            log.append({"attempt": attempt, "outcome": "invalid_output", "detail": str(exc)})
            continue
        log.append({"attempt": attempt, "outcome": "judged"})
        return JudgeResult(
            status="judged",
            rubric=rubric.name,
            rubric_version=rubric.version,
            prompt_version=JUDGE_PROMPT_VERSION,
            model_requested=caps.model,
            model_reported=model_reported,
            attempts=attempt,
            judgements=judgements,
            attempt_log=tuple(log),
        )
    return JudgeResult(
        status="failed",
        rubric=rubric.name,
        rubric_version=rubric.version,
        prompt_version=JUDGE_PROMPT_VERSION,
        model_requested=caps.model,
        model_reported=model_reported,
        attempts=len(log),
        failure=log[-1]["outcome"] if log else "no attempt was made",
        attempt_log=tuple(log),
    )


__all__ = [
    "DEFAULT_RUBRIC",
    "JUDGE_PROMPT_VERSION",
    "CriterionJudgement",
    "JudgeInput",
    "JudgeOutputError",
    "JudgeResult",
    "JudgeTurn",
    "Rubric",
    "RubricCriterion",
    "build_messages",
    "judge",
    "parse",
    "response_schema",
]
