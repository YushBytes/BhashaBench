"""Sarvam chat-completions client.

The only module that knows Sarvam's wire format. Everything vendor-specific is
here or in `sarvam_contract`; the caller strategy above deals in
`app.caller.llm.models` and has never heard of `max_tokens` or `choices`.

**Not verified against the live service.** It is built from the published
documentation and tested against a mock transport. No request has been sent
to Sarvam, and none can be: `complete` asks `require_live_calls` first, and
that refuses while the owner has not approved live testing.

The order inside `complete` is the safety design:

1. the live gate - nothing below runs while live calls are off;
2. the context-window check - a request that cannot fit is never paid for;
3. the budget reservation - the worst-case cost is committed to the durable
   ledger, or the request is refused;
4. the request, exactly once - this client never retries;
5. settlement - the reservation is lowered to the reported cost, or left at
   the worst case when usage is missing or the request failed.

A reservation is only ever released by step 5. A timeout, a cancellation or a
crash between 3 and 5 leaves the worst case charged, which is the direction
an unknown cost has to err in.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import httpx2

from app.caller.llm import budget as live_budget
from app.caller.llm.budget import LiveBudget
from app.caller.llm.clients import sarvam_contract as contract
from app.caller.llm.errors import (
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
from app.caller.llm.models import LlmCapabilities, LlmRequest, LlmResponse, LlmUsage
from app.caller.llm.pricing import (
    ModelPricing,
    cost_of_usage,
    prompt_token_upper_bound,
    worst_case_cost,
)
from app.transcription.redaction import PLACEHOLDER, redact
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.caller.llm.sarvam")

PROVIDER_NAME = "sarvam"

_MAX_ERROR_CHARS = 300


def _not_sent(error: LlmError) -> LlmError:
    """Mark a refusal made here, before any request, so nothing is charged for it."""
    error.request_sent = False
    return error


class SarvamChatClient:
    """`LlmClient` for one Sarvam model."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        budget: LiveBudget,
        live_calls_enabled: bool = False,
        base_url: str = contract.DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
        cost_margin: Decimal = Decimal(0),
        reasoning_effort: str | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        described = contract.MODELS.get(model)
        if described is None:
            raise ValueError(
                f"'{model}' is not a documented Sarvam chat model; "
                f"supported models are {sorted(contract.MODELS)}"
            )
        if reasoning_effort is not None:
            if not described.reasoning_documented:
                raise ValueError(
                    f"reasoning is not documented for '{model}', so no reasoning "
                    "effort can be requested from it"
                )
            if reasoning_effort not in contract.REASONING_EFFORTS:
                raise ValueError(
                    f"'{reasoning_effort}' is not a documented reasoning effort; "
                    f"use one of {sorted(contract.REASONING_EFFORTS)} or leave it unset"
                )
        if not base_url.startswith("https://"):
            # The request carries a credential.
            raise ValueError("the Sarvam base URL must use https://")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._model = described
        self._api_key = api_key
        self._budget = budget
        self._live_calls_enabled = live_calls_enabled
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._reasoning_effort = reasoning_effort
        self._pricing = ModelPricing(
            currency=contract.PRICING_CURRENCY,
            input_per_million=described.input_per_million,
            output_per_million=described.output_per_million,
            source=contract.PRICING_SOURCE,
            margin=cost_margin,
        )
        self._owns_client = client is None
        self._client: httpx2.AsyncClient | None = client

    @property
    def _http(self) -> httpx2.AsyncClient:
        """Built on first use: describing the provider must not open a pool."""
        if self._client is None:
            self._client = httpx2.AsyncClient(timeout=httpx2.Timeout(self._timeout_seconds))
        return self._client

    # -- Capabilities -------------------------------------------------------

    @property
    def capabilities(self) -> LlmCapabilities:
        model = self._model
        reasoning = (
            "Reasoning is disabled in every request (`reasoning_effort` is sent as null)."
            if model.reasoning_documented and self._reasoning_effort is None
            else f"Reasoning effort '{self._reasoning_effort}' is requested; reasoning "
            "tokens are billed as output and count toward the output limit."
            if model.reasoning_documented
            else "Reasoning is not documented for this model, so `reasoning_effort` is "
            "not sent; whether it reasons by default is unknown."
        )
        live = (
            "Live calls are authorised and switched on; every request is checked against "
            f"the live budget of {self._budget.ceiling} {contract.PRICING_CURRENCY} first."
            if live_budget.LIVE_CALLS_AUTHORISED and self._live_calls_enabled
            else "Live calls are off. Every request is refused before it is sent, and "
            "each turn is supplied by the fallback with the reason recorded."
        )
        return LlmCapabilities(
            provider=PROVIDER_NAME,
            display_name="Sarvam",
            model=model.model_id,
            contacts_external_service=True,
            requires_credentials=True,
            supports_seed=True,
            seed_is_verifiable=False,
            supports_json_schema=True,
            context_window_tokens=model.context_window_tokens,
            pricing=self._pricing,
            notes=(
                "Built from Sarvam's published documentation and tested offline only. "
                "No request has been sent to the live service, so the contract is "
                "unverified.",
                live,
                reasoning,
                "The seed is best-effort by the vendor's own description; it is recorded "
                "as sent, never as honoured.",
            ),
        )

    # -- One request --------------------------------------------------------

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Send `request` once.

        Raises:
            LiveCallsDisabledError: live calls are off. Nothing was sent.
            LlmRequestTooLargeError: it cannot fit the context window.
            BudgetExceededError: its worst case does not fit the live budget.
            LlmError: any provider or transport failure, normalised.
        """
        live_budget.require_live_calls(
            enabled_in_configuration=self._live_calls_enabled, provider=PROVIDER_NAME
        )
        if not self._api_key:
            raise _not_sent(
                LlmAuthenticationError(
                    "a Sarvam API key is required; set SARVAM_API_KEY", provider=PROVIDER_NAME
                )
            )

        prompt_bound = prompt_token_upper_bound(request.messages)
        window = self._model.context_window_tokens
        if prompt_bound + request.max_output_tokens > window:
            raise LlmRequestTooLargeError(
                f"a prompt of at most {prompt_bound} tokens plus {request.max_output_tokens} "
                f"output tokens does not fit the {window}-token context of "
                f"'{self._model.model_id}'",
                provider=PROVIDER_NAME,
            )

        body, parameters = self._build_body(request)
        worst = worst_case_cost(
            self._pricing,
            prompt_tokens_upper_bound=prompt_bound,
            max_output_tokens=request.max_output_tokens,
        )
        reservation = self._budget.reserve(worst.amount, currency=worst.currency)

        started = monotonic_seconds()
        try:
            response = await self._http.post(
                f"{self._base_url}{contract.CHAT_COMPLETIONS_PATH}",
                json=body,
                headers={contract.API_KEY_HEADER: self._api_key},
            )
        except httpx2.TimeoutException as exc:
            raise LlmTimeoutError(
                f"Sarvam did not respond within {self._timeout_seconds:g}s",
                provider=PROVIDER_NAME,
            ) from exc
        except httpx2.RequestError as exc:
            raise LlmUnavailableError(
                f"could not reach Sarvam: {self._safe(exc)}", provider=PROVIDER_NAME
            ) from exc
        latency_ms = round((monotonic_seconds() - started) * 1000, 3)

        self._raise_for_status(response)
        document = self._json_object(response)

        # Usage first: a reply we cannot use was still paid for, and its real
        # cost is worth more to the ledger than the worst case.
        usage = self._usage(document.get(contract.RESPONSE_USAGE))
        cost = cost_of_usage(self._pricing, usage)
        self._budget.settle(reservation, cost.amount if cost is not None else None)

        text, finish_reason = self._content(document)
        result = LlmResponse(
            text=text,
            provider=PROVIDER_NAME,
            model_requested=self._model.model_id,
            model_reported=self._string(document.get(contract.RESPONSE_MODEL)),
            usage=usage,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            parameters=parameters,
            seed_sent=request.seed is not None,
            system_fingerprint=self._string(document.get(contract.RESPONSE_SYSTEM_FINGERPRINT)),
            provider_request_id=self._string(document.get(contract.RESPONSE_ID)),
            cost=cost or worst,
        )
        logger.info(
            "caller.llm.completed",
            extra={
                "provider": PROVIDER_NAME,
                "model": self._model.model_id,
                "model_reported": result.model_reported,
                "correlation_id": request.correlation_id,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason,
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "usage_reported": usage is not None,
                # Never the prompt, the reply, a header or the key.
            },
        )
        return result

    # -- Request ------------------------------------------------------------

    def _build_body(self, request: LlmRequest) -> tuple[dict[str, Any], dict[str, Any]]:
        """The wire body, and a vendor-neutral record of the parameters in it."""
        if request.temperature is None:
            # The documented default is contradictory, so it is never relied on.
            raise _not_sent(
                LlmBadRequestError(
                    "a temperature is required: Sarvam's documented default is contradictory",
                    provider=PROVIDER_NAME,
                )
            )
        if not contract.TEMPERATURE_MIN <= request.temperature <= contract.TEMPERATURE_MAX:
            raise _not_sent(
                LlmBadRequestError(
                    f"temperature {request.temperature} is outside the documented "
                    f"{contract.TEMPERATURE_MIN:g}-{contract.TEMPERATURE_MAX:g} range",
                    provider=PROVIDER_NAME,
                )
            )

        messages = []
        for message in request.messages:
            if message.role.value not in contract.ROLES:  # pragma: no cover - enum is closed
                raise _not_sent(
                    LlmBadRequestError(
                        f"role '{message.role.value}' is not sent to Sarvam",
                        provider=PROVIDER_NAME,
                    )
                )
            messages.append(
                {
                    contract.MESSAGE_ROLE: message.role.value,
                    contract.MESSAGE_CONTENT: message.content,
                }
            )

        body: dict[str, Any] = {
            contract.FIELD_MODEL: self._model.model_id,
            contract.FIELD_MESSAGES: messages,
            contract.FIELD_MAX_TOKENS: request.max_output_tokens,
            contract.FIELD_TEMPERATURE: request.temperature,
        }
        parameters: dict[str, Any] = {
            "model": self._model.model_id,
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "structured_output": request.response_schema is not None,
        }
        if self._model.reasoning_documented:
            # Always explicit, null included: the documented default differs
            # between pages, and reasoning spends the output budget.
            body[contract.FIELD_REASONING_EFFORT] = self._reasoning_effort
            parameters["reasoning_effort"] = self._reasoning_effort or "disabled"
        else:
            parameters["reasoning_effort"] = "not_sent"
        if request.seed is not None:
            body[contract.FIELD_SEED] = request.seed
            parameters["seed"] = request.seed
        if request.response_schema is not None:
            body[contract.FIELD_RESPONSE_FORMAT] = {
                contract.RESPONSE_FORMAT_TYPE: contract.RESPONSE_FORMAT_JSON_SCHEMA,
                contract.RESPONSE_FORMAT_JSON_SCHEMA: {
                    contract.JSON_SCHEMA_NAME: request.schema_name,
                    contract.JSON_SCHEMA_SCHEMA: request.response_schema,
                    contract.JSON_SCHEMA_STRICT: True,
                },
            }
        return body, parameters

    # -- Response -----------------------------------------------------------

    def _json_object(self, response: httpx2.Response) -> dict[str, Any]:
        try:
            document = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LlmInvalidResponseError(
                "Sarvam answered 200 with a body that is not JSON", provider=PROVIDER_NAME
            ) from exc
        if not isinstance(document, dict):
            raise LlmInvalidResponseError(
                "Sarvam answered 200 with JSON that is not an object", provider=PROVIDER_NAME
            )
        return document

    @staticmethod
    def _string(value: object) -> str | None:
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _count(value: object) -> int | None:
        """A token count, or `None` for anything that is not one."""
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _usage(self, raw: object) -> LlmUsage | None:
        """Token counts as reported. Absent stays absent; nothing becomes zero."""
        if not isinstance(raw, dict):
            return None
        completion_details = raw.get(contract.USAGE_COMPLETION_DETAILS)
        prompt_details = raw.get(contract.USAGE_PROMPT_DETAILS)
        usage = LlmUsage(
            input_tokens=self._count(raw.get(contract.USAGE_PROMPT_TOKENS)),
            output_tokens=self._count(raw.get(contract.USAGE_COMPLETION_TOKENS)),
            reasoning_tokens=self._count(completion_details.get(contract.USAGE_REASONING_TOKENS))
            if isinstance(completion_details, dict)
            else None,
            cached_input_tokens=self._count(prompt_details.get(contract.USAGE_CACHED_TOKENS))
            if isinstance(prompt_details, dict)
            else None,
        )
        if usage.input_tokens is None and usage.output_tokens is None:
            return None
        return usage

    def _content(self, document: dict[str, Any]) -> tuple[str, str | None]:
        """The reply text and why generation stopped.

        Raises:
            LlmInvalidResponseError: no usable text. The message says whether
                the model was cut off, which is the documented way a low
                output limit shows up when reasoning consumes it.
        """
        choices = document.get(contract.RESPONSE_CHOICES)
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LlmInvalidResponseError(
                "Sarvam's response has no choices", provider=PROVIDER_NAME
            )
        choice = choices[0]
        finish_reason = self._string(choice.get(contract.CHOICE_FINISH_REASON))
        message = choice.get(contract.CHOICE_MESSAGE)
        content = message.get(contract.MESSAGE_CONTENT) if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LlmInvalidResponseError(
                f"Sarvam returned no text (finish_reason={finish_reason or 'not reported'})",
                provider=PROVIDER_NAME,
            )
        if finish_reason == contract.FINISH_LENGTH:
            raise LlmInvalidResponseError(
                "Sarvam's reply was cut off at the output-token limit", provider=PROVIDER_NAME
            )
        return content, finish_reason

    # -- Errors -------------------------------------------------------------

    def _safe(self, text: object) -> str:
        """Provider text made fit for a message: no key, one line, bounded."""
        value = text if isinstance(text, str) else str(text)
        if self._api_key:
            value = value.replace(self._api_key, PLACEHOLDER)
        return " ".join(redact(value).split())[:_MAX_ERROR_CHARS]

    def _error_fields(self, response: httpx2.Response) -> tuple[str, str | None, str | None]:
        """`(message, code, request_id)` from the documented error envelope."""
        try:
            document = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            document = None
        envelope = document.get(contract.ERROR_ENVELOPE) if isinstance(document, dict) else None
        if not isinstance(envelope, dict):
            return self._safe(response.text) or "no error body", None, None
        return (
            self._safe(envelope.get(contract.ERROR_MESSAGE) or "no message"),
            self._string(envelope.get(contract.ERROR_CODE)),
            self._string(envelope.get(contract.ERROR_REQUEST_ID)),
        )

    @staticmethod
    def _retry_after(response: httpx2.Response) -> float | None:
        raw = response.headers.get(contract.RETRY_AFTER_HEADER)
        if raw is None:
            return None
        try:
            seconds = float(raw)
        except ValueError:
            return None
        return seconds if seconds >= 0 else None

    def _raise_for_status(self, response: httpx2.Response) -> None:
        """Map a Sarvam HTTP status onto a normalised error."""
        status = response.status_code
        if status == 200:
            return
        message, code, request_id = self._error_fields(response)
        common: dict[str, Any] = {
            "provider": PROVIDER_NAME,
            "status_code": status,
            "provider_code": code,
            "request_id": request_id,
        }
        text = f"Sarvam returned {status}" + (f" ({code})" if code else "") + f": {message}"

        # By code before status: an empty balance must never be retried as
        # throttling, whichever status it arrives with.
        if code == contract.CODE_INSUFFICIENT_QUOTA or status == contract.STATUS_QUOTA:
            raise LlmQuotaExhaustedError(text, **common)
        if status == contract.STATUS_AUTH:
            raise LlmAuthenticationError(text, **common)
        if status == contract.STATUS_RATE_LIMIT:
            raise LlmRateLimitError(text, retry_after=self._retry_after(response), **common)
        if status in contract.STATUSES_RETRYABLE:
            raise LlmUnavailableError(text, **common)
        if status in contract.STATUSES_BAD_REQUEST:
            raise LlmBadRequestError(text, **common)
        # Undocumented for this endpoint. Not retried: an unknown failure is
        # not evidence that asking again, and paying again, would help.
        raise LlmError(text, retryable=False, **common)

    async def close(self) -> None:
        """Close the HTTP client, if this instance created it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["PROVIDER_NAME", "SarvamChatClient"]
