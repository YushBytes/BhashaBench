"""Telephony routes (Phase 8): the provider webhook and the calls of a run.

There is no route that places a call. No run mode can use one -
`telephony_test` is not implemented - so a dial button would be a control
that cannot honestly do anything. Calls are placed through
`telephony_service.place_call`, today only by the tests with the mock.

The webhook is public in the sense that it takes no session: a provider
cannot sign in. Its credential is the signature over the raw body, checked
before the body is parsed; an unsigned or tampered event is a 401.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.api.access import RunAccess
from app.api.deps import DbSession, SettingsDep
from app.schemas.common import ErrorResponse
from app.services import telephony_service
from app.services.errors import NotFoundError
from app.telephony import webhooks
from app.telephony.registry import TelephonyUnavailableError, build_telephony_provider
from app.utils.timing import utc_now

router = APIRouter(tags=["telephony"])

MAX_EVENT_BYTES = 16 * 1024


@router.post(
    "/telephony/events/{provider}",
    summary="Receive a signed call-status event from the configured provider",
    description=(
        "Signed with BhashaBench's own scheme (`X-BhashaBench-Timestamp`, "
        "`X-BhashaBench-Signature: v1=<hex HMAC-SHA256>` over `<timestamp>.<raw body>`), "
        "used by the mock provider - not any vendor's. 401 for a missing, stale or wrong "
        "signature; 404 for a provider that is not the configured one or a call it does not "
        "know. A duplicate or stale event is acknowledged with `applied: false`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorResponse},
    },
)
async def receive_event(
    provider: str, request: Request, session: DbSession, settings: SettingsDep
) -> dict[str, Any]:
    if provider != settings.telephony_provider or not provider:
        raise NotFoundError("telephony provider", provider)
    try:
        adapter = build_telephony_provider(provider, production=settings.is_production)
    except TelephonyUnavailableError as exc:
        raise NotFoundError("telephony provider", provider) from exc
    body = await request.body()
    if len(body) > MAX_EVENT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "the event body is too large")
    applied = await run_in_threadpool(
        telephony_service.apply_event,
        session,
        settings,
        adapter,
        body=body,
        timestamp=request.headers.get(webhooks.TIMESTAMP_HEADER),
        signature=request.headers.get(webhooks.SIGNATURE_HEADER),
        now=utc_now(),
    )
    return {"call_id": str(applied.call_id), "applied": applied.applied, "reason": applied.reason}


@router.get(
    "/test-runs/{run_id}/telephony/calls",
    summary="The telephony calls a run made",
    description=(
        "Every call attempt with its provider, `mocked` flag, masked number, status and the "
        "events in the order received (`applied: false` for duplicates and stale events). "
        "Empty for every run today: no run mode places calls."
    ),
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}},
    dependencies=[RunAccess.VIEW],
)
def list_calls(run_id: uuid.UUID, session: DbSession) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "calls": [
            {
                "call_id": str(call.id),
                "conversation_id": str(call.call_session_id),
                "provider": call.provider,
                "mocked": call.mocked,
                "to_number": call.to_number_masked,
                "status": None if call.status is None else call.status.value,
                "answered_at": None if call.answered_at is None else call.answered_at.isoformat(),
                "ended_at": None if call.ended_at is None else call.ended_at.isoformat(),
                "duration_seconds": call.duration_seconds,
                "events": call.events,
            }
            for call in telephony_service.calls_of_run(session, run_id)
        ],
    }


__all__ = ["router"]
