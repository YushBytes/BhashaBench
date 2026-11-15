"""The Sarvam client, tested entirely offline.

**No test here contacts Sarvam.** `httpx2.MockTransport` intercepts at the
socket, so the client's real request-building and response-handling paths
run against a handler in this file.

The repository ships with live calls unauthorised, and the first class below
asserts what that means in practice: the transport is never reached. The
remaining classes open the gate with `monkeypatch` *inside the test process
only* - still against the mock transport - because the code that will one day
talk to the vendor has to be exercised before that day, not on it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError

from app.caller.errors import CallerConfigurationError
from app.caller.llm import budget as live_budget
from app.caller.llm.budget import LiveBudget
from app.caller.llm.clients import sarvam_contract as contract
from app.caller.llm.clients.sarvam import PROVIDER_NAME, SarvamChatClient
from app.caller.llm.errors import (
    BudgetExceededError,
    LiveCallsDisabledError,
    LlmAuthenticationError,
    LlmBadRequestError,
    LlmError,
    LlmInvalidResponseError,
    LlmQuotaExhaustedError,
    LlmRateLimitError,
    LlmRequestTooLargeError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from app.caller.llm.models import LlmMessage, LlmRequest, LlmResponse, LlmRole
from app.caller.llm.pricing import prompt_token_upper_bound
from app.caller.llm.protocol import LlmClient
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.providers.llm import LlmCallerLimits, LlmCallerProvider
from app.caller.registry import build_provider, describe_providers
from app.core.config import SARVAM_DEFAULT_BASE_URL, AppEnv, Settings
from app.transcription.redaction import redact, redact_headers
from tests.test_caller_llm_contract import make_context, reply

API_KEY = "sk_test_NOT-A-REAL-KEY-0123456789"
BOTH_MODELS = [contract.MODEL_105B, contract.MODEL_105B_CONVERSATIONS]
SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}}}

Handler = Callable[[httpx2.Request], httpx2.Response]


def _never(_: httpx2.Request) -> httpx2.Response:
    raise AssertionError("no request may leave the process")


def _budget(tmp_path: Path, ceiling: str = "100") -> LiveBudget:
    return LiveBudget(tmp_path / "ledger.json", ceiling=Decimal(ceiling), provider=PROVIDER_NAME)


def _client(
    handler: Handler,
    tmp_path: Path,
    *,
    model: str = contract.MODEL_105B,
    ceiling: str = "100",
    **kwargs: Any,
) -> SarvamChatClient:
    values: dict[str, Any] = {
        "api_key": API_KEY,
        "live_calls_enabled": True,
        "budget": _budget(tmp_path, ceiling),
        "client": httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    }
    values.update(kwargs)
    return SarvamChatClient(model=model, **values)


def _request(**overrides: Any) -> LlmRequest:
    values: dict[str, Any] = {
        "messages": (
            LlmMessage(LlmRole.SYSTEM, "You are a caller."),
            LlmMessage(LlmRole.USER, "नमस्ते, आपका पॉलिसी नंबर क्या है?"),
        ),
        "max_output_tokens": 300,
        "temperature": 0.5,
        "correlation_id": "caller-test-1",
    }
    values.update(overrides)
    return LlmRequest(**values)


def _completion(
    content: str | None = "ठीक है।",
    *,
    model: str = contract.MODEL_105B,
    usage: dict[str, Any] | bool | None = True,
    finish_reason: str = "stop",
    **top: Any,
) -> httpx2.Response:
    """A response in the documented shape."""
    document: dict[str, Any] = {
        "id": "20261115_0a1b2c3d-0000-4000-8000-000000000000",
        "object": "chat.completion",
        "created": 1794700800,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "service_tier": None,
        "system_fingerprint": None,
    }
    if usage is True:
        document["usage"] = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}
    elif usage is not False:
        document["usage"] = usage
    document.update(top)
    return httpx2.Response(200, json=document)


def _error(status: int, code: str | None, message: str = "nope", **headers: str) -> httpx2.Response:
    error: dict[str, Any] = {"message": message}
    if code is not None:
        error["code"] = code
    return httpx2.Response(status, json={"error": error}, headers=headers)


def _send(client: SarvamChatClient, request: LlmRequest | None = None) -> LlmResponse:
    return asyncio.run(client.complete(request or _request()))


def _body(request: httpx2.Request) -> dict[str, Any]:
    return json.loads(request.content)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open the code-level gate for one test. The transport is still a mock."""
    monkeypatch.setattr(live_budget, "LIVE_CALLS_AUTHORISED", True)


# ---------------------------------------------------------------------------
# As shipped: nothing is sent
# ---------------------------------------------------------------------------


class TestLiveCallsAreOffAsShipped:
    @pytest.mark.parametrize("model", BOTH_MODELS)
    @pytest.mark.parametrize("enabled", [False, True])
    def test_no_request_is_sent_whatever_the_configuration(
        self, tmp_path: Path, model: str, enabled: bool
    ) -> None:
        """A key and the environment flag together are still not enough."""
        client = _client(_never, tmp_path, model=model, live_calls_enabled=enabled)
        with pytest.raises(LiveCallsDisabledError) as caught:
            _send(client)
        assert caught.value.request_sent is False

    def test_nothing_is_charged_for_a_refused_request(self, tmp_path: Path) -> None:
        client = _client(_never, tmp_path)
        with pytest.raises(LiveCallsDisabledError):
            _send(client)
        assert not (tmp_path / "ledger.json").exists()

    def test_live_calls_default_to_off_on_the_client(self, tmp_path: Path) -> None:
        client = SarvamChatClient(
            model=contract.MODEL_105B, api_key=API_KEY, budget=_budget(tmp_path)
        )
        with pytest.raises(LiveCallsDisabledError):
            _send(client)

    def test_the_capabilities_say_it_is_off_and_unverified(self, tmp_path: Path) -> None:
        notes = " ".join(_client(_never, tmp_path).capabilities.notes)
        assert "Live calls are off" in notes
        assert "unverified" in notes

    def test_the_whole_caller_falls_back_and_says_why(self, tmp_path: Path) -> None:
        """With Sarvam selected and live calls off, a conversation still runs:
        on the rule engine, with evidence that no model produced the turn."""
        provider = LlmCallerProvider(
            _client(_never, tmp_path),
            fallback=DeterministicCallerProvider(),
            limits=LlmCallerLimits(
                max_output_tokens=300,
                max_prompt_tokens=20_000,
                max_attempts=3,
                request_timeout_seconds=5.0,
                max_message_chars=600,
                max_cost_per_run=Decimal(5),
                temperature=0.5,
            ),
        )
        evidence = asyncio.run(provider.decide(make_context())).generation
        assert evidence is not None
        assert evidence.generated_by_language_model is False
        assert evidence.fallback_reason == "live_calls_disabled"
        assert evidence.provider == PROVIDER_NAME
        assert evidence.model == contract.MODEL_105B
        assert evidence.estimated_cost is None
        assert [attempt.request_sent for attempt in evidence.attempts] == [False]

    def test_the_contract_is_recorded_as_unverified(self) -> None:
        assert contract.VERIFIED_AGAINST_LIVE_SERVICE is False


# ---------------------------------------------------------------------------
# Construction and capabilities
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_it_is_an_llm_client(self, tmp_path: Path) -> None:
        assert isinstance(_client(_never, tmp_path), LlmClient)

    def test_an_undocumented_model_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a documented Sarvam chat model"):
            _client(_never, tmp_path, model="sarvam-m")

    def test_plain_http_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="https"):
            _client(_never, tmp_path, base_url="http://api.sarvam.ai")

    def test_reasoning_cannot_be_requested_from_the_conversations_model(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValueError, match="not documented"):
            _client(
                _never, tmp_path, model=contract.MODEL_105B_CONVERSATIONS, reasoning_effort="low"
            )

    def test_an_undocumented_reasoning_effort_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not a documented reasoning effort"):
            _client(_never, tmp_path, reasoning_effort="extreme")

    def test_a_closed_client_it_did_not_create_stays_open(self, tmp_path: Path) -> None:
        injected = httpx2.AsyncClient(transport=httpx2.MockTransport(_never))
        client = _client(_never, tmp_path, client=injected)
        asyncio.run(client.close())
        assert injected.is_closed is False
        asyncio.run(injected.aclose())


class TestTheTwoModels:
    def test_exactly_the_two_approved_models_are_supported(self) -> None:
        assert sorted(contract.MODELS) == ["sarvam-105b", "sarvam-105b-conversations"]

    @pytest.mark.parametrize("model", BOTH_MODELS)
    def test_each_reports_its_own_identifier(self, tmp_path: Path, model: str) -> None:
        described = _client(_never, tmp_path, model=model).capabilities
        assert described.model == model
        assert described.provider == "sarvam"
        assert described.contacts_external_service is True
        assert described.requires_credentials is True

    def test_their_context_windows_differ(self, tmp_path: Path) -> None:
        windows = {
            model: _client(_never, tmp_path, model=model).capabilities.context_window_tokens
            for model in BOTH_MODELS
        }
        assert windows == {"sarvam-105b": 128_000, "sarvam-105b-conversations": 32_000}

    @pytest.mark.parametrize("model", BOTH_MODELS)
    def test_the_seed_is_never_claimed_verifiable(self, tmp_path: Path, model: str) -> None:
        described = _client(_never, tmp_path, model=model).capabilities
        assert described.supports_seed is True
        assert described.seed_is_verifiable is False

    @pytest.mark.parametrize("model", BOTH_MODELS)
    def test_pricing_is_the_documented_figure_plus_the_margin(
        self, tmp_path: Path, model: str
    ) -> None:
        pricing = _client(
            _never, tmp_path, model=model, cost_margin=Decimal("0.18")
        ).capabilities.pricing
        assert pricing is not None
        assert pricing.currency == "INR"
        assert pricing.input_per_million == Decimal(15)
        assert pricing.output_per_million == Decimal(60)
        assert pricing.cost(input_tokens=1_000_000, output_tokens=0) == Decimal("17.70")
        assert "docs.sarvam.ai" in pricing.source

    def test_the_reasoning_note_differs_between_them(self, tmp_path: Path) -> None:
        big = " ".join(_client(_never, tmp_path).capabilities.notes)
        chat = " ".join(
            _client(_never, tmp_path, model=contract.MODEL_105B_CONVERSATIONS).capabilities.notes
        )
        assert "Reasoning is disabled in every request" in big
        assert "not documented for this model" in chat


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("live")
class TestRequestShape:
    def _capture(self, tmp_path: Path, request: LlmRequest | None = None, **kwargs: Any) -> Any:
        seen: dict[str, Any] = {}

        def handler(sent: httpx2.Request) -> httpx2.Response:
            seen["request"] = sent
            return _completion()

        _send(_client(handler, tmp_path, **kwargs), request)
        return seen["request"]

    def test_it_posts_to_the_documented_url(self, tmp_path: Path) -> None:
        sent = self._capture(tmp_path)
        assert sent.method == "POST"
        assert str(sent.url) == "https://api.sarvam.ai/v1/chat/completions"

    def test_the_key_goes_in_the_documented_header_only(self, tmp_path: Path) -> None:
        sent = self._capture(tmp_path)
        assert sent.headers["api-subscription-key"] == API_KEY
        assert "authorization" not in sent.headers
        assert API_KEY not in sent.content.decode("utf-8")
        assert API_KEY not in str(sent.url)

    @pytest.mark.parametrize("model", BOTH_MODELS)
    def test_the_selected_model_is_the_one_sent(self, tmp_path: Path, model: str) -> None:
        assert _body(self._capture(tmp_path, model=model))["model"] == model

    def test_messages_keep_their_roles_and_text(self, tmp_path: Path) -> None:
        assert _body(self._capture(tmp_path))["messages"] == [
            {"role": "system", "content": "You are a caller."},
            {"role": "user", "content": "नमस्ते, आपका पॉलिसी नंबर क्या है?"},
        ]

    def test_the_output_limit_and_temperature_are_always_explicit(self, tmp_path: Path) -> None:
        body = _body(self._capture(tmp_path))
        assert body["max_tokens"] == 300
        assert body["temperature"] == 0.5

    def test_only_documented_fields_are_sent(self, tmp_path: Path) -> None:
        body = _body(self._capture(tmp_path, _request(seed=7, response_schema=SCHEMA)))
        assert set(body) == {
            "model",
            "messages",
            "max_tokens",
            "temperature",
            "reasoning_effort",
            "seed",
            "response_format",
        }

    def test_reasoning_is_disabled_explicitly_on_the_reasoning_model(self, tmp_path: Path) -> None:
        body = _body(self._capture(tmp_path))
        assert "reasoning_effort" in body
        assert body["reasoning_effort"] is None

    def test_a_configured_reasoning_effort_is_sent(self, tmp_path: Path) -> None:
        body = _body(self._capture(tmp_path, reasoning_effort="low"))
        assert body["reasoning_effort"] == "low"

    def test_the_conversations_model_is_never_sent_a_reasoning_field(self, tmp_path: Path) -> None:
        body = _body(self._capture(tmp_path, model=contract.MODEL_105B_CONVERSATIONS))
        assert "reasoning_effort" not in body

    def test_no_seed_means_no_seed_field(self, tmp_path: Path) -> None:
        assert "seed" not in _body(self._capture(tmp_path))

    def test_a_seed_is_sent_as_given(self, tmp_path: Path) -> None:
        assert _body(self._capture(tmp_path, _request(seed=20261115)))["seed"] == 20261115

    def test_a_schema_becomes_the_documented_structured_output_request(
        self, tmp_path: Path
    ) -> None:
        body = _body(self._capture(tmp_path, _request(response_schema=SCHEMA)))
        assert body["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "caller_turn", "schema": SCHEMA, "strict": True},
        }

    def test_no_schema_means_no_response_format(self, tmp_path: Path) -> None:
        assert "response_format" not in _body(self._capture(tmp_path))

    def test_streaming_tools_and_n_are_never_requested(self, tmp_path: Path) -> None:
        body = _body(self._capture(tmp_path, _request(seed=1, response_schema=SCHEMA)))
        assert not {"stream", "tools", "tool_choice", "n"} & set(body)


@pytest.mark.usefixtures("live")
class TestRefusedBeforeSending:
    def test_a_missing_key_is_refused_locally(self, tmp_path: Path) -> None:
        with pytest.raises(LlmAuthenticationError, match="SARVAM_API_KEY") as caught:
            _send(_client(_never, tmp_path, api_key=""))
        assert caught.value.request_sent is False

    def test_a_missing_temperature_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(LlmBadRequestError, match="temperature is required") as caught:
            _send(_client(_never, tmp_path), _request(temperature=None))
        assert caught.value.request_sent is False

    @pytest.mark.parametrize("temperature", [-0.1, 2.1])
    def test_a_temperature_outside_the_documented_range_is_refused(
        self, tmp_path: Path, temperature: float
    ) -> None:
        with pytest.raises(LlmBadRequestError, match="outside the documented"):
            _send(_client(_never, tmp_path), _request(temperature=temperature))

    def test_a_prompt_that_cannot_fit_the_small_context_is_refused(self, tmp_path: Path) -> None:
        big = _request(messages=(LlmMessage(LlmRole.USER, "x" * 40_000),))
        with pytest.raises(LlmRequestTooLargeError, match="32000-token context") as caught:
            _send(_client(_never, tmp_path, model=contract.MODEL_105B_CONVERSATIONS), big)
        assert caught.value.request_sent is False

    def test_the_same_prompt_fits_the_large_context(self, tmp_path: Path) -> None:
        big = _request(messages=(LlmMessage(LlmRole.USER, "x" * 40_000),))
        assert _send(_client(lambda _: _completion(), tmp_path), big).text == "ठीक है।"

    def test_nothing_refused_here_touches_the_ledger(self, tmp_path: Path) -> None:
        with pytest.raises(LlmBadRequestError):
            _send(_client(_never, tmp_path), _request(temperature=None))
        assert not (tmp_path / "ledger.json").exists()


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("live")
class TestResponse:
    def test_the_text_and_evidence_are_read_from_the_response(self, tmp_path: Path) -> None:
        result = _send(
            _client(
                lambda _: _completion(reply(), system_fingerprint="fp_abc"),
                tmp_path,
            ),
            _request(seed=7, response_schema=SCHEMA),
        )
        assert json.loads(result.text)["intent"] == "provide_fact"
        assert result.provider == "sarvam"
        assert result.model_requested == "sarvam-105b"
        assert result.model_reported == "sarvam-105b"
        assert result.finish_reason == "stop"
        assert result.system_fingerprint == "fp_abc"
        assert result.provider_request_id == "20261115_0a1b2c3d-0000-4000-8000-000000000000"
        assert result.seed_sent is True
        assert result.parameters == {
            "model": "sarvam-105b",
            "max_output_tokens": 300,
            "temperature": 0.5,
            "structured_output": True,
            "reasoning_effort": "disabled",
            "seed": 7,
        }

    def test_the_model_the_response_names_is_reported_not_assumed(self, tmp_path: Path) -> None:
        result = _send(_client(lambda _: _completion(model="sarvam-105b-0917"), tmp_path))
        assert result.model_requested == "sarvam-105b"
        assert result.model_reported == "sarvam-105b-0917"

    def test_a_response_naming_no_model_reports_none(self, tmp_path: Path) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            document = json.loads(_completion().content)
            del document["model"]
            return httpx2.Response(200, json=document)

        assert _send(_client(handler, tmp_path)).model_reported is None

    def test_a_null_fingerprint_stays_none(self, tmp_path: Path) -> None:
        assert _send(_client(lambda _: _completion(), tmp_path)).system_fingerprint is None

    def test_the_parameters_never_hold_the_key(self, tmp_path: Path) -> None:
        result = _send(_client(lambda _: _completion(), tmp_path))
        assert API_KEY not in json.dumps(result.parameters)

    def test_usage_is_read_including_its_details(self, tmp_path: Path) -> None:
        usage = {
            "prompt_tokens": 900,
            "completion_tokens": 120,
            "total_tokens": 1020,
            "completion_tokens_details": {"reasoning_tokens": 40},
            "prompt_tokens_details": {"cached_tokens": 300},
        }
        result = _send(_client(lambda _: _completion(usage=usage), tmp_path))
        assert result.usage is not None
        assert result.usage.input_tokens == 900
        assert result.usage.output_tokens == 120
        assert result.usage.reasoning_tokens == 40
        assert result.usage.cached_input_tokens == 300

    def test_absent_usage_details_stay_none(self, tmp_path: Path) -> None:
        result = _send(_client(lambda _: _completion(), tmp_path))
        assert result.usage is not None
        assert result.usage.reasoning_tokens is None
        assert result.usage.cached_input_tokens is None

    @pytest.mark.parametrize("usage", [False, None, {}, {"prompt_tokens": "many"}])
    def test_missing_or_unusable_usage_is_none_not_zero(self, tmp_path: Path, usage: Any) -> None:
        result = _send(_client(lambda _: _completion(usage=usage), tmp_path))
        assert result.usage is None

    @pytest.mark.parametrize(
        "body",
        [
            b"<html>gateway</html>",
            b"[]",
            b'{"choices": []}',
            b'{"choices": "none"}',
            b'{"choices": [{"message": {"content": null}, "finish_reason": "tool_calls"}]}',
            b'{"choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]}',
            b'{"choices": [{"finish_reason": "stop"}]}',
        ],
    )
    def test_a_200_that_is_not_a_usable_completion_is_an_invalid_response(
        self, tmp_path: Path, body: bytes
    ) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, content=body)

        with pytest.raises(LlmInvalidResponseError) as caught:
            _send(_client(handler, tmp_path))
        assert caught.value.retryable is True

    def test_a_reply_cut_off_at_the_limit_is_not_accepted_as_a_turn(self, tmp_path: Path) -> None:
        with pytest.raises(LlmInvalidResponseError, match="cut off"):
            _send(_client(lambda _: _completion('{"mess', finish_reason="length"), tmp_path))

    def test_an_empty_reply_at_the_limit_reports_the_finish_reason(self, tmp_path: Path) -> None:
        """The documented symptom of reasoning consuming the output budget."""
        with pytest.raises(LlmInvalidResponseError, match="finish_reason=length"):
            _send(_client(lambda _: _completion("", finish_reason="length"), tmp_path))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("live")
class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "code", "expected", "retryable"),
        [
            (403, "invalid_api_key_error", LlmAuthenticationError, False),
            (402, "insufficient_quota_error", LlmQuotaExhaustedError, False),
            (429, "insufficient_quota_error", LlmQuotaExhaustedError, False),
            (429, "rate_limit_exceeded_error", LlmRateLimitError, True),
            (429, "model_rate_limit_exceeded_error", LlmRateLimitError, True),
            (400, "invalid_request_error", LlmBadRequestError, False),
            (404, "not_found_error", LlmBadRequestError, False),
            (413, "invalid_request_error", LlmBadRequestError, False),
            (422, "unprocessable_entity_error", LlmBadRequestError, False),
            (500, "internal_server_error", LlmUnavailableError, True),
            (502, "model_call_failed", LlmUnavailableError, True),
            (503, "model_overloaded", LlmUnavailableError, True),
        ],
    )
    def test_each_documented_status_maps_to_one_error(
        self,
        tmp_path: Path,
        status: int,
        code: str,
        expected: type[LlmError],
        retryable: bool,
    ) -> None:
        with pytest.raises(expected) as caught:
            _send(_client(lambda _: _error(status, code), tmp_path))
        error = caught.value
        assert type(error) is expected
        assert error.retryable is retryable
        assert error.status_code == status
        assert error.provider_code == code
        assert error.provider == "sarvam"
        assert error.request_sent is True

    def test_an_empty_balance_is_never_retried_as_throttling(self, tmp_path: Path) -> None:
        """The V1 reference titles its 429 'Quota Exceeded'. Retrying that
        would spend attempts on an account that cannot pay for them."""
        with pytest.raises(LlmQuotaExhaustedError) as caught:
            _send(_client(lambda _: _error(429, "insufficient_quota_error"), tmp_path))
        assert caught.value.retryable is False

    @pytest.mark.parametrize("status", [401, 418, 507])
    def test_an_undocumented_status_is_not_retried(self, tmp_path: Path, status: int) -> None:
        with pytest.raises(LlmError) as caught:
            _send(_client(lambda _: _error(status, None), tmp_path))
        assert type(caught.value) is LlmError
        assert caught.value.retryable is False

    def test_retry_after_is_honoured_when_it_is_a_number(self, tmp_path: Path) -> None:
        handler = lambda _: _error(429, "rate_limit_exceeded_error", **{"Retry-After": "12"})  # noqa: E731
        with pytest.raises(LlmRateLimitError) as caught:
            _send(_client(handler, tmp_path))
        assert caught.value.retry_after == 12.0

    @pytest.mark.parametrize("value", ["Wed, 21 Oct 2026 07:28:00 GMT", "-5", "soon"])
    def test_an_unusable_retry_after_is_ignored(self, tmp_path: Path, value: str) -> None:
        handler = lambda _: _error(429, "rate_limit_exceeded_error", **{"Retry-After": value})  # noqa: E731
        with pytest.raises(LlmRateLimitError) as caught:
            _send(_client(handler, tmp_path))
        assert caught.value.retry_after is None

    def test_no_retry_after_header_is_none(self, tmp_path: Path) -> None:
        with pytest.raises(LlmRateLimitError) as caught:
            _send(_client(lambda _: _error(429, "rate_limit_exceeded_error"), tmp_path))
        assert caught.value.retry_after is None

    def test_the_error_carries_the_provider_message_and_request_id(self, tmp_path: Path) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "message": "n must be 1",
                        "code": "invalid_request_error",
                        "request_id": "20261115_abc",
                    }
                },
            )

        with pytest.raises(LlmBadRequestError, match="n must be 1") as caught:
            _send(_client(handler, tmp_path))
        assert caught.value.request_id == "20261115_abc"

    def test_an_error_body_that_is_not_the_envelope_is_still_reported(self, tmp_path: Path) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(503, content=b"upstream connect error")

        with pytest.raises(LlmUnavailableError, match="upstream connect error") as caught:
            _send(_client(handler, tmp_path))
        assert caught.value.provider_code is None

    def test_a_timeout_is_retryable_and_counted_as_sent(self, tmp_path: Path) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("timed out", request=request)

        with pytest.raises(LlmTimeoutError) as caught:
            _send(_client(handler, tmp_path))
        assert caught.value.retryable is True
        assert caught.value.request_sent is True

    def test_a_transport_failure_is_normalised(self, tmp_path: Path) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection refused", request=request)

        with pytest.raises(LlmUnavailableError, match="could not reach Sarvam"):
            _send(_client(handler, tmp_path))

    def test_the_client_never_retries(self, tmp_path: Path) -> None:
        calls: list[int] = []

        def handler(_: httpx2.Request) -> httpx2.Response:
            calls.append(1)
            return _error(503, "model_overloaded")

        with pytest.raises(LlmUnavailableError):
            _send(_client(handler, tmp_path))
        assert len(calls) == 1


@pytest.mark.usefixtures("live")
class TestNoCredentialLeaks:
    def test_a_key_echoed_in_an_error_body_is_redacted(self, tmp_path: Path) -> None:
        handler = lambda _: _error(403, "invalid_api_key_error", f"bad key {API_KEY} supplied")  # noqa: E731
        with pytest.raises(LlmAuthenticationError) as caught:
            _send(_client(handler, tmp_path))
        assert API_KEY not in str(caught.value)
        assert "REDACTED" in str(caught.value)

    def test_a_key_in_a_transport_error_is_redacted(self, tmp_path: Path) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError(f"failed with header {API_KEY}", request=request)

        with pytest.raises(LlmUnavailableError) as caught:
            _send(_client(handler, tmp_path))
        assert API_KEY not in str(caught.value)

    def test_nothing_logged_holds_the_key_or_the_conversation(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="bhashabench"):
            _send(_client(lambda _: _completion("गुप्त उत्तर"), tmp_path))
        assert caplog.records, "the completion should be logged"
        dumped = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
        assert API_KEY not in dumped
        assert "गुप्त उत्तर" not in dumped
        assert "पॉलिसी" not in dumped

    def test_the_header_is_known_to_the_shared_redaction(self) -> None:
        """So a header dump from any layer loses the key, not only this client's."""
        assert redact_headers({"api-subscription-key": API_KEY}) == {
            "api-subscription-key": "***REDACTED***"
        }
        assert API_KEY not in redact(f"api-subscription-key: {API_KEY}")
        assert API_KEY not in redact(f'{{"api-subscription-key": "{API_KEY}"}}')

    def test_the_ledger_file_holds_no_key(self, tmp_path: Path) -> None:
        _send(_client(lambda _: _completion(), tmp_path))
        assert API_KEY not in (tmp_path / "ledger.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Cost and the budget
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("live")
class TestCostAndBudget:
    def _worst(self, request: LlmRequest, margin: str = "0") -> Decimal:
        tokens = prompt_token_upper_bound(request.messages)
        raw = (Decimal(tokens) * 15 + Decimal(request.max_output_tokens) * 60) / Decimal(1_000_000)
        return raw * (1 + Decimal(margin))

    def test_reported_usage_decides_the_cost(self, tmp_path: Path) -> None:
        result = _send(_client(lambda _: _completion(), tmp_path))
        assert result.cost is not None
        # 1000 input at 15/M + 100 output at 60/M.
        assert result.cost.amount == Decimal("0.021")
        assert result.cost.currency == "INR"
        assert result.cost.basis.value == "reported_usage"

    def test_the_margin_is_applied_to_the_cost(self, tmp_path: Path) -> None:
        client = _client(lambda _: _completion(), tmp_path, cost_margin=Decimal("0.18"))
        cost = _send(client).cost
        assert cost is not None
        assert cost.amount == Decimal("0.02478")

    def test_reasoning_tokens_are_not_charged_twice(self, tmp_path: Path) -> None:
        """They are a detail of `completion_tokens`, already billed as output."""
        usage = {
            "prompt_tokens": 1000,
            "completion_tokens": 100,
            "completion_tokens_details": {"reasoning_tokens": 60},
        }
        cost = _send(_client(lambda _: _completion(usage=usage), tmp_path)).cost
        assert cost is not None
        assert cost.amount == Decimal("0.021")

    def test_missing_usage_is_charged_at_the_worst_case(self, tmp_path: Path) -> None:
        request = _request()
        result = _send(_client(lambda _: _completion(usage=False), tmp_path), request)
        assert result.cost is not None
        assert result.cost.basis.value == "worst_case"
        assert result.cost.amount == self._worst(request)
        assert result.cost.amount > 0

    def test_the_ledger_ends_at_the_reported_cost(self, tmp_path: Path) -> None:
        _send(_client(lambda _: _completion(), tmp_path))
        assert _budget(tmp_path).committed() == Decimal("0.021")

    def test_the_worst_case_is_committed_while_the_request_is_in_flight(
        self, tmp_path: Path
    ) -> None:
        request = _request()
        seen: list[Decimal] = []

        def handler(_: httpx2.Request) -> httpx2.Response:
            seen.append(_budget(tmp_path).committed())
            return _completion()

        _send(_client(handler, tmp_path), request)
        assert seen == [self._worst(request)]

    def test_missing_usage_leaves_the_worst_case_in_the_ledger(self, tmp_path: Path) -> None:
        request = _request()
        _send(_client(lambda _: _completion(usage=False), tmp_path), request)
        assert _budget(tmp_path).committed() == self._worst(request)

    @pytest.mark.parametrize("status", [400, 403, 429, 500, 503])
    def test_a_failed_request_stays_charged_at_the_worst_case(
        self, tmp_path: Path, status: int
    ) -> None:
        request = _request()
        with pytest.raises(LlmError):
            _send(_client(lambda _: _error(status, None), tmp_path), request)
        assert _budget(tmp_path).committed() == self._worst(request)

    def test_a_timeout_stays_charged_at_the_worst_case(self, tmp_path: Path) -> None:
        request = _request()

        def handler(sent: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("timed out", request=sent)

        with pytest.raises(LlmTimeoutError):
            _send(_client(handler, tmp_path), request)
        assert _budget(tmp_path).committed() == self._worst(request)

    def test_an_unusable_reply_is_charged_at_its_reported_usage(self, tmp_path: Path) -> None:
        with pytest.raises(LlmInvalidResponseError):
            _send(_client(lambda _: _completion(None), tmp_path))
        assert _budget(tmp_path).committed() == Decimal("0.021")

    def test_a_request_that_does_not_fit_the_budget_is_never_sent(self, tmp_path: Path) -> None:
        with pytest.raises(BudgetExceededError) as caught:
            _send(_client(_never, tmp_path, ceiling="0.001"))
        assert caught.value.request_sent is False
        assert _budget(tmp_path).committed() == Decimal(0)

    def test_the_budget_stops_a_sequence_of_requests(self, tmp_path: Path) -> None:
        sent: list[int] = []

        def handler(_: httpx2.Request) -> httpx2.Response:
            sent.append(1)
            return _completion(usage=False)

        request = _request()
        ceiling = self._worst(request) * 3
        for _ in range(3):
            _send(_client(handler, tmp_path, ceiling=str(ceiling)), request)
        with pytest.raises(BudgetExceededError):
            _send(_client(handler, tmp_path, ceiling=str(ceiling)), request)
        assert len(sent) == 3

    def test_the_hundred_rupee_ceiling_cannot_be_configured_away(self, tmp_path: Path) -> None:
        (tmp_path / "ledger.json").write_text(
            json.dumps({"currency": "INR", "committed": "99.9999"}), encoding="utf-8"
        )
        with pytest.raises(BudgetExceededError, match="of the 100 INR live budget"):
            _send(_client(_never, tmp_path, ceiling="100000"))

    def test_a_corrupt_ledger_stops_spending(self, tmp_path: Path) -> None:
        (tmp_path / "ledger.json").write_text("{", encoding="utf-8")
        with pytest.raises(BudgetExceededError, match="could not be read"):
            _send(_client(_never, tmp_path))


# ---------------------------------------------------------------------------
# The vendor constants
# ---------------------------------------------------------------------------


class TestContract:
    def test_the_documented_transport(self) -> None:
        assert contract.DEFAULT_BASE_URL == "https://api.sarvam.ai"
        assert contract.CHAT_COMPLETIONS_PATH == "/v1/chat/completions"
        assert contract.API_KEY_HEADER == "api-subscription-key"

    def test_prices_are_recorded_as_excluding_tax(self) -> None:
        assert contract.PRICES_EXCLUDE_GST is True
        assert contract.PRICING_CURRENCY == "INR"

    def test_the_gaps_are_recorded(self) -> None:
        gaps = " ".join(contract.DOCUMENTATION_GAPS)
        for topic in ("Authentication", "seed", "reasoning", "Retry-After", "GST", "billed"):
            assert topic in gaps

    def test_the_documented_retry_set(self) -> None:
        assert frozenset({429, 500, 502, 503}) == contract.STATUSES_RETRYABLE


# ---------------------------------------------------------------------------
# Configuration and registration
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "secret_key": "test-secret-key-not-used-for-anything",
        "_env_file": None,
        "caller_provider": "sarvam",
        "caller_llm_budget_ledger_path": str(tmp_path / "ledger.json"),
    }
    values.update(overrides)
    return Settings(**values)


class TestSettings:
    def test_the_defaults_cannot_spend_anything(self, tmp_path: Path) -> None:
        settings = Settings(
            app_env=AppEnv.TEST, secret_key="test-secret-key-not-used", _env_file=None
        )
        assert settings.caller_provider == "deterministic"
        assert settings.caller_llm_live_calls_enabled is False
        assert settings.caller_llm_live_budget_inr == Decimal(0)
        assert settings.caller_llm_model == ""
        assert settings.sarvam_api_key.get_secret_value() == ""

    def test_the_budget_setting_cannot_exceed_one_hundred_rupees(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            _settings(tmp_path, caller_llm_live_budget_inr="100.01")
        assert _settings(
            tmp_path, caller_llm_live_budget_inr="100"
        ).caller_llm_live_budget_inr == Decimal(100)

    def test_attempts_are_bounded(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            _settings(tmp_path, caller_llm_max_attempts=4)

    def test_the_base_url_must_be_https(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="https"):
            _settings(tmp_path, sarvam_api_base_url="http://api.sarvam.ai")

    def test_the_default_base_url_is_the_documented_one(self) -> None:
        assert contract.DEFAULT_BASE_URL == SARVAM_DEFAULT_BASE_URL

    def test_the_key_never_appears_in_a_repr_or_a_dump(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path, sarvam_api_key=API_KEY)
        assert API_KEY not in repr(settings)
        assert API_KEY not in str(settings.model_dump())
        assert API_KEY not in settings.model_dump_json()

    def test_a_blank_seed_is_no_seed(self, tmp_path: Path) -> None:
        """What a copied `.env.example` supplies."""
        assert _settings(tmp_path, caller_llm_seed="").caller_llm_seed is None
        assert _settings(tmp_path, caller_llm_seed="7").caller_llm_seed == 7

    def test_the_model_name_is_normalised(self, tmp_path: Path) -> None:
        assert _settings(tmp_path, caller_llm_model="  Sarvam-105B ").caller_llm_model == (
            "sarvam-105b"
        )

    def test_a_relative_ledger_path_resolves_inside_ignored_storage(self) -> None:
        settings = Settings(
            app_env=AppEnv.TEST, secret_key="test-secret-key-not-used", _env_file=None
        )
        assert settings.caller_llm_budget_ledger.is_absolute()
        assert settings.caller_llm_budget_ledger.parts[-3:] == (
            "storage",
            "llm-budget",
            "ledger.json",
        )


class TestRegistration:
    def test_a_model_must_be_chosen_explicitly(self, tmp_path: Path) -> None:
        with pytest.raises(CallerConfigurationError, match="no default model"):
            build_provider(_settings(tmp_path))

    def test_an_unknown_model_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(CallerConfigurationError, match="not a documented Sarvam chat model"):
            build_provider(_settings(tmp_path, caller_llm_model="sarvam-m"))

    @pytest.mark.parametrize("model", BOTH_MODELS)
    def test_each_model_builds_without_a_key_while_live_calls_are_off(
        self, tmp_path: Path, model: str
    ) -> None:
        provider = build_provider(_settings(tmp_path, caller_llm_model=model))
        described = provider.capabilities
        assert described.name == "sarvam"
        assert model in described.display_name
        assert "Live calls are off" in " ".join(described.notes)

    def test_reasoning_on_the_conversations_model_is_a_configuration_error(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(CallerConfigurationError, match="reasoning is not documented"):
            build_provider(
                _settings(
                    tmp_path,
                    caller_llm_model=contract.MODEL_105B_CONVERSATIONS,
                    caller_llm_reasoning_effort="low",
                )
            )

    def test_switching_live_calls_on_without_a_key_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CallerConfigurationError, match="SARVAM_API_KEY"):
            build_provider(
                _settings(
                    tmp_path,
                    caller_llm_model=contract.MODEL_105B,
                    caller_llm_live_calls_enabled=True,
                )
            )

    def test_switching_live_calls_on_without_a_budget_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CallerConfigurationError, match="CALLER_LLM_LIVE_BUDGET_INR"):
            build_provider(
                _settings(
                    tmp_path,
                    caller_llm_model=contract.MODEL_105B,
                    caller_llm_live_calls_enabled=True,
                    sarvam_api_key=API_KEY,
                )
            )

    def test_no_error_message_holds_the_key(self, tmp_path: Path) -> None:
        with pytest.raises(CallerConfigurationError) as caught:
            build_provider(
                _settings(
                    tmp_path,
                    caller_llm_model="nonsense",
                    caller_llm_live_calls_enabled=True,
                    sarvam_api_key=API_KEY,
                )
            )
        assert API_KEY not in str(caught.value)

    @pytest.mark.parametrize("model", BOTH_MODELS)
    def test_everything_switched_on_still_sends_nothing(self, tmp_path: Path, model: str) -> None:
        """A key, the operator switch, the full budget and a model: the
        configuration of someone trying to make a live call. With the
        code-level authorisation withheld, the turn is a recorded fallback,
        nothing is charged, and no socket is opened - the client would build a
        real HTTP pool on first use, and it is never used."""
        provider = build_provider(
            _settings(
                tmp_path,
                caller_llm_model=model,
                caller_llm_live_calls_enabled=True,
                caller_llm_live_budget_inr="100",
                sarvam_api_key=API_KEY,
            )
        )
        decision = asyncio.run(provider.decide(make_context()))
        evidence = decision.generation
        assert evidence is not None
        assert evidence.model == model
        assert evidence.generated_by_language_model is False
        assert evidence.fallback_reason == "live_calls_disabled"
        assert evidence.retry_count == 0
        assert evidence.estimated_cost is None
        assert len(evidence.attempts) == 1
        assert decision.message
        assert not (tmp_path / "ledger.json").exists()
        assert provider._client._client is None  # type: ignore[attr-defined]

    def test_the_listing_describes_a_configured_model(self, tmp_path: Path) -> None:
        described = {
            name: (capabilities, reason)
            for name, capabilities, reason in describe_providers(
                _settings(tmp_path, caller_llm_model=contract.MODEL_105B_CONVERSATIONS)
            )
        }
        capabilities, reason = described["sarvam"]
        assert reason is None
        assert capabilities is not None
