"""Live Gnani Timbre verification. Opt-in, billable, never run by default.

A mocked transport cannot disagree with you. Every other speech test proves the
adapter sends what the *documentation* describes; only these prove Gnani
accepts it.

**Nothing here runs unless you ask for it twice.** Both must hold:

    SPEECH_LIVE_TESTS=true
    GNANI_API_KEY=<a real key>

With either missing, every test skips with a reason naming what is absent. CI
sets neither, so CI can neither spend money nor need a credential. The flag is
separate from `TRANSCRIPTION_LIVE_TESTS` so enabling one cannot silently
enable the other.

Run them deliberately:

    SPEECH_LIVE_TESTS=true GNANI_API_KEY=... pytest -m live

**Fixture lifecycle.** `live_provider` is function-scoped and injects a client
with keep-alive disabled, for the reasons learned the hard way in Phase 4: each
test drives its own `asyncio.run`, which closes its event loop, and a pooled
connection outliving that loop fails the *next* test with
`RuntimeError: Event loop is closed` while an orphaned socket reaches pytest as
`PytestUnraisableExceptionWarning` - which `filterwarnings = ["error"]` turns
into a failing exit code even when the test passed.

**What these tests do not establish.** They do not evaluate pronunciation,
prosody, intelligibility or accent. Nothing in an automated assertion can:
that needs a human listening. A passing test here means the provider accepted
the request and returned decodable audio of a plausible length - not that the
audio sounds right.
"""

from __future__ import annotations

import asyncio
import os
import wave
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import httpx2
import pytest

from app.speech.models import AudioConfig, AudioContainer, SpeechRequest, SpeechResult
from app.speech.providers import timbre_contract as contract
from app.speech.providers.timbre import GnaniTimbreProvider

pytestmark = pytest.mark.live

SMOKE_TEXT = "வணக்கம், உங்கள் பயிர் காப்பீட்டு விண்ணப்பத்தின் நிலையைச் சரிபார்க்கிறேன்."
"""One short, harmless Tamil line: "Hello, I am checking the status of your crop
insurance application." Chosen because it is the kind of utterance this project
exists to generate, and short enough to keep the call cheap."""

SMOKE_LANGUAGE = "ta-IN"
SMOKE_VOICE = "Kalpana"
"""A documented v3.0 voice catalogued for "customer care and insurance", which
is what the smoke line is."""


def _missing_prerequisite() -> str | None:
    """Return why live tests cannot run, or `None` when they can.

    Read from the process environment rather than `Settings`, so the opt-in is
    explicit per invocation and cannot be switched on by a stale `.env`.
    """
    if os.getenv("SPEECH_LIVE_TESTS", "").strip().lower() not in {"1", "true", "yes"}:
        return (
            "live speech tests are opt-in: set SPEECH_LIVE_TESTS=true to make "
            "real, billable calls to Gnani Timbre"
        )
    if not os.getenv("GNANI_API_KEY", "").strip():
        return (
            "SPEECH_LIVE_TESTS is enabled but GNANI_API_KEY is unset, so no live call can be made"
        )
    return None


def _save_for_inspection(result: SpeechResult, name: str) -> None:
    """Write the audio locally when `SPEECH_LIVE_AUDIO_DIR` is set.

    Off unless asked for, and local only - nothing is uploaded anywhere. The
    point is that a live call costs money, so the one artefact it produced
    should be listenable afterwards rather than discarded, and its measured
    properties printable without paying for a second call.
    """
    directory = os.getenv("SPEECH_LIVE_AUDIO_DIR", "").strip()
    if not directory:
        return

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"timbre-{name}.{result.container.value}"
    path.write_bytes(result.audio)

    lines = [
        f"saved {path}",
        f"container={result.container.value} content_type={result.content_type} "
        f"bytes={result.size_bytes}",
        f"model={result.model} voice={result.voice} language={result.language}",
        f"sample_rate_hz={result.sample_rate_hz} "
        f"requested={result.requested_sample_rate_hz} "
        f"honoured={result.rate_was_honoured}",
        f"channels={result.channels} duration_seconds={result.duration_seconds} "
        f"latency_ms={result.latency_ms}",
    ]
    # Printed because a paid call should report what it bought.
    report = "\n".join(f"[live] {line}" for line in lines)
    print(f"\n{report}")


@pytest.fixture
def live_provider() -> Iterator[GnaniTimbreProvider]:
    """A real Timbre adapter, or a loud skip explaining what is missing."""
    reason = _missing_prerequisite()
    if reason:
        pytest.skip(reason, allow_module_level=True)

    yield GnaniTimbreProvider(
        api_key=os.environ["GNANI_API_KEY"],
        base_url=os.getenv("GNANI_API_BASE_URL", contract.DEFAULT_BASE_URL),
        model=os.getenv("GNANI_TTS_MODEL", contract.DEFAULT_MODEL),
        timeout_seconds=90.0,
        # Keep-alive off, so no pooled connection outlives this test's event
        # loop. See the module docstring.
        client=httpx2.AsyncClient(
            timeout=httpx2.Timeout(90.0),
            limits=httpx2.Limits(max_keepalive_connections=0),
        ),
    )


class TestLiveSynthesis:
    """`POST /api/v1/tts/inference` against the real service."""

    def test_one_short_line_synthesises_end_to_end(
        self, live_provider: GnaniTimbreProvider
    ) -> None:
        """Phase 5's exit criterion, verified against the actual provider.

        Asserts that the request was accepted and that what came back is
        decodable audio of a plausible duration. It deliberately asserts
        nothing about how the audio *sounds*: that is a listening judgement, not
        an automated one.
        """
        result = asyncio.run(
            live_provider.synthesise(
                SpeechRequest(
                    text=SMOKE_TEXT,
                    language=SMOKE_LANGUAGE,
                    voice=SMOKE_VOICE,
                    audio=AudioConfig(
                        container=AudioContainer.WAV, sample_rate_hz=8000, channels=1
                    ),
                    correlation_id="live-verification",
                )
            )
        )

        assert result.provider == "timbre"
        assert result.size_bytes > 0, "the provider returned no audio"
        assert result.latency_ms > 0

        # A WAV carries a header, so these are exact rather than assumed.
        assert result.sample_rate_hz is not None, "the returned WAV had no readable rate"
        assert result.channels == 1
        assert result.duration_seconds is not None

        # A sentence of this length should take a second or two. The bound is
        # loose on purpose - it is here to catch a provider that returns a
        # fraction of a second of silence, not to grade the delivery.
        assert 0.5 < result.duration_seconds < 30.0, (
            f"a {len(SMOKE_TEXT)}-character line produced "
            f"{result.duration_seconds:.2f}s of audio, which is implausible"
        )

        # Decodable by a second, independent reader.
        with wave.open(BytesIO(result.audio), "rb") as handle:
            assert handle.getnframes() > 0
            assert handle.getsampwidth() == 2

        _save_for_inspection(result, "smoke")

    def test_the_requested_sample_rate_is_reported_honestly(
        self, live_provider: GnaniTimbreProvider
    ) -> None:
        """Whether the provider honoured 8 kHz is a finding either way.

        This asserts only that the comparison is *possible* - that a rate came
        back and is recorded next to the one requested. A mismatch is a real
        result to report, not a test failure, because the vendor's default is
        48 kHz and it may ignore the request.
        """
        result = asyncio.run(
            live_provider.synthesise(
                SpeechRequest(
                    text="வணக்கம்.",
                    language=SMOKE_LANGUAGE,
                    voice=SMOKE_VOICE,
                    audio=AudioConfig(container=AudioContainer.WAV, sample_rate_hz=8000),
                )
            )
        )
        assert result.requested_sample_rate_hz == 8000
        assert result.rate_was_honoured is not None

    def test_a_deliberately_invalid_key_is_rejected(self) -> None:
        """Confirms the documented 401 and that our mapping of it is right -
        the one error path that cannot be verified any other way."""
        reason = _missing_prerequisite()
        if reason:
            pytest.skip(reason)

        from app.speech.errors import SpeechAuthenticationError

        provider = GnaniTimbreProvider(
            api_key="definitely-not-a-valid-key-000000",
            base_url=os.getenv("GNANI_API_BASE_URL", contract.DEFAULT_BASE_URL),
            timeout_seconds=90.0,
            client=httpx2.AsyncClient(
                timeout=httpx2.Timeout(90.0),
                limits=httpx2.Limits(max_keepalive_connections=0),
            ),
        )
        with pytest.raises(SpeechAuthenticationError):
            asyncio.run(
                provider.synthesise(
                    SpeechRequest(text="வணக்கம்.", language=SMOKE_LANGUAGE, voice=SMOKE_VOICE)
                )
            )


class TestLiveVoiceCoverage:
    """The documented voice roster, checked against the service itself."""

    @pytest.mark.parametrize("voice", sorted(contract.V3_VOICE_NAMES))
    def test_each_documented_voice_is_accepted(
        self, live_provider: GnaniTimbreProvider, voice: str
    ) -> None:
        """Thirteen billable calls. Run deliberately, not casually.

        A voice the documentation lists but the service rejects is exactly the
        gap to find before a scenario depends on it.
        """
        from app.speech.errors import UnsupportedVoiceError

        try:
            result = asyncio.run(
                live_provider.synthesise(
                    SpeechRequest(text="வணக்கம்.", language=SMOKE_LANGUAGE, voice=voice)
                )
            )
        except UnsupportedVoiceError as exc:  # pragma: no cover
            pytest.fail(f"'{voice}' is documented but the live service rejected it: {exc}")
        assert result.size_bytes > 0


class TestLiveLanguageCoverage:
    """The documented language list, checked against the service itself."""

    @pytest.mark.parametrize("language", contract.PROVIDER_LANGUAGE_CODES)
    def test_each_documented_language_is_accepted(
        self, live_provider: GnaniTimbreProvider, language: str
    ) -> None:
        """Ten billable calls. Run deliberately, not casually."""
        from app.speech.errors import UnsupportedSpeechLanguageError

        try:
            result = asyncio.run(
                live_provider.synthesise(
                    SpeechRequest(text="Hello.", language=language, voice=SMOKE_VOICE)
                )
            )
        except UnsupportedSpeechLanguageError as exc:  # pragma: no cover
            pytest.fail(
                f"'{language}' is in the documented list but the live service rejected it: {exc}"
            )
        assert result.size_bytes > 0
