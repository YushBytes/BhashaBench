"""The full-conversation recording (Phase 10): every turn's audio, in order,
as one file, with a segment map linking each span back to its turn artefact.

What it is, stated so nothing reads more into it:

- **Assembled, not captured.** The turns are concatenated back to back after
  the run. Nothing here was recorded off a live line, and the gaps between
  turns are not reproduced: no silence is inserted, because invented timing
  would look like a latency measurement. Each segment carries its source
  reference, so the per-turn artefacts remain the evidence.
- **What was on the line.** For a caller turn the degraded variant is used
  when one exists, because that is what the bot heard; otherwise the
  original. Bot turns use the bot's audio as received.
- **Excluded, not guessed.** A turn whose audio is not 16-bit PCM WAV, or is
  missing from storage, is left out and listed with its reason. Silence is
  never substituted for it.
- One format: 16-bit mono at `TARGET_RATE_HZ`, resampled where needed.
"""

from __future__ import annotations

from array import array
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.pipeline.degradation import decode_pcm16_wav, encode_pcm16_wav, resample, to_mono

TARGET_RATE_HZ = 16_000
RECORDING_NAME = "conversation.wav"
MAX_RECORDING_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class Recording:
    audio: bytes | None
    """`None` when no turn could be included."""
    sample_rate_hz: int
    duration_seconds: float
    segments: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)


def _choose(artefacts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One artefact per turn: the degraded caller variant if present."""
    by_turn: dict[tuple[int, str], dict[str, Any]] = {}
    for record in artefacts:
        key = (int(record["turn_index"]), str(record["speaker"]))
        current = by_turn.get(key)
        if current is None or record.get("variant") == "degraded":
            by_turn[key] = record
    return [by_turn[key] for key in sorted(by_turn)]


def assemble(
    artefacts: Iterable[dict[str, Any]],
    read: Callable[[str], bytes],
    *,
    target_rate: int = TARGET_RATE_HZ,
) -> Recording:
    """Concatenate the turns' audio. Never raises for one bad turn."""
    pcm = array("h")
    segments: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for record in _choose(artefacts):
        where = {
            "turn_index": record["turn_index"],
            "speaker": record["speaker"],
            "variant": record.get("variant"),
            "source_reference": record["reference"],
        }
        try:
            samples, rate, channels = decode_pcm16_wav(read(record["reference"]))
        except Exception as exc:  # undecodable or missing: recorded, not hidden
            excluded.append({**where, "reason": f"{type(exc).__name__}: {str(exc)[:200]}"})
            continue
        mono = resample(to_mono(samples, channels), source_rate=rate, target_rate=target_rate)
        if (len(pcm) + len(mono)) / target_rate > MAX_RECORDING_SECONDS:
            excluded.append({**where, "reason": "the recording would exceed one hour"})
            continue
        segments.append(
            {
                **where,
                "start_seconds": round(len(pcm) / target_rate, 3),
                "duration_seconds": round(len(mono) / target_rate, 3),
                "source_sample_rate_hz": rate,
                "source_channels": channels,
            }
        )
        pcm.extend(mono)
    duration = round(len(pcm) / target_rate, 3)
    audio = encode_pcm16_wav(pcm, rate=target_rate, channels=1) if pcm else None
    return Recording(audio, target_rate, duration, segments, excluded)


__all__ = ["MAX_RECORDING_SECONDS", "RECORDING_NAME", "TARGET_RATE_HZ", "Recording", "assemble"]
