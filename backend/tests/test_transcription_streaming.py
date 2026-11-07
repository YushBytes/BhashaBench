"""Streaming transcription: the Prisma WebSocket adapter and the fake's stream.

The provider socket is replaced by `StubSocket`, which records what was sent
and replays a scripted sequence of server frames. The adapter's own protocol
loop, framing, pacing, event mapping and cleanup all run for real.

Pacing is the one thing stubbed out: Prisma requires real-time cadence, so the
adapter sleeps between frames. These tests patch `asyncio.sleep` inside the
adapter module to a no-op, because asserting the framing does not require
waiting a second per second of audio.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from app.transcription.errors import (
    UnsupportedFormatError,
    UnsupportedLanguageError,
)
from app.transcription.models import (
    FinalTranscript,
    PartialTranscript,
    StreamEventType,
    TranscriptionCompleted,
    TranscriptionFailed,
    TranscriptionStarted,
)
from app.transcription.providers import prisma as prisma_module
from app.transcription.providers import prisma_contract as contract
from app.transcription.providers.fake import FakeScript, FakeTranscriptionProvider
from app.transcription.providers.prisma import GnaniPrismaProvider

API_KEY = "gnani-test-key-0123456789abcdef"


def transcript_frame(
    text: str, index: int = 0, *, duration_ms: float = 1000.0, latency: float = 318.0
) -> str:
    """A `transcript` event exactly as the vendor documents it."""
    return json.dumps(
        {
            "type": "transcript",
            "timestamp": "2026-11-07T10:30:05.987Z",
            "text": text,
            "audio_duration_ms": duration_ms,
            "segment_id": f"seg_{index:04x}",
            "segment_index": index,
            "latency": latency,
        }
    )


CONNECTED_FRAME = json.dumps(
    {
        "type": "connected",
        "message": "ready",
        "config": {"sample_rate": 16000, "chunk_size": 1024},
        "timestamp": "2026-11-07T10:30:00.000Z",
    }
)
PROCESSING_FRAME = json.dumps({"type": "processing", "timestamp": "2026-11-07T10:30:05.000Z"})


class StubSocket:
    """A stand-in for a `websockets` client connection."""

    def __init__(self, frames: list[object]) -> None:
        self._frames = list(frames)
        self.sent: list[bytes] = []
        self.closed = False

    async def __aenter__(self) -> StubSocket:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> object:
        if not self._frames:
            # No end-of-stream acknowledgement is documented, so a clean close
            # is how a finished stream looks.
            raise ConnectionClosedOK(None, None)
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame


@pytest.fixture
def no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the real-time cadence so tests do not run in real time."""

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(prisma_module.asyncio, "sleep", instant)


@pytest.fixture
def connect_stub(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Replace `ws_connect`, capturing the URL and headers it was called with."""
    captured: dict[str, object] = {}

    def install(frames: list[object]) -> StubSocket:
        socket = StubSocket(frames)

        async def fake_connect(url: str, **kwargs: object) -> StubSocket:
            captured["url"] = url
            captured["headers"] = kwargs.get("additional_headers")
            return socket

        monkeypatch.setattr(prisma_module, "ws_connect", fake_connect)
        return socket

    install.captured = captured  # type: ignore[attr-defined]
    return install


async def _collect(provider: object, audio_chunks: list[bytes], **kwargs: object) -> list[object]:
    """Drive a stream to completion and return every event it emitted."""

    async def audio() -> AsyncIterator[bytes]:
        for chunk in audio_chunks:
            yield chunk

    events: list[object] = []
    async for event in provider.transcribe_stream(audio(), **kwargs):
        events.append(event)
    return events


def _pcm(seconds: float, sample_rate: int = 16000) -> bytes:
    """Silent 16-bit mono PCM of a given length."""
    return b"\x00\x00" * int(seconds * sample_rate)


# ---------------------------------------------------------------------------
# Connection and handshake
# ---------------------------------------------------------------------------


class TestStreamConnection:
    def test_it_connects_to_the_documented_url(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame("haan")])
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert connect_stub.captured["url"] == "wss://api.vachana.ai/stt/v3/stream"

    def test_it_sends_the_documented_upgrade_headers(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame("haan")])
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        headers = connect_stub.captured["headers"]
        assert headers["x-api-key-id"] == API_KEY  # type: ignore[index]
        assert headers["language_code"] == "hi-IN"  # type: ignore[index]
        assert headers["model"] == contract.DEFAULT_MODEL  # type: ignore[index]
        assert headers["x-sample-rate"] == "8000"  # type: ignore[index]

    def test_the_format_header_is_omitted_without_a_mode(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame("haan")])
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert "format" not in connect_stub.captured["headers"]  # type: ignore[operator]

    def test_an_unaccepted_sample_rate_is_refused_before_connecting(self) -> None:
        provider = GnaniPrismaProvider(api_key=API_KEY)
        with pytest.raises(UnsupportedFormatError, match="22050"):
            asyncio.run(_collect(provider, [_pcm(0.1)], language="hi-IN", sample_rate_hz=22050))

    def test_an_unsupported_language_is_refused_before_connecting(self) -> None:
        provider = GnaniPrismaProvider(api_key=API_KEY)
        with pytest.raises(UnsupportedLanguageError):
            asyncio.run(_collect(provider, [_pcm(0.1)], language="as-IN", sample_rate_hz=16000))


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


class TestFraming:
    """Prisma requires frames of exactly 1024 bytes."""

    def test_every_frame_is_exactly_the_documented_size(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        socket = connect_stub([transcript_frame("haan")])
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(1.0)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert socket.sent
        assert {len(frame) for frame in socket.sent} == {contract.STREAM_FRAME_BYTES}

    def test_caller_chunks_are_reframed_not_forwarded(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        """A caller sending 100-byte chunks must still produce 1024-byte frames."""
        socket = connect_stub([transcript_frame("haan")])
        chunks = [b"\x00\x00" * 50] * 60  # 60 x 100 bytes = 6000 bytes
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                chunks,
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert {len(frame) for frame in socket.sent} == {contract.STREAM_FRAME_BYTES}
        # 6000 bytes -> five full frames plus a padded tail.
        assert len(socket.sent) == 6

    def test_a_partial_tail_is_padded_with_silence_not_dropped(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        """Truncating would lose the end of the last word."""
        socket = connect_stub([transcript_frame("haan")])
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [b"\x00\x01" * 100],  # 200 bytes, well under one frame
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert len(socket.sent) == 1
        assert len(socket.sent[0]) == contract.STREAM_FRAME_BYTES
        assert socket.sent[0][:200] == b"\x00\x01" * 100
        assert socket.sent[0][200:] == b"\x00" * (contract.STREAM_FRAME_BYTES - 200)

    def test_empty_chunks_are_skipped(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        socket = connect_stub([transcript_frame("haan")])
        asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [b"", b"", _pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert all(len(f) == contract.STREAM_FRAME_BYTES for f in socket.sent)

    def test_no_audio_at_all_sends_nothing_and_still_completes(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        socket = connect_stub([])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert socket.sent == []
        assert isinstance(events[-1], TranscriptionCompleted)
        assert events[-1].result.is_empty


# ---------------------------------------------------------------------------
# Event mapping
# ---------------------------------------------------------------------------


class TestEventMapping:
    def test_a_stream_starts_with_started_and_ends_with_completed(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        connect_stub([CONNECTED_FRAME, transcript_frame("haan")])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
                correlation_id="run-7",
            )
        )
        assert isinstance(events[0], TranscriptionStarted)
        assert events[0].correlation_id == "run-7"
        assert isinstance(events[-1], TranscriptionCompleted)

    def test_exactly_one_terminal_event_is_emitted(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame("a"), transcript_frame("b", 1)])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.2)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        terminal = [
            e for e in events if isinstance(e, (TranscriptionCompleted, TranscriptionFailed))
        ]
        assert len(terminal) == 1

    def test_every_transcript_event_becomes_a_final_not_a_partial(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        """Prisma documents no interim indicator, so claiming partials would
        be inventing a capability the provider does not have."""
        connect_stub([transcript_frame("ek"), transcript_frame("do", 1)])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.2)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert [type(e).__name__ for e in events] == [
            "TranscriptionStarted",
            "FinalTranscript",
            "FinalTranscript",
            "TranscriptionCompleted",
        ]
        assert not any(isinstance(e, PartialTranscript) for e in events)

    def test_connected_and_processing_notices_are_not_surfaced(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        """They are vendor lifecycle notices with no transcript content;
        exposing them would leak the vendor's protocol into our interface."""
        connect_stub([CONNECTED_FRAME, PROCESSING_FRAME, transcript_frame("haan")])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert len([e for e in events if isinstance(e, FinalTranscript)]) == 1
        assert len(events) == 3  # started, final, completed

    def test_documented_transcript_fields_are_carried_through(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame("haan bilkul", 4, duration_ms=2340.0, latency=318.0)])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        final = next(e for e in events if isinstance(e, FinalTranscript))
        assert final.text == "haan bilkul"
        assert final.segment_index == 4
        assert final.segment_id == "seg_0004"
        assert final.audio_duration_ms == 2340.0
        assert final.latency_ms == 318.0

    def test_segments_are_aggregated_into_the_final_result(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame("mera order", 0), transcript_frame("kahan hai", 1)])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.2)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        completed = events[-1]
        assert isinstance(completed, TranscriptionCompleted)
        assert completed.result.text == "mera order kahan hai"
        assert completed.result.segments is not None
        assert len(completed.result.segments) == 2

    def test_segment_offsets_are_left_unset_because_prisma_omits_them(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        """Deriving offsets from arrival order would assume silence does not exist."""
        connect_stub([transcript_frame("haan")])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        segments = events[-1].result.segments  # type: ignore[union-attr]
        assert segments[0].start_seconds is None
        assert segments[0].end_seconds is None
        assert segments[0].confidence is None

    def test_event_ordering_is_preserved(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame(str(n), n) for n in range(6)])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.5)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        finals = [e for e in events if isinstance(e, FinalTranscript)]
        assert [f.text for f in finals] == ["0", "1", "2", "3", "4", "5"]
        assert [f.segment_index for f in finals] == [0, 1, 2, 3, 4, 5]


class TestMalformedFrames:
    """A long-lived socket should tolerate the unexpected, not die on it."""

    def test_a_non_json_frame_is_skipped(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub(["this is not json", transcript_frame("haan")])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert isinstance(events[-1], TranscriptionCompleted)
        assert events[-1].result.text == "haan"

    def test_a_frame_without_a_type_is_skipped(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([json.dumps({"text": "orphan"}), transcript_frame("haan")])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert events[-1].result.text == "haan"  # type: ignore[union-attr]

    def test_an_unexpected_binary_frame_is_skipped(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([b"\x80\x81\x82", transcript_frame("haan")])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert events[-1].result.text == "haan"  # type: ignore[union-attr]

    def test_a_transcript_frame_with_no_text_yields_an_empty_segment(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        connect_stub([json.dumps({"type": "transcript", "segment_index": 0})])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        final = next(e for e in events if isinstance(e, FinalTranscript))
        assert final.text == ""
        assert events[-1].result.is_empty  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestStreamFailures:
    def test_a_server_error_frame_becomes_a_failed_event(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([json.dumps({"type": "error", "message": "model overloaded"})])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        failed = events[-1]
        assert isinstance(failed, TranscriptionFailed)
        assert "model overloaded" in failed.message
        assert failed.retryable is True

    def test_an_unexpected_close_becomes_a_failed_event(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub(
            [
                transcript_frame("partial answer"),
                ConnectionClosedError(None, None),
            ]
        )
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.2)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert isinstance(events[-1], TranscriptionFailed)
        assert events[-1].error_type == "StreamClosedError"

    def test_a_refused_upgrade_with_401_becomes_an_auth_failure(
        self, monkeypatch: pytest.MonkeyPatch, no_pacing
    ) -> None:
        """Authentication failure arrives as an HTTP status on the upgrade."""

        class FakeResponse:
            status_code = 401

        from websockets.exceptions import InvalidStatus

        async def refuse(*_: object, **__: object) -> None:
            raise InvalidStatus(FakeResponse())  # type: ignore[arg-type]

        monkeypatch.setattr(prisma_module, "ws_connect", refuse)
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert isinstance(events[-1], TranscriptionFailed)
        assert events[-1].error_type == "AuthenticationError"
        assert events[-1].retryable is False

    def test_the_api_key_never_appears_in_a_failure_message(
        self, monkeypatch: pytest.MonkeyPatch, no_pacing
    ) -> None:
        class FakeResponse:
            status_code = 401

        from websockets.exceptions import InvalidStatus

        async def refuse(*_: object, **__: object) -> None:
            raise InvalidStatus(FakeResponse())  # type: ignore[arg-type]

        monkeypatch.setattr(prisma_module, "ws_connect", refuse)
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert API_KEY not in events[-1].message  # type: ignore[union-attr]

    def test_an_unreachable_provider_becomes_a_failed_event(
        self, monkeypatch: pytest.MonkeyPatch, no_pacing
    ) -> None:
        async def refuse(*_: object, **__: object) -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(prisma_module, "ws_connect", refuse)
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert isinstance(events[-1], TranscriptionFailed)
        assert events[-1].error_type == "ProviderUnavailableError"
        assert events[-1].retryable is True


# ---------------------------------------------------------------------------
# Cancellation and cleanup
# ---------------------------------------------------------------------------


class TestCancellationAndCleanup:
    def test_abandoning_the_stream_closes_the_provider_socket(
        self, connect_stub, no_pacing
    ) -> None:  # type: ignore[no-untyped-def]
        """A consumer that stops iterating must not leave a socket open."""
        socket = connect_stub([transcript_frame(str(n), n) for n in range(50)])

        async def scenario() -> None:
            async def audio() -> AsyncIterator[bytes]:
                for _ in range(100):
                    yield _pcm(0.05)

            events = GnaniPrismaProvider(api_key=API_KEY).transcribe_stream(
                audio(), language="hi-IN", sample_rate_hz=16000
            )
            seen = 0
            async for _ in events:
                seen += 1
                if seen == 3:
                    break
            # Closing the generator runs its `finally`.
            await events.aclose()

        asyncio.run(scenario())
        assert socket.closed

    def test_cancelling_the_task_does_not_hang(self, connect_stub, no_pacing) -> None:  # type: ignore[no-untyped-def]
        connect_stub([transcript_frame(str(n), n) for n in range(1000)])

        async def scenario() -> None:
            async def audio() -> AsyncIterator[bytes]:
                while True:
                    await asyncio.sleep(0)
                    yield _pcm(0.05)

            provider = GnaniPrismaProvider(api_key=API_KEY)
            events = provider.transcribe_stream(audio(), language="hi-IN", sample_rate_hz=16000)

            async def consume() -> None:
                async for _ in events:
                    pass

            task = asyncio.create_task(consume())
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await events.aclose()

        asyncio.run(asyncio.wait_for(scenario(), timeout=10))

    def test_the_transcript_accumulation_is_bounded(
        self, connect_stub, no_pacing, monkeypatch: pytest.MonkeyPatch
    ) -> None:  # type: ignore[no-untyped-def]
        """A provider that never stops must not grow our process without limit."""
        monkeypatch.setattr(prisma_module, "MAX_STREAM_TRANSCRIPT_CHARS", 50)
        connect_stub([transcript_frame("x" * 30, n) for n in range(10)])
        events = asyncio.run(
            _collect(
                GnaniPrismaProvider(api_key=API_KEY),
                [_pcm(0.1)],
                language="hi-IN",
                sample_rate_hz=16000,
            )
        )
        assert isinstance(events[-1], TranscriptionFailed)
        assert "without bound" in events[-1].message


# ---------------------------------------------------------------------------
# The fake provider's stream
# ---------------------------------------------------------------------------


class TestFakeStream:
    def test_it_emits_the_documented_event_sequence(self, raw_pcm_8k: bytes) -> None:
        events = asyncio.run(
            _collect(
                FakeTranscriptionProvider(FakeScript(segments=["ek", "do"])),
                [raw_pcm_8k],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        assert [e.type for e in events] == [  # type: ignore[attr-defined]
            StreamEventType.STARTED,
            StreamEventType.FINAL_TRANSCRIPT,
            StreamEventType.FINAL_TRANSCRIPT,
            StreamEventType.COMPLETED,
        ]

    def test_it_can_emit_partial_results_prisma_cannot(self, raw_pcm_8k: bytes) -> None:
        """Somebody has to exercise the interim-hypothesis path."""
        events = asyncio.run(
            _collect(
                FakeTranscriptionProvider(
                    FakeScript(segments=["mera order"], partials=["mera", "mera or"])
                ),
                [raw_pcm_8k],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        partials = [e for e in events if isinstance(e, PartialTranscript)]
        assert [p.text for p in partials] == ["mera", "mera or"]
        # A partial always precedes the final it refines.
        assert events.index(partials[-1]) < next(
            i for i, e in enumerate(events) if isinstance(e, FinalTranscript)
        )

    def test_it_actually_consumes_the_callers_audio(self, raw_pcm_8k: bytes) -> None:
        script = FakeScript()
        asyncio.run(
            _collect(
                FakeTranscriptionProvider(script),
                [raw_pcm_8k[:100], raw_pcm_8k[100:300]],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        assert script.frames_received == [100, 200]

    def test_a_mid_stream_drop_is_reported_after_the_segments_so_far(
        self, raw_pcm_8k: bytes
    ) -> None:
        events = asyncio.run(
            _collect(
                FakeTranscriptionProvider(
                    FakeScript(segments=["ek", "do", "teen"], fail_mid_stream_after=2)
                ),
                [raw_pcm_8k],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        assert len([e for e in events if isinstance(e, FinalTranscript)]) == 2
        assert isinstance(events[-1], TranscriptionFailed)
        assert events[-1].error_type == "StreamClosedError"

    def test_an_empty_stream_completes_with_an_empty_result(self, raw_pcm_8k: bytes) -> None:
        events = asyncio.run(
            _collect(
                FakeTranscriptionProvider(FakeScript(transcript="")),
                [raw_pcm_8k],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        assert events[-1].result.is_empty  # type: ignore[union-attr]

    def test_a_scripted_connection_failure_yields_only_a_failed_event(
        self, raw_pcm_8k: bytes
    ) -> None:
        from app.transcription.providers.fake import auth_failure

        events = asyncio.run(
            _collect(
                FakeTranscriptionProvider(FakeScript(failures=[auth_failure()])),
                [raw_pcm_8k],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        assert len(events) == 1
        assert isinstance(events[0], TranscriptionFailed)
        assert events[0].error_type == "AuthenticationError"

    def test_cancelling_mid_stream_stops_promptly(self, raw_pcm_8k: bytes) -> None:
        async def scenario() -> int:
            provider = FakeTranscriptionProvider(
                FakeScript(segments=[str(n) for n in range(100)], stream_delay_seconds=0.01)
            )

            async def audio() -> AsyncIterator[bytes]:
                yield raw_pcm_8k

            events = provider.transcribe_stream(audio(), language="hi-IN", sample_rate_hz=8000)
            seen = 0
            async for _ in events:
                seen += 1
                if seen == 2:
                    break
            await events.aclose()
            return seen

        assert asyncio.run(asyncio.wait_for(scenario(), timeout=10)) == 2


class TestStreamingRetryPolicy:
    def test_a_stream_failure_is_reported_not_silently_replayed(self, raw_pcm_8k: bytes) -> None:
        """Replaying consumed audio would transcribe a tail and call it the whole
        utterance, so the retry decision belongs to the caller."""
        script = FakeScript(segments=["ek"], fail_mid_stream_after=0)
        events = asyncio.run(
            _collect(
                FakeTranscriptionProvider(script),
                [raw_pcm_8k],
                language="hi-IN",
                sample_rate_hz=8000,
            )
        )
        assert isinstance(events[-1], TranscriptionFailed)
        # One stream attempt only.
        assert script.calls == ["stream"]
        # The caller is told it *could* be retried; it is not retried for them.
        assert events[-1].retryable is True
