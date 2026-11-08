"""Caller provider registration and selection.

Same shape as the transcription and speech registries - a dict of factories and
one lookup. Phase 6 registers exactly one provider.

**There is no `evon` entry, and adding a stub would be worse than the gap.**
Gate A established that Gnani documents no text-generation endpoint and that
`gnani/gnani-evon-v3.3-30B-A3B` has no hosted inference provider. A registered
name that raised on every call would make `SPEECH`-style capability listings
advertise Evon as a configurable option, and the first person to set
`CALLER_PROVIDER=evon` would get a runtime failure instead of the honest answer
they get now: that it is not a known provider.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.caller.errors import CallerConfigurationError
from app.caller.protocol import CallerProvider
from app.caller.providers.deterministic import PROVIDER_NAME as DETERMINISTIC_PROVIDER
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.core.config import Settings

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


_FACTORIES: dict[str, ProviderFactory] = {
    DETERMINISTIC_PROVIDER: _build_deterministic,
}


def available_providers() -> tuple[str, ...]:
    """Registered provider names, sorted for stable messages."""
    return tuple(sorted(_FACTORIES))


def build_provider(settings: Settings, name: str | None = None) -> CallerProvider:
    """Construct the configured caller provider.

    Raises:
        CallerConfigurationError: unknown name.
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
