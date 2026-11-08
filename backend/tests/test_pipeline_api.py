"""The test-run HTTP surface.

Drives the real routes through `TestClient` against real PostgreSQL, with the
engine's providers replaced by the offline fakes at the single seam the route
module exposes. The routes, the engine, the degradation and the repositories
are all the shipping implementation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.test_runs import get_engine_factory
from app.caller.artefacts import AudioArtefactStore
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.service import CallerService
from app.core.config import get_settings
from app.models import Scenario
from app.models import TestSuite as SuiteModel
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.registry import build_adapter
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.concurrency import RunSlots
from app.pipeline.engine import MAX_BOT_AUDIO_BYTES, RunEngine
from app.speech.models import AudioConfig
from app.speech.providers.fake import FakeSpeechScript, FakeSynthesisProvider
from app.speech.service import SpeechService
from app.transcription.models import TranscriptionResult

CLAIM = "0471883"
BASE = "/api/v1/test-runs"

SPEC: dict[str, Any] = {
    "name": "tamil_crop_insurance_status",
    "description": "A farmer checks a crop insurance claim.",
    "language": "ta-IN",
    "persona": {
        "identity": "Smallholder farmer",
        "speaking_style": "confused",
        "traits": ["unfamiliar with insurance terminology"],
    },
    "goal": {"objective": "Find out the status of my crop insurance claim.", "max_turns": 10},
    "known_facts": {"claim_reference": CLAIM},
    "expected_outcomes": ["Bot states the claim status"],
    "audio": {"noise_profile": "clean", "snr_db": 30.0, "packet_loss_percent": 0.0},
    "constraints": None,
}

COOPERATIVE = [
    "May I have your claim reference number, please?",
    f"Thank you. Claim {CLAIM} has been approved.",
    "Yes, that is correct.",
    "Goodbye.",
]


class _Sequenced:
    """A transcription service returning a different transcript per call."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    async def transcribe_batch(self, *_: object, **__: object) -> TranscriptionResult:
        text = self._texts[min(self.calls, len(self._texts) - 1)] if self._texts else ""
        self.calls += 1
        return TranscriptionResult(
            text=text,
            language="ta-IN",
            requested_language="ta-IN",
            provider="fake",
            model="fake-1",
            is_final=True,
            latency_ms=1.0,
        )


@pytest.fixture
def scenario_ids(db_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    suite = SuiteModel(name=f"api-suite-{uuid.uuid4().hex[:8]}", description="api fixture")
    db_session.add(suite)
    db_session.flush()
    scenario = Scenario(
        suite_id=suite.id,
        name=f"{SPEC['name']}_{uuid.uuid4().hex[:6]}",
        description=SPEC["description"],
        language="ta-IN",
        spec=SPEC,
        spec_version=1,
    )
    db_session.add(scenario)
    db_session.flush()
    return suite.id, scenario.id


@pytest.fixture
def wav(test_app: FastAPI) -> bytes:
    """A genuine 16-bit mono WAV."""
    settings = test_app.dependency_overrides[get_settings]()
    service = SpeechService(FakeSynthesisProvider(FakeSpeechScript(seconds=0.6)), settings=settings)
    return asyncio.run(
        service.synthesise("reply", language="ta-IN", audio=AudioConfig(sample_rate_hz=8000))
    ).audio


@pytest.fixture
def pipeline_client(
    api_client: TestClient,
    test_app: FastAPI,
    db_session: Session,
    tmp_path: Path,
) -> Iterator[TestClient]:
    """The API client with the engine's providers replaced by offline ones.

    Overrides the engine *factory*, the single seam the route module exposes,
    so the routes, the engine, the degradation and the repositories are all
    real.
    """
    settings = test_app.dependency_overrides[get_settings]().model_copy(
        update={
            "caller_audio_storage_dir": str(tmp_path / "audio"),
            "caller_synthesise_audio": True,
        }
    )
    store = AudioArtefactStore(settings.caller_audio_root)
    state: dict[str, Any] = {"adapter": None, "transcription": None, "slots": None}

    def factory(adapter_name: str | None) -> Iterator[RunEngine]:
        caller = CallerService(
            DeterministicCallerProvider(),
            settings=settings,
            speech=SpeechService(
                FakeSynthesisProvider(FakeSpeechScript(seconds=0.6)), settings=settings
            ),
        )
        # Through the real registry, so an unknown adapter name is still
        # refused by the code that refuses it in production.
        build_adapter(adapter_name or "scripted")
        if state["adapter"] is None:
            state["adapter"] = (
                ManualBotAdapter()
                if (adapter_name or "") == "manual"
                else ScriptedBotAdapter((), exhausted_is_error=False)
            )
        if state["transcription"] is None:
            state["transcription"] = _Sequenced(COOPERATIVE)
        orchestrator = ConversationOrchestrator(
            session=db_session,
            caller=caller,
            settings=settings,
            transcription=state["transcription"],
            artefacts=store,
        )
        yield RunEngine(
            session=db_session,
            orchestrator=orchestrator,
            settings=settings,
            bot_adapter=state["adapter"],
            artefacts=store,
            stt_provider="fake",
            tts_provider="fake",
            # None by default, so every other test in this module is unaffected
            # by admission control; a concurrency test installs a real limiter.
            slots=state["slots"],
        )

    test_app.dependency_overrides[get_engine_factory] = lambda: factory
    api_client.pipeline_state = state  # type: ignore[attr-defined]
    api_client.artefact_store = store  # type: ignore[attr-defined]
    yield api_client
    test_app.dependency_overrides.pop(get_engine_factory, None)


def _create(
    client: TestClient,
    scenario_ids: tuple[uuid.UUID, uuid.UUID],
    **overrides: Any,
) -> dict[str, Any]:
    suite_id, scenario_id = scenario_ids
    body: dict[str, Any] = {
        "suite_id": str(suite_id),
        "scenario_id": str(scenario_id),
        "mode": "offline_simulation",
    }
    body.update(overrides)
    response = client.post(BASE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Creating a run
# ---------------------------------------------------------------------------


class TestCreateRun:
    def test_a_run_is_created(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        body = _create(pipeline_client, scenario_ids)
        assert body["status"] == "created"
        assert body["scenario_name"] == "tamil_crop_insurance_status"
        assert body["language"] == "ta-IN"
        assert body["caller_turns"] == 0

    def test_a_new_run_has_no_outcome(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """An unfinished run has no result, and reporting one would be a
        fabricated figure."""
        body = _create(pipeline_client, scenario_ids)
        assert body["outcome"] is None
        assert body["goal_achieved"] is False
        assert body["finished_at"] is None

    def test_the_mode_is_recorded(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        body = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        assert body["mode"] == "audio_fixture_test"

    def test_telephony_mode_is_refused(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A mode that cannot run must not be creatable."""
        suite_id, scenario_id = scenario_ids
        response = pipeline_client.post(
            BASE,
            json={
                "suite_id": str(suite_id),
                "scenario_id": str(scenario_id),
                "mode": "telephony_test",
            },
        )
        assert response.status_code == 422
        assert "not implemented" in response.json()["error"]["message"]

    def test_an_unknown_mode_is_rejected_by_the_schema(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        suite_id, scenario_id = scenario_ids
        response = pipeline_client.post(
            BASE,
            json={
                "suite_id": str(suite_id),
                "scenario_id": str(scenario_id),
                "mode": "carrier_pigeon",
            },
        )
        assert response.status_code == 422

    def test_an_unknown_scenario_is_404(self, pipeline_client: TestClient) -> None:
        response = pipeline_client.post(
            BASE,
            json={"suite_id": str(uuid.uuid4()), "scenario_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    def test_a_malformed_uuid_is_422(self, pipeline_client: TestClient) -> None:
        response = pipeline_client.post(BASE, json={"suite_id": "nope", "scenario_id": "also-nope"})
        assert response.status_code == 422

    def test_a_missing_field_is_422(self, pipeline_client: TestClient) -> None:
        response = pipeline_client.post(BASE, json={"suite_id": str(uuid.uuid4())})
        assert response.status_code == 422

    def test_a_zero_turn_budget_is_rejected_by_the_schema(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        suite_id, scenario_id = scenario_ids
        response = pipeline_client.post(
            BASE,
            json={
                "suite_id": str(suite_id),
                "scenario_id": str(scenario_id),
                "max_turns": 0,
            },
        )
        assert response.status_code == 422

    def test_an_unknown_adapter_is_422(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        suite_id, scenario_id = scenario_ids
        response = pipeline_client.post(
            BASE,
            json={
                "suite_id": str(suite_id),
                "scenario_id": str(scenario_id),
                "bot_adapter": "some_vendor_bot",
            },
        )
        assert response.status_code == 422
        assert "not a known bot adapter" in response.json()["error"]["message"]

    def test_the_noise_profile_and_seed_are_recorded(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        body = _create(
            pipeline_client,
            scenario_ids,
            mode="audio_fixture_test",
            noise_profile="heavy_background_noise",
            seed=777,
        )
        assert body["noise_profile"] == "heavy_background_noise"
        assert body["degradation_seed"] == 777

    def test_every_response_denies_using_a_language_model(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        assert _create(pipeline_client, scenario_ids)["uses_language_model"] is False


# ---------------------------------------------------------------------------
# Executing a run
# ---------------------------------------------------------------------------


class TestStartRun:
    def test_a_fixture_run_executes_end_to_end(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(
            pipeline_client,
            scenario_ids,
            mode="audio_fixture_test",
            noise_profile="moderate_background_noise",
            seed=5,
        )
        response = pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["caller_turns"] >= 3
        assert body["bot_turns"] >= 2
        assert body["bot_transcripts_succeeded"] >= 2
        assert body["goal_achieved"] is True
        assert body["outcome"] == "goal_achieved"

    def test_a_fixture_run_is_not_reported_as_an_external_bot_test(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        body = pipeline_client.post(f"{BASE}/{run['run_id']}/start").json()
        assert body["bot_audio_externally_received"] is False

    def test_an_offline_run_executes_without_audio(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = _create(pipeline_client, scenario_ids, mode="offline_simulation")
        body = pipeline_client.post(f"{BASE}/{run['run_id']}/start").json()
        assert body["caller_turns"] >= 1
        artefacts = pipeline_client.get(f"{BASE}/{run['run_id']}/artifacts").json()
        assert artefacts["artefacts"] == []

    def test_starting_a_finished_run_is_409(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        again = pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        assert again.status_code == 409

    def test_starting_an_unknown_run_is_404(self, pipeline_client: TestClient) -> None:
        assert pipeline_client.post(f"{BASE}/{uuid.uuid4()}/start").status_code == 404


class TestArtefacts:
    @pytest.fixture
    def executed(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> str:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(
            pipeline_client,
            scenario_ids,
            mode="audio_fixture_test",
            noise_profile="moderate_background_noise",
            seed=5,
        )
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        return str(run["run_id"])

    def test_both_variants_are_listed(self, pipeline_client: TestClient, executed: str) -> None:
        artefacts = pipeline_client.get(f"{BASE}/{executed}/artifacts").json()["artefacts"]
        variants = {(a["speaker"], a["variant"]) for a in artefacts}
        assert ("caller", "original") in variants
        assert ("caller", "degraded") in variants

    def test_a_degraded_artefact_names_its_original(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        artefacts = pipeline_client.get(f"{BASE}/{executed}/artifacts").json()["artefacts"]
        degraded = [a for a in artefacts if a["variant"] == "degraded"]
        assert degraded
        assert all(a["derived_from"] for a in degraded)

    def test_the_degradation_record_is_complete(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        """§8 requires the transformation list, the parameters and the seed."""
        artefacts = pipeline_client.get(f"{BASE}/{executed}/artifacts").json()["artefacts"]
        degraded = next(a for a in artefacts if a["variant"] == "degraded")
        assert degraded["transformations"]
        assert degraded["degradation_parameters"]["snr_db"] == 15.0
        assert degraded["seed"] == 5
        assert degraded["sample_rate_hz"] == 8000
        assert degraded["channels"] == 1

    def test_no_reference_is_an_absolute_path(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        """An absolute filesystem path would disclose the server layout."""
        artefacts = pipeline_client.get(f"{BASE}/{executed}/artifacts").json()["artefacts"]
        for artefact in artefacts:
            reference = artefact["reference"]
            assert not reference.startswith("/")
            assert ":" not in reference
            assert ".." not in reference

    def test_the_total_audio_duration_is_reported(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        body = pipeline_client.get(f"{BASE}/{executed}/artifacts").json()
        assert body["total_audio_seconds"] > 0

    def test_artefacts_of_an_unknown_run_are_404(self, pipeline_client: TestClient) -> None:
        assert pipeline_client.get(f"{BASE}/{uuid.uuid4()}/artifacts").status_code == 404


class TestTurnsAndReport:
    @pytest.fixture
    def executed(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> str:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test", seed=5)
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        return str(run["run_id"])

    def test_the_turns_are_listed_in_order(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        turns = pipeline_client.get(f"{BASE}/{executed}/turns").json()["turns"]
        assert [t["index"] for t in turns] == list(range(len(turns)))
        assert turns[0]["speaker"] == "caller"

    def test_a_caller_turn_records_its_decision(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        turns = pipeline_client.get(f"{BASE}/{executed}/turns").json()["turns"]
        assert turns[0]["intent"] == "open"
        assert turns[0]["rule_ids"] == ["open.introduce"]
        assert turns[0]["state_before"] == "initial"

    def test_turns_of_an_unknown_run_are_404(self, pipeline_client: TestClient) -> None:
        assert pipeline_client.get(f"{BASE}/{uuid.uuid4()}/turns").status_code == 404

    def test_the_report_carries_every_stage(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        body = pipeline_client.get(f"{BASE}/{executed}/report").json()
        stages = {event["stage"] for event in body["events"]}
        assert {
            "caller_turn",
            "degradation",
            "bot_exchange",
            "bot_audio_validation",
            "bot_transcription",
        } <= stages

    def test_the_report_carries_the_state_transitions(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        body = pipeline_client.get(f"{BASE}/{executed}/report").json()
        assert len(body["state_transitions"]) >= 3

    def test_the_report_says_it_is_not_a_score(
        self, pipeline_client: TestClient, executed: str
    ) -> None:
        """So a consumer cannot mistake these counts for a quality metric."""
        note = pipeline_client.get(f"{BASE}/{executed}/report").json()["measurement_note"]
        assert "no accuracy score" in note
        assert "no word error rate" in note

    def test_the_report_of_an_unknown_run_is_404(self, pipeline_client: TestClient) -> None:
        assert pipeline_client.get(f"{BASE}/{uuid.uuid4()}/report").status_code == 404


# ---------------------------------------------------------------------------
# External bot audio
# ---------------------------------------------------------------------------


class TestBotAudioSubmission:
    def test_a_manual_run_waits_for_audio(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Waiting is healthy: the run stays running and says which turn it
        wants audio for."""
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        body = pipeline_client.post(f"{BASE}/{run['run_id']}/start").json()
        assert body["status"] == "running"
        assert body["awaiting_bot_audio_for_turn"] == 0
        assert body["outcome"] is None

    def test_supplied_audio_continues_the_run(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        response = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("reply.wav", wav, "audio/wav")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["accepted_bytes"] == len(wav)
        assert body["run"]["bot_turns"] >= 1
        assert body["run"]["bot_transcripts_succeeded"] >= 1

    def test_supplied_audio_is_recorded_as_externally_obtained(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        """The only path by which a run may claim an external bot test."""
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        body = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("reply.wav", wav, "audio/wav")},
        ).json()
        assert body["run"]["bot_audio_externally_received"] is True

    def test_audio_for_a_run_that_is_not_waiting_is_422(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        run = _create(pipeline_client, scenario_ids, mode="offline_simulation")
        response = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("reply.wav", wav, "audio/wav")},
        )
        assert response.status_code == 422
        assert "not waiting for bot audio" in response.json()["error"]["message"]

    def test_oversized_audio_is_refused(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """The read is capped: `UploadFile` spools to disk, so an unbounded
        read lets one request write arbitrarily much first."""
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        response = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("big.wav", b"\x00" * (MAX_BOT_AUDIO_BYTES + 1), "audio/wav")},
        )
        assert response.status_code == 413

    def test_audio_that_is_not_audio_is_refused(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        response = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("notes.txt", b"this is not audio", "audio/wav")},
        )
        assert response.status_code == 415

    def test_a_rejected_upload_leaves_the_run_waiting(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        """A mistyped filename is the operator's mistake, not a reason to
        discard the conversation - so they can post the right file."""
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("notes.txt", b"this is not audio", "audio/wav")},
        )
        state = pipeline_client.get(f"{BASE}/{run['run_id']}").json()
        assert state["status"] == "running"
        assert state["awaiting_bot_audio_for_turn"] == 0
        assert state["bot_turns"] == 0

        good = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("reply.wav", wav, "audio/wav")},
        )
        assert good.status_code == 200
        assert good.json()["run"]["bot_turns"] >= 1

    def test_a_missing_file_is_422(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = _create(pipeline_client, scenario_ids)
        assert pipeline_client.post(f"{BASE}/{run['run_id']}/bot-audio").status_code == 422

    def test_audio_for_an_unknown_run_is_404(self, pipeline_client: TestClient, wav: bytes) -> None:
        response = pipeline_client.post(
            f"{BASE}/{uuid.uuid4()}/bot-audio",
            files={"audio": ("reply.wav", wav, "audio/wav")},
        )
        assert response.status_code == 404


class TestCancellation:
    def test_a_run_can_be_cancelled(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = _create(pipeline_client, scenario_ids)
        response = pipeline_client.post(f"{BASE}/{run['run_id']}/cancel")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "cancelled"
        assert body["outcome"] == "cancelled"

    def test_cancelling_twice_is_409(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        run = _create(pipeline_client, scenario_ids)
        pipeline_client.post(f"{BASE}/{run['run_id']}/cancel")
        assert pipeline_client.post(f"{BASE}/{run['run_id']}/cancel").status_code == 409

    def test_cancelling_an_unknown_run_is_404(self, pipeline_client: TestClient) -> None:
        assert pipeline_client.post(f"{BASE}/{uuid.uuid4()}/cancel").status_code == 404


# ---------------------------------------------------------------------------
# Adapters, security and OpenAPI
# ---------------------------------------------------------------------------


class TestAdapterListing:
    def test_both_adapters_are_listed(self, pipeline_client: TestClient) -> None:
        body = pipeline_client.get(f"{BASE}/bot-adapters/available").json()
        assert sorted(a["name"] for a in body["adapters"]) == ["manual", "scripted"]

    def test_no_adapter_contacts_an_external_system(self, pipeline_client: TestClient) -> None:
        """Which is why the default configuration is safe: nothing in this
        phase sends audio anywhere by itself."""
        body = pipeline_client.get(f"{BASE}/bot-adapters/available").json()
        assert all(a["contacts_external_system"] is False for a in body["adapters"])

    def test_no_adapter_needs_a_credential(self, pipeline_client: TestClient) -> None:
        body = pipeline_client.get(f"{BASE}/bot-adapters/available").json()
        assert all(a["requires_credentials"] is False for a in body["adapters"])

    def test_the_default_adapter_is_the_one_that_sends_nowhere(
        self, pipeline_client: TestClient
    ) -> None:
        body = pipeline_client.get(f"{BASE}/bot-adapters/available").json()
        assert body["selected"] == "scripted"

    def test_telephony_is_declared_not_implemented(self, pipeline_client: TestClient) -> None:
        body = pipeline_client.get(f"{BASE}/bot-adapters/available").json()
        assert "Not implemented" in body["telephony_status"]

    def test_telephony_is_absent_from_the_usable_modes(self, pipeline_client: TestClient) -> None:
        body = pipeline_client.get(f"{BASE}/bot-adapters/available").json()
        assert "telephony_test" not in body["execution_modes"]
        assert sorted(body["execution_modes"]) == [
            "audio_fixture_test",
            "external_bot_test",
            "offline_simulation",
        ]


class TestSecurity:
    def test_a_traversal_shaped_filename_cannot_escape_the_store(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
        tmp_path: Path,
    ) -> None:
        """The uploaded filename reaches no path: references are built from a
        UUID, a turn index, a speaker enum and a whitelisted suffix."""
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        response = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("../../../../etc/passwd.wav", wav, "audio/wav")},
        )
        assert response.status_code == 200
        for artefact in pipeline_client.get(f"{BASE}/{run['run_id']}/artifacts").json()[
            "artefacts"
        ]:
            assert ".." not in artefact["reference"]
            assert "passwd" not in artefact["reference"]
        assert not (tmp_path.parent / "etc").exists()

    def test_no_response_carries_a_credential_shaped_string(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        for path in ("", "/turns", "/artifacts", "/report"):
            text = pipeline_client.get(f"{BASE}/{run['run_id']}{path}").text.lower()
            assert "api_key" not in text
            assert "authorization" not in text
            assert "bearer " not in text

    def test_no_response_exposes_the_storage_root(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        text = pipeline_client.get(f"{BASE}/{run['run_id']}/report").text
        assert "C:\\" not in text
        assert "/tmp/" not in text
        assert "AppData" not in text


class TestConcurrencyLimit:
    """The limit, enforced through the real route rather than in isolation.

    The engine-level tests stub the turn loop, which is right for the admission
    logic but says nothing about whether a refusal reaches a client as a status
    code. These exhaust the limiter before the request, which is deterministic:
    no second request has to be timed against the first.
    """

    def test_a_run_is_refused_with_503_when_capacity_is_exhausted(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        run = _create(pipeline_client, scenario_ids)

        with slots.hold_sync():
            response = pipeline_client.post(f"{BASE}/{run['run_id']}/start")

        assert response.status_code == 503
        message = response.json()["error"]["message"]
        assert "concurrent run slots are in use" in message
        assert "retry" in message

    def test_a_refused_run_keeps_its_state_and_is_retryable(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """The refusal must not fail or advance the run - that is what makes
        retrying safe rather than a second chance at a broken run."""
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        run = _create(pipeline_client, scenario_ids)

        with slots.hold_sync():
            assert pipeline_client.post(f"{BASE}/{run['run_id']}/start").status_code == 503

        after = pipeline_client.get(f"{BASE}/{run['run_id']}").json()
        assert after["status"] == "created"
        assert after["outcome"] is None
        assert after["caller_turns"] == 0
        assert after["error"] is None

        # And once the slot is free, the same request succeeds.
        resumed = pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        assert resumed.status_code == 200
        assert resumed.json()["caller_turns"] >= 1

    def test_the_refusal_releases_nothing_it_did_not_take(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A refused request that decremented the counter on its way out would
        hand the next caller phantom capacity."""
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        run = _create(pipeline_client, scenario_ids)

        with slots.hold_sync():
            for _ in range(3):
                assert pipeline_client.post(f"{BASE}/{run['run_id']}/start").status_code == 503
            assert slots.in_use == 1

        assert slots.in_use == 0
        assert slots.available == 1

    def test_a_completed_run_releases_its_slot(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [wav] * 4, exhausted_is_error=False
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        assert pipeline_client.post(f"{BASE}/{run['run_id']}/start").status_code == 200
        assert slots.in_use == 0
        assert slots.peak_in_use == 1

    def test_a_failed_run_releases_its_slot(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A run that ends `failed` must still give the slot back, or a few bad
        scenarios would wedge the server."""
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        pipeline_client.pipeline_state["adapter"] = ScriptedBotAdapter(
            [b"this is not audio at all"]
        )
        run = _create(pipeline_client, scenario_ids, mode="audio_fixture_test")
        body = pipeline_client.post(f"{BASE}/{run['run_id']}/start").json()
        assert body["status"] == "failed"
        assert slots.in_use == 0
        assert slots.available == 1

    def test_supplying_bot_audio_does_not_refuse_itself(
        self,
        pipeline_client: TestClient,
        scenario_ids: tuple[uuid.UUID, uuid.UUID],
        wav: bytes,
    ) -> None:
        """The re-entrancy case over HTTP: `supply_bot_audio` holds a slot and
        then drives the run on, which must not 503 against its own slot even
        when the limit is one."""
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")

        response = pipeline_client.post(
            f"{BASE}/{run['run_id']}/bot-audio",
            files={"audio": ("reply.wav", wav, "audio/wav")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["run"]["bot_turns"] >= 1
        assert slots.in_use == 0

    def test_cancelling_a_waiting_run_leaves_no_slot_held(
        self, pipeline_client: TestClient, scenario_ids: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        slots = RunSlots(1)
        pipeline_client.pipeline_state["slots"] = slots
        pipeline_client.pipeline_state["adapter"] = ManualBotAdapter()
        run = _create(pipeline_client, scenario_ids, mode="external_bot_test", bot_adapter="manual")
        pipeline_client.post(f"{BASE}/{run['run_id']}/start")
        assert slots.in_use == 0

        assert pipeline_client.post(f"{BASE}/{run['run_id']}/cancel").status_code == 200
        assert slots.in_use == 0

    def test_the_503_is_documented_on_the_start_endpoint(self, pipeline_client: TestClient) -> None:
        paths = pipeline_client.get("/openapi.json").json()["paths"]
        responses = paths[f"{BASE}/{{run_id}}/start"]["post"]["responses"]
        assert "503" in responses
        assert "retry" in responses["503"]["description"]

    def test_the_start_endpoint_documents_that_it_does_not_queue(
        self, pipeline_client: TestClient
    ) -> None:
        paths = pipeline_client.get("/openapi.json").json()["paths"]
        description = paths[f"{BASE}/{{run_id}}/start"]["post"]["description"]
        assert "PIPELINE_MAX_CONCURRENT_RUNS" in description
        assert "rather than queueing" in description


class TestOpenAPI:
    def test_every_pipeline_route_is_documented(self, pipeline_client: TestClient) -> None:
        paths = pipeline_client.get("/openapi.json").json()["paths"]
        assert BASE in paths
        assert f"{BASE}/{{run_id}}" in paths
        assert f"{BASE}/{{run_id}}/start" in paths
        assert f"{BASE}/{{run_id}}/bot-audio" in paths
        assert f"{BASE}/{{run_id}}/cancel" in paths
        assert f"{BASE}/{{run_id}}/turns" in paths
        assert f"{BASE}/{{run_id}}/artifacts" in paths
        assert f"{BASE}/{{run_id}}/report" in paths
        assert f"{BASE}/bot-adapters/available" in paths

    def test_the_mode_field_documents_the_telephony_refusal(
        self, pipeline_client: TestClient
    ) -> None:
        schema = pipeline_client.get("/openapi.json").json()["components"]["schemas"][
            "CreateRunRequest"
        ]
        assert "telephony" in schema["properties"]["mode"]["description"]

    def test_the_external_flag_is_documented_as_the_honesty_check(
        self, pipeline_client: TestClient
    ) -> None:
        schema = pipeline_client.get("/openapi.json").json()["components"]["schemas"]["RunResponse"]
        description = schema["properties"]["bot_audio_externally_received"]["description"]
        assert "mislabelled" in description

    def test_the_earlier_phase_endpoints_still_resolve(self, pipeline_client: TestClient) -> None:
        """Mounting the pipeline router must not shadow anything Phases 1 to 6
        shipped."""
        assert pipeline_client.get("/api/v1/languages").status_code == 200
        assert pipeline_client.get("/api/v1/health").status_code == 200
        assert pipeline_client.get("/api/v1/caller/providers").status_code == 200
