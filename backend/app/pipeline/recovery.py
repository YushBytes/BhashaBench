"""Find and close runs nothing will ever finish.

A run advances only inside a request (`/start`, `/bot-audio`, `/bot-text`).
If that request dies - a killed process, a crash, a pre-Phase-0
`offline_simulation` that had no reply source - the run stays `running` with
no worker coming back for it. Nothing sweeps such runs automatically, by
design: deciding that a run is dead rather than slow is a judgement, and this
module makes it explicit, dry-run first, never on a timer.

**What counts as abandoned.** A pipeline run whose recorded status is
`running` or `initializing`, that is **not** waiting for an operator (no
`awaiting_bot_audio_for_turn` or `awaiting_bot_text_for_turn` - a waiting run
is healthy however long it waits), and whose row has not changed for longer
than the threshold. The threshold may not be shorter than
`PIPELINE_RUN_TIMEOUT_SECONDS`: no request can still be executing a run past
its own wall-clock ceiling, so anything quieter than that is not in flight.

**What recovery changes.** The run is finished as `failed` with outcome
`abandoned` and an error naming when it was last active; a `recovery` stage
event and a `recovered` record are appended to its metadata; a conversation
still open is closed as operator-terminated. Turns, events and artefacts are
never deleted or rewritten, and `started_at` is kept, so the evidence of what
the run did before it stopped survives intact. `finished_at` is the moment of
recovery, and the metadata says so.

**No new database status.** The run's database status becomes `failed` - one
of the five values the `test_runs` check constraint already allows.
`abandoned` is the pipeline *outcome* recorded in the run's metadata, not a
status, so recovery needs no migration.

**Two runs are never touched.** `PROTECTED_RUN_IDS` names the two historical
runs kept as evidence of the pre-Phase-0 offline defect. They meet every
abandonment criterion, which is exactly why they are excluded by identity:
`find_stale_runs` never returns them and `abandon` refuses them, with or
without `--apply`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.caller.schemas import TerminationReason
from app.caller.state import CallerState
from app.caller.state import is_terminal as caller_state_is_terminal
from app.models.call_session import CallStatus
from app.models.test_run import RunStatus, TestRun
from app.pipeline.modes import PipelineStatus, RunOutcome
from app.repositories import caller_conversations as caller_repo
from app.repositories import pipeline_runs as repo

_IN_FLIGHT = frozenset({PipelineStatus.RUNNING.value, PipelineStatus.INITIALIZING.value})

PROTECTED_RUN_IDS: frozenset[uuid.UUID] = frozenset(
    {
        uuid.UUID("e5160aa5-d690-4eca-aaf7-e75612af03ea"),
        uuid.UUID("285e4fe9-f464-4e1c-bb7f-8eb2f7b4cd88"),
    }
)
"""Historical runs recovery must never select or update.

Both are `offline_simulation` runs left `running` by the defect Phase 0 fixed
(docs/COMPETITION_READINESS_REPORT.md, section 6.5), and they are preserved
exactly as stored as the record of it. Full ids, matched exactly: a prefix
match could one day catch an unrelated run. There is deliberately no flag to
override this - closing either is a code change, reviewed as one.
"""


class ProtectedRunError(RuntimeError):
    """Recovery was asked to close a run in `PROTECTED_RUN_IDS`."""


@dataclass(frozen=True, slots=True)
class StaleRun:
    """A run recovery would close, and the facts that made it eligible."""

    run: TestRun
    scenario_name: str
    mode: str
    pipeline_status: str
    last_activity_at: datetime
    idle: timedelta


def find_stale_runs(session: Session, *, older_than: timedelta, now: datetime) -> list[StaleRun]:
    """Every run that meets the abandonment criteria, oldest activity first.

    Reads only. Never mutates a row. A run in `PROTECTED_RUN_IDS` is never
    returned, whatever its state.
    """
    found: list[StaleRun] = []
    for run in repo.runs_in_status(session, RunStatus.RUNNING):
        if run.id in PROTECTED_RUN_IDS:
            continue
        meta = repo.pipeline_metadata_of(run)
        if not meta:
            continue  # a caller-only conversation, not a pipeline run
        if meta.get("status") not in _IN_FLIGHT:
            continue
        if meta.get("awaiting_bot_audio_for_turn") is not None:
            continue
        if meta.get("awaiting_bot_text_for_turn") is not None:
            continue
        last = run.updated_at
        idle = now - last
        if idle < older_than:
            continue
        found.append(
            StaleRun(
                run=run,
                scenario_name=str(meta.get("scenario_name", "")),
                mode=str(meta.get("mode", "")),
                pipeline_status=str(meta.get("status")),
                last_activity_at=last,
                idle=idle,
            )
        )
    return sorted(found, key=lambda stale: stale.last_activity_at)


def abandon(session: Session, stale: StaleRun, *, now: datetime) -> None:
    """Finish one stale run: database status `failed`, outcome `abandoned`.

    The caller owns the transaction. Refuses a protected run before touching
    anything, so a caller that built its own `StaleRun` cannot bypass the
    exclusion in `find_stale_runs`.
    """
    run = stale.run
    if run.id in PROTECTED_RUN_IDS:
        raise ProtectedRunError(
            f"run {run.id} is a protected historical run and is never modified by recovery"
        )
    meta: dict[str, Any] = dict(repo.pipeline_metadata_of(run))
    events: list[dict[str, Any]] = list(meta.get("events", []))
    last_turn = max((int(event.get("turn_index", 0)) for event in events), default=0)
    when = stale.last_activity_at.isoformat()
    detail = (
        f"abandoned: no activity since {when}; closed by "
        f"'bhashabench runs recover-stale --apply' at {now.isoformat()}"
    )
    events.append(
        {
            "turn_index": last_turn,
            "stage": "recovery",
            "status": "ok",
            "duration_ms": None,
            "detail": detail,
        }
    )
    meta["events"] = events
    meta["recovered"] = {
        "at": now.isoformat(),
        "last_activity_at": when,
        "idle_seconds": round(stale.idle.total_seconds(), 1),
        "previous_status": stale.pipeline_status,
        "by": "bhashabench runs recover-stale",
        "finished_at_is_recovery_time": True,
    }
    meta["status"] = PipelineStatus.FAILED.value
    meta["outcome"] = RunOutcome.ABANDONED.value

    conversation = repo.conversation_of(session, run.id)
    if conversation is not None:
        caller_meta = dict(caller_repo.caller_metadata_of(conversation))
        state = CallerState(caller_meta.get("state", CallerState.INITIAL.value))
        if not caller_state_is_terminal(state):
            caller_meta.update(
                {
                    "state": CallerState.TERMINATED.value,
                    "termination_reason": TerminationReason.OPERATOR_TERMINATED.value,
                }
            )
            caller_repo.finish_conversation(
                session, conversation, status=CallStatus.FAILED, caller_metadata=caller_meta
            )

    repo.finish_run(
        session,
        run,
        status=RunStatus.FAILED,
        metadata=meta,
        error_message=f"abandoned: no activity since {when}",
    )


__all__ = ["PROTECTED_RUN_IDS", "ProtectedRunError", "StaleRun", "abandon", "find_stale_runs"]
