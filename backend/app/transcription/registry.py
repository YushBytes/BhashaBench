"""Provider registration and selection.

A dict of factories and one lookup function. That is the whole mechanism, and
it is deliberate: a plugin system with entry points would let a provider be
installed without appearing in this file, and "which engine produced this
score?" is a question a benchmark must always be able to answer by reading the
source.

Adding a provider in a later phase means writing an adapter and adding one
entry to `_FACTORIES`. Nothing in `app/services` or `app/api` changes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.config import AppEnv, Settings
from app.transcription.base import TranscriptionProvider
from app.transcription.errors import ConfigurationError
from app.transcription.providers.fake import PROVIDER_NAME as FAKE_PROVIDER
from app.transcription.providers.fake import FakeTranscriptionProvider
from app.transcription.providers.prisma import PROVIDER_NAME as PRISMA_PROVIDER
from app.transcription.providers.prisma import GnaniPrismaProvider
from app.transcription.redaction import mask_secret

logger = logging.getLogger("bhashabench.transcription.registry")

ProviderFactory = Callable[[Settings], TranscriptionProvider]


def _build_prisma(settings: Settings) -> TranscriptionProvider:
    """Construct the Gnani Prisma adapter from settings.

    The missing-key check lives here rather than in the adapter so the message
    names the environment variable the operator has to set. An adapter that
    raised "api_key is required" would be correct and useless.
    """
    if not settings.gnani_api_key:
        raise ConfigurationError(
            "TRANSCRIPTION_PROVIDER=prisma requires GNANI_API_KEY to be set. "
            "Obtain a key from your Gnani account dashboard at app.gnani.ai, "
            "put it in your local .env, and never commit it. For tests and "
            "local development without credentials, set TRANSCRIPTION_PROVIDER=fake.",
            provider=PRISMA_PROVIDER,
        )

    return GnaniPrismaProvider(
        api_key=settings.gnani_api_key,
        base_url=settings.gnani_api_base_url,
        model=settings.gnani_stt_model,
        timeout_seconds=settings.transcription_timeout_seconds,
        max_audio_bytes=settings.transcription_max_upload_bytes,
    )


def _build_fake(settings: Settings) -> TranscriptionProvider:
    """Construct the offline fake.

    Refuses to run in production. The fake returns scripted text, so a
    production deployment that selected it would publish fabricated transcripts
    and report them as measurements - the exact failure mode this project's
    first rule forbids. Failing at startup is the only safe behaviour.
    """
    if settings.app_env is AppEnv.PRODUCTION:
        raise ConfigurationError(
            "TRANSCRIPTION_PROVIDER=fake is refused when APP_ENV=production: the "
            "fake provider returns scripted transcripts, not recognised speech. "
            "Configure a real provider.",
            provider=FAKE_PROVIDER,
        )
    return FakeTranscriptionProvider()


_FACTORIES: dict[str, ProviderFactory] = {
    PRISMA_PROVIDER: _build_prisma,
    FAKE_PROVIDER: _build_fake,
}


def available_providers() -> tuple[str, ...]:
    """Registered provider names, sorted for stable messages and listings."""
    return tuple(sorted(_FACTORIES))


def build_provider(settings: Settings, name: str | None = None) -> TranscriptionProvider:
    """Construct the configured provider.

    Args:
        settings: Application settings.
        name: Override the configured provider. Used by tests and by the
            capability endpoint, which describes every provider rather than
            only the selected one.

    Raises:
        ConfigurationError: unknown name, missing credential, or a provider
            that may not run in this environment.
    """
    selected = (name or settings.transcription_provider).strip().lower()

    factory = _FACTORIES.get(selected)
    if factory is None:
        raise ConfigurationError(
            f"'{selected}' is not a known transcription provider; "
            f"available providers are {list(available_providers())}"
        )

    provider = factory(settings)

    logger.info(
        "transcription.provider_selected",
        extra={
            "provider": selected,
            "environment": str(settings.app_env),
            # A fingerprint, never the key: enough to tell two environments
            # apart in a log, not enough to authenticate with.
            "credential": mask_secret(settings.gnani_api_key)
            if selected == PRISMA_PROVIDER
            else "<not required>",
        },
    )
    return provider


def describe_providers(settings: Settings) -> list[tuple[str, object | None, str | None]]:
    """Describe every registered provider, configured or not.

    Returns `(name, capabilities, unavailable_reason)` per provider. A provider
    that cannot be constructed here is reported with its reason rather than
    omitted: "prisma is not listed" and "prisma has no API key" look identical
    to a developer, and only one of them is true.

    Capabilities are static metadata, so constructing a provider to read them
    opens no connection.
    """
    described: list[tuple[str, object | None, str | None]] = []
    for name in available_providers():
        try:
            provider = build_provider(settings, name)
        except ConfigurationError as exc:
            described.append((name, None, str(exc)))
            continue
        described.append((name, provider.capabilities, None))
    return described


__all__ = ["ProviderFactory", "available_providers", "build_provider", "describe_providers"]
