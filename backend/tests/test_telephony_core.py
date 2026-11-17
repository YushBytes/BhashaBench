"""Phase 8 telephony core, offline: E.164 numbers, guardrails, webhook
signatures, the status rules, the mock provider and the registry. No call
is placed and nothing is contacted."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.models.call_session import CallStatus
from app.pipeline.modes import IMPLEMENTED_MODES, ExecutionMode
from app.telephony import guardrails, numbers, webhooks
from app.telephony.mock import MockEventError, MockTelephonyProvider
from app.telephony.models import CALL_STATUS, TERMINAL, ProviderCallStatus, advances
from app.telephony.registry import TelephonyUnavailableError, build_telephony_provider
from app.utils.timing import utc_now

SECRET = "s" * 40
BOT = "+919876543210"


class TestNumbers:
    @pytest.mark.parametrize(
        ("raw", "canonical"), [("+91 98765-43210", BOT), ("+1 (415) 555.0100", "+14155550100")]
    )
    def test_formatting_is_removed(self, raw: str, canonical: str) -> None:
        assert numbers.normalise(raw) == canonical

    @pytest.mark.parametrize(
        "raw", ["9876543210", "+0919876543210", "+91abc", "+1234567890123456", "", "+"]
    )
    def test_non_e164_is_refused_not_repaired(self, raw: str) -> None:
        with pytest.raises(numbers.InvalidNumberError):
            numbers.normalise(raw)

    def test_masking_hides_the_subscriber_number(self) -> None:
        assert numbers.masked(BOT) == "+91********10"


LIMITS = guardrails.Limits(
    frozenset({BOT}), max_calls_per_run=2, max_concurrent_calls=1, max_minutes_per_day=10
)
IDLE = guardrails.Usage(calls_in_run=0, calls_in_progress=0, minutes_today=0)


class TestGuardrails:
    def test_an_allow_listed_number_within_limits_passes(self) -> None:
        assert guardrails.check("+91 98765 43210", LIMITS, IDLE) == BOT

    @pytest.mark.parametrize(
        ("number", "usage", "needle"),
        [
            ("+14155550100", IDLE, "not on TELEPHONY_ALLOWED_NUMBERS"),
            ("not a number", IDLE, "E.164"),
            (BOT, guardrails.Usage(2, 0, 0), "TELEPHONY_MAX_CALLS_PER_RUN"),
            (BOT, guardrails.Usage(0, 1, 0), "TELEPHONY_MAX_CONCURRENT_CALLS"),
            (BOT, guardrails.Usage(0, 0, 10.0), "TELEPHONY_MAX_MINUTES_PER_DAY"),
        ],
    )
    def test_every_limit_refuses_before_dialling(
        self, number: str, usage: guardrails.Usage, needle: str
    ) -> None:
        with pytest.raises(guardrails.GuardrailError, match=needle):
            guardrails.check(number, LIMITS, usage)

    def test_an_empty_allowlist_allows_nothing(self) -> None:
        empty = guardrails.Limits(frozenset(), 5, 5, 60)
        with pytest.raises(guardrails.GuardrailError):
            guardrails.check(BOT, empty, IDLE)

    def test_a_refusal_never_names_the_full_number(self) -> None:
        with pytest.raises(guardrails.GuardrailError) as refused:
            guardrails.check("+14155550100", LIMITS, IDLE)
        assert "4155550100" not in str(refused.value)

    def test_one_bad_allowlist_entry_fails_the_list(self) -> None:
        assert guardrails.parse_allowlist(f"{BOT}, +14155550100") == {BOT, "+14155550100"}
        with pytest.raises(ValueError):
            guardrails.parse_allowlist(f"{BOT},0800")


class TestWebhookSignatures:
    def test_a_signed_body_verifies(self) -> None:
        body, now = b'{"a":1}', utc_now()
        headers = webhooks.sign(SECRET, body, now=now)
        webhooks.verify(
            SECRET,
            body,
            timestamp=headers[webhooks.TIMESTAMP_HEADER],
            signature=headers[webhooks.SIGNATURE_HEADER],
            now=now,
        )

    @pytest.mark.parametrize(
        ("mutate", "needle"),
        [
            (lambda b, h: (b + b" ", h), "does not match"),
            (
                lambda b, h: (b, {**h, webhooks.SIGNATURE_HEADER: "v1=" + "0" * 64}),
                "does not match",
            ),
            (
                lambda b, h: (
                    b,
                    {**h, webhooks.SIGNATURE_HEADER: "v2=" + h[webhooks.SIGNATURE_HEADER][3:]},
                ),
                "does not match",
            ),
            (
                lambda b, h: (b, {webhooks.TIMESTAMP_HEADER: h[webhooks.TIMESTAMP_HEADER]}),
                "not signed",
            ),
            (lambda b, h: (b, {**h, webhooks.TIMESTAMP_HEADER: "yesterday"}), "malformed"),
        ],
    )
    def test_tampering_is_refused(self, mutate, needle: str) -> None:
        body, now = b'{"a":1}', utc_now()
        body, headers = mutate(body, webhooks.sign(SECRET, body, now=now))
        with pytest.raises(webhooks.WebhookSignatureError, match=needle):
            webhooks.verify(
                SECRET,
                body,
                timestamp=headers.get(webhooks.TIMESTAMP_HEADER),
                signature=headers.get(webhooks.SIGNATURE_HEADER),
                now=now,
            )

    def test_an_old_event_is_a_replay(self) -> None:
        body, then = b"{}", utc_now() - timedelta(minutes=10)
        headers = webhooks.sign(SECRET, body, now=then)
        with pytest.raises(webhooks.WebhookSignatureError, match="window"):
            webhooks.verify(
                SECRET,
                body,
                timestamp=headers[webhooks.TIMESTAMP_HEADER],
                signature=headers[webhooks.SIGNATURE_HEADER],
                now=utc_now(),
            )

    def test_an_unconfigured_secret_verifies_nothing(self) -> None:
        body, now = b"{}", utc_now()
        headers = webhooks.sign("", body, now=now)
        with pytest.raises(webhooks.WebhookSignatureError, match="not configured"):
            webhooks.verify(
                "",
                body,
                timestamp=headers[webhooks.TIMESTAMP_HEADER],
                signature=headers[webhooks.SIGNATURE_HEADER],
                now=now,
            )


class TestStatusRules:
    def test_every_provider_status_maps_to_a_call_status(self) -> None:
        assert set(CALL_STATUS) == set(ProviderCallStatus)

    def test_only_provider_events_reach_the_telephony_only_states(self) -> None:
        reachable = set(CALL_STATUS.values())
        assert {CallStatus.DIALING, CallStatus.NO_ANSWER, CallStatus.BUSY} <= reachable

    def test_calls_only_move_forward(self) -> None:
        status = ProviderCallStatus
        assert advances(None, status.QUEUED)
        assert advances(status.QUEUED, status.RINGING) and not advances(
            status.RINGING, status.QUEUED
        )
        assert advances(status.RINGING, status.BUSY)
        for terminal in TERMINAL:
            assert not any(advances(terminal, s) for s in status)

    def test_telephony_test_mode_stays_unimplemented(self) -> None:
        assert ExecutionMode.TELEPHONY_TEST not in IMPLEMENTED_MODES


class TestMockProvider:
    def test_it_is_labelled_mocked_and_places_no_real_calls(self) -> None:
        caps = MockTelephonyProvider().capabilities
        assert (caps.mocked, caps.places_real_calls, caps.streams_media) == (True, False, False)
        assert MockTelephonyProvider().place_call(to_number=BOT, call_reference="r").mocked is True

    @pytest.mark.parametrize(
        ("outcome", "last"),
        [
            ("answered", "completed"),
            ("busy", "busy"),
            ("no_answer", "no_answer"),
            ("failed", "failed"),
        ],
    )
    def test_scripts_parse_back_in_order(self, outcome: str, last: str) -> None:
        provider = MockTelephonyProvider()
        placed = provider.place_call(to_number=BOT, call_reference="r")
        events = [
            provider.parse_event(b)
            for b in provider.script(placed.provider_call_id, outcome, start=utc_now())
        ]  # type: ignore[arg-type]
        assert events[-1].status.value == last
        assert [e.occurred_at for e in events] == sorted(e.occurred_at for e in events)
        assert all(
            json.loads(b)["mocked"]
            for b in provider.script(placed.provider_call_id, outcome, start=utc_now())
        )  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "body",
        [
            b"not json",
            b"{}",
            b'{"event_id":"e","call_id":"c","status":"teleported","occurred_at":"2026-01-01T00:00:00+00:00"}',
            b'{"event_id":"e","call_id":"c","status":"busy","occurred_at":"2026-01-01T00:00:00"}',
        ],
    )
    def test_a_malformed_event_is_refused(self, body: bytes) -> None:
        with pytest.raises(MockEventError):
            MockTelephonyProvider().parse_event(body)


class TestRegistry:
    def test_the_mock_is_available_outside_production(self) -> None:
        assert build_telephony_provider("mock", production=False).capabilities.mocked

    def test_the_mock_is_refused_in_production(self) -> None:
        with pytest.raises(TelephonyUnavailableError, match="scripted"):
            build_telephony_provider("mock", production=True)

    @pytest.mark.parametrize(
        ("name", "needle"),
        [("", "not configured"), ("twilio", "paid number"), ("x", "only provider")],
    )
    def test_nothing_else_exists(self, name: str, needle: str) -> None:
        with pytest.raises(TelephonyUnavailableError, match=needle):
            build_telephony_provider(name, production=False)
