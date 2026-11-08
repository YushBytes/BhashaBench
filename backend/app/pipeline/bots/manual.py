"""A bot whose replies a person or an external system supplies, one at a time.

This is how a real bot gets tested without this repository inventing an
integration for it. The pipeline synthesises the caller's turn, degrades it and
stores it; an operator plays that artefact to their bot - over a phone, through
a web widget, however the bot is reachable - records the answer and posts it
back to `POST /api/v1/test-runs/{id}/bot-audio`. The run then continues.

So the audio exchange is genuinely with the bot under test, while the transport
is a human rather than a protocol this project guessed at. That is the honest
maximum available until a bot publishes an API or Phase 8 builds telephony.

**`received_from_bot` is the operator's assertion, and it is recorded as
such.** Submitting audio through this adapter marks it as externally obtained,
because the operator is stating that it came from their bot. The report says
which adapter was used, so a reader can weigh that claim appropriately; the
pipeline cannot verify it, and does not pretend to.
"""

from __future__ import annotations

import uuid

from app.pipeline.bots.protocol import BotCapabilities, BotReply
from app.pipeline.errors import BotAudioPendingError

PROVIDER_NAME = "manual"


class ManualBotAdapter:
    """Holds one pending reply at a time, supplied out of band.

    Deliberately a single slot rather than a queue: the pipeline is strictly
    turn-by-turn, and a queue would let a second reply arrive for a turn that
    has not been asked yet, which is a race nobody needs.
    """

    def __init__(self) -> None:
        self._pending: BotReply | None = None
        self._awaiting_turn: int | None = None
        self.closed = False

    @property
    def capabilities(self) -> BotCapabilities:
        return BotCapabilities(
            name=PROVIDER_NAME,
            display_name="Manual external audio exchange",
            # False: *this process* contacts nothing. The operator does the
            # contacting, which is exactly why no audio is sent anywhere
            # automatically and the default configuration is safe.
            contacts_external_system=False,
            supports_sessions=True,
            requires_credentials=False,
            accepts_containers=frozenset({"wav"}),
            notes=(
                "The pipeline stores the caller's audio and waits. An operator "
                "plays it to the bot under test and posts the reply back.",
                "Audio supplied this way is recorded as externally obtained "
                "because the operator asserts it came from their bot. The "
                "pipeline cannot verify that claim.",
                "Sends no request anywhere itself.",
            ),
        )

    @property
    def awaiting_turn(self) -> int | None:
        """The turn index a reply is wanted for, or `None` if none is wanted."""
        return self._awaiting_turn

    def supply(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        session_id: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """Hand the adapter the bot's reply for the awaited turn."""
        self._pending = BotReply(
            audio=audio,
            content_type=content_type,
            # The operator's assertion, recorded as the operator's assertion.
            received_from_bot=True,
            session_id=session_id,
            latency_ms=latency_ms,
            metadata={"source": "manual_submission"},
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
        """Return the supplied reply, or say the run is waiting for one."""
        if self._pending is None:
            self._awaiting_turn = turn_index
            raise BotAudioPendingError(
                f"the caller's audio for turn {turn_index} is stored and the run "
                "is waiting for the bot's reply; submit it to this run's "
                "bot-audio endpoint to continue",
                adapter=PROVIDER_NAME,
                retryable=True,
                run_id=str(run_id),
                stage="bot_exchange",
            )
        reply = self._pending
        self._pending = None
        self._awaiting_turn = None
        return reply

    async def close(self) -> None:
        self._pending = None
        self.closed = True


__all__ = ["PROVIDER_NAME", "ManualBotAdapter"]
