"""Turn-taking over a live audio stream (Phase 9): framing, voice activity,
end-pointing, barge-in, silence timeouts and deadlines. Pure: no sockets, no
clock of its own - every decision is a function of frames and the times they
were observed, so each rule is unit-testable with synthetic audio.

**Wire format.** 16-bit little-endian mono PCM at 16 kHz in 20 ms frames
(640 bytes), the shape `bhashabench-voice-bot/1` uses (docs/BOT_PROTOCOL.md).

**Voice activity.** A frame is voiced when its RMS level is at or above
`TurnPolicy.voice_threshold_dbfs`. Energy, not a learned model: it is
transparent, needs no dependency, and its failure mode (a loud non-speech
noise counts as speech) is documented rather than hidden. Every decision it
makes is recorded with its threshold, so a reader can tell a bot that never
spoke from a detector that never heard it.

**What is measured, and from where.** Bot latency is the time from the moment
the caller's last frame was sent to the moment the first *voiced* bot frame
arrived - the delay a person on the line would hear, not the delay until the
first packet. Times come from the adapter's monotonic clock, never from the
bot.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass, field
from enum import StrEnum

SAMPLE_RATE_HZ = 16_000
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE_HZ * FRAME_MS // 1000
FRAME_BYTES = SAMPLES_PER_FRAME * 2


def frames(pcm: bytes) -> list[bytes]:
    """Split PCM into whole 20 ms frames; a short final frame is zero-padded."""
    if not pcm:
        return []
    usable = pcm[: len(pcm) - (len(pcm) % 2)]
    out = [usable[i : i + FRAME_BYTES] for i in range(0, len(usable), FRAME_BYTES)]
    if len(out[-1]) < FRAME_BYTES:
        out[-1] = out[-1] + b"\x00" * (FRAME_BYTES - len(out[-1]))
    return out


def level_dbfs(frame: bytes) -> float:
    """RMS level relative to full scale; -inf for digital silence."""
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % 2)])
    if not samples:
        return float("-inf")
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return float("-inf") if rms == 0 else 20 * math.log10(rms / 32768)


class EndedBy(StrEnum):
    END_OF_TURN_SILENCE = "end_of_turn_silence"
    """The bot spoke, then stayed quiet for `end_of_turn_ms`."""
    BOT_SIGNAL = "bot_signal"
    """The bot sent `turn_end` itself."""
    SILENCE_TIMEOUT = "silence_timeout"
    """The bot never spoke within `silence_timeout_seconds`: a finding."""
    DEADLINE = "deadline"
    """The bot was still speaking at `max_turn_seconds`: cut off, a finding."""
    BOT_HANGUP = "bot_hangup"


@dataclass(frozen=True, slots=True)
class TurnPolicy:
    voice_threshold_dbfs: float = -45.0
    end_of_turn_ms: float = 700.0
    silence_timeout_seconds: float = 5.0
    max_turn_seconds: float = 30.0
    yield_on_barge_in: bool = True
    """Stop streaming the caller's remaining audio when the bot talks over it,
    as a person would. Recorded either way."""
    caller_barge_in_after_ms: float | None = None
    """The reverse barge-in: once the bot has been speaking this long, the
    caller talks over it. `None` (the default) never interrupts."""
    caller_barge_in_ms: float = 600.0
    """How much caller audio the interruption carries."""
    yield_window_ms: float = 500.0
    """The bot counts as having yielded if no voiced audio of its own
    arrives later than this after the interruption began. Short on purpose:
    a reply that was about to end anyway is indistinguishable from yielding,
    and a tight window makes that coincidence less likely."""

    def as_dict(self) -> dict[str, object]:
        return {
            "voice_threshold_dbfs": self.voice_threshold_dbfs,
            "end_of_turn_ms": self.end_of_turn_ms,
            "silence_timeout_seconds": self.silence_timeout_seconds,
            "max_turn_seconds": self.max_turn_seconds,
            "yield_on_barge_in": self.yield_on_barge_in,
            "caller_barge_in_after_ms": self.caller_barge_in_after_ms,
            "caller_barge_in_ms": self.caller_barge_in_ms,
            "yield_window_ms": self.yield_window_ms,
        }


@dataclass
class BotTurnTracker:
    """Follows one bot turn as frames arrive.

    `caller_started_at` and `caller_ended_at` are set by the adapter as it
    streams; `observe` is called with each bot frame and its arrival time and
    returns why the turn ended, or `None` while it is still going.
    """

    policy: TurnPolicy
    caller_started_at: float
    caller_ended_at: float | None = None
    speech_started_at: float | None = None
    last_voiced_at: float | None = None
    barge_in_at: float | None = None
    voiced_frames: int = 0
    total_frames: int = 0
    audio: bytearray = field(default_factory=bytearray)

    def observe(self, frame: bytes, at: float) -> EndedBy | None:
        self.total_frames += 1
        self.audio.extend(frame)
        if level_dbfs(frame) >= self.policy.voice_threshold_dbfs:
            self.voiced_frames += 1
            if self.speech_started_at is None:
                self.speech_started_at = at
                if self.caller_ended_at is None:
                    self.barge_in_at = at
            self.last_voiced_at = at
        return self.check(at)

    def check(self, now: float) -> EndedBy | None:
        """Time-based endings, also called when no frame arrives."""
        if self.speech_started_at is None:
            if (
                self.caller_ended_at is not None
                and now - self.caller_ended_at >= self.policy.silence_timeout_seconds
            ):
                return EndedBy.SILENCE_TIMEOUT
            return None
        if now - self.speech_started_at >= self.policy.max_turn_seconds:
            return EndedBy.DEADLINE
        if (
            self.caller_ended_at is not None
            and self.last_voiced_at is not None
            and (now - self.last_voiced_at) * 1000 >= self.policy.end_of_turn_ms
        ):
            return EndedBy.END_OF_TURN_SILENCE
        return None

    @property
    def barged_in(self) -> bool:
        return self.barge_in_at is not None

    def latency_ms(self) -> float | None:
        """Caller end to first voiced bot frame. `None` if the bot never spoke,
        and negative when it spoke before the caller finished (a barge-in)."""
        if self.speech_started_at is None or self.caller_ended_at is None:
            return None
        return round((self.speech_started_at - self.caller_ended_at) * 1000, 1)

    def evidence(
        self,
        ended_by: EndedBy,
        *,
        caller_frames_sent: int,
        caller_frames_total: int,
        ended_at: float | None = None,
    ) -> dict[str, object]:
        return {
            "ended_by": ended_by.value,
            "bot_latency_ms": self.latency_ms(),
            "barge_in": self.barged_in,
            "barge_in_after_caller_start_ms": (
                None
                if self.barge_in_at is None
                else round((self.barge_in_at - self.caller_started_at) * 1000, 1)
            ),
            "caller_frames_sent": caller_frames_sent,
            "caller_frames_total": caller_frames_total,
            "caller_truncated": caller_frames_sent < caller_frames_total,
            "bot_frames": self.total_frames,
            "bot_voiced_frames": self.voiced_frames,
            "bot_audio_seconds": round(self.total_frames * FRAME_MS / 1000, 3),
            # Audio received and wall time differ when a sender paces loosely;
            # the deadline is judged on wall time, so both are recorded.
            "bot_speaking_wall_seconds": (
                None
                if self.speech_started_at is None or ended_at is None
                else round(ended_at - self.speech_started_at, 3)
            ),
            "policy": self.policy.as_dict(),
            "vad": "energy",
        }


__all__ = [
    "FRAME_BYTES",
    "FRAME_MS",
    "SAMPLE_RATE_HZ",
    "BotTurnTracker",
    "EndedBy",
    "TurnPolicy",
    "frames",
    "level_dbfs",
]
