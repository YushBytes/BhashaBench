"""The model-backed caller strategy, driven end to end by the scripted client.

No network and no vendor: every reply, failure and delay is scripted, and the
client records what it was sent. What is under test is the strategy - retry,
fallback, limits and the evidence each turn carries.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from app.caller.errors import CallerConfigurationError
from app.caller.llm.decision import LLM_RULE_ID
from app.caller.llm.errors import (
    LiveCallsDisabledError,
    LlmAuthenticationError,
    LlmBadRequestError,
    LlmQuotaExhaustedError,
    LlmRateLimitError,
    LlmUnavailableError,
)
from app.caller.llm.fake import FAKE_MODEL, FAKE_PROVIDER, Fail, Reply, ScriptedLlmClient, Step
from app.caller.llm.models import LlmCapabilities, LlmRequest, LlmResponse, LlmUsage
from app.caller.llm.pricing import ModelPricing, prompt_token_upper_bound
from app.caller.llm.prompt import PROMPT_VERSION
from app.caller.protocol import CallerProvider
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.providers.llm import LlmCallerLimits, LlmCallerProvider
from app.caller.registry import available_providers, build_provider
from app.caller.schemas import CallerContext, CallerDecision, CallerResourceUse
from app.caller.state import CallerState
from app.core.config import AppEnv, Settings
from app.transcription.retry import RetryPolicy
from tests.conftest import PRODUCTION_SAFE
from tests.test_caller_llm_contract import PRICING, make_context, reply

USAGE = LlmUsage(input_tokens=1000, output_tokens=100)
USAGE_COST = Decimal("0.021")
BAD_NUMBER = reply(message="Mera number 9988776655 hai.", facts_used=[])


def limits(**overrides: Any) -> LlmCallerLimits:
    values: dict[str, Any] = {
        "max_output_tokens": 500,
        "max_prompt_tokens": 20_000,
        "max_attempts": 3,
        "request_timeout_seconds": 5.0,
        "max_message_chars": 600,
        "max_cost_per_run": Decimal(5),
        "temperature": 0.2,
        "seed": 7,
        "backoff": RetryPolicy(
            max_attempts=3, initial_backoff_seconds=1.0, max_backoff_seconds=8.0
        ),
    }
    values.update(overrides)
    return LlmCallerLimits(**values)


class Harness:
    """A provider wired to a scripted client, with sleeps recorded not taken."""

    def __init__(
        self, script: list[Step], *, pricing: ModelPricing | None = PRICING, **kw: Any
    ) -> None:
        client_options = {
            key: kw.pop(key) for key in ("supports_json_schema", "supports_seed") if key in kw
        }
        self.client = ScriptedLlmClient(script, pricing=pricing, **client_options)
        self.sleeps: list[float] = []
        self.provider = LlmCallerProvider(
            self.client,
            fallback=DeterministicCallerProvider(),
            limits=limits(**kw),
            sleep=self._sleep,
            rand=lambda: 1.0,
        )

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def decide(self, context: CallerContext | None = None) -> CallerDecision:
        return asyncio.run(self.provider.decide(context or make_context()))


def worst_case(context: CallerContext, *, max_output_tokens: int = 500) -> Decimal:
    from app.caller.llm.prompt import build_messages

    bound = prompt_token_upper_bound(build_messages(context, max_message_chars=600))
    return PRICING.cost(input_tokens=bound, output_tokens=max_output_tokens)


class TestGeneratedTurn:
    def test_the_models_words_are_what_the_caller_says(self) -> None:
        decision = Harness([Reply(reply(), usage=USAGE)]).decide()
        assert decision.message == "Mera policy number 0471883 hai."
        assert decision.rule_ids == (LLM_RULE_ID,)

    def test_the_evidence_says_a_model_generated_it(self) -> None:
        evidence = Harness([Reply(reply(), usage=USAGE)]).decide().generation
        assert evidence is not None
        assert evidence.generated_by_language_model is True
        assert evidence.fallback_used is False
        assert evidence.fallback_reason is None
        assert evidence.provider == FAKE_PROVIDER
        assert evidence.model == FAKE_MODEL
        assert evidence.model_reported == FAKE_MODEL
        assert evidence.prompt_version == PROMPT_VERSION
        assert evidence.retry_count == 0
        assert [a.outcome for a in evidence.attempts] == ["ok"]

    def test_tokens_and_cost_come_from_the_reported_usage(self) -> None:
        evidence = Harness([Reply(reply(), usage=USAGE)]).decide().generation
        assert evidence is not None
        assert (evidence.input_tokens, evidence.output_tokens) == (1000, 100)
        assert Decimal(evidence.estimated_cost or "nan") == USAGE_COST
        assert evidence.currency == "INR"
        assert evidence.cost_basis == "reported_usage"

    def test_the_double_is_marked_as_contacting_nothing(self) -> None:
        """So its simulated cost can never be read as real spend."""
        evidence = Harness([Reply(reply(), usage=USAGE)]).decide().generation
        assert evidence is not None
        assert evidence.contacts_external_service is False

    def test_a_seed_is_recorded_as_sent_but_never_as_honoured(self) -> None:
        evidence = Harness([Reply(reply(), usage=USAGE)]).decide().generation
        assert evidence is not None
        assert evidence.seed_requested == 7
        assert evidence.seed_sent is True
        assert evidence.seed_honoured is None
        assert evidence.parameters["seed"] == 7

    def test_a_client_without_seed_support_is_not_sent_one(self) -> None:
        harness = Harness([Reply(reply(), usage=USAGE)], supports_seed=False)
        evidence = harness.decide().generation
        assert harness.client.requests[0].seed is None
        assert evidence is not None
        assert evidence.seed_requested == 7
        assert evidence.seed_sent is False
        assert "seed" not in evidence.parameters

    def test_the_request_carries_the_limits_and_this_turns_schema(self) -> None:
        harness = Harness([Reply(reply(), usage=USAGE)], max_output_tokens=321, temperature=0.4)
        harness.decide()
        request = harness.client.requests[0]
        assert request.max_output_tokens == 321
        assert request.temperature == 0.4
        assert request.response_schema is not None
        assert "providing_details" in request.response_schema["properties"]["next_state"]["enum"]

    def test_a_client_without_structured_output_gets_no_schema_and_is_still_parsed(self) -> None:
        harness = Harness([Reply(reply(), usage=USAGE)], supports_json_schema=False)
        decision = harness.decide()
        assert harness.client.requests[0].response_schema is None
        assert decision.generation is not None
        assert decision.generation.generated_by_language_model is True

    def test_a_field_the_provider_did_not_report_stays_none(self) -> None:
        evidence = Harness([Reply(reply(), usage=None, model_reported=None)]).decide().generation
        assert evidence is not None
        assert evidence.input_tokens is None
        assert evidence.output_tokens is None
        assert evidence.reasoning_tokens is None
        assert evidence.model_reported is None
        assert evidence.system_fingerprint is None
        assert evidence.provider_request_id is None


class TestUnknownUsageIsNotFree:
    def test_a_reply_without_usage_is_charged_the_worst_case(self) -> None:
        context = make_context()
        evidence = Harness([Reply(reply(), usage=None)]).decide(context).generation
        assert evidence is not None
        assert evidence.cost_basis == "worst_case"
        assert Decimal(evidence.estimated_cost or "0") == worst_case(context)
        assert Decimal(evidence.estimated_cost or "0") > 0

    def test_a_request_that_failed_after_leaving_is_charged_the_worst_case(self) -> None:
        context = make_context()
        harness = Harness(
            [Fail(LlmUnavailableError("503", provider="x")), Reply(reply(), usage=USAGE)]
        )
        evidence = harness.decide(context).generation
        assert evidence is not None
        assert Decimal(evidence.estimated_cost or "0") == worst_case(context) + USAGE_COST
        assert evidence.cost_basis == "mixed"

    def test_a_client_with_no_pricing_reports_no_cost_rather_than_zero(self) -> None:
        evidence = Harness([Reply(reply(), usage=USAGE)], pricing=None, max_cost_per_run=None)
        generated = evidence.decide().generation
        assert generated is not None
        assert generated.estimated_cost is None
        assert generated.currency is None
        assert generated.cost_basis is None


class TestRetry:
    def test_an_unusable_reply_is_asked_again_without_waiting(self) -> None:
        harness = Harness([Reply("not json", usage=USAGE), Reply(reply(), usage=USAGE)])
        evidence = harness.decide().generation
        assert evidence is not None
        assert evidence.generated_by_language_model is True
        assert evidence.retry_count == 1
        assert [a.outcome for a in evidence.attempts] == ["invalid_output", "ok"]
        assert harness.sleeps == []

    def test_a_reply_the_gate_rejects_is_asked_again(self) -> None:
        harness = Harness([Reply(BAD_NUMBER, usage=USAGE), Reply(reply(), usage=USAGE)])
        decision = harness.decide()
        assert decision.message == "Mera policy number 0471883 hai."
        assert decision.generation is not None
        assert [a.outcome for a in decision.generation.attempts] == ["validation_rejected", "ok"]

    def test_both_attempts_are_paid_for(self) -> None:
        evidence = (
            Harness([Reply("not json", usage=USAGE), Reply(reply(), usage=USAGE)])
            .decide()
            .generation
        )
        assert evidence is not None
        assert Decimal(evidence.estimated_cost or "0") == USAGE_COST * 2
        assert (evidence.input_tokens, evidence.output_tokens) == (2000, 200)

    def test_a_rate_limit_waits_as_long_as_the_provider_asked(self) -> None:
        harness = Harness(
            [
                Fail(LlmRateLimitError("slow down", provider="x", retry_after=3.0)),
                Reply(reply(), usage=USAGE),
            ]
        )
        evidence = harness.decide().generation
        assert harness.sleeps == [3.0]
        assert evidence is not None
        assert evidence.generated_by_language_model is True
        assert evidence.attempts[0].outcome == "rate_limited"

    def test_a_requested_wait_is_capped(self) -> None:
        harness = Harness(
            [
                Fail(LlmRateLimitError("slow down", provider="x", retry_after=3600.0)),
                Reply(reply(), usage=USAGE),
            ]
        )
        harness.decide()
        assert harness.sleeps == [8.0]

    def test_an_outage_backs_off_exponentially(self) -> None:
        harness = Harness(
            [
                Fail(LlmUnavailableError("503", provider="x")),
                Fail(LlmUnavailableError("503", provider="x")),
                Reply(reply(), usage=USAGE),
            ]
        )
        harness.decide()
        assert harness.sleeps == [1.0, 2.0]

    @pytest.mark.parametrize("max_attempts", [1, 2, 3])
    def test_no_mix_of_failures_exceeds_the_attempt_limit(self, max_attempts: int) -> None:
        """The bound on spend: however a turn fails, at most this many requests."""
        script: list[Step] = [
            Fail(LlmUnavailableError("503", provider="x")),
            Reply("not json", usage=USAGE),
            Reply(BAD_NUMBER, usage=USAGE),
            Reply(reply(), usage=USAGE),
            Reply(reply(), usage=USAGE),
        ]
        harness = Harness(script[:max_attempts] + script, max_attempts=max_attempts)
        evidence = harness.decide().generation
        assert len(harness.client.requests) == max_attempts
        assert evidence is not None
        assert len(evidence.attempts) == max_attempts


class TestFallback:
    def _rule_decision(self, context: CallerContext) -> CallerDecision:
        return asyncio.run(DeterministicCallerProvider().decide(context))

    def test_persistent_bad_output_hands_the_turn_to_the_rule_engine(self) -> None:
        context = make_context()
        decision = Harness([Reply("nope", usage=USAGE)] * 3).decide(context)
        expected = self._rule_decision(context)
        assert decision.message == expected.message
        assert decision.rule_ids == expected.rule_ids
        assert LLM_RULE_ID not in decision.rule_ids

    def test_a_fallback_turn_is_not_reported_as_model_generated(self) -> None:
        evidence = Harness([Reply("nope", usage=USAGE)] * 3).decide().generation
        assert evidence is not None
        assert evidence.generated_by_language_model is False
        assert evidence.fallback_used is True
        assert evidence.fallback_reason == "invalid_output"
        assert evidence.retry_count == 2
        # The failed requests were still sent and are still paid for.
        assert Decimal(evidence.estimated_cost or "0") == USAGE_COST * 3

    def test_a_persistently_rejected_reply_falls_back_with_that_reason(self) -> None:
        evidence = Harness([Reply(BAD_NUMBER, usage=USAGE)] * 3).decide().generation
        assert evidence is not None
        assert evidence.fallback_reason == "validation_rejected"
        assert evidence.generated_by_language_model is False

    @pytest.mark.parametrize(
        ("error", "reason"),
        [
            (LlmAuthenticationError("403", provider="x"), "authentication_failed"),
            (LlmQuotaExhaustedError("402", provider="x"), "quota_exhausted"),
            (LlmBadRequestError("400", provider="x"), "bad_request"),
        ],
    )
    def test_a_failure_that_cannot_succeed_is_not_retried(self, error: Any, reason: str) -> None:
        harness = Harness([Fail(error), Reply(reply(), usage=USAGE)])
        evidence = harness.decide().generation
        assert len(harness.client.requests) == 1
        assert harness.sleeps == []
        assert evidence is not None
        assert evidence.fallback_reason == reason
        assert evidence.generated_by_language_model is False

    def test_a_reply_that_never_arrives_times_out_and_falls_back(self) -> None:
        context = make_context()
        harness = Harness(
            [Reply(reply(), usage=USAGE, delay_seconds=30.0)] * 2,
            max_attempts=2,
            request_timeout_seconds=0.02,
        )
        evidence = harness.decide(context).generation
        assert evidence is not None
        assert evidence.fallback_reason == "timeout"
        assert [a.outcome for a in evidence.attempts] == ["timeout", "timeout"]
        assert all(a.request_sent for a in evidence.attempts)
        # Both left the process; neither reported usage; both are charged.
        assert Decimal(evidence.estimated_cost or "0") == worst_case(context) * 2
        assert evidence.cost_basis == "worst_case"

    def test_a_local_refusal_is_not_retried_and_costs_nothing(self) -> None:
        harness = Harness(
            [
                Fail(LiveCallsDisabledError("live calls are disabled", provider="x")),
                Reply(reply(), usage=USAGE),
            ]
        )
        evidence = harness.decide().generation
        assert len(harness.client.requests) == 1
        assert evidence is not None
        assert evidence.fallback_reason == "live_calls_disabled"
        assert evidence.attempts[0].request_sent is False
        assert evidence.estimated_cost is None
        assert evidence.retry_count == 0

    def test_a_credential_in_an_error_does_not_reach_the_record(self) -> None:
        error = LlmAuthenticationError(
            "rejected: Authorization: Bearer sk_live_abcdefghijklmnop", provider="x"
        )
        evidence = Harness([Fail(error)]).decide().generation
        assert evidence is not None
        recorded = f"{evidence.fallback_detail} {evidence.attempts[0].detail}"
        assert "sk_live_abcdefghijklmnop" not in recorded

    def test_the_fallback_is_only_ever_the_rule_engine(self) -> None:
        """There is no second model to try, so a failure cannot cause another paid call."""
        harness = Harness([Fail(LlmAuthenticationError("403", provider="x"))])
        assert isinstance(harness.provider._fallback, DeterministicCallerProvider)
        harness.decide()
        assert len(harness.client.requests) == 1


class TestLimits:
    def test_a_prompt_over_the_token_limit_is_never_sent(self) -> None:
        harness = Harness([Reply(reply(), usage=USAGE)], max_prompt_tokens=50)
        evidence = harness.decide().generation
        assert harness.client.requests == []
        assert evidence is not None
        assert evidence.fallback_reason == "prompt_over_limit"
        assert evidence.attempts == ()
        assert evidence.estimated_cost is None

    def test_a_run_already_at_its_cost_limit_sends_nothing(self) -> None:
        context = make_context().model_copy(
            update={"resources": CallerResourceUse(estimated_cost="4.99", currency="INR")}
        )
        harness = Harness([Reply(reply(), usage=USAGE)])
        evidence = harness.decide(context).generation
        assert harness.client.requests == []
        assert evidence is not None
        assert evidence.fallback_reason == "run_cost_limit"
        assert evidence.attempts[0].request_sent is False

    def test_the_limit_is_judged_on_the_worst_case_not_the_likely_cost(self) -> None:
        """A request that would probably fit is still refused if it might not."""
        context = make_context()
        just_under = worst_case(context) - Decimal("0.000001")
        harness = Harness([Reply(reply(), usage=USAGE)], max_cost_per_run=just_under)
        assert harness.decide(context).generation.fallback_reason == "run_cost_limit"  # type: ignore[union-attr]
        assert harness.client.requests == []

        exact = Harness([Reply(reply(), usage=USAGE)], max_cost_per_run=worst_case(context))
        assert exact.decide(context).generation.generated_by_language_model is True  # type: ignore[union-attr]

    def test_a_retry_is_refused_once_the_first_attempt_used_the_headroom(self) -> None:
        context = make_context()
        # Enough for the first request, a hair short of a second after it.
        room_for_one = worst_case(context) + USAGE_COST - Decimal("0.000001")
        harness = Harness(
            [Reply("not json", usage=USAGE), Reply(reply(), usage=USAGE)],
            max_cost_per_run=room_for_one,
        )
        evidence = harness.decide(context).generation
        assert len(harness.client.requests) == 1
        assert evidence is not None
        assert evidence.fallback_reason == "run_cost_limit"
        assert [a.outcome for a in evidence.attempts] == ["invalid_output", "run_cost_limit"]
        assert Decimal(evidence.estimated_cost or "0") == USAGE_COST

    def test_the_output_cap_is_what_the_client_is_asked_for(self) -> None:
        harness = Harness([Reply(reply(), usage=USAGE)], max_output_tokens=64)
        harness.decide()
        assert harness.client.requests[0].max_output_tokens == 64

    @pytest.mark.parametrize(
        "bad",
        [
            {"max_attempts": 0},
            {"max_output_tokens": 0},
            {"max_prompt_tokens": 0},
            {"request_timeout_seconds": 0},
            {"max_cost_per_run": Decimal(0)},
        ],
    )
    def test_a_nonsensical_limit_is_refused(self, bad: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            limits(**bad)


class _ExternalClient:
    """A stand-in for a live client: it declares that it contacts a service."""

    def __init__(self, pricing: ModelPricing | None) -> None:
        self._pricing = pricing

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(
            provider="external-stub",
            display_name="External stub",
            model="stub-1",
            contacts_external_service=True,
            requires_credentials=True,
            supports_seed=False,
            seed_is_verifiable=False,
            supports_json_schema=False,
            pricing=self._pricing,
        )

    async def complete(self, request: LlmRequest) -> LlmResponse:  # pragma: no cover
        raise AssertionError("must never be called in these tests")

    async def close(self) -> None:
        return None


class TestLiveClientsMustBeBounded:
    def test_a_live_client_without_a_price_cannot_be_wired_up(self) -> None:
        with pytest.raises(ValueError, match="declares no pricing"):
            LlmCallerProvider(
                _ExternalClient(None), fallback=DeterministicCallerProvider(), limits=limits()
            )

    def test_a_live_client_without_a_run_limit_cannot_be_wired_up(self) -> None:
        with pytest.raises(ValueError, match="per-run cost limit is required"):
            LlmCallerProvider(
                _ExternalClient(PRICING),
                fallback=DeterministicCallerProvider(),
                limits=limits(max_cost_per_run=None),
            )


class TestCapabilities:
    def test_it_declares_a_language_model_and_no_reproducibility(self) -> None:
        capabilities = Harness([]).provider.capabilities
        assert capabilities.uses_language_model is True
        assert capabilities.is_deterministic is False
        assert capabilities.name == FAKE_PROVIDER
        assert FAKE_MODEL in capabilities.display_name

    def test_its_languages_are_the_fallbacks(self) -> None:
        assert (
            Harness([]).provider.capabilities.languages
            == DeterministicCallerProvider().capabilities.languages
        )

    def test_it_satisfies_the_caller_provider_protocol(self) -> None:
        assert isinstance(Harness([]).provider, CallerProvider)

    def test_closing_it_closes_the_client(self) -> None:
        harness = Harness([])
        asyncio.run(harness.provider.close())
        assert harness.client.closed is True


class TestTheFakeIsNotAProvider:
    def test_no_configuration_value_selects_it(self) -> None:
        assert FAKE_PROVIDER not in available_providers()
        assert "fake" not in available_providers()

    @pytest.mark.parametrize("env", [AppEnv.DEVELOPMENT, AppEnv.TEST, AppEnv.PRODUCTION])
    def test_asking_for_it_by_name_is_refused_in_every_environment(self, env: AppEnv) -> None:
        settings = Settings(
            app_env=env,
            secret_key="a-real-enough-secret-for-tests",
            _env_file=None,
            **PRODUCTION_SAFE,
        )
        with pytest.raises(CallerConfigurationError, match="not a known caller provider"):
            build_provider(settings, FAKE_PROVIDER)

    def test_an_exhausted_script_fails_loudly(self) -> None:
        evidence = Harness([]).decide().generation
        assert evidence is not None
        assert evidence.fallback_reason == "bad_request"
        assert "no step left" in (evidence.fallback_detail or "")

    def test_it_opens_the_conversation_too(self) -> None:
        opening = reply(
            message="Namaste, main apne claim ke baare mein jaanna chahta hoon.",
            intent="open",
            next_state="introducing",
            facts_used=[],
        )
        decision = Harness([Reply(opening, usage=USAGE)]).decide(
            make_context(state=CallerState.INITIAL)
        )
        assert decision.next_state is CallerState.INTRODUCING
