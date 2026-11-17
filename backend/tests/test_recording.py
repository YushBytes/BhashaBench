"""Phase 10 full-conversation recordings: assembly from synthetic turn audio,
then the recording a real audio run stores and serves through the API."""

from __future__ import annotations

import io
import math
import struct
import uuid
import wave
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.recording import TARGET_RATE_HZ, assemble
from tests import test_pipeline_api as pipeline_tests

# The pipeline API module's fixtures, re-bound so pytest finds them here.
pipeline_client = pipeline_tests.pipeline_client
scenario_ids = pipeline_tests.scenario_ids
wav = pipeline_tests.wav
BASE = pipeline_tests.BASE
_create = pipeline_tests._create


def _tone(seconds: float, rate: int, channels: int = 1, freq: float = 440.0) -> bytes:
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        samples = []
        for i in range(frames):
            value = int(8000 * math.sin(2 * math.pi * freq * i / rate))
            samples.extend([value] * channels)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buffer.getvalue()


def _record(turn: int, speaker: str, reference: str, variant: str | None = None) -> dict[str, Any]:
    return {"turn_index": turn, "speaker": speaker, "variant": variant, "reference": reference}


class TestAssembly:
    def test_turns_are_concatenated_in_order_with_offsets(self) -> None:
        files = {"a": _tone(1.0, 16000), "b": _tone(0.5, 8000), "c": _tone(0.25, 16000, channels=2)}
        result = assemble(
            [_record(2, "caller", "c"), _record(0, "caller", "a"), _record(1, "bot", "b")],
            files.__getitem__,
        )
        assert [s["turn_index"] for s in result.segments] == [0, 1, 2]
        assert [s["start_seconds"] for s in result.segments] == [0.0, 1.0, 1.5]
        assert result.duration_seconds == pytest.approx(1.75, abs=0.01)
        with wave.open(io.BytesIO(result.audio or b"")) as handle:
            assert (handle.getframerate(), handle.getnchannels()) == (TARGET_RATE_HZ, 1)
            assert handle.getnframes() / TARGET_RATE_HZ == pytest.approx(1.75, abs=0.01)
        assert result.segments[1]["source_sample_rate_hz"] == 8000
        assert result.segments[2]["source_channels"] == 2

    def test_the_degraded_caller_variant_is_what_was_on_the_line(self) -> None:
        files = {"orig": _tone(1.0, 16000), "deg": _tone(0.5, 16000)}
        result = assemble(
            [_record(0, "caller", "orig", "original"), _record(0, "caller", "deg", "degraded")],
            files.__getitem__,
        )
        assert [s["source_reference"] for s in result.segments] == ["deg"]

    def test_an_undecodable_or_missing_turn_is_excluded_never_filled(self) -> None:
        files = {"good": _tone(0.5, 16000), "mp3": b"ID3\x03\x00\x00\x00junk"}
        result = assemble(
            [_record(0, "caller", "good"), _record(1, "bot", "mp3"), _record(2, "bot", "gone")],
            files.__getitem__,
        )
        assert [s["turn_index"] for s in result.segments] == [0]
        assert [e["turn_index"] for e in result.excluded] == [1, 2]
        assert all(e["reason"] for e in result.excluded)
        assert result.duration_seconds == pytest.approx(0.5, abs=0.01)

    def test_nothing_decodable_is_no_audio_not_silence(self) -> None:
        result = assemble([_record(0, "bot", "x")], {"x": b"not audio"}.__getitem__)
        assert result.audio is None
        assert result.duration_seconds == 0


class TestStoredRecording:
    def _audio_run(self, client: TestClient, ids: tuple[uuid.UUID, uuid.UUID], wav: bytes) -> str:
        client.pipeline_state["adapter"] = ScriptedBotAdapter([wav] * 4, exhausted_is_error=False)
        run = _create(
            client,
            ids,
            mode="audio_fixture_test",
            noise_profile="moderate_background_noise",
            seed=3,
        )
        assert client.post(f"{BASE}/{run['run_id']}/start").json()["status"] == "completed"
        return run["run_id"]

    def test_a_finished_audio_run_stores_a_linked_recording(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes
    ) -> None:
        run_id = self._audio_run(pipeline_client, scenario_ids, wav)
        manifest = pipeline_client.get(f"{BASE}/{run_id}/recording").json()
        assert manifest["status"] == "stored"
        assert manifest["reference"].endswith("/conversation.wav")
        artefacts = {
            a["reference"]
            for a in pipeline_client.get(f"{BASE}/{run_id}/artifacts").json()["artefacts"]
        }
        assert {s["source_reference"] for s in manifest["segments"]} <= artefacts
        caller_sources = [s for s in manifest["segments"] if s["speaker"] == "caller"]
        assert caller_sources and all(s["variant"] == "degraded" for s in caller_sources)
        assert "no silence inserted" in manifest["assembly"]

        audio = pipeline_client.get(f"{BASE}/{run_id}/recording/audio")
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/wav")
        with wave.open(io.BytesIO(audio.content)) as handle:
            seconds = handle.getnframes() / handle.getframerate()
        assert seconds == pytest.approx(manifest["duration_seconds"], abs=0.01)
        assert seconds == pytest.approx(
            sum(s["duration_seconds"] for s in manifest["segments"]), abs=0.05
        )

    def test_a_run_with_no_audio_says_so(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = _create(pipeline_client, scenario_ids, mode="offline_simulation")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        manifest = pipeline_client.get(f"{BASE}/{run['run_id']}/recording").json()
        assert manifest["status"] == "not_applicable"
        assert pipeline_client.get(f"{BASE}/{run['run_id']}/recording/audio").status_code == 404

    def test_an_unfinished_run_has_no_recording_yet(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        assert pipeline_client.get(f"{BASE}/{run['run_id']}/recording").status_code == 404

    def test_the_recording_is_deleted_with_the_conversation(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID], wav: bytes
    ) -> None:
        run_id = self._audio_run(pipeline_client, scenario_ids, wav)
        manifest = pipeline_client.get(f"{BASE}/{run_id}/recording").json()
        store = pipeline_client.artefact_store
        conversation = uuid.UUID(manifest["reference"].split("/")[0])
        assert store.exists(manifest["reference"])
        assert store.delete_conversation(conversation) >= len(manifest["segments"]) + 1
        assert not store.exists(manifest["reference"])
        assert pipeline_client.get(f"{BASE}/{run_id}/recording/audio").status_code == 404
