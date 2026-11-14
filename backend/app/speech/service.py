"""Speech-synthesis business rules.

Sits between the API and the provider, in `app/speech/` rather than
`app/services/` so the subsystem stays one readable package - the same shape
Phase 4 settled on for transcription. No vendor field name, no HTTP status and
no `HTTPException` appears here.

What it owns:

* checking the language against both the BhashaBench catalogue *and* the
  selected provider's capabilities, which are different questions;
* checking the voice, the container and the audio tags against declared
  capabilities, before any request is sent;
* applying the retry policy;
* measuring end-to-end latency, so the number reported is what a caller
  actually waited rather than what the last attempt took.

**No persistence.** Phase 5 stores nothing. Generated audio is returned to the
caller and forgotten: deciding where a caller utterance belongs is conversation
orchestration (Phase 9), and an audio artefact store with no run to attach it
to would be guesswork. These endpoints work with PostgreSQL down.
"""

from __future__ import annotations

import logging

from app.core import languages
from app.core.config import Settings
from app.speech.base import SynthesisCapabilities, SynthesisProvider
from app.speech.errors import (
    InvalidTextError,
    SpeechError,
    UnsupportedAudioConfigError,
    UnsupportedSpeechLanguageError,
    UnsupportedVoiceError,
)
from app.speech.models import AudioConfig, SpeechRequest, SpeechResult, SpeechSpeed
from app.transcription.retry import RetryPolicy, call_with_retry
from app.utils.timing import monotonic_seconds

logger = logging.getLogger("bhashabench.speech")

PROVIDER_LEVEL_LANGUAGE_VALUES: frozenset[str] = frozenset({"auto", "hi-en"})
"""Language values that are provider vocabulary rather than catalogue tags.

`auto` and `hi-en` are not BCP 47 and never will be in `app/core/languages.py`,
but refusing them would make Hinglish callers unsynthesisable. They bypass the
catalogue check and are validated against the provider's declared capabilities
instead.
"""


def retry_policy_from(settings: Settings) -> RetryPolicy:
    """Build the retry policy the configuration asks for."""
    return RetryPolicy(
        max_attempts=settings.speech_max_attempts,
        initial_backoff_seconds=settings.speech_initial_backoff_seconds,
        max_backoff_seconds=settings.speech_max_backoff_seconds,
    )


class SpeechService:
    """Synthesise text through whichever provider is configured."""

    def __init__(
        self,
        provider: SynthesisProvider,
        *,
        settings: Settings,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._policy = policy or retry_policy_from(settings)

    @property
    def capabilities(self) -> SynthesisCapabilities:
        """The selected provider's capabilities."""
        return self._provider.capabilities

    # -- Validation ---------------------------------------------------------

    def _check_language(self, language: str) -> str:
        """Validate a language value against the catalogue, then the provider.

        Three distinct failures, reported distinctly:

        * a provider-level value (`auto`, `hi-en`) the provider does not offer;
        * not a BhashaBench language at all - a typo or unsupported locale,
          where `languages.validate_tag` already distinguishes malformed from
          unknown;
        * a real catalogue language with no *voice model* behind it. Urdu, Odia
          and Assamese are authorable and not speakable, and saying
          "unsupported language" without saying *by the provider* sends an
          author hunting for a typo that is not there.
        """
        capabilities = self.capabilities

        if language in PROVIDER_LEVEL_LANGUAGE_VALUES:
            if language not in capabilities.extra_language_values:
                raise UnsupportedSpeechLanguageError(
                    f"the '{capabilities.name}' provider does not accept the "
                    f"language value '{language}'; it accepts "
                    f"{sorted(capabilities.extra_language_values)} alongside "
                    "ordinary language tags",
                    language=language,
                    supported=tuple(sorted(capabilities.extra_language_values)),
                    provider=capabilities.name,
                )
            return language

        tag = languages.validate_tag(language)

        if not capabilities.supports_language(tag):
            raise UnsupportedSpeechLanguageError(
                f"'{tag}' is a supported BhashaBench language, but the "
                f"'{capabilities.name}' provider cannot synthesise speech in it. "
                f"Languages this provider speaks: {sorted(capabilities.languages)}.",
                language=tag,
                supported=tuple(sorted(capabilities.languages)),
                provider=capabilities.name,
            )
        return tag

    def _check_voice(self, voice: str | None) -> str | None:
        """Reject a voice the provider does not know, when it can be sure.

        Only when the roster is exhaustive. Timbre v2.5 documents 42 voices of
        which nine are published, so rejecting an unlisted name there would
        refuse valid input - the provider's own rejection is better than ours.
        """
        if voice is None:
            return None
        capabilities = self.capabilities
        if not capabilities.voices_are_exhaustive:
            return voice
        if not capabilities.knows_voice(voice):
            raise UnsupportedVoiceError(
                f"'{voice}' is not a voice the '{capabilities.name}' provider "
                f"documents; available voices are "
                f"{sorted(v.name for v in capabilities.voices)}",
                voice=voice,
                supported=tuple(sorted(v.name for v in capabilities.voices)),
                provider=capabilities.name,
            )
        return voice

    def _check_audio(self, audio: AudioConfig) -> AudioConfig:
        """Reject a container, encoding or sample rate the provider lacks."""
        capabilities = self.capabilities
        if capabilities.containers and audio.container not in capabilities.containers:
            raise UnsupportedAudioConfigError(
                f"the '{capabilities.name}' provider does not produce the "
                f"'{audio.container.value}' container; it produces "
                f"{sorted(c.value for c in capabilities.containers)}",
                provider=capabilities.name,
            )
        if capabilities.encodings and audio.encoding not in capabilities.encodings:
            raise UnsupportedAudioConfigError(
                f"the '{capabilities.name}' provider does not support the "
                f"'{audio.encoding.value}' encoding",
                provider=capabilities.name,
            )
        if capabilities.sample_rates and audio.sample_rate_hz not in capabilities.sample_rates:
            raise UnsupportedAudioConfigError(
                f"the '{capabilities.name}' provider does not produce "
                f"{audio.sample_rate_hz} Hz audio; accepted rates are "
                f"{sorted(capabilities.sample_rates)} Hz",
                provider=capabilities.name,
            )
        return audio

    def _check_text(self, text: str) -> str:
        """Reject empty or over-long text before the provider is called."""
        if not text.strip():
            raise InvalidTextError("the text to synthesise is empty")
        limit = self._effective_text_limit()
        if len(text) > limit:
            raise InvalidTextError(
                f"the text is {len(text)} characters, which exceeds the {limit} "
                "character limit (SPEECH_MAX_TEXT_CHARS)"
            )
        return text

    def _effective_text_limit(self) -> int:
        """The smaller of our configured limit and the provider's own."""
        configured = self._settings.speech_max_text_chars
        provider_limit = self.capabilities.max_text_chars
        if provider_limit is None:
            return configured
        return min(configured, provider_limit)

    def _check_audio_tags(self, text: str) -> None:
        """Reject an expression tag the provider does not implement.

        Tags are inline in the text, so a caller using one against a model
        that ignores them gets `<laugh>` *spoken aloud* rather than performed.
        Catching it here is the difference between a clear error and a very
        confusing audio file.
        """
        capabilities = self.capabilities
        if "<" not in text:
            return

        import re

        used = set(re.findall(r"<[^<>]{1,32}>", text))
        if not used:
            return

        known = set(capabilities.audio_tags)
        unknown = sorted(used - known)
        if not unknown:
            return

        if not capabilities.supports_audio_tags:
            raise UnsupportedAudioConfigError(
                f"the text contains what looks like expression tags {unknown}, but "
                f"the '{capabilities.name}' provider does not support audio tags - "
                "they would be read out as words. Remove them or use a model that "
                "supports them.",
                provider=capabilities.name,
            )
        raise UnsupportedAudioConfigError(
            f"{unknown} are not documented audio tags; supported tags are {sorted(known)}",
            provider=capabilities.name,
        )

    # -- Synthesis ----------------------------------------------------------

    async def synthesise(
        self,
        text: str,
        *,
        language: str,
        voice: str | None = None,
        model: str | None = None,
        speed: float | SpeechSpeed | None = None,
        audio: AudioConfig | None = None,
        correlation_id: str | None = None,
    ) -> SpeechResult:
        """Synthesise `text`.

        Validation order is cheapest-first and intentional: text, language,
        voice, audio settings, then tags. A request for Odia never has its
        audio configuration examined.

        Raises:
            app.core.languages.UnsupportedLanguageError: not a BhashaBench tag.
            SpeechError: any provider or validation failure, normalised.
        """
        capabilities = self.capabilities
        checked_text = self._check_text(text)
        checked_language = self._check_language(language)
        checked_voice = self._check_voice(voice)
        checked_audio = self._check_audio(audio or AudioConfig())
        self._check_audio_tags(checked_text)

        request = SpeechRequest(
            text=checked_text,
            language=checked_language,
            voice=checked_voice,
            model=model,
            speed=speed,
            audio=checked_audio,
            correlation_id=correlation_id,
        )

        started = monotonic_seconds()
        result, attempts = await call_with_retry(
            lambda: self._provider.synthesise(request),
            policy=self._policy,
            provider=capabilities.name,
            operation_name="synthesise",
            correlation_id=correlation_id,
            retryable_base=SpeechError,
        )
        elapsed_ms = round((monotonic_seconds() - started) * 1000, 3)

        logger.info(
            "speech.completed",
            extra={
                "provider": capabilities.name,
                "operation": "synthesise",
                "language": checked_language,
                "voice": result.voice,
                "model": result.model,
                "container": result.container.value,
                "correlation_id": correlation_id,
                "attempts": attempts,
                "latency_ms": elapsed_ms,
                "audio_bytes": result.size_bytes,
                "sample_rate_hz": result.sample_rate_hz,
                "duration_seconds": result.duration_seconds,
                "rate_was_honoured": result.rate_was_honoured,
                # Length, never content.
                "text_chars": len(checked_text),
            },
        )

        # Replace the adapter's single-call latency with the end-to-end figure
        # and record the attempt count: a result that took three tries must not
        # report the time the last one happened to take.
        return result.model_copy(update={"latency_ms": elapsed_ms, "attempts": attempts})

    async def close(self) -> None:
        """Release the provider's connections."""
        await self._provider.close()


def classify(error: SpeechError) -> str:
    """A stable, machine-readable category for an error.

    `SpeechAuthenticationError` -> `speech_authentication_error`. Used by the
    API's error envelope so a client can branch without parsing prose.
    """
    name = type(error).__name__
    if name.endswith("Error"):
        name = name[: -len("Error")]
    snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
    return f"{snake}_error"


__all__ = ["PROVIDER_LEVEL_LANGUAGE_VALUES", "SpeechService", "classify", "retry_policy_from"]
