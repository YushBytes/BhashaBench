"""Live Gnani Prisma verification. Opt-in, billable, never run by default.

This module exists because a mocked transport cannot disagree with you. Every
other test in this suite proves the adapter sends what the *documentation*
describes; only these prove Gnani accepts it.

**Nothing here runs unless you ask for it twice.** Both of these must hold:

    TRANSCRIPTION_LIVE_TESTS=true
    GNANI_API_KEY=<a real key>

With either missing, every test is skipped with a reason naming what is
absent. CI sets neither, so CI can neither spend money nor need a credential.

Run them deliberately:

    TRANSCRIPTION_LIVE_TESTS=true GNANI_API_KEY=... pytest -m live

These calls cost money and count against your quota. The fixtures used are the
shortest committed ones - a single second of audio - for exactly that reason.

**Status in this repository: partially executed, 2026-11-07.**

Verified against the live service: authentication with a real key, one real
batch request, and the response parsing into a `TranscriptionResult` carrying a
provider `request_id`.

Still unverified: the streaming endpoint, and the nine non-Hindi languages.
Recognition accuracy is **not** verified by any test here and cannot be - the
committed fixtures are synthesised tones with no reviewed ground truth. See
`docs/PROVIDERS.md` for the per-capability table.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import httpx2
import pytest

from app.transcription.models import (
    AudioEncoding,
    TranscriptionCompleted,
    TranscriptionFailed,
    TranscriptionRequest,
)
from app.transcription.providers import prisma_contract as contract
from app.transcription.providers.prisma import GnaniPrismaProvider

pytestmark = pytest.mark.live


def _missing_prerequisite() -> str | None:
    """Return why live tests cannot run, or `None` when they can.

    Read from the process environment rather than `Settings` so the opt-in is
    explicit per invocation and cannot be switched on by a stale `.env` that a
    developer forgot about.
    """
    if os.getenv("TRANSCRIPTION_LIVE_TESTS", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        return (
            "live provider tests are opt-in: set TRANSCRIPTION_LIVE_TESTS=true to "
            "make real, billable calls to Gnani Prisma"
        )
    if not os.getenv("GNANI_API_KEY", "").strip():
        return (
            "TRANSCRIPTION_LIVE_TESTS is enabled but GNANI_API_KEY is unset, so no "
            "live call can be made"
        )
    return None


@pytest.fixture
def live_provider() -> Iterator[GnaniPrismaProvider]:
    """A real Prisma adapter, or a loud skip explaining what is missing.

    **Function-scoped, and that is load-bearing.** It was module-scoped, which
    broke the second test in the module with `RuntimeError: Event loop is
    closed` - a failure that looks like an authentication problem in the
    output and is nothing of the kind.

    The mechanism: the adapter lazily builds one `httpx2.AsyncClient`, whose
    connection pool holds a keep-alive socket bound to whichever event loop
    first used it. Each test here calls `asyncio.run`, which *closes* its loop
    on return. A second test sharing the provider then reuses that client, and
    httpcore tries to release the pooled connection against a dead loop.

    One provider per test means one client per loop, which is the invariant
    that actually matters. The cost is a TLS handshake per test, which is
    irrelevant here and is exactly what a shared pool is for in production.

    Reproduced against a local HTTP server, with no provider calls: shared
    provider plus two `asyncio.run` calls fails on the second; a fresh
    provider per call passes both.
    """
    reason = _missing_prerequisite()
    if reason:
        pytest.skip(reason, allow_module_level=True)

    yield GnaniPrismaProvider(
        api_key=os.environ["GNANI_API_KEY"],
        base_url=os.getenv("GNANI_API_BASE_URL", contract.DEFAULT_BASE_URL),
        model=os.getenv("GNANI_STT_MODEL", contract.DEFAULT_MODEL),
        # Generous but bounded: a live endpoint is slower than a mock, and a
        # hung test is worse than a failed one.
        timeout_seconds=60.0,
        # Keep-alive disabled, which is the other half of the loop problem.
        #
        # The adapter cannot be closed in this fixture's teardown: by then
        # `asyncio.run` has closed the loop its client belongs to, and
        # `aclose()` from a fresh loop raises "Event loop is closed". Leaving
        # the socket to the garbage collector is not an option either - the
        # resulting ResourceWarning reaches pytest as
        # `PytestUnraisableExceptionWarning`, and `filterwarnings = ["error"]`
        # turns it into a failing exit code even though the test itself passed.
        # That is exactly what happened on the first run of this fixture.
        #
        # With no pooled connections there is nothing left bound to the loop:
        # httpx closes the connection when the response completes, inside the
        # test's own loop. Measured against a local server - one request then
        # drop and collect: default client 1 ResourceWarning, this client 0.
        #
        # Correct here precisely because each live test makes a single request,
        # so pooling buys nothing. Production keeps the default pooling, and
        # the adapter is untouched - this uses its existing `client` seam.
        client=httpx2.AsyncClient(
            timeout=httpx2.Timeout(60.0),
            limits=httpx2.Limits(max_keepalive_connections=0),
        ),
    )


class TestLiveBatch:
    """`POST /stt/v3` against the real service."""

    def test_a_fixture_file_transcribes_end_to_end(
        self, live_provider: GnaniPrismaProvider, wav_8k: bytes
    ) -> None:
        """Phase 4's exit criterion, verified against the actual provider.

        The fixture is a synthesised tone, not speech, so the transcript is not
        asserted to contain any particular words - there is no reviewed ground
        truth for it. What is asserted is that the provider accepted the
        request and returned a well-formed, normalisable response. An empty
        transcript is a legitimate outcome for a tone.
        """
        result = asyncio.run(
            live_provider.transcribe_batch(
                TranscriptionRequest(
                    audio=wav_8k,
                    language="hi-IN",
                    encoding=AudioEncoding.WAV,
                    correlation_id="live-verification",
                )
            )
        )
        assert result.provider == "prisma"
        assert isinstance(result.text, str)
        assert result.request_id, "the provider should return a request_id"
        assert result.latency_ms > 0

    def test_authentication_succeeds_with_the_configured_key(
        self, live_provider: GnaniPrismaProvider, wav_8k: bytes
    ) -> None:
        """Separated from the transcription assertion on purpose: "the key
        works" and "the response parses" are different claims, and the report
        has to be able to state them independently."""
        from app.transcription.errors import AuthenticationError

        try:
            asyncio.run(
                live_provider.transcribe_batch(
                    TranscriptionRequest(audio=wav_8k, language="hi-IN", encoding=AudioEncoding.WAV)
                )
            )
        except AuthenticationError as exc:  # pragma: no cover - credential problem
            pytest.fail(f"the configured GNANI_API_KEY was rejected: {exc}")

    def test_a_deliberately_invalid_key_is_rejected(self, wav_8k: bytes) -> None:
        """Confirms the documented 401 behaviour, and that our mapping of it is
        right - the one error path that cannot be verified any other way."""
        reason = _missing_prerequisite()
        if reason:
            pytest.skip(reason)

        from app.transcription.errors import AuthenticationError

        provider = GnaniPrismaProvider(
            api_key="definitely-not-a-valid-key-000000",
            base_url=os.getenv("GNANI_API_BASE_URL", contract.DEFAULT_BASE_URL),
            timeout_seconds=60.0,
            # Same reason as the `live_provider` fixture: no pooled connection
            # may outlive this test's event loop.
            client=httpx2.AsyncClient(
                timeout=httpx2.Timeout(60.0),
                limits=httpx2.Limits(max_keepalive_connections=0),
            ),
        )
        with pytest.raises(AuthenticationError):
            asyncio.run(
                provider.transcribe_batch(
                    TranscriptionRequest(audio=wav_8k, language="hi-IN", encoding=AudioEncoding.WAV)
                )
            )


class TestLiveStreaming:
    """`wss://.../stt/v3/stream` against the real service."""

    def test_a_stream_completes_with_a_terminal_event(
        self, live_provider: GnaniPrismaProvider, raw_pcm_8k: bytes
    ) -> None:
        """Asserts the lifecycle, not the words: the fixture is not speech.

        Confirms that the documented framing is accepted, that events arrive in
        a parsable shape, and that the stream terminates - which is what a
        mocked socket cannot establish.
        """

        async def drive() -> list[object]:
            async def audio() -> AsyncIterator[bytes]:
                # Feed it in provider-sized frames; the adapter reframes anyway.
                for offset in range(0, len(raw_pcm_8k), contract.STREAM_FRAME_BYTES):
                    yield raw_pcm_8k[offset : offset + contract.STREAM_FRAME_BYTES]

            return [
                event
                async for event in live_provider.transcribe_stream(
                    audio(),
                    language="hi-IN",
                    sample_rate_hz=8000,
                    correlation_id="live-verification",
                )
            ]

        events = asyncio.run(asyncio.wait_for(drive(), timeout=120))

        assert events, "the stream produced no events at all"
        terminal = events[-1]
        assert isinstance(terminal, (TranscriptionCompleted, TranscriptionFailed))
        if isinstance(terminal, TranscriptionFailed):  # pragma: no cover
            pytest.fail(f"the live stream failed: {terminal.error_type}: {terminal.message}")

    def test_no_partial_events_arrive_as_documented(
        self, live_provider: GnaniPrismaProvider, raw_pcm_8k: bytes
    ) -> None:
        """Verifies the capability claim rather than trusting the documentation.

        `supports_partial_results=False` is asserted everywhere else from the
        documentation. This is the only test that can observe it.
        """
        from app.transcription.models import PartialTranscript

        async def drive() -> list[object]:
            async def audio() -> AsyncIterator[bytes]:
                for offset in range(0, len(raw_pcm_8k), contract.STREAM_FRAME_BYTES):
                    yield raw_pcm_8k[offset : offset + contract.STREAM_FRAME_BYTES]

            return [
                event
                async for event in live_provider.transcribe_stream(
                    audio(), language="hi-IN", sample_rate_hz=8000
                )
            ]

        events = asyncio.run(asyncio.wait_for(drive(), timeout=120))
        assert not [e for e in events if isinstance(e, PartialTranscript)]


class TestLiveLanguageCoverage:
    """The documented language list, checked against the service itself."""

    @pytest.mark.parametrize("language", contract.PROVIDER_LANGUAGE_CODES)
    def test_each_documented_language_is_accepted(
        self, live_provider: GnaniPrismaProvider, wav_8k: bytes, language: str
    ) -> None:
        """Ten billable calls. Run this one deliberately, not casually.

        A language the documentation lists but the service rejects is exactly
        the kind of gap that must be found before a benchmark reports a score
        for it.
        """
        from app.transcription.errors import UnsupportedLanguageError

        try:
            result = asyncio.run(
                live_provider.transcribe_batch(
                    TranscriptionRequest(
                        audio=wav_8k, language=language, encoding=AudioEncoding.WAV
                    )
                )
            )
        except UnsupportedLanguageError as exc:  # pragma: no cover
            pytest.fail(
                f"'{language}' is in the documented language list but the live "
                f"service rejected it: {exc}"
            )
        assert result.requested_language == language
