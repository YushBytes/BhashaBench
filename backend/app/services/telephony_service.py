"""Placing calls through the guardrails, and applying provider events.

`place_call` reads the run's call count, the calls in progress and today's
minutes from the database, checks every guardrail, and only then asks the
provider to dial. `apply_event` verifies the webhook signature over the raw
body, parses the event, and moves the call - and its conversation - forward:

- a duplicate event id changes nothing;
- a stale event (one that would rewind the call) is recorded with
  `applied: false` and changes nothing;
- the conversation's status is set from `CALL_STATUS`, which is the only way
  `DIALING`, `NO_ANSWER` or `BUSY` are ever set, and the conversation's
  `telephony` metadata names the provider and whether it was mocked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings
from app.models.call_session import CallSession
from app.models.telephony import TelephonyCall
from app.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UnauthenticatedError,
)
from app.telephony import guardrails, webhooks
from app.telephony.base import TelephonyProvider
from app.telephony.models import CALL_STATUS, TERMINAL, ProviderCallStatus, advances
from app.telephony.numbers import masked

TELEPHONY_NAMESPACE = "telephony"


@dataclass(frozen=True, slots=True)
class Applied:
    call_id: uuid.UUID
    applied: bool
    reason: str


def limits_of(settings: Settings) -> guardrails.Limits:
    return guardrails.Limits(
        allowed_numbers=guardrails.parse_allowlist(settings.telephony_allowed_numbers),
        max_calls_per_run=settings.telephony_max_calls_per_run,
        max_concurrent_calls=settings.telephony_max_concurrent_calls,
        max_minutes_per_day=settings.telephony_max_minutes_per_day,
    )


def usage_for(session: Session, conversation: CallSession, now: datetime) -> guardrails.Usage:
    in_run = session.scalar(
        select(func.count())
        .select_from(TelephonyCall)
        .join(CallSession, CallSession.id == TelephonyCall.call_session_id)
        .where(CallSession.test_run_id == conversation.test_run_id)
    )
    in_progress = session.scalar(
        select(func.count())
        .select_from(TelephonyCall)
        .where(TelephonyCall.status.is_(None) | TelephonyCall.status.not_in(list(TERMINAL)))
    )
    midnight = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    seconds_today = session.scalar(
        select(func.coalesce(func.sum(TelephonyCall.duration_seconds), 0.0)).where(
            TelephonyCall.created_at >= midnight
        )
    )
    return guardrails.Usage(int(in_run or 0), int(in_progress or 0), float(seconds_today or 0) / 60)


def place_call(
    session: Session,
    settings: Settings,
    provider: TelephonyProvider,
    *,
    conversation_id: uuid.UUID,
    to_number: str,
    now: datetime,
) -> TelephonyCall:
    conversation = session.get(CallSession, conversation_id)
    if conversation is None:
        raise NotFoundError("Conversation", conversation_id)
    try:
        number = guardrails.check(
            to_number, limits_of(settings), usage_for(session, conversation, now)
        )
    except guardrails.GuardrailError as exc:
        raise InvalidRequestError(f"call refused before dialling: {exc}") from exc
    capabilities = provider.capabilities
    placed = provider.place_call(to_number=number, call_reference=str(conversation_id))
    call = TelephonyCall(
        call_session_id=conversation.id,
        provider=placed.provider,
        provider_call_id=placed.provider_call_id,
        to_number_masked=masked(number),
        mocked=capabilities.mocked,
    )
    session.add(call)
    metadata = dict(conversation.call_metadata or {})
    metadata[TELEPHONY_NAMESPACE] = {
        "provider": capabilities.name,
        "mocked": capabilities.mocked,
        "places_real_calls": capabilities.places_real_calls,
    }
    conversation.call_metadata = metadata
    flag_modified(conversation, "call_metadata")
    session.commit()
    return call


def apply_event(
    session: Session,
    settings: Settings,
    provider: TelephonyProvider,
    *,
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    now: datetime,
) -> Applied:
    try:
        webhooks.verify(
            settings.telephony_webhook_secret.get_secret_value(),
            body,
            timestamp=timestamp,
            signature=signature,
            now=now,
        )
    except webhooks.WebhookSignatureError as exc:
        raise UnauthenticatedError(f"telephony event refused: {exc}") from exc
    try:
        event = provider.parse_event(body)
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    call = session.scalar(
        select(TelephonyCall).where(
            TelephonyCall.provider == event.provider,
            TelephonyCall.provider_call_id == event.provider_call_id,
        )
    )
    if call is None:
        raise NotFoundError("telephony call", event.provider_call_id)
    if any(e.get("event_id") == event.event_id for e in call.events):
        return Applied(call.id, False, "duplicate event")

    moves = advances(call.status, event.status)
    call.events = [
        *call.events,
        {
            "event_id": event.event_id,
            "status": event.status.value,
            "occurred_at": event.occurred_at.isoformat(),
            "received_at": now.isoformat(),
            "applied": moves,
        },
    ]
    if moves:
        _advance(session, call, event.status, event.occurred_at, event.duration_seconds)
    session.commit()
    return Applied(call.id, moves, "applied" if moves else "stale: the call is already past it")


def _advance(
    session: Session,
    call: TelephonyCall,
    status: ProviderCallStatus,
    at: datetime,
    duration: float | None,
) -> None:
    call.status = status
    if status is ProviderCallStatus.IN_PROGRESS and call.answered_at is None:
        call.answered_at = at
    if status in TERMINAL:
        call.ended_at = (
            at if call.answered_at is None or at >= call.answered_at else call.answered_at
        )
        call.duration_seconds = duration if duration is not None else 0.0
    conversation = session.get(CallSession, call.call_session_id)
    if conversation is None:  # pragma: no cover - the foreign key guarantees it
        raise ConflictError("the call's conversation is gone")
    conversation.status = CALL_STATUS[status]
    metadata = dict(conversation.call_metadata or {})
    telephony = dict(metadata.get(TELEPHONY_NAMESPACE, {}))
    telephony.update(
        {"last_status": status.value, "last_status_at": at.isoformat(), "mocked": call.mocked}
    )
    metadata[TELEPHONY_NAMESPACE] = telephony
    conversation.call_metadata = metadata
    flag_modified(conversation, "call_metadata")


def calls_of_run(session: Session, run_id: uuid.UUID) -> list[TelephonyCall]:
    return list(
        session.scalars(
            select(TelephonyCall)
            .join(CallSession, CallSession.id == TelephonyCall.call_session_id)
            .where(CallSession.test_run_id == run_id)
            .order_by(TelephonyCall.created_at, TelephonyCall.id)
        )
    )


__all__ = [
    "TELEPHONY_NAMESPACE",
    "Applied",
    "apply_event",
    "calls_of_run",
    "limits_of",
    "place_call",
]
