"""Phase 9 streaming voice: the turn-taking rules on a simulated clock, then
the `ws_voice` adapter against the reference bot over a real localhost
socket - in real time, because accelerated timings would be fiction - and a
whole run through the engine."""

from __future__ import annotations

import asyncio
import io
import math
import struct
import uuid
import wave
from collections.abc import Iterator

import pytest
from pydantic import SecretStr

from app.core.outbound import OutboundPolicy
from app.pipeline.bots.ws_voice import VoiceBotConfig, WebSocketVoiceBotAdapter
from app.pipeline.errors import BotTargetRefusedError, BotUnavailableError
from app.pipeline.streaming import (
    FRAME_BYTES,
    BotTurnTracker,
    EndedBy,
    TurnPolicy,
    frames,
    level_dbfs,
)
from reference_bot.app import BotConfig, create_app
from reference_bot.voice import VoiceTurn
from tests.socket_server import serve

TOKEN = "voice-reference-token-0123456789"
TONE = struct.pack(
    "<320h", *[int(8000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(320)]
)
QUIET = b"\x00\x00" * 320


def _wav(seconds: float, rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        n = int(seconds * rate)
        handle.writeframes(
            struct.pack(
                f"<{n}h", *[int(6000 * math.sin(2 * math.pi * 300 * i / rate)) for i in range(n)]
            )
        )
    return buffer.getvalue()


class TestTurnRules:
    def test_framing_and_levels(self) -> None:
        assert [len(f) for f in frames(b"\x01\x00" * 500)] == [FRAME_BYTES, FRAME_BYTES]
        assert level_dbfs(QUIET) == float("-inf")
        assert level_dbfs(TONE) > -45

    def test_latency_is_caller_end_to_first_voiced_frame(self) -> None:
        tracker = BotTurnTracker(TurnPolicy(), caller_started_at=0.0, caller_ended_at=1.0)
        assert tracker.observe(QUIET, 1.1) is None  # silence is not speech
        tracker.observe(TONE, 1.35)
        assert tracker.latency_ms() == 350.0
        assert not tracker.barged_in

    def test_end_of_turn_silence(self) -> None:
        tracker = BotTurnTracker(
            TurnPolicy(end_of_turn_ms=500), caller_started_at=0, caller_ended_at=1
        )
        tracker.observe(TONE, 1.2)
        assert tracker.observe(QUIET, 1.5) is None
        assert tracker.observe(QUIET, 1.71) is EndedBy.END_OF_TURN_SILENCE

    def test_silence_timeout_when_the_bot_never_speaks(self) -> None:
        tracker = BotTurnTracker(
            TurnPolicy(silence_timeout_seconds=2), caller_started_at=0, caller_ended_at=1
        )
        assert tracker.check(2.9) is None
        assert tracker.check(3.0) is EndedBy.SILENCE_TIMEOUT
        assert tracker.latency_ms() is None

    def test_the_deadline_cuts_off_a_bot_that_runs_on(self) -> None:
        tracker = BotTurnTracker(
            TurnPolicy(max_turn_seconds=1), caller_started_at=0, caller_ended_at=1
        )
        tracker.observe(TONE, 1.1)
        assert tracker.observe(TONE, 1.6) is None
        assert tracker.observe(TONE, 2.1) is EndedBy.DEADLINE

    def test_speaking_before_the_caller_ends_is_a_barge_in(self) -> None:
        tracker = BotTurnTracker(TurnPolicy(), caller_started_at=0.0)
        tracker.observe(TONE, 0.2)
        tracker.caller_ended_at = 0.4
        assert tracker.barged_in
        assert tracker.latency_ms() == -200.0
        evidence = tracker.evidence(
            EndedBy.BOT_SIGNAL, caller_frames_sent=10, caller_frames_total=30
        )
        assert evidence["caller_truncated"] is True
        assert evidence["barge_in_after_caller_start_ms"] == 200.0
        assert evidence["vad"] == "energy" and "voice_threshold_dbfs" in evidence["policy"]


@pytest.fixture
def bot(request: pytest.FixtureRequest) -> Iterator[str]:
    script = getattr(request, "param", (VoiceTurn(),))
    with serve(create_app(BotConfig(token=TOKEN, voice_script=script))) as url:
        yield url.replace("http://", "ws://") + "/v1/voice"


def _adapter(url: str, token: str = TOKEN, **policy: float) -> WebSocketVoiceBotAdapter:
    return WebSocketVoiceBotAdapter(
        VoiceBotConfig(
            url=url,
            token=SecretStr(token),
            policy=OutboundPolicy.from_setting(
                "127.0.0.1", allow_loopback=True, allow_private=False
            ),
            turn_policy=TurnPolicy(**policy),
        )
    )


async def _turns(
    adapter: WebSocketVoiceBotAdapter, count: int, caller_seconds: float = 0.4
) -> list:
    run = uuid.uuid4()
    try:
        return [
            await adapter.send_turn(
                _wav(caller_seconds),
                run_id=run,
                turn_index=i,
                content_type="audio/wav",
                language="hi-IN",
                timeout_seconds=20,
            )
            for i in range(count)
        ]
    finally:
        await adapter.close()


class TestAgainstTheReferenceBot:
    def test_a_prompt_answer_records_measured_latency(self, bot: str) -> None:
        reply = asyncio.run(_turns(_adapter(bot), 1))[0]
        assert reply.received_from_bot is True
        assert reply.stream["ended_by"] == "bot_signal"
        assert 250 <= reply.latency_ms <= 1500  # the bot waits 300 ms; real time, real socket
        assert reply.audio[:4] == b"RIFF"
        assert reply.stream["caller_truncated"] is False

    def test_several_turns_share_one_socket(self, bot: str) -> None:
        replies = asyncio.run(_turns(_adapter(bot), 2))
        assert [r.stream["ended_by"] for r in replies] == ["bot_signal", "bot_signal"]

    @pytest.mark.parametrize("bot", [(VoiceTurn(signal_end=False),)], indirect=True)
    def test_without_a_signal_the_turn_is_end_pointed(self, bot: str) -> None:
        reply = asyncio.run(_turns(_adapter(bot, end_of_turn_ms=400), 1))[0]
        assert reply.stream["ended_by"] == "end_of_turn_silence"

    @pytest.mark.parametrize(
        "bot", [(VoiceTurn(behaviour="barge_in", delay_ms=100),)], indirect=True
    )
    def test_a_barge_in_makes_the_caller_yield(self, bot: str) -> None:
        reply = asyncio.run(_turns(_adapter(bot), 1, caller_seconds=1.5))[0]
        assert reply.stream["barge_in"] is True
        assert reply.stream["caller_truncated"] is True
        assert reply.latency_ms < 0

    @pytest.mark.parametrize("bot", [(VoiceTurn(behaviour="silent"),)], indirect=True)
    def test_a_silent_bot_times_out_with_no_audio(self, bot: str) -> None:
        reply = asyncio.run(_turns(_adapter(bot, silence_timeout_seconds=1.0), 1))[0]
        assert reply.stream["ended_by"] == "silence_timeout"
        assert reply.audio == b"" and reply.latency_ms is None

    @pytest.mark.parametrize(
        "bot", [(VoiceTurn(behaviour="endless", delay_ms=100),)], indirect=True
    )
    def test_a_bot_that_runs_on_hits_the_deadline(self, bot: str) -> None:
        reply = asyncio.run(_turns(_adapter(bot, max_turn_seconds=1.0), 1))[0]
        assert reply.stream["ended_by"] == "deadline"
        assert 1.0 <= reply.stream["bot_speaking_wall_seconds"] <= 2.5
        assert 0 < reply.stream["bot_audio_seconds"] <= reply.stream["bot_speaking_wall_seconds"]

    @pytest.mark.parametrize(
        "bot", [(VoiceTurn(speech_ms=3000, yields_to_caller=True),)], indirect=True
    )
    def test_a_bot_that_yields_stops_soon_after_the_caller_barges_in(self, bot: str) -> None:
        adapter = _adapter(bot)
        adapter.set_caller_barge_in(400)
        barge = asyncio.run(_turns(adapter, 1))[0].stream["caller_barge_in"]
        assert barge["sent"] is True and barge["bot_yielded"] is True
        assert barge["sent_after_bot_speech_ms"] >= 400
        assert barge["bot_stopped_after_ms"] < 300  # real time, a real socket
        assert "re-sent" in barge["source"]
        assert "looks the same as yielding" in barge["limitation"]

    @pytest.mark.parametrize("bot", [(VoiceTurn(speech_ms=2500),)], indirect=True)
    def test_a_bot_that_talks_on_is_recorded_as_not_yielding(self, bot: str) -> None:
        adapter = _adapter(bot)
        adapter.set_caller_barge_in(400)
        barge = asyncio.run(_turns(adapter, 1))[0].stream["caller_barge_in"]
        assert barge["sent"] is True and barge["bot_yielded"] is False
        assert barge["bot_stopped_after_ms"] > barge["yield_window_ms"]

    @pytest.mark.parametrize("bot", [(VoiceTurn(speech_ms=200),)], indirect=True)
    def test_a_turn_shorter_than_the_interruption_point_sends_nothing(self, bot: str) -> None:
        adapter = _adapter(bot)
        adapter.set_caller_barge_in(1500)
        barge = asyncio.run(_turns(adapter, 1))[0].stream["caller_barge_in"]
        assert barge["sent"] is False and barge["bot_yielded"] is None
        assert "ended before" in barge["not_sent_reason"]

    def test_without_a_request_there_is_no_barge_in_evidence(self, bot: str) -> None:
        assert "caller_barge_in" not in asyncio.run(_turns(_adapter(bot), 1))[0].stream

    def test_a_wrong_token_is_refused_at_the_handshake(self, bot: str) -> None:
        with pytest.raises(BotUnavailableError):
            asyncio.run(_turns(_adapter(bot, token="not-the-token-0123456789"), 1))

    def test_a_host_off_the_allowlist_is_refused_before_connecting(self) -> None:
        with pytest.raises(BotTargetRefusedError):
            WebSocketVoiceBotAdapter(
                VoiceBotConfig(
                    url="ws://169.254.169.254/v1/voice",
                    token=SecretStr(TOKEN),
                    policy=OutboundPolicy.from_setting(
                        "bots.example", allow_loopback=False, allow_private=False
                    ),
                )
            )

    def test_the_token_never_reaches_an_error(self, bot: str) -> None:
        with pytest.raises(BotUnavailableError) as refused:
            asyncio.run(_turns(_adapter(bot.replace("/v1/voice", "/nope"), token=TOKEN), 1))
        assert TOKEN not in str(refused.value)

    def test_a_redirect_is_refused_and_the_token_never_follows_it(self) -> None:
        # websockets follows a 3xx handshake answer, cross-origin included, and
        # resends our headers. The target never passed check_url, so a bot
        # could aim us anywhere and collect the bearer token.
        async def scenario() -> list[bytes]:
            followed: list[bytes] = []

            async def elsewhere(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                followed.append(await reader.read(4096))
                writer.close()

            async def redirector(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ) -> None:
                await reader.read(4096)
                writer.write(
                    b"HTTP/1.1 302 Found\r\nLocation: ws://127.0.0.1:%d/v1/voice\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n" % target_port
                )
                await writer.drain()
                writer.close()

            target = await asyncio.start_server(elsewhere, "127.0.0.1", 0)
            target_port = target.sockets[0].getsockname()[1]
            source = await asyncio.start_server(redirector, "127.0.0.1", 0)
            source_port = source.sockets[0].getsockname()[1]
            adapter = _adapter(f"ws://127.0.0.1:{source_port}/v1/voice")
            try:
                with pytest.raises(BotUnavailableError):
                    await adapter.send_turn(
                        _wav(0.1),
                        run_id=uuid.uuid4(),
                        turn_index=0,
                        content_type="audio/wav",
                        language="hi-IN",
                        timeout_seconds=5,
                    )
            finally:
                await adapter.close()
                source.close()
                target.close()
                await source.wait_closed()
                await target.wait_closed()
            return followed

        assert asyncio.run(scenario()) == []


# ---------------------------------------------------------------------------
# A whole run through the engine
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from tests import test_pipeline_api as pipeline_tests  # noqa: E402

pipeline_client = pipeline_tests.pipeline_client
scenario_ids = pipeline_tests.scenario_ids


class TestAStreamingRun:
    @pytest.mark.parametrize(
        "bot", [(VoiceTurn(), VoiceTurn(behaviour="silent"), VoiceTurn())], indirect=True
    )
    def test_an_external_bot_test_records_streaming_evidence_per_turn(
        self,
        bot: str,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The harness validates the recorded adapter name through the registry,
        # which would build ws_voice from settings; the adapter under test is
        # injected instead, so only that validation is stubbed.
        monkeypatch.setattr(pipeline_tests, "build_adapter", lambda *a, **k: None)
        pipeline_client.pipeline_state["adapter"] = _adapter(bot, silence_timeout_seconds=1.0)
        run = pipeline_tests._create(
            pipeline_client, scenario_ids, mode="external_bot_test", max_turns=3
        )
        body = pipeline_client.post(f"{pipeline_tests.BASE}/{run['run_id']}/start").json()
        assert body["status"] in ("completed", "failed"), body
        assert body["bot_audio_externally_received"] is True
        report = pipeline_client.get(f"{pipeline_tests.BASE}/{run['run_id']}/report").json()
        exchanges = [
            e for e in report["events"] if e["stage"] == "bot_exchange" and e["status"] == "ok"
        ]
        assert exchanges and all(e["evidence"]["vad"] == "energy" for e in exchanges)
        assert exchanges[0]["evidence"]["bot_latency_ms"] is not None
        assert "silence_timeout" in [e["evidence"]["ended_by"] for e in exchanges]
        turns = pipeline_client.get(f"{pipeline_tests.BASE}/{run['run_id']}/turns").json()["turns"]
        silent = [t for t in turns if t["speaker"] == "bot" and t["text"] == ""]
        assert silent, "a silent bot turn is recorded as the bot saying nothing"

    def test_fixture_mode_refuses_an_external_voice_bot(
        self, bot: str, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = _adapter(bot)
        suite_id, scenario_id = scenario_ids
        response = pipeline_client.post(
            pipeline_tests.BASE,
            json={
                "suite_id": str(suite_id),
                "scenario_id": str(scenario_id),
                "mode": "audio_fixture_test",
            },
        )
        assert response.status_code == 422
        assert "external_bot_test" in response.json()["error"]["message"]

    @pytest.mark.parametrize(
        "bot", [(VoiceTurn(speech_ms=2000, yields_to_caller=True),)], indirect=True
    )
    def test_a_run_with_caller_barge_in_records_it_on_every_exchange(
        self,
        bot: str,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pipeline_tests, "build_adapter", lambda *a, **k: None)
        pipeline_client.pipeline_state["adapter"] = _adapter(bot)
        run = pipeline_tests._create(
            pipeline_client,
            scenario_ids,
            mode="external_bot_test",
            max_turns=2,
            caller_barge_in_after_ms=300,
        )
        assert run["caller_barge_in_after_ms"] == 300
        pipeline_client.post(f"{pipeline_tests.BASE}/{run['run_id']}/start")
        report = pipeline_client.get(f"{pipeline_tests.BASE}/{run['run_id']}/report").json()
        exchanges = [
            e for e in report["events"] if e["stage"] == "bot_exchange" and e["status"] == "ok"
        ]
        assert exchanges
        for exchange in exchanges:
            barge = exchange["evidence"]["caller_barge_in"]
            assert barge["sent"] is True and barge["bot_yielded"] is True

    def test_an_adapter_without_a_live_stream_refuses_caller_barge_in(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        suite_id, scenario_id = scenario_ids
        response = pipeline_client.post(
            pipeline_tests.BASE,
            json={
                "suite_id": str(suite_id),
                "scenario_id": str(scenario_id),
                "mode": "audio_fixture_test",
                "caller_barge_in_after_ms": 500,
            },
        )
        assert response.status_code == 422
        assert "cannot interrupt the bot" in response.json()["error"]["message"]

    def test_the_adapter_listing_says_which_adapters_can_barge_in(
        self, pipeline_client: TestClient
    ) -> None:
        listing = pipeline_client.get(f"{pipeline_tests.BASE}/bot-adapters/available").json()
        capable = {a["name"]: a["supports_caller_barge_in"] for a in listing["adapters"]}
        assert capable["ws_voice"] is True
        assert capable["scripted"] is False and capable["http"] is False

    @pytest.mark.parametrize("bot", [(VoiceTurn(),)], indirect=True)
    def test_a_barge_in_run_no_longer_claims_the_caller_never_interrupts(
        self,
        bot: str,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pipeline_tests, "build_adapter", lambda *a, **k: None)
        pipeline_client.pipeline_state["adapter"] = _adapter(bot)
        plain = pipeline_tests._create(pipeline_client, scenario_ids, mode="external_bot_test")
        barging = pipeline_tests._create(
            pipeline_client, scenario_ids, mode="external_bot_test", caller_barge_in_after_ms=300
        )
        listed = [{e["setting"] for e in run["settings_not_enforced"]} for run in (plain, barging)]
        assert "constraints.allow_interruptions" in listed[0]
        assert "constraints.allow_interruptions" not in listed[1]
