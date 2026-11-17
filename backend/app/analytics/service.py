"""Summaries, comparisons, regressions and trends over evaluated runs.

Every figure is computed from stored runs and their latest evaluations; none
is estimated. Four rules keep the numbers honest:

1. **A pass rate counts decided runs only.** `pass / (pass + fail)`;
   `undetermined` and never-evaluated runs are counted beside it, never in
   the denominator, because an outage is not a failure and an unscored run
   is not a pass.
2. **Every rate carries a Wilson 95% interval and its n.** "80%" from five
   runs and from five hundred are different claims.
3. **Mixed evaluator versions are flagged.** Scores under different
   versions are not comparable, and a summary that pooled them would say so.
4. **Significance needs evidence.** A regression is reported only when
   Fisher's exact test gives p < 0.05 *and* each group has at least
   `MIN_SAMPLE_PER_GROUP` decided runs; otherwise the result says the
   evidence is insufficient, whatever the point difference.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.analytics.stats import ALPHA, MIN_SAMPLE_PER_GROUP, fisher_exact, nearest_rank, wilson
from app.models.evaluation import Verdict
from app.repositories import analytics as repo
from app.repositories import evaluations as eval_repo
from app.repositories import pipeline_runs as pipeline_repo
from app.repositories.analytics import RunFilter
from app.services.errors import ConflictError, NotFoundError

NUMERIC_METRICS: dict[str, tuple[str, str]] = {
    # name -> (path inside metrics, direction)
    "wer": ("wer.value", "lower"),
    "cer": ("cer.value", "lower"),
    "bot_response_latency_p50_ms": ("bot_response_latency_ms.p50", "lower"),
    "bot_response_latency_p90_ms": ("bot_response_latency_ms.p90", "lower"),
    "expected_outcome_keyword_coverage": ("expected_outcome_keyword_coverage.value", "higher"),
    "transcription_failure_rate": ("transcription_failure_rate.value", "lower"),
}


def dig(document: dict[str, Any], path: str) -> float | None:
    value: Any = document
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _tally(rows: list[tuple[str | None, int]]) -> dict[str, Any]:
    counts = {v.value: 0 for v in Verdict} | {"not_evaluated": 0}
    for verdict, n in rows:
        counts[verdict or "not_evaluated"] += n
    decided = counts["pass"] + counts["fail"]
    return {
        "runs": sum(counts.values()),
        "verdicts": counts,
        "pass_rate": wilson(counts["pass"], decided).as_dict(),
    }


def _warnings(versions: list[str]) -> list[str]:
    if len(versions) > 1:
        return [
            f"evaluations under {len(versions)} evaluator versions ({', '.join(versions)}) are "
            "pooled here; scores under different versions are not comparable. Re-evaluate to "
            "bring them to one version."
        ]
    return []


def summary(session: Session, run_filter: RunFilter, *, group_by: str | None) -> dict[str, Any]:
    rows = repo.verdict_counts(session, run_filter, group_by=group_by)
    overall = _tally([(v, n) for _, v, n in rows])
    groups: dict[str | None, list[tuple[str | None, int]]] = {}
    for group, verdict, n in rows:
        groups.setdefault(group, []).append((verdict, n))
    metrics = _metric_summary(repo.metric_rows(session, run_filter))
    versions = repo.evaluator_versions(session, run_filter)
    return {
        "filter": run_filter.as_dict(),
        "group_by": group_by,
        "overall": overall,
        "groups": (
            [
                {"key": key, **_tally(values)}
                for key, values in sorted(groups.items(), key=lambda kv: str(kv[0]))
            ]
            if group_by
            else []
        ),
        "metrics": metrics,
        "evaluator_versions": versions,
        "warnings": _warnings(versions),
    }


def _metric_summary(rows: list[tuple[uuid.UUID, dict[str, Any]]]) -> dict[str, Any]:
    """Pooled error rates and the distribution of per-run latency."""
    errors = length = 0
    scored_runs = 0
    for _, metrics in rows:
        wer = metrics.get("wer") or {}
        if isinstance(wer.get("errors"), int) and isinstance(wer.get("reference_length"), int):
            errors += wer["errors"]
            length += wer["reference_length"]
            scored_runs += 1
    p50s = [v for _, m in rows if (v := dig(m, "bot_response_latency_ms.p50")) is not None]
    return {
        "wer_pooled": {
            "value": round(errors / length, 6) if length else None,
            "errors": errors,
            "reference_words": length,
            "runs_with_references": scored_runs,
        },
        "per_run_median_latency_ms": {
            "p50": nearest_rank(p50s, 50),
            "p90": nearest_rank(p50s, 90),
            "runs": len(p50s),
            "note": "the distribution of each run's own median, not a pooled latency",
        },
    }


def compare_runs(
    session: Session, baseline_id: uuid.UUID, candidate_id: uuid.UUID
) -> dict[str, Any]:
    """Two runs, side by side. Single runs support no statistical claim."""
    sides: dict[str, dict[str, Any]] = {}
    for label, run_id in (("baseline", baseline_id), ("candidate", candidate_id)):
        run = pipeline_repo.get_run(session, run_id)
        if run is None:
            raise NotFoundError("TestRun", run_id)
        evaluation = eval_repo.latest_evaluation(session, run_id)
        if evaluation is None:
            raise ConflictError(
                f"run {run_id} has not been evaluated; POST /api/v1/test-runs/{run_id}/evaluations "
                "first. Comparing an unevaluated run would invent its scores."
            )
        meta = pipeline_repo.pipeline_metadata_of(run)
        sides[label] = {
            "run_id": str(run_id),
            "scenario_name": meta.get("scenario_name"),
            "language": meta.get("language"),
            "mode": meta.get("mode"),
            "bot_adapter": meta.get("bot_adapter"),
            "evaluator_version": evaluation.evaluator_version,
            "evidence_fingerprint": evaluation.evidence_fingerprint,
            "verdict": evaluation.verdict.value,
            "metrics": evaluation.results.get("metrics", {}),
        }
    base, cand = sides["baseline"], sides["candidate"]
    warnings = [
        f"the runs differ in {key}: {base[key]!r} vs {cand[key]!r}"
        for key in ("scenario_name", "language", "mode", "evaluator_version")
        if base[key] != cand[key]
    ]
    deltas = []
    for name, (path, better) in NUMERIC_METRICS.items():
        b, c = dig(base["metrics"], path), dig(cand["metrics"], path)
        if b is None or c is None:
            deltas.append(
                {
                    "metric": name,
                    "baseline": b,
                    "candidate": c,
                    "delta": None,
                    "change": "not_comparable",
                }
            )
            continue
        delta = round(c - b, 6)
        worse = delta > 0 if better == "lower" else delta < 0
        change = "unchanged" if delta == 0 else ("worse" if worse else "better")
        deltas.append(
            {"metric": name, "baseline": b, "candidate": c, "delta": delta, "change": change}
        )
    order = {"pass": 2, "fail": 1, "undetermined": 0}
    if "undetermined" in (base["verdict"], cand["verdict"]):
        verdict_change = "not_comparable"
    elif order[cand["verdict"]] < order[base["verdict"]]:
        verdict_change = "regressed"
    elif order[cand["verdict"]] > order[base["verdict"]]:
        verdict_change = "improved"
    else:
        verdict_change = "unchanged"
    return {
        "baseline": {k: v for k, v in base.items() if k != "metrics"},
        "candidate": {k: v for k, v in cand.items() if k != "metrics"},
        "verdict_change": verdict_change,
        "metric_deltas": deltas,
        "comparable": not warnings,
        "warnings": warnings,
        "statistical_note": (
            "Two single runs. A difference here is an observation, not a significant result; "
            "compare groups of runs for that."
        ),
    }


def compare_groups(session: Session, baseline: RunFilter, candidate: RunFilter) -> dict[str, Any]:
    """Regression detection between two groups of runs, with an exact test."""
    groups = {}
    for label, run_filter in (("baseline", baseline), ("candidate", candidate)):
        tally = _tally([(v, n) for _, v, n in repo.verdict_counts(session, run_filter)])
        groups[label] = {"filter": run_filter.as_dict(), **tally}
    b, c = groups["baseline"]["verdicts"], groups["candidate"]["verdicts"]
    b_n, c_n = b["pass"] + b["fail"], c["pass"] + c["fail"]
    p_value = fisher_exact(b["pass"], b["fail"], c["pass"], c["fail"]) if b_n and c_n else None
    b_rate, c_rate = (
        groups["baseline"]["pass_rate"]["rate"],
        groups["candidate"]["pass_rate"]["rate"],
    )
    difference = None if b_rate is None or c_rate is None else round(c_rate - b_rate, 6)
    enough = b_n >= MIN_SAMPLE_PER_GROUP and c_n >= MIN_SAMPLE_PER_GROUP
    if p_value is None or difference is None:
        conclusion = "insufficient_evidence"
        reason = "a group has no decided runs (pass or fail)"
    elif not enough:
        conclusion = "insufficient_evidence"
        reason = (
            f"each group needs at least {MIN_SAMPLE_PER_GROUP} decided runs before a difference "
            f"is called significant (baseline {b_n}, candidate {c_n})"
        )
    elif p_value < ALPHA and difference < 0:
        conclusion, reason = "regression", f"pass rate fell by {-difference:.3f}, p = {p_value:.4f}"
    elif p_value < ALPHA and difference > 0:
        conclusion, reason = "improvement", f"pass rate rose by {difference:.3f}, p = {p_value:.4f}"
    else:
        conclusion = "no_significant_difference"
        reason = f"p = {p_value:.4f} is not below {ALPHA}"
    versions = sorted(
        set(repo.evaluator_versions(session, baseline))
        | set(repo.evaluator_versions(session, candidate))
    )
    return {
        "baseline": groups["baseline"],
        "candidate": groups["candidate"],
        "pass_rate_difference": difference,
        "test": "fisher_exact_two_sided",
        "p_value": None if p_value is None else round(p_value, 6),
        "alpha": ALPHA,
        "min_decided_runs_per_group": MIN_SAMPLE_PER_GROUP,
        "conclusion": conclusion,
        "reason": reason,
        "evaluator_versions": versions,
        "warnings": _warnings(versions),
    }


def trend(session: Session, run_filter: RunFilter, *, bucket: str) -> dict[str, Any]:
    periods: dict[str, list[tuple[str | None, int]]] = {}
    for period, verdict, n in repo.trend_counts(session, run_filter, bucket=bucket):
        periods.setdefault(period.isoformat(), []).append((verdict, n))
    versions = repo.evaluator_versions(session, run_filter)
    return {
        "filter": run_filter.as_dict(),
        "bucket": bucket,
        "periods": [{"period": key, **_tally(rows)} for key, rows in periods.items()],
        "evaluator_versions": versions,
        "warnings": _warnings(versions),
    }


__all__ = ["NUMERIC_METRICS", "compare_groups", "compare_runs", "dig", "summary", "trend"]
