"""Speech-synthesis endpoints.

Two of them, mirroring the transcription surface: generate audio, and ask what
the provider can do.

**The success response is binary audio, not JSON.** That is the right shape for
a caller that is going to hand the bytes to a telephony stream (Phase 9) -
base64 inside a JSON envelope would inflate every utterance by a third and
force a decode step on the only consumer. The cost is that metadata cannot
travel in the body, so it travels in `X-Speech-*` response headers, documented
below. Errors remain JSON, in the project's standard envelope.

`async def` for the same reason as the transcription routes: no database is
touched, and the work is entirely network-bound.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import SettingsDep
from app.core import languages
from app.schemas.common import ErrorResponse
from app.schemas.speech import (
    SpeechGenerateRequest,
    SpeechProviderListResponse,
    SpeechProviderResponse,
    VoiceResponse,
)
from app.speech.base import SynthesisCapabilities
from app.speech.models import AudioConfig
from app.speech.registry import build_provider, describe_providers
from app.speech.service import SpeechService

logger = logging.getLogger("bhashabench.api.speech")

router = APIRouter(prefix="/speech", tags=["speech"])


def get_speech_service_factory(settings: SettingsDep) -> Callable[[], SpeechService]:
    """Return a callable that builds the configured speech service.

    A factory for the same reason the transcription one is: it defers
    construction, and it is the single override point a test replaces to swap
    in the offline fake for every route at once.
    """
    return lambda: SpeechService(build_provider(settings), settings=settings)


SpeechServiceFactoryDep = Annotated[
    Callable[[], SpeechService], Depends(get_speech_service_factory)
]


async def get_speech_service(
    factory: SpeechServiceFactoryDep,
) -> AsyncIterator[SpeechService]:
    """Provide a speech service for one request, and close it after.

    A dependency with `yield`, like `get_db` and the transcription equivalent:
    the provider and its HTTP client are built per request, so the teardown has
    to run whether the handler returned or raised. Phase 4 shipped this leak
    once already - a route-local `try/finally` is the version a later route
    forgets.
    """
    service = factory()
    try:
        yield service
    finally:
        await service.close()


SpeechServiceDep = Annotated[SpeechService, Depends(get_speech_service)]


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    summary="Synthesise speech from text",
    description=(
        "Renders text as audio and returns the **binary audio** with the "
        "container's media type - `audio/wav` by default. This is not a JSON "
        "endpoint on success.\n\n"
        "Metadata that cannot travel in a binary body is returned in headers:\n"
        "- `X-Speech-Provider`, `X-Speech-Model`, `X-Speech-Voice`\n"
        "- `X-Speech-Language` (the value sent to the provider)\n"
        "- `X-Speech-Container`, `X-Speech-Size-Bytes`, `X-Speech-Latency-Ms`\n"
        "- `X-Speech-Sample-Rate-Hz`, `X-Speech-Duration-Seconds` - present "
        "**only when they could be verified from the returned audio**. A WAV "
        "carries a header so both are exact; an MP3 does not, so they are "
        "omitted rather than echoed back from the request.\n"
        "- `X-Speech-Requested-Sample-Rate-Hz`, always present, so a provider "
        "that ignored the request is visible.\n"
        "- `X-Speech-Correlation-Id`, when you supplied one.\n\n"
        "Errors are JSON in the standard error envelope."
    ),
    responses={
        status.HTTP_200_OK: {
            "description": "Binary audio in the requested container.",
            "content": {
                "audio/wav": {"schema": {"type": "string", "format": "binary"}},
                "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
                "audio/ogg": {"schema": {"type": "string", "format": "binary"}},
                "audio/basic": {"schema": {"type": "string", "format": "binary"}},
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "model": ErrorResponse,
            "description": "A container, encoding, sample rate, speed or audio tag "
            "the provider does not support.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "Empty or over-long text, an unknown voice, or a language "
            "the provider cannot speak.",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "The provider is rate limiting.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": ErrorResponse,
            "description": "The provider was unreachable, rejected our credentials, "
            "or returned something that is not usable audio.",
        },
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "model": ErrorResponse,
            "description": "The provider did not respond in time.",
        },
    },
)
async def generate_speech(
    payload: SpeechGenerateRequest,
    service: SpeechServiceDep,
) -> Response:
    """Synthesise `payload.text` and return the audio."""
    result = await service.synthesise(
        payload.text,
        language=payload.language,
        voice=payload.voice,
        model=payload.model,
        speed=payload.speed,
        audio=AudioConfig(
            container=payload.container,
            encoding=payload.encoding,
            sample_rate_hz=payload.sample_rate_hz,
            channels=payload.channels,
            sample_width_bytes=payload.sample_width_bytes,
            bitrate=payload.bitrate,
        ),
        correlation_id=payload.correlation_id,
    )

    headers = {
        "X-Speech-Provider": result.provider,
        "X-Speech-Model": result.model,
        "X-Speech-Language": result.language,
        "X-Speech-Container": result.container.value,
        "X-Speech-Size-Bytes": str(result.size_bytes),
        "X-Speech-Latency-Ms": f"{result.latency_ms:.3f}",
        "X-Speech-Requested-Sample-Rate-Hz": str(result.requested_sample_rate_hz),
        "X-Speech-Attempts": str(result.attempts),
    }
    # Only what was actually established. An absent header means "not
    # measurable", which is a different statement from a wrong number.
    if result.voice:
        headers["X-Speech-Voice"] = result.voice
    if result.sample_rate_hz is not None:
        headers["X-Speech-Sample-Rate-Hz"] = str(result.sample_rate_hz)
    if result.duration_seconds is not None:
        headers["X-Speech-Duration-Seconds"] = f"{result.duration_seconds:.3f}"
    if result.channels is not None:
        headers["X-Speech-Channels"] = str(result.channels)
    if payload.correlation_id:
        headers["X-Speech-Correlation-Id"] = payload.correlation_id

    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers=headers,
    )


@router.get(
    "/providers",
    response_model=SpeechProviderListResponse,
    summary="List speech providers, voices and capabilities",
    description=(
        "Describes every registered synthesis provider, whether or not it is "
        "currently usable. A provider missing a credential is listed as "
        "`available: false` with the reason - never omitted, because an absent "
        "entry and an unconfigured one look identical to a caller.\n\n"
        "`voices` carries each voice's catalogued character, which is what "
        "makes it possible to match a voice to a scenario persona. "
        "`voices_are_exhaustive: false` means the provider has more voices than "
        "are documented, so an unlisted name is forwarded rather than refused. "
        "`notes` carries verified vendor documentation gaps."
    ),
)
def list_speech_providers(settings: SettingsDep) -> SpeechProviderListResponse:
    """Describe all registered synthesis providers.

    Synchronous: static metadata, no connection opened.
    """
    catalogue = set(languages.SUPPORTED_CODES)
    described: list[SpeechProviderResponse] = []

    for name, capabilities, reason in describe_providers(settings):
        if capabilities is None:
            described.append(_unavailable(name, reason, selected=name == settings.speech_provider))
            continue
        if not isinstance(capabilities, SynthesisCapabilities):  # pragma: no cover
            raise TypeError(f"provider '{name}' reported unusable capabilities")

        described.append(
            SpeechProviderResponse(
                name=capabilities.name,
                display_name=capabilities.display_name,
                selected=capabilities.name == settings.speech_provider,
                available=True,
                unavailable_reason=None,
                languages=sorted(capabilities.languages),
                extra_language_values=sorted(capabilities.extra_language_values),
                unsupported_catalogue_languages=sorted(catalogue - capabilities.languages),
                voices=[
                    VoiceResponse(name=v.name, gender=v.gender, character=v.character)
                    for v in capabilities.voices
                ],
                voices_are_exhaustive=capabilities.voices_are_exhaustive,
                models=sorted(capabilities.models),
                default_model=capabilities.default_model,
                containers=sorted(capabilities.containers),
                encodings=sorted(capabilities.encodings),
                sample_rates=sorted(capabilities.sample_rates),
                speed_min=capabilities.speed_range[0] if capabilities.speed_range else None,
                speed_max=capabilities.speed_range[1] if capabilities.speed_range else None,
                speed_aliases=sorted(capabilities.speed_aliases),
                audio_tags=list(capabilities.audio_tags),
                supports_audio_tags=capabilities.supports_audio_tags,
                supports_streaming=capabilities.supports_streaming,
                max_text_chars=capabilities.max_text_chars,
                requires_credentials=capabilities.requires_credentials,
                serialises_requests=capabilities.serialises_requests,
                notes=list(capabilities.notes),
            )
        )

    return SpeechProviderListResponse(selected=settings.speech_provider, providers=described)


def _unavailable(name: str, reason: str | None, *, selected: bool) -> SpeechProviderResponse:
    """Describe a provider that cannot currently be constructed.

    Its capabilities are genuinely unknown - the adapter was never built - so
    the lists are empty and the booleans false rather than guessed. The reason
    is the useful part.
    """
    return SpeechProviderResponse(
        name=name,
        display_name=name,
        selected=selected,
        available=False,
        unavailable_reason=reason,
        languages=[],
        extra_language_values=[],
        unsupported_catalogue_languages=[],
        voices=[],
        voices_are_exhaustive=False,
        models=[],
        default_model="",
        containers=[],
        encodings=[],
        sample_rates=[],
        speed_min=None,
        speed_max=None,
        speed_aliases=[],
        audio_tags=[],
        supports_audio_tags=False,
        supports_streaming=False,
        max_text_chars=None,
        requires_credentials=True,
        serialises_requests=False,
        notes=[],
    )


__all__ = ["get_speech_service", "get_speech_service_factory", "router"]
