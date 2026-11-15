"""Vendor-neutral request and response types for text generation.

Nothing here names a vendor field. A client translates these to and from its
own wire format, so the caller strategy above it never sees `max_tokens`,
`choices` or `prompt_tokens`.

**Optional means optional.** A provider that reports no token usage yields
`usage=None`, not zeros; a response that names no model yields
`model_reported=None`, not an echo of the request. Every consumer downstream
treats `None` as "not reported", and the cost arithmetic treats it as "charge
the worst case".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.caller.llm.pricing import CostEstimate, ModelPricing


class LlmRole(StrEnum):
    """Who a message is from."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    """One message of a prompt."""

    role: LlmRole
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    """What the caller asks a model for."""

    messages: tuple[LlmMessage, ...]
    max_output_tokens: int
    temperature: float | None = None
    seed: int | None = None
    response_schema: dict[str, Any] | None = None
    """A JSON Schema the reply must satisfy, when the client supports one."""
    schema_name: str = "caller_turn"
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("a request needs at least one message")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1")


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Token counts as the provider reported them. `None` is "not reported"."""

    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LlmResponse:
    """What a model returned, and the evidence that came with it."""

    text: str
    provider: str
    model_requested: str
    model_reported: str | None
    usage: LlmUsage | None
    finish_reason: str | None
    latency_ms: float
    parameters: dict[str, Any] = field(default_factory=dict)
    """The generation parameters as sent. Never a credential or a header."""
    seed_sent: bool = False
    system_fingerprint: str | None = None
    provider_request_id: str | None = None
    cost: CostEstimate | None = None
    """What this request is charged at: from usage when reported, otherwise
    the worst case. `None` only when the client has no pricing at all, which a
    live client is never allowed to be."""


@dataclass(frozen=True, slots=True)
class LlmCapabilities:
    """What a text-generation client can do, declared rather than discovered."""

    provider: str
    display_name: str
    model: str
    contacts_external_service: bool
    """False for an offline double. Its usage and cost are simulated."""
    requires_credentials: bool
    supports_seed: bool
    seed_is_verifiable: bool
    """Whether a response can show that the seed was honoured. False for a
    best-effort seed, so evidence records `seed_honoured=None`, never True."""
    supports_json_schema: bool
    context_window_tokens: int | None = None
    pricing: ModelPricing | None = None
    notes: tuple[str, ...] = ()


__all__ = [
    "LlmCapabilities",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "LlmRole",
    "LlmUsage",
]
