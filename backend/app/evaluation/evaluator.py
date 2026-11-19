"""Evaluate a run from its stored evidence, and persist the result.

The evaluator reads only what the run recorded - its outcome, its turns and
their metadata, the scenario it ran, and any reviewed references - computes
every metric in the registry from that, and writes one append-only row. It
calls no provider and changes no evidence.

**Reproducible by construction.** The evidence is gathered into one canonical
document first, fingerprinted with SHA-256, and every metric is a pure
function of that document. Two evaluations with the same fingerprint and the
same `EVALUATOR_VERSION` produce identical results; a test asserts it.

**The verdict** is a conjunction of the criteria that apply:
`task_completion`, plus `required_phrases` and `forbidden_phrases` when the
scenario declares them. `pass` if every applicable criterion passes, `fail`
if any fails, `undetermined` when the run is unfinished or ended for a reason
that says nothing about the bot. Informational metrics (keyword coverage,
error rates, latency, transcription failures) never move the verdict.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.evaluation import scripts
from app.evaluation.metrics import character_error_rate, word_error_rate
from app.evaluation.registry import EVALUATOR_VERSION
from app.evaluation.text import normalise, words
from app.models.evaluation import RunEvaluation, Verdict
from app.pipeline.modes import (
    OUR_FAULT_OUTCOMES,
    TERMINAL_STATUSES,
    TEXT_MODES,
    ExecutionMode,
    RunOutcome,
)
from app.repositories import caller_conversations as caller_repo
from app.repositories import evaluations as eval_repo
from app.repositories import pipeline_runs as pipeline_repo
from app.services.errors import NotFoundError

PASS, FAIL, NOT_EVALUATED, UNDETERMINED = "pass", "fail", "not_evaluated", "undetermined"


def gather_evidence(session: Session, run_id: uuid.UUID) -> dict[str, Any]:
    """Everything an evaluation may read, as one canonical document.

    Raises:
        NotFoundError: no such run.
    """
    run = pipeline_repo.get_run(session, run_id)
    if run is None:
        raise NotFoundError("TestRun", run_id)
    meta = pipeline_repo.pipeline_metadata_of(run)
    conversation = pipeline_repo.conversation_of(session, run_id)
    turns = caller_repo.list_turns(session, conversation.id) if conversation is not None else []
    spec: dict[str, Any] = {}
    if conversation is not None:
        scenario = caller_repo.get_scenario(session, conversation.scenario_id)
        spec = dict(scenario.spec) if scenario is not None else {}
    bot_turns = [t for t in turns if t.speaker.value == "bot"]
    references = eval_repo.latest_references(session, [t.id for t in bot_turns])
    constraints = spec.get("constraints") or {}
    return {
        "run_id": str(run.id),
        "mode": meta.get("mode"),
        "status": meta.get("status"),
        "outcome": meta.get("outcome"),
        "language": meta.get("language") or spec.get("language"),
        "expected_outcomes": list(spec.get("expected_outcomes") or []),
        "required_phrases": list(constraints.get("required_phrases") or []),
        "forbidden_phrases": list(constraints.get("forbidden_phrases") or []),
        "caller_turns": sum(1 for t in turns if t.speaker.value == "caller"),
        "caller_texts": [t.content or "" for t in turns if t.speaker.value == "caller"],
        "bot_turns": [
            {
                "turn_index": t.turn_index,
                "text": t.content,
                "latency_ms": (t.turn_metadata or {}).get("latency_ms"),
                "transcription_failed": bool((t.turn_metadata or {}).get("transcription_error")),
                "reference": references[t.id].text if t.id in references else None,
            }
            for t in bot_turns
        ],
    }


def fingerprint(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _nearest_rank(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile: the smallest value with at least p% at or below it."""
    ordered = sorted(values)
    rank = max(math.ceil(percentile / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def _bot_text(evidence: dict[str, Any]) -> list[str]:
    return [t["text"] for t in evidence["bot_turns"] if t["text"]]


@dataclass(frozen=True, slots=True)
class Evaluated:
    verdict: Verdict
    results: dict[str, Any]
    fingerprint: str


def evaluate_evidence(evidence: dict[str, Any]) -> Evaluated:
    """A pure function of the evidence document."""
    language = evidence.get("language")
    status = evidence.get("status")
    outcome = evidence.get("outcome")
    texts = _bot_text(evidence)
    joined = normalise(" ".join(texts), language=language)
    metrics: dict[str, Any] = {}
    criteria: list[dict[str, Any]] = []

    # -- Task completion ---------------------------------------------------
    finished = status in {s.value for s in TERMINAL_STATUSES}
    excused = {o.value for o in OUR_FAULT_OUTCOMES} | {RunOutcome.CANCELLED.value}
    if not finished or outcome is None:
        task = {"value": None, "status": UNDETERMINED, "reason": "the run has not finished"}
    elif outcome in excused:
        task = {
            "value": None,
            "status": UNDETERMINED,
            "reason": f"the run ended with '{outcome}', which says nothing about the bot",
        }
    elif outcome == RunOutcome.GOAL_ACHIEVED.value:
        task = {"value": 1, "status": PASS, "reason": "the caller achieved its objective"}
    else:
        task = {
            "value": 0,
            "status": FAIL,
            "reason": f"the run ended with '{outcome}' before the objective was achieved",
        }
    metrics["task_completion"] = task
    criteria.append({"name": "task_completion", "status": task["status"], "reason": task["reason"]})

    # -- Required and forbidden phrases -------------------------------------
    required = evidence["required_phrases"]
    if required:
        missing = [p for p in required if normalise(p, language=language) not in joined]
        status_r = FAIL if missing else PASS
        reason = (
            f"missing from every bot turn: {missing}"
            if missing
            else "every required phrase appeared"
        )
        metrics["required_phrases"] = {"status": status_r, "missing": missing}
    else:
        status_r, reason = NOT_EVALUATED, "the scenario declares no required phrases"
        metrics["required_phrases"] = {"status": status_r}
    criteria.append({"name": "required_phrases", "status": status_r, "reason": reason})

    forbidden = evidence["forbidden_phrases"]
    if forbidden:
        found = [p for p in forbidden if normalise(p, language=language) in joined]
        status_f = FAIL if found else PASS
        reason = f"spoken by the bot: {found}" if found else "no forbidden phrase appeared"
        metrics["forbidden_phrases"] = {"status": status_f, "found": found}
    else:
        status_f, reason = NOT_EVALUATED, "the scenario declares no forbidden phrases"
        metrics["forbidden_phrases"] = {"status": status_f}
    criteria.append({"name": "forbidden_phrases", "status": status_f, "reason": reason})

    # -- Keyword coverage (informational) -----------------------------------
    expected = evidence["expected_outcomes"]
    if expected:
        tokens = set(joined.split())
        per = []
        for item in expected:
            content = [w for w in words(item, language=language) if len(w) >= 3]
            per.append({"outcome": item, "covered": bool(content) and set(content) <= tokens})
        covered = sum(1 for p in per if p["covered"])
        metrics["expected_outcome_keyword_coverage"] = {
            "value": round(covered / len(expected), 6),
            "covered": covered,
            "declared": len(expected),
            "per_outcome": per,
        }
    else:
        metrics["expected_outcome_keyword_coverage"] = {"value": None, "status": NOT_EVALUATED}

    # -- Error rates against reviewed references -----------------------------
    scored = [
        t
        for t in evidence["bot_turns"]
        if t["reference"] is not None and not t["transcription_failed"] and t["text"] is not None
    ]
    excluded = sum(
        1 for t in evidence["bot_turns"] if t["reference"] is not None and t not in scored
    )
    for name, function in (("wer", word_error_rate), ("cer", character_error_rate)):
        if not scored:
            metrics[name] = {
                "value": None,
                "scored_turns": 0,
                "reason": "no bot turn has a reviewed reference transcript",
            }
            continue
        per_turn = [
            {
                "turn_index": t["turn_index"],
                **function(t["reference"], t["text"], language=language).as_dict(),
            }
            for t in scored
        ]
        errors = sum(p["substitutions"] + p["deletions"] + p["insertions"] for p in per_turn)
        length = sum(p["reference_length"] for p in per_turn)
        metrics[name] = {
            "value": round(errors / length, 6) if length else None,
            "errors": errors,
            "reference_length": length,
            "scored_turns": len(scored),
            "excluded_turns": excluded,
            "per_turn": per_turn,
        }

    # -- Script switching (observable code-mixing) ----------------------------
    # Script, not language: see app/evaluation/scripts.py for what that misses.
    metrics["script_mixing"] = {
        "caller": scripts.summary(list(evidence.get("caller_texts") or [])),
        "bot": scripts.summary([t["text"] for t in evidence["bot_turns"] if t["text"]]),
        "measures": "script switching, not language switching",
    }

    # -- Error rates split by script --------------------------------------
    # WER over only the reference words written in one script, against only
    # the hypothesis words in that script: where code-mixed speech was lost,
    # this says in which language's words.
    if scored:
        by_script: dict[str, dict[str, Any]] = {}
        for t in scored:
            present = {s.script for s in scripts.segments(t["reference"])}
            for code in sorted(present):
                ref = scripts.words_in_script(t["reference"], code)
                hyp = scripts.words_in_script(t["text"], code)
                rate = word_error_rate(ref, hyp, language=language).as_dict()
                entry = by_script.setdefault(code, {"errors": 0, "reference_length": 0})
                entry["errors"] += rate["substitutions"] + rate["deletions"] + rate["insertions"]
                entry["reference_length"] += rate["reference_length"]
        metrics["wer_by_script"] = {
            "value": {
                code: {
                    "value": round(e["errors"] / e["reference_length"], 6)
                    if e["reference_length"]
                    else None,
                    **e,
                }
                for code, e in by_script.items()
            },
            "scored_turns": len(scored),
        }
    else:
        metrics["wer_by_script"] = {
            "value": None,
            "scored_turns": 0,
            "reason": "no bot turn has a reviewed reference transcript",
        }

    # -- Latency ------------------------------------------------------------
    latencies = [
        float(t["latency_ms"])
        for t in evidence["bot_turns"]
        if isinstance(t["latency_ms"], int | float)
    ]
    if latencies:
        metrics["bot_response_latency_ms"] = {
            "p50": _nearest_rank(latencies, 50),
            "p90": _nearest_rank(latencies, 90),
            "max": max(latencies),
            "samples": len(latencies),
            "method": "nearest-rank",
        }
    else:
        metrics["bot_response_latency_ms"] = {
            "value": None,
            "samples": 0,
            "reason": "no bot turn carries a measured latency",
        }

    # -- Transcription failures (ours) --------------------------------------
    mode = evidence.get("mode")
    if mode in {m.value for m in TEXT_MODES} or not evidence["bot_turns"]:
        metrics["transcription_failure_rate"] = {
            "value": None,
            "status": NOT_EVALUATED,
            "reason": "no bot audio was transcribed in this run",
        }
    else:
        failed = sum(1 for t in evidence["bot_turns"] if t["transcription_failed"])
        metrics["transcription_failure_rate"] = {
            "value": round(failed / len(evidence["bot_turns"]), 6),
            "failed": failed,
            "bot_turns": len(evidence["bot_turns"]),
        }

    # -- Verdict -----------------------------------------------------------
    statuses = [c["status"] for c in criteria]
    if task["status"] == UNDETERMINED:
        verdict = Verdict.UNDETERMINED
    elif FAIL in statuses:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.PASS

    results = {
        "evaluator_version": EVALUATOR_VERSION,
        "mode": mode,
        "measures_audio": mode not in {m.value for m in TEXT_MODES}
        and mode != ExecutionMode.OFFLINE_SIMULATION.value,
        "verdict": verdict.value,
        "criteria": criteria,
        "metrics": metrics,
    }
    return Evaluated(verdict=verdict, results=results, fingerprint=fingerprint(evidence))


def evaluate_run(session: Session, run_id: uuid.UUID) -> RunEvaluation:
    """Evaluate and persist. The caller owns the transaction."""
    evidence = gather_evidence(session, run_id)
    evaluated = evaluate_evidence(evidence)
    return eval_repo.add_evaluation(
        session,
        test_run_id=run_id,
        evaluator_version=EVALUATOR_VERSION,
        verdict=evaluated.verdict,
        evidence_fingerprint=evaluated.fingerprint,
        results=evaluated.results,
    )


__all__ = ["Evaluated", "evaluate_evidence", "evaluate_run", "fingerprint", "gather_evidence"]
