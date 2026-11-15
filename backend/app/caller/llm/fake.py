"""A scripted text-generation client for tests. Not a provider.

It replays a list of steps - a reply, a failure, a reply that arrives too
late - and records every request it was given, so a test can drive the whole
caller workflow with no network and then assert on exactly what a model would
have been sent.

**It is not registered anywhere.** There is no `CALLER_PROVIDER` value that
selects it and no setting that feeds it a script, so it cannot be configured
into a deployment by accident or on purpose: the only way to use it is to
construct it in code. Its capabilities say `contacts_external_service=False`,
and every turn it produces carries that flag in its evidence, so its simulated
token counts and costs can never be mistaken for spend.

It applies the same cost rules as a live client - reported usage when the
step has usage, the worst case when it does not - so the "unknown usage is
not zero" path is exercised without a vendor.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.caller.llm.errors import LlmBadRequestError, LlmError
from app.caller.llm.models import LlmCapabilities, LlmRequest, LlmResponse, LlmUsage
from app.caller.llm.pricing import (
    ModelPricing,
    cost_of_usage,
    prompt_token_upper_bound,
    worst_case_cost,
)

FAKE_PROVIDER = "scripted-fake"
FAKE_MODEL = "scripted-fake-1"


@dataclass(frozen=True, slots=True)
class Reply:
    """Answer with `text`, after `delay_seconds`."""

    text: str
    usage: LlmUsage | None = None
    """`None` simulates a provider that reports no token counts."""
    delay_seconds: float = 0.0
    """Simulated latency. Longer than the caller's timeout simulates a hang."""
    finish_reason: str | None = "stop"
    model_reported: str | None = FAKE_MODEL


@dataclass(frozen=True, slots=True)
class Fail:
    """Raise `error` instead of answering."""

    error: LlmError


Step = Reply | Fail


class ScriptedLlmClient:
    """An `LlmClient` that replays a script and records its requests."""

    def __init__(
        self,
        script: Sequence[Step],
        *,
        pricing: ModelPricing | None = None,
        supports_json_schema: bool = True,
        supports_seed: bool = True,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._script = list(script)
        self._pricing = pricing
        self._supports_json_schema = supports_json_schema
        self._supports_seed = supports_seed
        self._sleep = sleep
        self.requests: list[LlmRequest] = []
        self.closed = False

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(
            provider=FAKE_PROVIDER,
            display_name="Scripted fake (tests only)",
            model=FAKE_MODEL,
            contacts_external_service=False,
            requires_credentials=False,
            supports_seed=self._supports_seed,
            seed_is_verifiable=False,
            supports_json_schema=self._supports_json_schema,
            pricing=self._pricing,
            notes=(
                "A test double. It replays scripted text; nothing is generated "
                "and nothing leaves the process.",
            ),
        )

    @property
    def remaining(self) -> int:
        """Steps not yet consumed."""
        return len(self._script)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if not self._script:
            raise LlmBadRequestError(
                "the scripted client has no step left for this request", provider=FAKE_PROVIDER
            )
        step = self._script.pop(0)
        if isinstance(step, Fail):
            raise step.error

        if step.delay_seconds:
            await self._sleep(step.delay_seconds)

        cost = None
        if self._pricing is not None:
            cost = cost_of_usage(self._pricing, step.usage) or worst_case_cost(
                self._pricing,
                prompt_tokens_upper_bound=prompt_token_upper_bound(request.messages),
                max_output_tokens=request.max_output_tokens,
            )
        seed_sent = self._supports_seed and request.seed is not None
        parameters: dict[str, object] = {
            "model": FAKE_MODEL,
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "structured_output": self._supports_json_schema and request.response_schema is not None,
        }
        if seed_sent:
            parameters["seed"] = request.seed
        return LlmResponse(
            text=step.text,
            provider=FAKE_PROVIDER,
            model_requested=FAKE_MODEL,
            model_reported=step.model_reported,
            usage=step.usage,
            finish_reason=step.finish_reason,
            latency_ms=round(step.delay_seconds * 1000, 3),
            parameters=parameters,
            seed_sent=seed_sent,
            cost=cost,
        )

    async def close(self) -> None:
        self.closed = True


__all__ = ["FAKE_MODEL", "FAKE_PROVIDER", "Fail", "Reply", "ScriptedLlmClient", "Step"]
