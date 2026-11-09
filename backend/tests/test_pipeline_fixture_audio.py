"""Tests for the fixture audio an API-started scripted run replays.

`AUDIO_FIXTURE_TEST` was unusable through the API: the route built the
scripted adapter with no replies, so the first turn failed with "the scripted
bot has no reply for turn 0". The tests in `test_pipeline_api.py` never caught
it because they override the engine factory and inject their own adapter - so
the one seam that was broken was the one seam those tests replace.

These tests drive the real `get_engine_factory`, which is the code that was
wrong. Two behaviours are pinned:

- With `PIPELINE_FIXTURE_AUDIO_PATH` set, the scripted adapter replays that
  file and the reply is still marked as *not* received from a bot.
- With it unset, nothing changes. A scripted run has no replies, exactly as
  before, because that failure is honest when no fixture is configured.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.api.v1.test_runs import get_engine_factory
from app.core.config import Settings
from app.pipeline.bots.registry import fixture_replies_from_path
from app.pipeline.engine import RunEngine
from app.pipeline.errors import BotAdapterError, PipelineConfigurationError

WAV_NAME = "tone_8k_mono.wav"


@pytest.fixture
def fixture_wav(audio_fixtures: Path) -> Path:
    """A real WAV from the committed fixtures - a tone, not speech."""
    return audio_fixtures / WAV_NAME


# ---------------------------------------------------------------------------
# Reading the fixture
# ---------------------------------------------------------------------------


class TestFixtureReplies:
    def test_the_file_is_repeated_once_per_turn(self, fixture_wav: Path) -> None:
        replies = fixture_replies_from_path(fixture_wav, count=5)

        assert len(replies) == 5
        assert all(reply == fixture_wav.read_bytes() for reply in replies)

    def test_the_payload_is_referenced_not_copied(self, fixture_wav: Path) -> None:
        """A 100-turn budget must not hold 100 copies of the audio."""
        replies = fixture_replies_from_path(fixture_wav, count=20)

        assert all(reply is replies[0] for reply in replies)

    def test_a_missing_file_names_the_path(self, tmp_path: Path) -> None:
        """Fail where the mistake is, not later as the turn-0 error."""
        missing = tmp_path / "nope.wav"

        with pytest.raises(PipelineConfigurationError) as excinfo:
            fixture_replies_from_path(missing, count=1)

        assert "nope.wav" in str(excinfo.value)
        assert "PIPELINE_FIXTURE_AUDIO_PATH" in str(excinfo.value)

    def test_a_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PipelineConfigurationError):
            fixture_replies_from_path(tmp_path, count=1)

    def test_an_empty_file_is_refused(self, tmp_path: Path) -> None:
        """An empty reply and a bot saying nothing must not look alike."""
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")

        with pytest.raises(PipelineConfigurationError) as excinfo:
            fixture_replies_from_path(empty, count=1)

        assert "empty" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Wiring it through the real engine factory
# ---------------------------------------------------------------------------


def _engine(settings: Settings, session: Session, adapter: str | None) -> RunEngine:
    """Build an engine through the production factory.

    The generator is left open deliberately: its teardown only drops provider
    references, and the adapter has to outlive this call to be asserted on.
    """
    factory = get_engine_factory(settings, session)
    return next(factory(adapter))


async def _reply(engine: RunEngine, audio: bytes = b"caller") -> object:
    # `_bot` is private, and this is the one test that reaches for it: the
    # defect was in how the factory wires the adapter, so the adapter itself
    # is what has to be observed.
    return await engine._bot.send_turn(
        audio,
        run_id=uuid.uuid4(),
        turn_index=0,
        content_type="audio/wav",
        language="ta-IN",
        timeout_seconds=5.0,
    )


class TestEngineFactoryWiring:
    def test_a_configured_fixture_is_replayed(
        self, settings: Settings, db_session: Session, fixture_wav: Path
    ) -> None:
        configured = settings.model_copy(update={"pipeline_fixture_audio_path": str(fixture_wav)})

        engine = _engine(configured, db_session, "scripted")
        reply = asyncio.run(_reply(engine))

        assert reply.audio == fixture_wav.read_bytes()  # type: ignore[attr-defined]

    def test_a_replayed_fixture_is_not_claimed_as_bot_audio(
        self, settings: Settings, db_session: Session, fixture_wav: Path
    ) -> None:
        """The honesty control: a fixture can never read as an external bot."""
        configured = settings.model_copy(update={"pipeline_fixture_audio_path": str(fixture_wav)})

        engine = _engine(configured, db_session, "scripted")
        reply = asyncio.run(_reply(engine))

        assert reply.received_from_bot is False  # type: ignore[attr-defined]

    def test_without_the_setting_a_scripted_run_still_has_no_replies(
        self, settings: Settings, db_session: Session
    ) -> None:
        """Unset must mean unchanged, including the failure."""
        assert settings.pipeline_fixture_audio_path is None

        engine = _engine(settings, db_session, "scripted")

        with pytest.raises(BotAdapterError, match="no reply for turn 0"):
            asyncio.run(_reply(engine))

    def test_the_manual_adapter_is_not_offered_the_fixture(
        self, settings: Settings, db_session: Session, fixture_wav: Path
    ) -> None:
        """It refuses scripted replies, so offering them would break it.

        This is the regression guard for the branch that only passes replies
        to the scripted adapter.
        """
        configured = settings.model_copy(update={"pipeline_fixture_audio_path": str(fixture_wav)})

        engine = _engine(configured, db_session, "manual")

        assert engine._bot.capabilities.name == "manual"
