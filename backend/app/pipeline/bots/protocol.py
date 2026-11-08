"""What a voice bot under test has to look like to this pipeline.

One method that matters: hand it caller audio, get bot audio back. Everything
else - timeouts, sessions, metadata - exists because a real integration will
need it, and retrofitting a parameter into a protocol that adapters already
implement is worse than declaring it now.

**No third-party bot API is invented here.** There are two adapters: one that
replays fixtures, and one that waits for a human or an external system to
supply the reply. Both are honest about being offline. A real integration is
an adapter someone writes against a real bot's documentation, registered the
same way a speech provider is - see `docs/PIPELINE.md`.

**The default must not send audio anywhere.** §7 requires it, and the registry
enforces it: the default adapter is the scripted one, and no adapter in this
phase opens a socket.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class BotReply:
    """One bot utterance as audio, plus what is known about where it came from.

    `received_from_bot` is the field that keeps the report honest. A fixture
    replayed from disk and audio returned by a real bot are both `BotReply`
    instances, and only the flag distinguishes them - so `ExecutionMode` can be
    checked against reality rather than against intent.
    """

    audio: bytes
    content_type: str = "audio/wav"
    received_from_bot: bool = False
    """True only when a system outside this process produced this audio.

    False for fixtures. The engine refuses to describe a run as an
    `EXTERNAL_BOT_TEST` if any reply came back with this unset.
    """
    session_id: str | None = None
    """The bot's own identifier for the conversation, where it has one."""
    latency_ms: float | None = None
    """Measured, not estimated. `None` when the adapter did not time anything."""
    metadata: dict[str, str] = field(default_factory=dict)
    """Adapter-specific detail. Must never carry a credential."""

    @property
    def size_bytes(self) -> int:
        return len(self.audio)


@dataclass(frozen=True, slots=True)
class BotCapabilities:
    """What an adapter can do, and what it is.

    Mirrors `ProviderCapabilities` and `CallerCapabilities`: the same honesty
    discipline, declared rather than inferred.
    """

    name: str
    display_name: str
    contacts_external_system: bool
    """Whether using this adapter causes a request to leave this process.

    False for both Phase 7 adapters. The engine uses this to decide whether a
    run may claim `EXTERNAL_BOT_TEST`, and the API reports it so an operator
    can see at a glance that nothing is being sent anywhere.
    """
    supports_sessions: bool
    requires_credentials: bool
    accepts_containers: frozenset[str]
    notes: tuple[str, ...]
    """Honest limitations, in the same spirit as the speech providers'."""


@runtime_checkable
class BotAdapter(Protocol):
    """A voice bot the pipeline can hold a conversation with."""

    @property
    def capabilities(self) -> BotCapabilities:
        """What this adapter is and can do."""
        ...

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
        """Deliver one caller utterance and return the bot's reply.

        `timeout_seconds` is a ceiling on the whole exchange, and an adapter
        that cannot honour it must raise rather than block - a run that hangs
        is worse than a run that fails, because it holds a database session.

        Raises:
            BotAudioPendingError: the reply is not available yet. Not a
                failure; the run is waiting for input.
            BotTimeoutError: no reply within `timeout_seconds`.
            BotUnavailableError: the bot could not be reached.
            BotAdapterError: any other adapter failure.
        """
        ...

    async def close(self) -> None:
        """Release anything the adapter holds."""
        ...


__all__ = ["BotAdapter", "BotCapabilities", "BotReply"]
