"""Reporting and analytics endpoints (Phase 12).

Read-only. Every figure is computed from stored runs and their latest
evaluations; see `app/analytics/service.py` for the rules that keep the
numbers honest, and `docs/REPORTING.md` for the contract.

No `from __future__ import annotations` here, deliberately: the filter
dependency builds its query aliases from a closure variable, and postponed
annotations would turn those `Annotated[..., Query(alias=f"...")]` hints into
strings FastAPI cannot resolve.
"""

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from app.analytics import service
from app.analytics.export import RUN_COLUMNS, TURN_COLUMNS, to_csv
from app.analytics.service import NUMERIC_METRICS, dig
from app.api.access import RunAccess
from app.api.deps import CurrentPrincipal, DbSession
from app.auth.permissions import Permission
from app.evaluation.registry import EVALUATOR_VERSION
from app.models.identity import Project
from app.models.suite import TestSuite
from app.repositories import analytics as repo
from app.repositories import caller_conversations as caller_repo
from app.repositories import evaluations as eval_repo
from app.repositories import pipeline_runs as pipeline_repo
from app.repositories.analytics import DIMENSIONS, RunFilter
from app.schemas.common import ErrorResponse
from app.services import access_service
from app.services.errors import NotFoundError
from app.utils.timing import utc_now

router = APIRouter(prefix="/analytics", tags=["analytics"])
run_router = APIRouter(prefix="/test-runs", tags=["analytics"])

MAX_EXPORT_ROWS = 10_000
Dimension = Literal["language", "scenario_name", "bot_adapter", "mode", "outcome", "suite_id"]


def _filter(
    prefix: str = "",
) -> Any:
    """A dependency building a `RunFilter` from query parameters with `prefix`."""

    def build(
        session: DbSession,
        principal: CurrentPrincipal,
        suite_id: Annotated[uuid.UUID | None, Query(alias=f"{prefix}suite_id")] = None,
        mode: Annotated[str | None, Query(alias=f"{prefix}mode", max_length=40)] = None,
        language: Annotated[str | None, Query(alias=f"{prefix}language", max_length=35)] = None,
        scenario_name: Annotated[
            str | None, Query(alias=f"{prefix}scenario_name", max_length=200)
        ] = None,
        bot_adapter: Annotated[
            str | None, Query(alias=f"{prefix}bot_adapter", max_length=40)
        ] = None,
        created_after: Annotated[datetime | None, Query(alias=f"{prefix}created_after")] = None,
        created_before: Annotated[datetime | None, Query(alias=f"{prefix}created_before")] = None,
    ) -> RunFilter:
        if suite_id is not None:
            access_service.require_suite(session, principal, suite_id, Permission.VIEW)
        return RunFilter(
            project_ids=access_service.visible_project_ids(session, principal),
            suite_id=suite_id,
            mode=mode,
            language=language,
            scenario_name=scenario_name,
            bot_adapter=bot_adapter,
            created_after=created_after,
            created_before=created_before,
        )

    return build


Filter = Annotated[RunFilter, Depends(_filter())]
BaselineFilter = Annotated[RunFilter, Depends(_filter("baseline_"))]
CandidateFilter = Annotated[RunFilter, Depends(_filter("candidate_"))]


@router.get(
    "/summary",
    summary="Verdict counts and pass rates, optionally grouped",
    description=(
        "Each run contributes its latest evaluation. The pass rate is pass / (pass + fail) "
        "with a Wilson 95% interval; undetermined and never-evaluated runs are counted "
        "beside it, never in it. `group_by` is one of: " + ", ".join(DIMENSIONS) + "."
    ),
)
def summary(
    session: DbSession, run_filter: Filter, group_by: Dimension | None = None
) -> dict[str, Any]:
    return service.summary(session, run_filter, group_by=group_by)


@router.get(
    "/compare",
    summary="Compare two runs",
    description=(
        "Verdict change and per-metric deltas between two evaluated runs, with warnings "
        "when they differ in scenario, language, mode or evaluator version. Two single "
        "runs support no statistical claim; use /regressions for groups."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Not evaluated."},
    },
)
def compare(
    session: DbSession, principal: CurrentPrincipal, baseline: uuid.UUID, candidate: uuid.UUID
) -> dict[str, Any]:
    for run_id in (baseline, candidate):
        access_service.require_run(session, principal, run_id, Permission.VIEW)
    return service.compare_runs(session, baseline, candidate)


@router.get(
    "/regressions",
    summary="Detect a pass-rate regression between two groups of runs",
    description=(
        "Groups are chosen with `baseline_*` and `candidate_*` filters (suite_id, mode, "
        "language, scenario_name, bot_adapter, created_after, created_before). Fisher's exact "
        "test, two-sided; a regression is reported only when p < 0.05 and each group has at "
        "least five decided runs. Otherwise the conclusion is insufficient_evidence or "
        "no_significant_difference."
    ),
)
def regressions(
    session: DbSession, baseline: BaselineFilter, candidate: CandidateFilter
) -> dict[str, Any]:
    return service.compare_groups(session, baseline, candidate)


@router.get("/trend", summary="Pass rate per day or week")
def trend(
    session: DbSession, run_filter: Filter, bucket: Literal["day", "week"] = "day"
) -> dict[str, Any]:
    return service.trend(session, run_filter, bucket=bucket)


@router.get(
    "/runs.csv",
    summary="Export runs with their latest verdict as CSV",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_runs(
    session: DbSession,
    run_filter: Filter,
    limit: Annotated[int, Query(ge=1, le=MAX_EXPORT_ROWS)] = 1000,
) -> Response:
    rows = []
    for run, verdict, metrics in repo.runs_with_latest(session, run_filter, limit=limit):
        meta = pipeline_repo.pipeline_metadata_of(run)
        metrics = metrics or {}
        rows.append(
            (
                run.id,
                run.created_at.isoformat(),
                run.suite_id,
                meta.get("scenario_name"),
                meta.get("language"),
                meta.get("mode"),
                meta.get("bot_adapter"),
                meta.get("status"),
                meta.get("outcome"),
                verdict or "not_evaluated",
                dig(metrics, NUMERIC_METRICS["wer"][0]),
                dig(metrics, NUMERIC_METRICS["cer"][0]),
                dig(metrics, NUMERIC_METRICS["bot_response_latency_p50_ms"][0]),
                meta.get("uses_language_model", False),
            )
        )
    return Response(
        to_csv(RUN_COLUMNS, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bhashabench-runs.csv"'},
    )


@run_router.get(
    "/{run_id}/export",
    summary="Export one run's evidence and latest evaluation",
    description=(
        "`format=json` (default): the run's stored metadata, every turn, and the latest "
        "evaluation with its fingerprint. `format=csv`: one row per turn, cells neutralised "
        "against spreadsheet formula injection."
    ),
    response_class=Response,
    responses={
        200: {"content": {"application/json": {}, "text/csv": {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    },
    dependencies=[RunAccess.VIEW],
)
def export_run(
    run_id: uuid.UUID, session: DbSession, format: Literal["json", "csv"] = "json"
) -> Response:
    run = pipeline_repo.get_run(session, run_id)
    if run is None:
        raise NotFoundError("TestRun", run_id)
    meta = pipeline_repo.pipeline_metadata_of(run)
    conversation = pipeline_repo.conversation_of(session, run_id)
    turns = caller_repo.list_turns(session, conversation.id) if conversation is not None else []
    references = eval_repo.latest_references(session, [t.id for t in turns])
    evaluation = eval_repo.latest_evaluation(session, run_id)
    suite = session.get(TestSuite, run.suite_id)
    project = None if suite is None else session.get(Project, suite.project_id)
    filename = f"bhashabench-run-{run_id}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "csv":
        rows = [
            (
                t.turn_index,
                t.speaker.value,
                t.content,
                (t.turn_metadata or {}).get("source"),
                (t.turn_metadata or {}).get("latency_ms"),
                (t.turn_metadata or {}).get("transcription_error"),
                references[t.id].text if t.id in references else None,
            )
            for t in turns
        ]
        return Response(
            to_csv(TURN_COLUMNS, rows), media_type="text/csv; charset=utf-8", headers=headers
        )
    document = {
        "export": {
            "format": "bhashabench.run-export/v1",
            "exported_at": utc_now().isoformat(),
            "current_evaluator_version": EVALUATOR_VERSION,
        },
        # Where the run belongs, by name as well as id, so a report read
        # outside the workspace still says which project and suite it is.
        "project": None if project is None else {"id": str(project.id), "name": project.name},
        "suite": None if suite is None else {"id": str(suite.id), "name": suite.name},
        "run": {
            "run_id": str(run.id),
            "suite_id": str(run.suite_id),
            "created_at": run.created_at.isoformat(),
            "started_at": None if run.started_at is None else run.started_at.isoformat(),
            "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
            "error": run.error_message,
            "pipeline": meta,
        },
        "turns": [
            {
                "turn_index": t.turn_index,
                "speaker": t.speaker.value,
                "text": t.content,
                "metadata": t.turn_metadata or {},
                "reference": references[t.id].text if t.id in references else None,
            }
            for t in turns
        ],
        "evaluation": None
        if evaluation is None
        else {
            "evaluation_id": str(evaluation.id),
            "evaluator_version": evaluation.evaluator_version,
            "verdict": evaluation.verdict.value,
            "evidence_fingerprint": evaluation.evidence_fingerprint,
            "created_at": evaluation.created_at.isoformat(),
            "results": evaluation.results,
        },
    }
    return Response(
        json.dumps(document, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers=headers,
    )


__all__ = ["router", "run_router"]
