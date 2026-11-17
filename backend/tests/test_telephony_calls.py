"""Phase 8 telephony with the mock provider, against PostgreSQL and the real
webhook route: guardrails before dialling, signed events driving a call and
its conversation forward, and everything labelled mocked."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CallSession, TelephonyCall
from app.models.call_session import CallStatus
from app.services import telephony_service
from app.services.errors import InvalidRequestError
from app.telephony import webhooks
from app.telephony.mock import MockTelephonyProvider
from app.utils.timing import utc_now
from tests import test_pipeline_api as pipeline_tests

pipeline_client = pipeline_tests.pipeline_client
scenario_ids = pipeline_tests.scenario_ids
BASE = pipeline_tests.BASE
SECRET = "w" * 40
BOT = "+919876543210"
EVENTS = "/api/v1/telephony/events/mock"


@pytest.fixture
def configured(settings: Settings) -> Settings:
    settings.telephony_provider = "mock"
    settings.telephony_webhook_secret = type(settings.telephony_webhook_secret)(SECRET)
    settings.telephony_allowed_numbers = BOT
    settings.telephony_max_calls_per_run = 2
    settings.telephony_max_concurrent_calls = 1
    settings.telephony_max_minutes_per_day = 1.0
    return settings


@pytest.fixture
def run(
    pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], db_session: Session
) -> tuple[str, CallSession]:
    created = pipeline_tests._create(pipeline_client, scenario_ids, mode="offline_simulation")
    pipeline_client.post(f"{BASE}/{created['run_id']}/start")
    conversation = db_session.scalar(
        select(CallSession).where(CallSession.test_run_id == uuid.UUID(created["run_id"]))
    )
    assert conversation is not None
    return created["run_id"], conversation


def _place(
    db: Session,
    settings: Settings,
    provider: MockTelephonyProvider,
    conversation: CallSession,
    number: str = BOT,
) -> TelephonyCall:
    return telephony_service.place_call(
        db, settings, provider, conversation_id=conversation.id, to_number=number, now=utc_now()
    )


def _deliver(
    client: TestClient, body: bytes, *, secret: str = SECRET, path: str = EVENTS
) -> object:
    return client.post(
        path,
        content=body,
        headers={"content-type": "application/json", **webhooks.sign(secret, body, now=utc_now())},
    )


class TestPlacing:
    def test_a_call_is_stored_masked_and_labelled_mocked(
        self, configured: Settings, run: tuple[str, CallSession], db_session: Session
    ) -> None:
        _, conversation = run
        provider = MockTelephonyProvider()
        call = _place(db_session, configured, provider, conversation)
        assert call.mocked is True
        assert call.to_number_masked == "+91********10"
        assert BOT not in str(call.to_number_masked)
        assert provider.placed == [(BOT, str(conversation.id))]
        db_session.refresh(conversation)
        assert conversation.call_metadata["telephony"] == {
            "provider": "mock",
            "mocked": True,
            "places_real_calls": False,
        }
        assert "caller" in conversation.call_metadata  # the caller's namespace is untouched

    def test_placing_alone_claims_no_telephony_status(
        self, configured: Settings, run: tuple[str, CallSession], db_session: Session
    ) -> None:
        _, conversation = run
        before = conversation.status
        call = _place(db_session, configured, MockTelephonyProvider(), conversation)
        assert call.status is None
        db_session.refresh(conversation)
        assert conversation.status == before
        assert conversation.status not in (
            CallStatus.DIALING,
            CallStatus.NO_ANSWER,
            CallStatus.BUSY,
        )

    def test_a_number_off_the_allowlist_is_refused_before_the_provider_is_contacted(
        self, configured: Settings, run: tuple[str, CallSession], db_session: Session
    ) -> None:
        _, conversation = run
        provider = MockTelephonyProvider()
        with pytest.raises(InvalidRequestError, match="refused before dialling"):
            _place(db_session, configured, provider, conversation, "+14155550100")
        assert provider.placed == []
        assert (
            db_session.scalar(
                select(TelephonyCall).where(TelephonyCall.call_session_id == conversation.id)
            )
            is None
        )

    def test_concurrent_calls_and_calls_per_run_are_limited(
        self,
        configured: Settings,
        run: tuple[str, CallSession],
        db_session: Session,
        pipeline_client: TestClient,
    ) -> None:
        _, conversation = run
        provider = MockTelephonyProvider()
        first = _place(db_session, configured, provider, conversation)
        with pytest.raises(InvalidRequestError, match="MAX_CONCURRENT"):
            _place(db_session, configured, provider, conversation)
        for body in provider.script(first.provider_call_id, "busy", start=utc_now()):
            assert _deliver(pipeline_client, body).status_code == 200
        _place(db_session, configured, provider, conversation)
        with pytest.raises(InvalidRequestError, match="MAX_CALLS_PER_RUN"):
            _place(db_session, configured, provider, conversation)

    def test_minutes_per_day_are_limited(
        self,
        configured: Settings,
        run: tuple[str, CallSession],
        db_session: Session,
        pipeline_client: TestClient,
    ) -> None:
        _, conversation = run
        configured.telephony_max_calls_per_run = 5
        provider = MockTelephonyProvider()
        call = _place(db_session, configured, provider, conversation)
        for body in provider.script(
            call.provider_call_id,
            "answered",
            start=utc_now() - timedelta(seconds=90),
            talk_seconds=75,
        ):
            _deliver(pipeline_client, body)
        with pytest.raises(InvalidRequestError, match="MAX_MINUTES_PER_DAY"):
            _place(db_session, configured, provider, conversation)


class TestEvents:
    @pytest.mark.parametrize(
        ("outcome", "final"),
        [
            ("answered", CallStatus.COMPLETED),
            ("busy", CallStatus.BUSY),
            ("no_answer", CallStatus.NO_ANSWER),
            ("failed", CallStatus.FAILED),
        ],
    )
    def test_signed_events_drive_the_call_and_its_conversation(
        self, configured: Settings, run: tuple[str, CallSession], db_session: Session,
        pipeline_client: TestClient, outcome: str, final: CallStatus,
    ) -> None:  # fmt: skip
        run_id, conversation = run
        provider = MockTelephonyProvider()
        call = _place(db_session, configured, provider, conversation)
        seen = []
        for body in provider.script(
            call.provider_call_id, outcome, start=utc_now() - timedelta(minutes=2), talk_seconds=20
        ):  # type: ignore[arg-type]
            response = _deliver(pipeline_client, body)
            assert response.status_code == 200, response.text
            db_session.refresh(conversation)
            seen.append(conversation.status)
        assert seen[0] is CallStatus.DIALING
        assert seen[-1] is final
        assert conversation.call_metadata["telephony"]["mocked"] is True
        listed = pipeline_client.get(f"{BASE}/{run_id}/telephony/calls").json()["calls"]
        assert len(listed) == 1 and listed[0]["mocked"] is True
        assert listed[0]["to_number"] == "+91********10"
        assert all(e["applied"] for e in listed[0]["events"])

    def test_an_unsigned_or_tampered_event_changes_nothing(
        self,
        configured: Settings,
        run: tuple[str, CallSession],
        db_session: Session,
        pipeline_client: TestClient,
    ) -> None:
        _, conversation = run
        provider = MockTelephonyProvider()
        call = _place(db_session, configured, provider, conversation)
        body = provider.script(call.provider_call_id, "busy", start=utc_now())[1]
        assert pipeline_client.post(EVENTS, content=body).status_code == 401
        assert _deliver(pipeline_client, body, secret="x" * 40).status_code == 401
        headers = webhooks.sign(SECRET, body, now=utc_now())
        tampered = body.replace(b'"busy"', b'"completed"')
        assert pipeline_client.post(EVENTS, content=tampered, headers=headers).status_code == 401
        db_session.refresh(call)
        assert call.status is None and call.events == []

    def test_duplicates_and_stale_events_are_recorded_but_not_applied(
        self,
        configured: Settings,
        run: tuple[str, CallSession],
        db_session: Session,
        pipeline_client: TestClient,
    ) -> None:
        _, conversation = run
        provider = MockTelephonyProvider()
        call = _place(db_session, configured, provider, conversation)
        queued, ringing, answered, completed = provider.script(
            call.provider_call_id, "answered", start=utc_now() - timedelta(minutes=2)
        )
        for body in (queued, answered):
            assert _deliver(pipeline_client, body).json()["applied"] is True
        late = _deliver(pipeline_client, ringing).json()
        assert late == {
            "call_id": str(call.id),
            "applied": False,
            "reason": "stale: the call is already past it",
        }
        assert _deliver(pipeline_client, answered).json()["reason"] == "duplicate event"
        _deliver(pipeline_client, completed)
        db_session.refresh(call)
        assert call.status.value == "completed"
        assert [e["applied"] for e in call.events] == [True, True, False, True]

    def test_unknown_providers_and_calls_are_404(
        self,
        configured: Settings,
        run: tuple[str, CallSession],
        db_session: Session,
        pipeline_client: TestClient,
    ) -> None:
        provider = MockTelephonyProvider()
        body = provider.script("mock-unknown", "busy", start=utc_now())[0]
        assert _deliver(pipeline_client, body).status_code == 404
        assert (
            _deliver(pipeline_client, body, path="/api/v1/telephony/events/twilio").status_code
            == 404
        )

    def test_with_telephony_off_the_webhook_does_not_exist(
        self, settings: Settings, pipeline_client: TestClient
    ) -> None:
        assert settings.telephony_provider == ""
        assert _deliver(pipeline_client, b"{}").status_code == 404

    def test_an_oversized_event_is_refused(
        self, configured: Settings, pipeline_client: TestClient
    ) -> None:
        assert _deliver(pipeline_client, b"x" * 20_000).status_code == 413

    def test_deleting_the_run_deletes_its_calls(
        self,
        configured: Settings,
        run: tuple[str, CallSession],
        db_session: Session,
        pipeline_client: TestClient,
    ) -> None:
        run_id, conversation = run
        call = _place(db_session, configured, MockTelephonyProvider(), conversation)
        call_id = call.id
        assert pipeline_client.delete(f"{BASE}/{run_id}").status_code == 200
        db_session.expire_all()
        assert db_session.get(TelephonyCall, call_id) is None


def test_an_invalid_allowlist_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="TELEPHONY_ALLOWED_NUMBERS"):
        Settings(telephony_allowed_numbers=f"{BOT},0800-not-e164", _env_file=None)
