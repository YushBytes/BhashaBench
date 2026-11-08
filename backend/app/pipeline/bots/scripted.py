"""A bot whose replies are read from a fixed list of audio payloads.

The offline adapter: no network, no credential, deterministic. It is what makes
`AUDIO_FIXTURE_TEST` possible, and what the tests use to drive a whole
multi-turn run through real synthesis, real degradation, real storage and real
transcription with only the bot stubbed.

It declares `received_from_bot=False` on every reply, which is the mechanism
preventing a fixture run from being reported as an external bot test.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.pipeline.bots.protocol import BotCapabilities, BotReply
from app.pipeline.errors import BotAdapterError

PROVIDER_NAME = "scripted"


class ScriptedBotAdapter:
    """Replays pre-supplied audio, one payload per turn.

    `failures` is consumed alongside the replies so a test can drive the exact
    sequence a retry or a failure path needs: a script of
    `[None, BotTimeoutError(...)]` succeeds once and then times out.
    """

    def __init__(
        self,
        replies: Sequence[bytes],
        *,
        content_type: str = "audio/wav",
        failures: Sequence[BotAdapterError | None] | None = None,
        exhausted_is_error: bool = True,
    ) -> None:
        self._replies = list(replies)
        self._content_type = content_type
        self._failures = list(failures or ())
        self._exhausted_is_error = exhausted_is_error
        self.calls: list[tuple[int, int]] = []
        """(turn_index, bytes received) for each call, so a test can assert
        what the pipeline actually sent rather than what it meant to send."""
        self.closed = False

    @property
    def capabilities(self) -> BotCapabilities:
        return BotCapabilities(
            name=PROVIDER_NAME,
            display_name="Scripted offline bot",
            # The field that matters. Nothing leaves this process.
            contacts_external_system=False,
            supports_sessions=False,
            requires_credentials=False,
            accepts_containers=frozenset({"wav"}),
            notes=(
                "Replays fixed audio payloads. It is not a voice bot and its "
                "replies establish nothing about any bot's behaviour.",
                "Sends no request anywhere. Safe as the default adapter.",
                "Deterministic: the same script produces the same run.",
            ),
        )

    async def send_turn(
        self,
        audio: bytes,
        *,
        run_id: uuid.UUID,
        turn_index: int,
        content_type: str,
        language: str,
        timeout_seconds: float,
        session_id: str | None = None,
    ) -> BotReply:
        """Return the next scripted reply."""
        self.calls.append((turn_index, len(audio)))

        if self._failures:
            failure = self._failures.pop(0)
            if failure is not None:
                raise failure

        if not self._replies:
            if self._exhausted_is_error:
                raise BotAdapterError(
                    f"the scripted bot has no reply for turn {turn_index}; "
                    f"{len(self.calls)} replies were requested",
                    adapter=PROVIDER_NAME,
                    run_id=str(run_id),
                    stage="bot_exchange",
                )
            # Silence rather than an error, for a test that wants the caller's
            # own unintelligible-bot path rather than an adapter failure.
            return BotReply(audio=b"", content_type=self._content_type)

        return BotReply(
            audio=self._replies.pop(0),
            content_type=self._content_type,
            received_from_bot=False,
            metadata={"source": "scripted_fixture"},
        )

    async def close(self) -> None:
        self.closed = True


__all__ = ["PROVIDER_NAME", "ScriptedBotAdapter"]
