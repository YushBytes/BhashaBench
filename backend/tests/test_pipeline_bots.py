"""The bot adapter abstraction and the two adapters that ship.

Small, because the adapters are small. The assertions that matter are the
honesty ones: that neither adapter contacts anything, that the default is the
one which contacts nothing, that a fixture reply is never marked as having come
from a bot, and that no registry entry pretends a real voice bot exists.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.pipeline.bots.manual import PROVIDER_NAME as MANUAL
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.protocol import BotAdapter, BotReply
from app.pipeline.bots.registry import (
    DEFAULT_ADAPTER,
    available_adapters,
    build_adapter,
    describe_adapters,
    fixture_text_replies_from_path,
)
from app.pipeline.bots.scripted import PROVIDER_NAME as SCRIPTED
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.errors import (
    BotAdapterError,
    BotAudioPendingError,
    BotTimeoutError,
    PipelineConfigurationError,
)

RUN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _send(adapter: BotAdapter, audio: bytes = b"RIFF....", *, turn: int = 0) -> BotReply:
    return asyncio.run(
        adapter.send_turn(
            audio,
            run_id=RUN_ID,
            turn_index=turn,
            content_type="audio/wav",
            language="ta-IN",
            timeout_seconds=5.0,
        )
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_both_adapters_are_registered(self) -> None:
        assert available_adapters() == (MANUAL, SCRIPTED)

    def test_the_default_sends_audio_nowhere(self) -> None:
        """§7 requires the default configuration to be safe, and the way to be
        safe is to default to the adapter that contacts nothing."""
        assert DEFAULT_ADAPTER == SCRIPTED
        assert build_adapter(DEFAULT_ADAPTER).capabilities.contacts_external_system is False

    def test_no_adapter_contacts_an_external_system(self) -> None:
        assert all(c.contacts_external_system is False for c in describe_adapters())

    def test_no_adapter_requires_a_credential(self) -> None:
        assert all(c.requires_credentials is False for c in describe_adapters())

    def test_there_is_no_adapter_for_an_invented_bot_api(self) -> None:
        """A registry entry for a bot whose interface nobody has read would be
        the same dishonesty as an invented provider endpoint."""
        for name in ("twilio", "dialogflow", "gnani_bot", "evon"):
            assert name not in available_adapters()

    def test_an_unknown_adapter_is_refused_with_an_explanation(self) -> None:
        with pytest.raises(PipelineConfigurationError) as caught:
            build_adapter("some_vendor_bot")
        message = str(caught.value)
        assert "not a known bot adapter" in message
        assert "does not invent one" in message

    @pytest.mark.parametrize("spelling", ["SCRIPTED", "  scripted  ", "Scripted"])
    def test_the_adapter_name_is_normalised(self, spelling: str) -> None:
        assert build_adapter(spelling).capabilities.name == SCRIPTED

    def test_the_manual_adapter_takes_no_scripted_replies(self) -> None:
        """Ignoring them silently would hide a configuration mistake: the whole
        point of that adapter is that the audio arrives later."""
        with pytest.raises(PipelineConfigurationError, match="takes no scripted replies"):
            build_adapter(MANUAL, replies=[b"RIFF"])

    def test_both_adapters_satisfy_the_protocol(self) -> None:
        for name in available_adapters():
            assert isinstance(build_adapter(name), BotAdapter)

    def test_every_adapter_discloses_its_limitations(self) -> None:
        for capabilities in describe_adapters():
            assert capabilities.notes
            assert all(note.strip() for note in capabilities.notes)


# ---------------------------------------------------------------------------
# The scripted adapter
# ---------------------------------------------------------------------------


class TestScriptedAdapter:
    def test_it_replays_its_replies_in_order(self) -> None:
        adapter = ScriptedBotAdapter([b"one", b"two"])
        assert _send(adapter).audio == b"one"
        assert _send(adapter, turn=1).audio == b"two"

    def test_a_fixture_reply_is_never_marked_as_coming_from_a_bot(self) -> None:
        """The mechanism that stops a fixture run being reported as an external
        bot test."""
        assert _send(ScriptedBotAdapter([b"one"])).received_from_bot is False

    def test_it_records_what_it_was_actually_sent(self) -> None:
        """So a test can assert what the pipeline sent rather than what it
        meant to send."""
        adapter = ScriptedBotAdapter([b"one"])
        _send(adapter, b"0123456789", turn=3)
        assert adapter.calls == [(3, 10)]

    def test_running_out_of_replies_is_an_error_by_default(self) -> None:
        adapter = ScriptedBotAdapter([])
        with pytest.raises(BotAdapterError, match="no reply for turn"):
            _send(adapter)

    def test_running_out_can_be_made_silence_instead(self) -> None:
        """For a test that wants the caller's own unintelligible-bot path
        rather than an adapter failure."""
        adapter = ScriptedBotAdapter([], exhausted_is_error=False)
        assert _send(adapter).audio == b""

    def test_a_scripted_failure_is_raised(self) -> None:
        adapter = ScriptedBotAdapter(
            [b"one"], failures=[BotTimeoutError("timed out", adapter=SCRIPTED)]
        )
        with pytest.raises(BotTimeoutError):
            _send(adapter)

    def test_a_scripted_failure_can_precede_a_success(self) -> None:
        """`[failure, None]` drives fail-then-succeed, which is the path a
        retry has to handle."""
        adapter = ScriptedBotAdapter(
            [b"one"], failures=[BotTimeoutError("timed out", adapter=SCRIPTED), None]
        )
        with pytest.raises(BotTimeoutError):
            _send(adapter)
        assert _send(adapter, turn=1).audio == b"one"

    def test_it_is_deterministic(self) -> None:
        first = ScriptedBotAdapter([b"one", b"two"])
        second = ScriptedBotAdapter([b"one", b"two"])
        assert [_send(first).audio, _send(first, turn=1).audio] == [
            _send(second).audio,
            _send(second, turn=1).audio,
        ]

    def test_closing_is_recorded(self) -> None:
        adapter = ScriptedBotAdapter([])
        asyncio.run(adapter.close())
        assert adapter.closed


# ---------------------------------------------------------------------------
# The manual adapter
# ---------------------------------------------------------------------------


class TestManualAdapter:
    def test_it_says_the_run_is_waiting_rather_than_failing(self) -> None:
        """A run awaiting input is healthy, and recording it as a bot outage
        would be false."""
        adapter = ManualBotAdapter()
        with pytest.raises(BotAudioPendingError) as caught:
            _send(adapter, turn=2)
        assert caught.value.retryable is True
        assert "waiting for the bot's reply" in str(caught.value)

    def test_it_records_which_turn_it_wants_audio_for(self) -> None:
        adapter = ManualBotAdapter()
        with pytest.raises(BotAudioPendingError):
            _send(adapter, turn=4)
        assert adapter.awaiting_turn == 4

    def test_supplied_audio_is_returned(self) -> None:
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply")
        assert _send(adapter).audio == b"the reply"

    def test_supplied_audio_is_marked_as_externally_obtained(self) -> None:
        """The operator's assertion, recorded as the operator's assertion."""
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply")
        assert _send(adapter).received_from_bot is True

    def test_a_reply_is_consumed_once(self) -> None:
        """A single slot rather than a queue: the pipeline is strictly
        turn-by-turn, and a queue would let a reply arrive for a turn that has
        not been asked yet."""
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply")
        _send(adapter)
        with pytest.raises(BotAudioPendingError):
            _send(adapter, turn=1)

    def test_the_awaited_turn_is_cleared_once_answered(self) -> None:
        adapter = ManualBotAdapter()
        with pytest.raises(BotAudioPendingError):
            _send(adapter)
        adapter.supply(b"the reply")
        _send(adapter)
        assert adapter.awaiting_turn is None

    def test_a_session_identifier_is_carried_through(self) -> None:
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply", session_id="call-42")
        assert _send(adapter).session_id == "call-42"

    def test_a_measured_latency_is_carried_through(self) -> None:
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply", latency_ms=1234.5)
        assert _send(adapter).latency_ms == 1234.5

    def test_latency_is_none_when_nothing_was_timed(self) -> None:
        """Measured or absent, never estimated."""
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply")
        assert _send(adapter).latency_ms is None

    def test_its_notes_say_the_claim_cannot_be_verified(self) -> None:
        notes = " ".join(ManualBotAdapter().capabilities.notes).lower()
        assert "cannot verify" in notes

    def test_closing_discards_a_pending_reply(self) -> None:
        adapter = ManualBotAdapter()
        adapter.supply(b"the reply")
        asyncio.run(adapter.close())
        assert adapter.closed
        with pytest.raises(BotAudioPendingError):
            _send(adapter)


class TestBotReply:
    def test_the_default_reply_is_not_from_a_bot(self) -> None:
        """The safe default: a reply has to be positively asserted as external,
        so a new adapter cannot claim one by forgetting the field."""
        assert BotReply(audio=b"x").received_from_bot is False

    def test_the_size_is_derived_from_the_payload(self) -> None:
        assert BotReply(audio=b"12345").size_bytes == 5

    def test_metadata_defaults_to_empty(self) -> None:
        assert BotReply(audio=b"x").metadata == {}


# ---------------------------------------------------------------------------
# Text replies for offline_simulation
# ---------------------------------------------------------------------------


class TestFixtureTextReplies:
    """`PIPELINE_FIXTURE_BOT_TEXT_PATH`: the scripted bot's side offline."""

    def test_lines_are_used_in_order_and_repeated(self, tmp_path: Path) -> None:
        path = tmp_path / "replies.txt"
        path.write_text("first\nsecond\n", encoding="utf-8")

        assert fixture_text_replies_from_path(path, count=5) == (
            "first",
            "second",
            "first",
            "second",
            "first",
        )

    def test_blank_and_comment_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "replies.txt"
        path.write_text("# a comment\n\n  only reply  \n", encoding="utf-8")

        assert fixture_text_replies_from_path(path, count=2) == ("only reply", "only reply")

    def test_a_missing_file_is_refused_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineConfigurationError, match="PIPELINE_FIXTURE_BOT_TEXT_PATH"):
            fixture_text_replies_from_path(tmp_path / "absent.txt", count=3)

    def test_a_file_with_no_replies_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "replies.txt"
        path.write_text("# only comments\n\n", encoding="utf-8")

        with pytest.raises(PipelineConfigurationError, match="holds no replies"):
            fixture_text_replies_from_path(path, count=3)

    def test_the_shipped_fixture_loads(self) -> None:
        shipped = Path(__file__).parent / "fixtures" / "bot_text" / "cooperative_en.txt"
        replies = fixture_text_replies_from_path(shipped, count=4)

        assert len(set(replies)) == 4
        assert not any(reply.startswith("#") for reply in replies)
