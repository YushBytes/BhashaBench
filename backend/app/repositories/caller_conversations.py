"""Every SQL statement the caller subsystem issues.

Here rather than in `app/caller/` because CLAUDE.md's layering rule is explicit
that repositories hold all SQL, and because the orchestrator should be testable
against a session without also being the thing that knows the schema.

**No new tables.** Phase 2 created `TestRun -> CallSession -> ConversationTurn`
as foundational schema, and this is what it was foundational *for*. One caller
conversation is a `CallSession`; each utterance is a `ConversationTurn`, whose
docstring already says "Per-turn detail later phases attach". The caller's own
state goes in the existing JSONB columns rather than in new ones:
`call_metadata` for conversation state, `turn_metadata` for the decision and
the audio reference. So Phase 6 adds no migration, and nothing about Phases
1-5 moves.

Functions here never commit. The service owns the transaction boundary, as in
every other repository in this project.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.call_session import CallSession, CallStatus
from app.models.conversation_turn import ConversationTurn, Speaker
from app.models.scenario import Scenario
from app.models.test_run import RunStatus, TestRun
from app.utils.timing import utc_now

# The `call_metadata` key under which the caller keeps its own state. Namespaced
# so Phase 9's telephony metadata can share the column without collision.
CALLER_NAMESPACE = "caller"


def create_run(session: Session, *, suite_id: uuid.UUID, metadata: dict[str, Any]) -> TestRun:
    """Open a `TestRun` to own one or more caller conversations.

    A conversation needs a run because `CallSession.test_run_id` is NOT NULL -
    the schema's view is that calls happen inside runs, and honouring that is
    cheaper and more honest than relaxing the constraint. A single-conversation
    run is a legitimate run of one.
    """
    run = TestRun(
        suite_id=suite_id,
        status=RunStatus.RUNNING,
        started_at=utc_now(),
        run_metadata=metadata,
    )
    session.add(run)
    session.flush()
    return run


def finish_run(session: Session, run: TestRun, *, status: RunStatus) -> TestRun:
    """Close a run, honouring the `finished_at_matches_status` constraint.

    That CHECK requires a finish time for exactly the terminal statuses, so
    setting one without the other fails at the database rather than silently.
    """
    run.status = status
    run.finished_at = utc_now()
    session.add(run)
    session.flush()
    return run


def create_conversation(
    session: Session,
    *,
    test_run_id: uuid.UUID,
    scenario_id: uuid.UUID,
    caller_metadata: dict[str, Any],
) -> CallSession:
    """Open a conversation as a `CallSession`.

    `IN_PROGRESS` rather than `PENDING`: nothing is dialled, so there is no
    pending period, and `DIALING`/`NO_ANSWER`/`BUSY` are telephony states that
    an offline simulation must not claim.
    """
    conversation = CallSession(
        test_run_id=test_run_id,
        scenario_id=scenario_id,
        status=CallStatus.IN_PROGRESS,
        started_at=utc_now(),
        call_metadata={CALLER_NAMESPACE: caller_metadata},
    )
    session.add(conversation)
    session.flush()
    return conversation


def get_conversation(session: Session, conversation_id: uuid.UUID) -> CallSession | None:
    """Fetch one conversation with its turns and scenario eagerly loaded.

    Eager by necessity, not preference: the models set
    `lazy="raise_on_sql"`, so touching `conversation.turns` outside a loaded
    query raises rather than emitting a surprise SELECT. That is the project's
    deliberate guard against N+1, and this is how a caller honours it.
    """
    statement = (
        select(CallSession)
        .where(CallSession.id == conversation_id)
        .options(
            selectinload(CallSession.turns),
            selectinload(CallSession.scenario),
        )
    )
    return session.execute(statement).scalar_one_or_none()


def get_scenario(session: Session, scenario_id: uuid.UUID) -> Scenario | None:
    """Fetch one scenario by id."""
    return session.execute(select(Scenario).where(Scenario.id == scenario_id)).scalar_one_or_none()


def next_turn_index(session: Session, conversation_id: uuid.UUID) -> int:
    """The index the next turn should take.

    Read from the database rather than from a loaded collection, so two
    concurrent requests both see the committed maximum. The unique constraint
    on `(call_session_id, turn_index)` is still what guarantees correctness -
    this only avoids losing the race in the common case.
    """
    statement = (
        select(ConversationTurn.turn_index)
        .where(ConversationTurn.call_session_id == conversation_id)
        .order_by(ConversationTurn.turn_index.desc())
        .limit(1)
    )
    highest = session.execute(statement).scalar_one_or_none()
    return 0 if highest is None else highest + 1


def add_turn(
    session: Session,
    *,
    conversation_id: uuid.UUID,
    turn_index: int,
    speaker: Speaker,
    content: str | None,
    metadata: dict[str, Any],
    spoken_at: datetime | None = None,
) -> ConversationTurn:
    """Append one utterance.

    Relies on the schema's unique constraint for duplicate protection rather
    than checking first: a check-then-insert has a race, and the constraint
    does not.
    """
    turn = ConversationTurn(
        call_session_id=conversation_id,
        turn_index=turn_index,
        speaker=speaker,
        content=content,
        spoken_at=spoken_at or utc_now(),
        turn_metadata=metadata,
    )
    session.add(turn)
    session.flush()
    return turn


def list_turns(session: Session, conversation_id: uuid.UUID) -> list[ConversationTurn]:
    """Every turn of a conversation, in sequence order."""
    statement = (
        select(ConversationTurn)
        .where(ConversationTurn.call_session_id == conversation_id)
        .order_by(ConversationTurn.turn_index)
    )
    return list(session.execute(statement).scalars())


def update_caller_metadata(
    session: Session, conversation: CallSession, caller_metadata: dict[str, Any]
) -> CallSession:
    """Replace the caller's slice of `call_metadata`.

    Reassigns the whole dict rather than mutating in place: SQLAlchemy does not
    track mutation inside a JSONB value, so an in-place edit would be silently
    dropped at flush. A frequent and well-hidden bug, which is why this is a
    function rather than something each caller does for itself.
    """
    merged = dict(conversation.call_metadata or {})
    merged[CALLER_NAMESPACE] = caller_metadata
    conversation.call_metadata = merged
    session.add(conversation)
    session.flush()
    return conversation


def finish_conversation(
    session: Session,
    conversation: CallSession,
    *,
    status: CallStatus,
    caller_metadata: dict[str, Any],
    error_message: str | None = None,
) -> CallSession:
    """Close a conversation and record its outcome."""
    conversation.status = status
    conversation.ended_at = utc_now()
    if conversation.started_at is not None:
        delta = conversation.ended_at - conversation.started_at
        # The CHECK requires a non-negative duration; clamp rather than risk a
        # constraint violation on a clock that stepped backwards.
        conversation.duration_seconds = max(int(delta.total_seconds()), 0)
    if error_message is not None:
        conversation.error_message = error_message

    merged = dict(conversation.call_metadata or {})
    merged[CALLER_NAMESPACE] = caller_metadata
    conversation.call_metadata = merged

    session.add(conversation)
    session.flush()
    return conversation


def caller_metadata_of(conversation: CallSession) -> dict[str, Any]:
    """The caller's slice of `call_metadata`, or an empty dict."""
    return dict((conversation.call_metadata or {}).get(CALLER_NAMESPACE) or {})


__all__ = [
    "CALLER_NAMESPACE",
    "add_turn",
    "caller_metadata_of",
    "create_conversation",
    "create_run",
    "finish_conversation",
    "finish_run",
    "get_conversation",
    "get_scenario",
    "list_turns",
    "next_turn_index",
    "update_caller_metadata",
]
