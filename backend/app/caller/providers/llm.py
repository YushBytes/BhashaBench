"""The model-backed caller strategy, independent of any vendor.

Given an `LlmClient` it produces a caller turn the way the rule engine does -
a validated `CallerDecision` - and records how the turn came to be.

**Every turn ends one of two ways, and the evidence says which.** Either a
model's reply parsed, passed the validation gate and is what the caller says
(`generated_by_language_model=True`), or it did not and the deterministic
caller supplied the turn instead (`fallback_used=True`, with the reason). A
failure is never dressed as a generated turn, and a generated turn is never
silently swapped for a rule.

**The fallback is the rule engine and only the rule engine.** It is passed in
as a `CallerProvider`; there is no list of alternative models to try, so a
failing provider can never cause a request to a different paid one.

**Spending is bounded here, before a client is asked.** Each attempt is
allowed only if its worst-case cost fits what is left of the per-run limit.
Anything that was sent is charged - at the reported usage when the provider
gave it, at the worst case when it did not or when the request failed after
leaving the process. An unknown cost is never recorded as zero. (A live
client applies its own, global budget on top; this limit is per
conversation.)

The attempt limit counts every kind of failure together - a timeout, a rate
limit, an unusable reply, a reply the gate rejected - so no combination of
them can exceed `max_attempts` requests for one turn.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal

from app.caller.errors import InvalidCallerDecisionError
from app.caller.llm.decision import parse_decision
from app.caller.llm.errors import LlmError, LlmInvalidResponseError, LlmTimeoutError
from app.caller.llm.models import LlmRequest, LlmResponse
from app.caller.llm.pricing import (
    CostBasis,
    CostEstimate,
    prompt_token_upper_bound,
    worst_case_cost,
)
from app.caller.llm.prompt import (
    PROMPT_VERSION,
    allowed_next_states,
    build_messages,
    response_schema,
)
from app.caller.llm.protocol import LlmClient
from app.caller.protocol import CallerCapabilities, CallerProvider
from app.caller.schemas import (
    CallerContext,
    CallerDecision,
    GenerationAttempt,
    GenerationEvidence,
)
from app.caller.validation import validate_decision
from app.transcription.redaction import redact
from app.transcription.retry import RetryPolicy
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.caller.llm")

# Fallback reasons that are not an `LlmError.code`.
REASON_PROMPT_OVER_LIMIT = "prompt_over_limit"
REASON_RUN_COST_LIMIT = "run_cost_limit"
REASON_PRICING_UNKNOWN = "pricing_unknown"
REASON_NO_LEGAL_STATE = "no_legal_state"
REASON_VALIDATION_REJECTED = "validation_rejected"

_MAX_DETAIL_CHARS = 300


@dataclass(frozen=True, slots=True)
class LlmCallerLimits:
    """Every bound on what one turn, and one conversation, may consume."""

    max_output_tokens: int
    max_prompt_tokens: int
    """Compared with the prompt's upper bound, not a tokenizer's count."""
    max_attempts: int
    request_timeout_seconds: float
    max_message_chars: int
    max_cost_per_run: Decimal | None
    """In the client's pricing currency. `None` is only acceptable for a
    client that contacts nothing; a live client without a limit is refused."""
    temperature: float | None = None
    seed: int | None = None
    backoff: RetryPolicy = field(default_factory=RetryPolicy)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.max_output_tokens < 1 or self.max_prompt_tokens < 1:
            raise ValueError("token limits must be at least 1")
        if self.request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if self.max_cost_per_run is not None and self.max_cost_per_run <= 0:
            raise ValueError("max_cost_per_run must be positive when set")


class _Ledger:
    """What one turn has consumed so far, across its attempts."""

    def __init__(self) -> None:
        self.attempts: list[GenerationAttempt] = []
        self.cost = Decimal(0)
        self.currency: str | None = None
        self.bases: set[CostBasis] = set()
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None
        self.reasoning_tokens: int | None = None
        self.last_response: LlmResponse | None = None
        self.requests_sent = 0

    def charge(self, estimate: CostEstimate | None) -> None:
        if estimate is None:
            return
        self.cost += estimate.amount
        self.currency = estimate.currency
        self.bases.add(estimate.basis)

    def count(self, response: LlmResponse) -> None:
        """Add reported usage. A field nobody reported stays `None`."""
        self.last_response = response
        usage = response.usage
        if usage is None:
            return
        if usage.input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + usage.output_tokens
        if usage.reasoning_tokens is not None:
            self.reasoning_tokens = (self.reasoning_tokens or 0) + usage.reasoning_tokens

    @property
    def basis(self) -> str | None:
        if not self.bases:
            return None
        return next(iter(self.bases)).value if len(self.bases) == 1 else CostBasis.MIXED.value


def _one_line(text: object) -> str:
    """Redacted, single-line, bounded: fit for a database column and an API."""
    return " ".join(redact(text).split())[:_MAX_DETAIL_CHARS]


class LlmCallerProvider:
    """A `CallerProvider` whose words come from a language model."""

    def __init__(
        self,
        client: LlmClient,
        *,
        fallback: CallerProvider,
        limits: LlmCallerLimits,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        described = client.capabilities
        if described.contacts_external_service:
            # Refused at construction, so a live client can never be wired up
            # without the two things that bound what it can spend.
            if described.pricing is None:
                raise ValueError(
                    f"the '{described.provider}' client contacts an external service "
                    "but declares no pricing; its cost could not be bounded"
                )
            if limits.max_cost_per_run is None:
                raise ValueError(
                    f"the '{described.provider}' client contacts an external service; "
                    "a per-run cost limit is required"
                )
        self._client = client
        self._fallback = fallback
        self._limits = limits
        self._sleep = sleep
        self._rand = rand

    @property
    def capabilities(self) -> CallerCapabilities:
        described = self._client.capabilities
        fallback = self._fallback.capabilities
        return CallerCapabilities(
            name=described.provider,
            display_name=f"{described.display_name} ({described.model})",
            is_deterministic=False,
            uses_language_model=True,
            # The fallback must be able to take any turn, so a language it has
            # no reviewed phrases for cannot be offered at all.
            languages=fallback.languages,
            supports_code_mixing=True,
            requires_credentials=described.requires_credentials,
            max_turns_supported=None,
            notes=(
                f"Turns are generated by the model '{described.model}'. They are not "
                "reproducible: the same context can yield different words.",
                f"When generation fails or a reply is rejected, the '{fallback.name}' caller "
                "supplies the turn instead. Each turn's evidence records which happened; "
                "`uses_language_model` for a conversation is true only if a model actually "
                "produced at least one of its turns.",
                f"Languages are limited to those the '{fallback.name}' fallback covers.",
                *described.notes,
            ),
        )

    # -- One turn -----------------------------------------------------------

    async def decide(self, context: CallerContext) -> CallerDecision:
        """Generate the caller's next turn, or fall back and say why.

        Raises:
            CallerError: only if the deterministic fallback itself fails.
        """
        started = monotonic_seconds()
        ledger = _Ledger()
        described = self._client.capabilities
        limits = self._limits

        if not allowed_next_states(context):
            return await self._fall_back(
                context, ledger, started, REASON_NO_LEGAL_STATE, "no state is open to a model here"
            )

        messages = build_messages(context, max_message_chars=limits.max_message_chars)
        prompt_bound = prompt_token_upper_bound(messages)
        if prompt_bound > limits.max_prompt_tokens:
            return await self._fall_back(
                context,
                ledger,
                started,
                REASON_PROMPT_OVER_LIMIT,
                f"the prompt is at most {prompt_bound} tokens, over the "
                f"{limits.max_prompt_tokens} limit",
            )

        request = LlmRequest(
            messages=messages,
            max_output_tokens=limits.max_output_tokens,
            temperature=limits.temperature,
            seed=limits.seed if described.supports_seed else None,
            response_schema=(
                response_schema(context, max_message_chars=limits.max_message_chars)
                if described.supports_json_schema
                else None
            ),
            correlation_id=f"caller-{context.scenario_id}-{context.turn_index}",
        )
        worst = (
            worst_case_cost(
                described.pricing,
                prompt_tokens_upper_bound=prompt_bound,
                max_output_tokens=limits.max_output_tokens,
            )
            if described.pricing is not None
            else None
        )
        spent_before = Decimal(context.resources.estimated_cost)

        for attempt in range(1, limits.max_attempts + 1):
            if described.contacts_external_service and worst is None:
                ledger.attempts.append(
                    GenerationAttempt(
                        attempt=attempt, outcome=REASON_PRICING_UNKNOWN, request_sent=False
                    )
                )
                return await self._fall_back(
                    context, ledger, started, REASON_PRICING_UNKNOWN, "no price is configured"
                )
            if (
                worst is not None
                and limits.max_cost_per_run is not None
                and spent_before + ledger.cost + worst.amount > limits.max_cost_per_run
            ):
                detail = (
                    f"this request could cost up to {worst.amount} {worst.currency}; "
                    f"{spent_before + ledger.cost} of the {limits.max_cost_per_run} per-run "
                    "limit is already committed"
                )
                ledger.attempts.append(
                    GenerationAttempt(
                        attempt=attempt,
                        outcome=REASON_RUN_COST_LIMIT,
                        detail=detail,
                        request_sent=False,
                    )
                )
                return await self._fall_back(
                    context, ledger, started, REASON_RUN_COST_LIMIT, detail
                )

            attempt_started = monotonic_seconds()
            failure: LlmError | InvalidCallerDecisionError
            try:
                try:
                    response = await asyncio.wait_for(
                        self._client.complete(request), timeout=limits.request_timeout_seconds
                    )
                except TimeoutError as exc:
                    raise LlmTimeoutError(
                        f"no reply within {limits.request_timeout_seconds:g}s",
                        provider=described.provider,
                    ) from exc
            except LlmError as exc:
                failure = exc
                if exc.request_sent:
                    ledger.requests_sent += 1
                    # It left the process and may have been billed. With no
                    # usage to go on, the worst case is the only honest figure.
                    ledger.charge(worst)
                self._record_failure(ledger, attempt, exc.code, exc, attempt_started)
            else:
                ledger.requests_sent += 1
                ledger.count(response)
                ledger.charge(response.cost if response.cost is not None else worst)
                try:
                    decision = parse_decision(response.text, context, provider=described.provider)
                    validate_decision(
                        decision,
                        context,
                        max_message_chars=limits.max_message_chars,
                        provider=described.provider,
                    )
                except LlmError as exc:
                    failure = exc
                    self._record_failure(ledger, attempt, exc.code, exc, attempt_started)
                except InvalidCallerDecisionError as exc:
                    failure = exc
                    self._record_failure(
                        ledger, attempt, REASON_VALIDATION_REJECTED, exc, attempt_started
                    )
                else:
                    ledger.attempts.append(
                        GenerationAttempt(
                            attempt=attempt,
                            outcome="ok",
                            latency_ms=self._elapsed_ms(attempt_started),
                            request_sent=True,
                        )
                    )
                    evidence = self._evidence(
                        ledger, started, generated=True, reason=None, detail=None
                    )
                    self._log(context, evidence)
                    return decision.model_copy(update={"generation": evidence})

            # A reply the gate rejected is worth one more ask, like any other
            # unusable reply: a model asked again may well comply.
            gate_rejection = isinstance(failure, InvalidCallerDecisionError)
            reason = REASON_VALIDATION_REJECTED if gate_rejection else failure.code
            retryable = gate_rejection or failure.retryable
            # A refusal made locally (a disabled gate, an exhausted budget)
            # would be made again, so it is never retried.
            sent = gate_rejection or failure.request_sent
            if not retryable or not sent or attempt == limits.max_attempts:
                return await self._fall_back(context, ledger, started, reason, str(failure))

            if not gate_rejection and not isinstance(failure, LlmInvalidResponseError):
                # Back off only for the provider's sake; an unusable reply is
                # not load, and waiting would not change what a model says.
                await self._sleep(
                    limits.backoff.backoff_for(
                        attempt,
                        retry_after=getattr(failure, "retry_after", None),
                        rand=self._rand,
                    )
                )

        raise AssertionError(
            "unreachable: the loop returns on its last attempt"
        )  # pragma: no cover

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((monotonic_seconds() - started) * 1000, 3)

    def _record_failure(
        self,
        ledger: _Ledger,
        attempt: int,
        outcome: str,
        error: LlmError | InvalidCallerDecisionError,
        attempt_started: float,
    ) -> None:
        sent = True if isinstance(error, InvalidCallerDecisionError) else error.request_sent
        ledger.attempts.append(
            GenerationAttempt(
                attempt=attempt,
                outcome=outcome,
                error_type=type(error).__name__,
                detail=_one_line(error),
                latency_ms=self._elapsed_ms(attempt_started),
                request_sent=sent,
            )
        )

    def _evidence(
        self,
        ledger: _Ledger,
        started: float,
        *,
        generated: bool,
        reason: str | None,
        detail: str | None,
    ) -> GenerationEvidence:
        described = self._client.capabilities
        response = ledger.last_response
        sent = ledger.requests_sent > 0
        parameters = (
            dict(response.parameters)
            if response is not None
            else {
                "max_output_tokens": self._limits.max_output_tokens,
                "temperature": self._limits.temperature,
            }
        )
        return GenerationEvidence(
            provider=described.provider,
            model=described.model,
            model_reported=response.model_reported if response is not None else None,
            contacts_external_service=described.contacts_external_service,
            prompt_version=PROMPT_VERSION,
            parameters=parameters,
            seed_requested=self._limits.seed,
            seed_sent=bool(response is not None and response.seed_sent),
            # No client here can prove a seed was honoured, so this stays
            # unknown rather than being assumed from the request.
            seed_honoured=None,
            system_fingerprint=response.system_fingerprint if response is not None else None,
            provider_request_id=response.provider_request_id if response is not None else None,
            input_tokens=ledger.input_tokens,
            output_tokens=ledger.output_tokens,
            reasoning_tokens=ledger.reasoning_tokens,
            latency_ms=self._elapsed_ms(started),
            estimated_cost=str(ledger.cost) if sent and ledger.currency is not None else None,
            currency=ledger.currency if sent else None,
            cost_basis=ledger.basis if sent else None,
            attempts=tuple(ledger.attempts),
            retry_count=max(ledger.requests_sent - 1, 0),
            fallback_used=not generated,
            fallback_reason=reason,
            fallback_detail=_one_line(detail) if detail else None,
            generated_by_language_model=generated,
        )

    async def _fall_back(
        self,
        context: CallerContext,
        ledger: _Ledger,
        started: float,
        reason: str,
        detail: str,
    ) -> CallerDecision:
        """Let the deterministic caller take the turn, and record that it did."""
        decision = await self._fallback.decide(context)
        evidence = self._evidence(ledger, started, generated=False, reason=reason, detail=detail)
        self._log(context, evidence)
        return decision.model_copy(update={"generation": evidence})

    def _log(self, context: CallerContext, evidence: GenerationEvidence) -> None:
        log = logger.warning if evidence.fallback_used else logger.info
        log(
            "caller.llm_turn",
            extra={
                "provider": evidence.provider,
                "model": evidence.model,
                "turn_index": context.turn_index,
                "generated_by_language_model": evidence.generated_by_language_model,
                "fallback_reason": evidence.fallback_reason,
                "requests_sent": sum(1 for a in evidence.attempts if a.request_sent),
                "input_tokens": evidence.input_tokens,
                "output_tokens": evidence.output_tokens,
                "estimated_cost": evidence.estimated_cost,
                "currency": evidence.currency,
                "latency_ms": evidence.latency_ms,
                # Never the prompt, the reply or the scenario's facts.
            },
        )

    async def close(self) -> None:
        """Release the client and the fallback."""
        await self._client.close()
        await self._fallback.close()


__all__ = [
    "REASON_NO_LEGAL_STATE",
    "REASON_PRICING_UNKNOWN",
    "REASON_PROMPT_OVER_LIMIT",
    "REASON_RUN_COST_LIMIT",
    "REASON_VALIDATION_REJECTED",
    "LlmCallerLimits",
    "LlmCallerProvider",
]
