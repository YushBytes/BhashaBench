"""The Sarvam chat-completions wire contract, as published by the vendor.

Transcribed from Sarvam's official documentation at <https://docs.sarvam.ai>,
read on 2026-11-15:

* `api-reference-docs/chat/chat-completions` - the V1 reference (request,
  response and error schemas);
* `api/token-factory/models/sarvam-105b` - the model page, including its
  "conversational variant" section and limits table;
* `api-reference-docs/getting-started/models` - the model table;
* `api-reference-docs/ratelimits` - pricing, credits and rate limits;
* `api/getting-started/errors-troubleshooting` - the error table.

Nothing here is inferred from another vendor's "OpenAI-compatible" API, and
**nothing here has been confirmed against the live service**: no request has
been sent. Every constant is what the documentation says, and
`DOCUMENTATION_GAPS` records where it is silent or disagrees with itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

DOCUMENTATION_URL = "https://docs.sarvam.ai/api-reference-docs/chat/chat-completions"
VERIFIED_AGAINST_LIVE_SERVICE = False
"""No live call has been made. Flip only after an authorised live test."""

# -- Transport --------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.sarvam.ai"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
"""`POST`, JSON in, JSON out. "This endpoint serves only `sarvam-105b` and
`sarvam-105b-conversations`." The V2 endpoint is a different contract and does
not serve the conversations model; it is not used."""

API_KEY_HEADER = "api-subscription-key"
"""The bare key. The header every documented cURL example sends. A bearer
`Authorization` header is documented as also accepted; see the gaps."""

# -- Request field names ----------------------------------------------------

FIELD_MODEL = "model"
FIELD_MESSAGES = "messages"
FIELD_TEMPERATURE = "temperature"
FIELD_MAX_TOKENS = "max_tokens"
FIELD_SEED = "seed"
FIELD_REASONING_EFFORT = "reasoning_effort"
FIELD_RESPONSE_FORMAT = "response_format"

MESSAGE_ROLE = "role"
MESSAGE_CONTENT = "content"
ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})
"""The subset of documented roles this client sends."""

TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0
"""'Sampling temperature between 0 and 2.'"""

REASONING_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "max"})
"""Documented enum values that turn reasoning on. The enum also lists `none`;
this client disables reasoning the other documented way, with JSON `null`
("Can be disabled by explicitly setting to None")."""

RESPONSE_FORMAT_TYPE = "type"
RESPONSE_FORMAT_JSON_SCHEMA = "json_schema"
JSON_SCHEMA_NAME = "name"
JSON_SCHEMA_SCHEMA = "schema"
JSON_SCHEMA_STRICT = "strict"
"""`{"type": "json_schema", "json_schema": {"name", "schema", "strict"}}`.
The reply arrives as a JSON *string* in `message.content`."""

# -- Response field names ---------------------------------------------------

RESPONSE_ID = "id"
RESPONSE_MODEL = "model"
RESPONSE_CHOICES = "choices"
RESPONSE_SYSTEM_FINGERPRINT = "system_fingerprint"
RESPONSE_USAGE = "usage"
CHOICE_MESSAGE = "message"
CHOICE_FINISH_REASON = "finish_reason"

FINISH_STOP = "stop"
FINISH_LENGTH = "length"
FINISH_REASONS: frozenset[str] = frozenset(
    {FINISH_STOP, FINISH_LENGTH, "tool_calls", "content_filter", "function_call"}
)

USAGE_PROMPT_TOKENS = "prompt_tokens"
USAGE_COMPLETION_TOKENS = "completion_tokens"
USAGE_COMPLETION_DETAILS = "completion_tokens_details"
USAGE_REASONING_TOKENS = "reasoning_tokens"
"""'Tokens spent on the chain-of-thought. Billed as completion / output
tokens.' A detail of `completion_tokens`, not an addition to it."""
USAGE_PROMPT_DETAILS = "prompt_tokens_details"
USAGE_CACHED_TOKENS = "cached_tokens"

# -- Errors -----------------------------------------------------------------

ERROR_ENVELOPE = "error"
ERROR_MESSAGE = "message"
ERROR_CODE = "code"
ERROR_REQUEST_ID = "request_id"

CODE_INSUFFICIENT_QUOTA = "insufficient_quota_error"
"""'Credit balance is empty'. Documented with 402 on the error page; the V1
reference titles its 429 'Quota Exceeded'. Matched by code at any status, so
an exhausted account is never retried as if it were throttling."""

STATUS_AUTH = 403
"""'Auth failures use HTTP `403`, not `401`.'"""
STATUS_QUOTA = 402
STATUS_RATE_LIMIT = 429
STATUSES_BAD_REQUEST: frozenset[int] = frozenset({400, 404, 413, 422})
STATUSES_RETRYABLE: frozenset[int] = frozenset({429, 500, 502, 503})
"""'Use retries only for 429, 500, 502 and 503: not for 400, 402, 403 or 422.'"""

RETRY_AFTER_HEADER = "Retry-After"
"""'honour `Retry-After` when it is present'. Its format is not documented;
only a plain number of seconds is honoured."""

# -- Models -----------------------------------------------------------------

PRICING_SOURCE = "https://docs.sarvam.ai/api-reference-docs/ratelimits (read 2026-11-15)"
PRICING_CURRENCY = "INR"
PRICES_EXCLUDE_GST = True
"""'All prices are in Indian Rupees (₹) and exclude GST.'"""


@dataclass(frozen=True, slots=True)
class SarvamModel:
    """What the documentation says about one model id."""

    model_id: str
    display_name: str
    context_window_tokens: int
    """The documented '128K' / '32K', read as thousands - the smaller of the
    two possible readings, so a request is refused early rather than late."""
    reasoning_documented: bool
    """Whether the model table lists reasoning for this model. Decides whether
    `reasoning_effort` is sent at all."""
    input_per_million: Decimal
    output_per_million: Decimal
    """₹ per 1M tokens, GST excluded. The cached-input discount is ignored,
    so an estimate can only err high."""


MODEL_105B = "sarvam-105b"
MODEL_105B_CONVERSATIONS = "sarvam-105b-conversations"

MODELS: dict[str, SarvamModel] = {
    MODEL_105B: SarvamModel(
        model_id=MODEL_105B,
        display_name="Sarvam 105B",
        context_window_tokens=128_000,
        reasoning_documented=True,
        input_per_million=Decimal(15),
        output_per_million=Decimal(60),
    ),
    MODEL_105B_CONVERSATIONS: SarvamModel(
        model_id=MODEL_105B_CONVERSATIONS,
        display_name="Sarvam 105B Conversations",
        context_window_tokens=32_000,
        reasoning_documented=False,
        input_per_million=Decimal(15),
        output_per_million=Decimal(60),
    ),
}
"""The two are separate entries on purpose. Today they differ in context
window and in whether reasoning is documented; their prices happen to match.
Nothing assumes they behave alike."""

# -- What the documentation does not settle ----------------------------------

DOCUMENTATION_GAPS: tuple[str, ...] = (
    "Authentication: the V1 reference lists `api-subscription-key` as required in "
    "one section and optional in another, and its SDK snippets use a bearer "
    "`Authorization` header. This client sends `api-subscription-key` only, as every "
    "documented cURL example does.",
    "Default temperature: 0.2 on the V1 reference; 0.5 when reasoning is enabled on "
    "the model page. This client always sends an explicit temperature so neither "
    "default applies.",
    "Default reasoning effort: `medium` on the V1 reference, `low` on the model page "
    "and model table. This client never relies on the default.",
    "Disabling reasoning: documented as 'explicitly setting to None', while the enum "
    "also lists the string `none`. This client sends JSON null. Unverified.",
    "`sarvam-105b-conversations` and reasoning: the model table says 'No'; whether "
    "the endpoint accepts, ignores or rejects `reasoning_effort` for it is not "
    "stated. The field is therefore not sent for that model, and whether it then "
    "reasons by default (and bills reasoning tokens against `max_tokens`) is unknown.",
    "Context windows are given as '128K' and '32K'; the exact token counts are not documented.",
    "No per-model maximum for `max_tokens` is documented, only per-plan caps "
    "(4096 on the lowest plan). Reasoning tokens count toward `max_tokens`.",
    "`seed` is 'in Beta' and 'best effort': 'Determinism is not guaranteed', and "
    "'Output is not bit-reproducible, even at `0`' temperature. A seed is recorded "
    "as sent, never as honoured.",
    "Structured output: `json_schema` is documented to guarantee a matching reply, "
    "but which JSON Schema keywords `strict` mode accepts is not documented.",
    "Error codes: the V1 reference's enum and the error page's table disagree "
    "(`authentication_error` appears only in the first; `model_overloaded`, "
    "`model_call_failed` and `model_rate_limit_exceeded_error` only in the second). "
    "The V1 reference does not list 402 or 503 for this endpoint; the error page does.",
    "`Retry-After`: mentioned as possibly present; neither its format nor when it is "
    "sent is documented.",
    "Whether a failed request (4xx/5xx or a timeout) is billed is not documented. "
    "Every request that leaves the process is charged at its worst case.",
    "The response `id` and an error's `request_id` share a documented format; whether "
    "they are the same identifier is not stated.",
    "Rate limits: 60 requests/minute on the pay-as-you-go plan for both models; the "
    "Business plan has no documented figure.",
    "Prices exclude GST and the documentation does not state the rate. The margin "
    "added on top is this project's configuration, not a vendor figure.",
)

__all__ = [
    "API_KEY_HEADER",
    "CHAT_COMPLETIONS_PATH",
    "DEFAULT_BASE_URL",
    "DOCUMENTATION_GAPS",
    "DOCUMENTATION_URL",
    "MODELS",
    "MODEL_105B",
    "MODEL_105B_CONVERSATIONS",
    "REASONING_EFFORTS",
    "VERIFIED_AGAINST_LIVE_SERVICE",
    "SarvamModel",
]
