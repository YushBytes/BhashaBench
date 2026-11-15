"""Caller provider registration and selection.

Same shape as the transcription and speech registries - a dict of factories and
one lookup. Two providers are registered:

* `deterministic` - the rule engine. The default, and the only one that can
  produce a turn today.
* `sarvam` - a Sarvam model asked for each turn, with the rule engine as its
  fallback. Implemented from the published documentation and tested offline;
  **not verified against the live service, and not able to contact it**: live
  calls are unauthorised in code (`app/caller/llm/budget.py`), so every turn
  it is asked for is a fallback whose evidence says `live_calls_disabled`.

**There is no `evon` entry, and adding a stub would be worse than the gap.**
Gate A established that Gnani documents no text-generation endpoint and that
`gnani/gnani-evon-v3.3-30B-A3B` has no hosted inference provider. A registered
name that raised on every call would advertise Evon as a configurable option,
and the first person to set `CALLER_PROVIDER=evon` would get a runtime failure
instead of the honest answer they get now: that it is not a known provider.
Sarvam is different in kind - its contract is published and cited - which is
why it is registered and Evon is not.

**The scripted test client is not registered either.** No configuration value
selects it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.caller.errors import CallerConfigurationError
from app.caller.llm.budget import HARD_LIVE_BUDGET_INR, shared_budget
from app.caller.llm.clients import sarvam_contract
from app.caller.llm.clients.sarvam import PROVIDER_NAME as SARVAM_PROVIDER
from app.caller.llm.clients.sarvam import SarvamChatClient
from app.caller.protocol import CallerProvider
from app.caller.providers.deterministic import PROVIDER_NAME as DETERMINISTIC_PROVIDER
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.providers.llm import LlmCallerLimits, LlmCallerProvider
from app.core.config import Settings
from app.transcription.retry import RetryPolicy

logger = logging.getLogger("bhashabench.caller.registry")

ProviderFactory = Callable[[Settings], CallerProvider]


def _build_deterministic(settings: Settings) -> CallerProvider:
    """Construct the rule-based caller.

    Needs no credentials, which is why the default caller works in CI and on a
    fresh checkout - unlike the speech providers, whose defaults are fakes.
    This provider is not a fake: it is the real Phase 6 implementation, and
    nothing about it pretends to be a model.
    """
    return DeterministicCallerProvider(max_clarifications=settings.caller_max_clarifications)


def _build_sarvam(settings: Settings) -> CallerProvider:
    """Construct the Sarvam-backed caller for the explicitly configured model.

    Building it sends nothing and needs no key: with live calls off it only
    ever falls back. A key is demanded here once the operator switch is on, so
    a misconfiguration is reported at selection rather than on the first turn.

    Raises:
        CallerConfigurationError: no model chosen, an unknown model, a
            reasoning effort the model does not document, or live calls
            switched on without a key or a budget.
    """
    model = settings.caller_llm_model
    supported = sorted(sarvam_contract.MODELS)
    if not model:
        raise CallerConfigurationError(
            "CALLER_PROVIDER=sarvam needs CALLER_LLM_MODEL set explicitly to one of "
            f"{supported}; there is no default model"
        )
    if model not in sarvam_contract.MODELS:
        raise CallerConfigurationError(
            f"CALLER_LLM_MODEL='{model}' is not a documented Sarvam chat model; "
            f"supported models are {supported}"
        )

    api_key = settings.sarvam_api_key.get_secret_value()
    if settings.caller_llm_live_calls_enabled:
        if not api_key:
            raise CallerConfigurationError(
                "CALLER_LLM_LIVE_CALLS_ENABLED is true but SARVAM_API_KEY is not set"
            )
        if settings.caller_llm_live_budget_inr <= 0:
            raise CallerConfigurationError(
                "CALLER_LLM_LIVE_CALLS_ENABLED is true but CALLER_LLM_LIVE_BUDGET_INR is "
                f"zero; choose a budget of at most {HARD_LIVE_BUDGET_INR} rupees"
            )

    try:
        client = SarvamChatClient(
            model=model,
            api_key=api_key,
            budget=shared_budget(
                settings.caller_llm_budget_ledger,
                settings.caller_llm_live_budget_inr,
                SARVAM_PROVIDER,
            ),
            live_calls_enabled=settings.caller_llm_live_calls_enabled,
            base_url=settings.sarvam_api_base_url,
            timeout_seconds=settings.caller_llm_request_timeout_seconds,
            cost_margin=settings.caller_llm_cost_margin,
            reasoning_effort=settings.caller_llm_reasoning_effort or None,
        )
    except ValueError as exc:
        raise CallerConfigurationError(f"the Sarvam caller is misconfigured: {exc}") from exc

    return LlmCallerProvider(
        client,
        # The rule engine and nothing else: there is no second model to try,
        # so a failing provider can never cause a request to another paid one.
        fallback=_build_deterministic(settings),
        limits=LlmCallerLimits(
            max_output_tokens=settings.caller_llm_max_output_tokens,
            max_prompt_tokens=settings.caller_llm_max_prompt_tokens,
            max_attempts=settings.caller_llm_max_attempts,
            request_timeout_seconds=settings.caller_llm_request_timeout_seconds,
            max_message_chars=settings.caller_max_message_chars,
            max_cost_per_run=settings.caller_llm_max_cost_per_run_inr,
            temperature=settings.caller_llm_temperature,
            seed=settings.caller_llm_seed,
            backoff=RetryPolicy(max_attempts=settings.caller_llm_max_attempts),
        ),
    )


_FACTORIES: dict[str, ProviderFactory] = {
    DETERMINISTIC_PROVIDER: _build_deterministic,
    SARVAM_PROVIDER: _build_sarvam,
}


def available_providers() -> tuple[str, ...]:
    """Registered provider names, sorted for stable messages."""
    return tuple(sorted(_FACTORIES))


def build_provider(settings: Settings, name: str | None = None) -> CallerProvider:
    """Construct the configured caller provider.

    Raises:
        CallerConfigurationError: unknown name, or a provider that is
            registered and misconfigured.
    """
    selected = (name or settings.caller_provider).strip().lower()

    factory = _FACTORIES.get(selected)
    if factory is None:
        raise CallerConfigurationError(
            f"'{selected}' is not a known caller provider; available providers "
            f"are {list(available_providers())}. Gnani Evon is not available: "
            "no text-generation endpoint is documented and the published model "
            "has no hosted inference provider."
        )

    provider = factory(settings)
    logger.info(
        "caller.provider_selected",
        extra={
            "provider": selected,
            "environment": str(settings.app_env),
            "uses_language_model": provider.capabilities.uses_language_model,
        },
    )
    return provider


def describe_providers(settings: Settings) -> list[tuple[str, object | None, str | None]]:
    """Describe every registered provider, configured or not."""
    described: list[tuple[str, object | None, str | None]] = []
    for name in available_providers():
        try:
            provider = build_provider(settings, name)
        except CallerConfigurationError as exc:
            described.append((name, None, str(exc)))
            continue
        described.append((name, provider.capabilities, None))
    return described


__all__ = ["ProviderFactory", "available_providers", "build_provider", "describe_providers"]
