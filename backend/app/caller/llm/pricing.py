"""Token prices and the cost arithmetic built on them.

`Decimal` throughout. A budget is compared against a ceiling, and a float sum
of many small amounts drifts in the direction nobody checks.

Three rules this module exists to make hard to break:

* **An unknown price is not zero.** A model with no `ModelPricing` cannot be
  costed, and the caller refuses to send rather than assume it is free.
* **Unknown usage is not zero.** When a provider returns no token counts the
  request is charged at its worst case - the prompt's upper bound plus every
  output token it was allowed to produce.
* **The estimate errs high.** Cached-input discounts are ignored, and a
  `margin` covers what a published price leaves out (tax, for one).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from enum import StrEnum

from app.caller.llm.models import LlmMessage, LlmUsage

_MILLION = Decimal(1_000_000)
_QUANTUM = Decimal("0.000001")

PER_MESSAGE_TOKEN_OVERHEAD = 16
REQUEST_TOKEN_OVERHEAD = 64
"""Allowance for the role markers and template a chat API wraps around the
text. Not a vendor figure - no vendor publishes one - so it is set generously
and the real count replaces the estimate whenever usage is reported."""


class CostBasis(StrEnum):
    """What a cost figure was computed from."""

    REPORTED_USAGE = "reported_usage"
    WORST_CASE = "worst_case"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """What one model costs, and where that figure came from."""

    currency: str
    input_per_million: Decimal
    output_per_million: Decimal
    source: str
    """Where the prices were read, so a stale figure can be traced."""
    margin: Decimal = Decimal(0)
    """Fraction added on top, e.g. `0.18` for tax a published price excludes."""

    def __post_init__(self) -> None:
        if self.input_per_million <= 0 or self.output_per_million <= 0:
            raise ValueError("token prices must be positive; an unknown price is not zero")
        if self.margin < 0:
            raise ValueError("margin must not be negative")

    def cost(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        """Cost of a request with these token counts, margin included, rounded up."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must not be negative")
        raw = (
            Decimal(input_tokens) * self.input_per_million
            + Decimal(output_tokens) * self.output_per_million
        ) / _MILLION
        return (raw * (1 + self.margin)).quantize(_QUANTUM, rounding=ROUND_UP)


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """A cost and what it was computed from."""

    amount: Decimal
    currency: str
    basis: CostBasis


def prompt_token_upper_bound(messages: Iterable[LlmMessage]) -> int:
    """An upper bound on the prompt's token count, without a tokenizer.

    Counts UTF-8 bytes: a token covers at least one byte of text in every
    byte-level tokenizer, so the byte count cannot be below the token count.
    That makes Indic text look several times costlier than it is, which is the
    safe direction for a number used only to refuse.
    """
    total = REQUEST_TOKEN_OVERHEAD
    for message in messages:
        total += len(message.content.encode("utf-8")) + PER_MESSAGE_TOKEN_OVERHEAD
    return total


def worst_case_cost(
    pricing: ModelPricing, *, prompt_tokens_upper_bound: int, max_output_tokens: int
) -> CostEstimate:
    """The most a request can cost: the whole prompt bound and every output token."""
    return CostEstimate(
        amount=pricing.cost(
            input_tokens=prompt_tokens_upper_bound, output_tokens=max_output_tokens
        ),
        currency=pricing.currency,
        basis=CostBasis.WORST_CASE,
    )


def cost_of_usage(pricing: ModelPricing, usage: LlmUsage | None) -> CostEstimate | None:
    """Cost from reported token counts, or `None` when they are not all known.

    `None` means "cannot be computed from usage" - the caller then keeps the
    worst case. It never means the request was free.
    """
    if usage is None or usage.input_tokens is None or usage.output_tokens is None:
        return None
    return CostEstimate(
        amount=pricing.cost(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens),
        currency=pricing.currency,
        basis=CostBasis.REPORTED_USAGE,
    )


__all__ = [
    "PER_MESSAGE_TOKEN_OVERHEAD",
    "REQUEST_TOKEN_OVERHEAD",
    "CostBasis",
    "CostEstimate",
    "ModelPricing",
    "cost_of_usage",
    "prompt_token_upper_bound",
    "worst_case_cost",
]
