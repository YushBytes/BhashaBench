"""Synthesis provider registration and selection.

Deliberately the same shape as `app.transcription.registry` - a dict of
factories and one lookup - rather than a shared generic registry the two
subsystems import. A generic one would have to be parameterised over the
protocol, the error type and the settings fields, which is more machinery than
two dicts and makes "which engine spoke this line?" harder to answer by
reading the source. Duplicating thirty lines is the cheaper mistake.

Adding a provider means writing an adapter and adding one entry to
`_FACTORIES`. Nothing in `app/api` or the caller agent changes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.config import AppEnv, Settings
from app.speech.base import SynthesisProvider
from app.speech.errors import SpeechConfigurationError
from app.speech.providers.fake import PROVIDER_NAME as FAKE_PROVIDER
from app.speech.providers.fake import FakeSynthesisProvider
from app.speech.providers.timbre import PROVIDER_NAME as TIMBRE_PROVIDER
from app.speech.providers.timbre import GnaniTimbreProvider
from app.transcription.redaction import mask_secret

logger = logging.getLogger("bhashabench.speech.registry")

ProviderFactory = Callable[[Settings], SynthesisProvider]


def _build_timbre(settings: Settings) -> SynthesisProvider:
    """Construct the Gnani Timbre adapter from settings.

    Reuses `GNANI_API_KEY`. The vendor documents one key per account across the
    platform and one `X-API-Key-ID` header for both STT and TTS, so a second
    credential setting would be a variable nobody can fill in.

    Worth knowing when a 403 appears: one key does not guarantee both scopes.
    The adapter's 403 message says so, because "forbidden" on a key that
    demonstrably works for Prisma is otherwise baffling.
    """
    if not settings.gnani_api_key:
        raise SpeechConfigurationError(
            "SPEECH_PROVIDER=timbre requires GNANI_API_KEY to be set. It is the "
            "same key Prisma speech-to-text uses - obtain one from your Gnani "
            "dashboard at app.gnani.ai, put it in your local .env, and never "
            "commit it. For tests and local development without credentials, "
            "set SPEECH_PROVIDER=fake.",
            provider=TIMBRE_PROVIDER,
        )

    return GnaniTimbreProvider(
        api_key=settings.gnani_api_key,
        base_url=settings.gnani_api_base_url,
        model=settings.gnani_tts_model,
        default_voice=settings.gnani_tts_voice,
        timeout_seconds=settings.speech_timeout_seconds,
        max_text_chars=settings.speech_max_text_chars,
    )


def _build_fake(settings: Settings) -> SynthesisProvider:
    """Construct the offline fake.

    Refused in production: it returns a synthesised tone, not speech. A
    deployment that selected it would play a sine wave at a bot under test and
    score the result, which is the same class of dishonesty as a fabricated
    transcript.
    """
    if settings.app_env is AppEnv.PRODUCTION:
        raise SpeechConfigurationError(
            "SPEECH_PROVIDER=fake is refused when APP_ENV=production: the fake "
            "provider returns a synthesised tone, not speech. Configure a real "
            "provider.",
            provider=FAKE_PROVIDER,
        )
    return FakeSynthesisProvider()


_FACTORIES: dict[str, ProviderFactory] = {
    TIMBRE_PROVIDER: _build_timbre,
    FAKE_PROVIDER: _build_fake,
}


def available_providers() -> tuple[str, ...]:
    """Registered provider names, sorted for stable messages and listings."""
    return tuple(sorted(_FACTORIES))


def build_provider(settings: Settings, name: str | None = None) -> SynthesisProvider:
    """Construct the configured synthesis provider.

    Raises:
        SpeechConfigurationError: unknown name, missing credential, or a
            provider that may not run in this environment.
    """
    selected = (name or settings.speech_provider).strip().lower()

    factory = _FACTORIES.get(selected)
    if factory is None:
        raise SpeechConfigurationError(
            f"'{selected}' is not a known speech provider; "
            f"available providers are {list(available_providers())}"
        )

    provider = factory(settings)

    logger.info(
        "speech.provider_selected",
        extra={
            "provider": selected,
            "environment": str(settings.app_env),
            "credential": mask_secret(settings.gnani_api_key)
            if selected == TIMBRE_PROVIDER
            else "<not required>",
        },
    )
    return provider


def describe_providers(settings: Settings) -> list[tuple[str, object | None, str | None]]:
    """Describe every registered provider, configured or not.

    Returns `(name, capabilities, unavailable_reason)`. A provider that cannot
    be constructed is reported with its reason rather than omitted - an absent
    entry and an unconfigured one look identical to a caller, and only one of
    them is true.
    """
    described: list[tuple[str, object | None, str | None]] = []
    for name in available_providers():
        try:
            provider = build_provider(settings, name)
        except SpeechConfigurationError as exc:
            described.append((name, None, str(exc)))
            continue
        described.append((name, provider.capabilities, None))
    return described


__all__ = ["ProviderFactory", "available_providers", "build_provider", "describe_providers"]
