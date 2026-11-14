"""Multi-turn runs with audio all the way through, against real PostgreSQL.

The acceptance test for Phase 7. Caller text is produced by the real Phase 6
rule engine, synthesised into real 16-bit WAV by the offline speech fake,
degraded by the real DSP, written to a real file, handed to a bot adapter,
validated by the real WAV inspector, and transcribed by the offline
transcription fake. Only the two providers and the bot are stubs; every stage
between them is the shipping implementation.

These need PostgreSQL (`docker compose up -d db`) and never skip silently.
"""

from __future__ import annotations

import array
import asyncio
import io
import math
import uuid
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.caller.orchestrator import ConversationOrchestrator
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.service import CallerService
from app.caller.state import CallerState
from app.core.config import AppEnv, Settings
from app.models import CallSession, Scenario
from app.models import TestSuite as SuiteModel
from app.models.test_run import RunStatus
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.degradation import NoiseProfile, degrade, profile_config
from app.pipeline.engine import RunConfig, RunEngine, RunReport
from app.pipeline.errors import (
    BotTimeoutError,
    PipelineConfigurationError,
    RunNotActiveError,
)
from app.pipeline.modes import ExecutionMode, PipelineStatus, RunOutcome
from app.repositories import caller_conversations as caller_repo
from app.repositories import pipeline_runs as repo
from app.services.errors import NotFoundError
from app.services.transcription_service import TranscriptionService
from app.speech.errors import SpeechProviderUnavailableError
from app.speech.models import AudioConfig, SpeechResult
from app.speech.providers.fake import FakeSpeechScript, FakeSynthesisProvider
from app.speech.service import SpeechService
from app.transcription.errors import InvalidAudioError, ProviderUnavailableError
from app.transcription.models import TranscriptionResult
from app.transcription.providers.fake import FakeScript, FakeTranscriptionProvider

CLAIM = "0471883"

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "audio"),
        # On, because a pipeline run without caller audio has nothing to send.
        caller_synthesise_audio=True,
        _env_file=None,
    )


@pytest.fixture
def store(pipeline_settings: Settings) -> AudioArtefactStore:
    return AudioArtefactStore(pipeline_settings.caller_audio_root)


def _wav(settings: Settings, *, seconds: float = 1.0, rate: int = 8000) -> bytes:
    """A genuine 16-bit mono WAV from the offline speech fake."""
    service = SpeechService(
        FakeSynthesisProvider(FakeSpeechScript(seconds=seconds)), settings=settings
    )
    result = asyncio.run(
        service.synthesise("reply", language="ta-IN", audio=AudioConfig(sample_rate_hz=rate))
    )
    return result.audio


@pytest.fixture
def bot_wavs(pipeline_settings: Settings) -> list[bytes]:
    """Four distinct bot replies as real audio."""
    return [_wav(pipeline_settings, seconds=0.5 + 0.1 * n) for n in range(4)]


def _make_scenario(
    session: Session, *, language: str = "ta-IN", spec: dict[str, Any] | None = None
) -> tuple[SuiteModel, Scenario]:
    suite = SuiteModel(name=f"pipe-suite-{uuid.uuid4().hex[:8]}", description="pipeline fixture")
    session.add(suite)
    session.flush()
    document = dict(spec or SPEC)
    document["language"] = language
    scenario = Scenario(
        suite_id=suite.id,
        name=f"{document['name']}_{uuid.uuid4().hex[:6]}",
        description=document.get("description"),
        language=language,
        spec={**document, "name": document["name"]},
        spec_version=1,
    )
    session.add(scenario)
    session.flush()
    return suite, scenario


def _engine(
    session: Session,
    settings: Settings,
    store: AudioArtefactStore,
    *,
    bot: Any = None,
    transcripts: list[str] | None = None,
    transcription: Any = None,
    speech: Any = None,
    stt_provider: str | None = "fake",
    tts_provider: str | None = "fake",
) -> RunEngine:
    """Build an engine with the real services and offline providers."""
    texts = transcripts if transcripts is not None else COOPERATIVE
    caller = CallerService(
        DeterministicCallerProvider(),
        settings=settings,
        speech=speech
        if speech is not None
        else SpeechService(FakeSynthesisProvider(FakeSpeechScript(seconds=0.5)), settings=settings),
    )
    stt = (
        transcription
        if transcription is not None
        else TranscriptionService(
            FakeTranscriptionProvider(FakeScript(transcript=texts[0], segments=texts)),
            settings=settings,
        )
    )
    orchestrator = ConversationOrchestrator(
        session=session,
        caller=caller,
        settings=settings,
        transcription=stt,
        artefacts=store,
    )
    return RunEngine(
        session=session,
        orchestrator=orchestrator,
        settings=settings,
        bot_adapter=bot if bot is not None else ScriptedBotAdapter((), exhausted_is_error=False),
        artefacts=store,
        stt_provider=stt_provider,
        tts_provider=tts_provider,
    )


class _SequencedTranscription:
    """Returns a different transcript per call, so the caller advances.

    The transcription fake's `segments` drive its *streaming* path; a batch
    call returns the same text every time, which would make the caller see one
    repeated utterance. This is the batch equivalent.
    """

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    @property
    def capabilities(self) -> Any:  # pragma: no cover - not read by the engine
        raise NotImplementedError

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


def _run(
    engine: RunEngine,
    suite: SuiteModel,
    scenario: Scenario,
    config: RunConfig,
) -> RunReport:
    run = engine.create(suite_id=suite.id, scenario_id=scenario.id, config=config)
    return asyncio.run(engine.run_to_completion(run.id))


# ---------------------------------------------------------------------------
# Run creation
# ---------------------------------------------------------------------------


class TestRunCreation:
    def test_a_run_is_created_with_its_conversation(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        # Pending, not running: the run has been created and not started.
        assert run.status is RunStatus.PENDING
        assert run.started_at is None
        assert repo.conversation_of(db_session, run.id) is not None

    def test_the_run_records_its_mode_and_configuration(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """The configuration is part of the evidence: a report quotes it as
        what produced the artefacts."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(
                mode=ExecutionMode.AUDIO_FIXTURE_TEST,
                noise_profile=NoiseProfile.HEAVY_BACKGROUND_NOISE,
                seed=11,
            ),
        )
        meta = repo.pipeline_metadata_of(run)
        assert meta["mode"] == "audio_fixture_test"
        assert meta["noise_profile"] == "heavy_background_noise"
        assert meta["degradation_seed"] == 11
        assert meta["status"] == "created"

    def test_the_pipeline_metadata_is_namespaced(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """So a later phase recording its own run context cannot collide."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION),
        )
        assert repo.PIPELINE_NAMESPACE in (run.run_metadata or {})

    def test_telephony_mode_is_refused(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """No telephony exists, so a run must not be creatable in that mode.
        An enum value that cannot be used is the honest record of the gap."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        with pytest.raises(PipelineConfigurationError, match="not implemented"):
            engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.TELEPHONY_TEST),
            )

    def test_an_audio_mode_without_transcription_is_refused(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, stt_provider=None)
        with pytest.raises(PipelineConfigurationError, match="transcription provider"):
            engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
            )

    def test_an_audio_mode_without_speech_is_refused(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, tts_provider=None)
        with pytest.raises(PipelineConfigurationError, match="speech provider"):
            engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
            )

    def test_an_offline_run_needs_no_providers(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Which is what makes the offline mode usable on a fresh checkout."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, stt_provider=None, tts_provider=None)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION),
        )
        assert repo.pipeline_metadata_of(run)["stt_provider"] is None

    def test_a_zero_turn_budget_is_refused(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        with pytest.raises(PipelineConfigurationError, match="at least 1"):
            engine.create(
                suite_id=suite.id,
                scenario_id=scenario.id,
                config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST, max_turns=0),
            )

    def test_an_unknown_scenario_is_not_found(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        engine = _engine(db_session, pipeline_settings, store)
        with pytest.raises(NotFoundError):
            engine.create(
                suite_id=uuid.uuid4(),
                scenario_id=uuid.uuid4(),
                config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
            )

    def test_the_scenarios_own_noise_profile_is_honoured(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """A scenario's audio section is part of the test's definition, so
        running it clean would report a result for a condition never applied."""
        spec = {**SPEC, "audio": {**SPEC["audio"], "noise_profile": "market"}}
        suite, scenario = _make_scenario(db_session, spec=spec)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        meta = repo.pipeline_metadata_of(run)
        assert meta["noise_profile"] == "heavy_background_noise"
        # Both are recorded: the engine applies a severity, not a market, and
        # flattening the two would imply the environment was recreated.
        assert meta["scenario_noise_profile"] == "market"

    def test_an_explicit_profile_overrides_the_scenarios(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        spec = {**SPEC, "audio": {**SPEC["audio"], "noise_profile": "market"}}
        suite, scenario = _make_scenario(db_session, spec=spec)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(
                mode=ExecutionMode.AUDIO_FIXTURE_TEST,
                noise_profile=NoiseProfile.LIGHT_BACKGROUND_NOISE,
            ),
        )
        assert repo.pipeline_metadata_of(run)["noise_profile"] == "light_background_noise"


# ---------------------------------------------------------------------------
# The full audio workflow — the acceptance test
# ---------------------------------------------------------------------------


class TestAudioFixtureRun:
    """A whole multi-turn conversation with audio at every stage."""

    @pytest.fixture
    def report(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> RunReport:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_SequencedTranscription(COOPERATIVE),
        )
        return _run(
            engine,
            suite,
            scenario,
            RunConfig(
                mode=ExecutionMode.AUDIO_FIXTURE_TEST,
                noise_profile=NoiseProfile.MODERATE_BACKGROUND_NOISE,
                seed=99,
            ),
        )

    def test_the_run_completes(self, report: RunReport) -> None:
        assert report.status is PipelineStatus.COMPLETED
        assert report.error is None

    def test_the_caller_took_several_turns(self, report: RunReport) -> None:
        """A one-turn run proves nothing about a multi-turn audio pipeline."""
        assert report.caller_turns >= 3

    def test_the_bot_replied_several_times(self, report: RunReport) -> None:
        assert report.bot_turns >= 2

    def test_every_bot_reply_was_transcribed(self, report: RunReport) -> None:
        assert report.bot_transcripts_succeeded >= 2
        assert report.bot_transcripts_failed == 0

    def test_the_goal_was_reached(self, report: RunReport) -> None:
        assert report.goal_achieved
        assert report.outcome is RunOutcome.GOAL_ACHIEVED
        assert report.caller_state is CallerState.GOAL_ACHIEVED

    def test_both_original_and_degraded_caller_audio_exist(self, report: RunReport) -> None:
        """§8: the original must survive, because a degraded artefact is only
        evidence if the thing it came from is still there to compare against."""
        variants = {(a.speaker, a.variant) for a in report.artefacts}
        assert ("caller", "original") in variants
        assert ("caller", "degraded") in variants

    def test_each_degraded_artefact_points_at_its_original(self, report: RunReport) -> None:
        for artefact in report.artefacts:
            if artefact.variant == "degraded":
                assert artefact.derived_from
                assert artefact.derived_from != artefact.reference

    def test_the_degraded_audio_records_its_transformations_and_seed(
        self, report: RunReport
    ) -> None:
        degraded = [a for a in report.artefacts if a.variant == "degraded"]
        assert degraded
        for artefact in degraded:
            assert artefact.seed == 99
            assert "add_noise" in artefact.transformations
            assert artefact.degradation_parameters["snr_db"] == 15.0

    def test_the_degraded_audio_is_telephony_rate(self, report: RunReport) -> None:
        """Measured from the produced bytes, not copied from the request."""
        for artefact in report.artefacts:
            if artefact.variant == "degraded":
                assert artefact.sample_rate_hz == 8000
                assert artefact.channels == 1

    def test_every_artefact_reference_is_relative(self, report: RunReport) -> None:
        """An absolute filesystem path in a report discloses the server layout."""
        for artefact in report.artefacts:
            assert artefact.reference
            assert not Path(artefact.reference).is_absolute()
            assert ".." not in artefact.reference

    def test_the_artefacts_are_actually_on_disk(
        self, report: RunReport, store: AudioArtefactStore
    ) -> None:
        for artefact in report.artefacts:
            assert store.exists(artefact.reference), artefact.reference

    def test_bot_audio_duration_was_measured(self, report: RunReport) -> None:
        bot = [a for a in report.artefacts if a.speaker == "bot"]
        assert bot
        assert all(a.duration_seconds and a.duration_seconds > 0 for a in bot)

    def test_total_audio_duration_is_reported(self, report: RunReport) -> None:
        assert report.total_audio_seconds > 0

    def test_every_stage_of_every_turn_was_recorded(self, report: RunReport) -> None:
        """§6 forbids silently skipping a step, so each one leaves an event."""
        stages = {event.stage for event in report.events}
        assert {
            "caller_turn",
            "degradation",
            "bot_exchange",
            "bot_audio_validation",
            "bot_transcription",
        } <= stages

    def test_no_stage_failed(self, report: RunReport) -> None:
        failures = [(e.stage, e.detail) for e in report.events if e.status == "failed"]
        assert failures == []

    def test_stage_timings_were_measured(self, report: RunReport) -> None:
        timed = [e for e in report.events if e.duration_ms is not None]
        assert timed
        assert all(e.duration_ms >= 0 for e in timed)

    def test_the_caller_state_transitions_were_recorded(self, report: RunReport) -> None:
        assert len(report.state_transitions) >= 3
        first = report.state_transitions[0]
        assert first["state_before"] == "initial"
        assert first["state_after"] == "introducing"

    def test_a_fixture_run_is_not_reported_as_an_external_bot_test(self, report: RunReport) -> None:
        """The honesty check for the whole phase. A scripted reply is not a
        bot, and one fixture reply makes the whole run not an external test."""
        assert report.bot_audio_externally_received is False

    def test_the_report_names_every_provider(self, report: RunReport) -> None:
        assert report.caller_provider == "deterministic"
        assert report.stt_provider == "fake"
        assert report.tts_provider == "fake"
        assert report.bot_adapter == "scripted"

    def test_the_report_denies_using_a_language_model(self, report: RunReport) -> None:
        assert report.uses_language_model is False

    def test_the_run_row_is_completed_with_a_finish_time(
        self, report: RunReport, db_session: Session
    ) -> None:
        run = repo.get_run(db_session, report.run_id)
        assert run is not None
        assert run.status is RunStatus.COMPLETED
        assert run.started_at is not None
        assert run.finished_at is not None

    def test_the_caller_and_bot_turns_alternate_in_the_database(
        self, report: RunReport, db_session: Session
    ) -> None:
        assert report.conversation_id is not None
        turns = caller_repo.list_turns(db_session, report.conversation_id)
        assert [t.turn_index for t in turns] == list(range(len(turns)))
        assert turns[0].speaker.value == "caller"


class TestReproducibility:
    def test_the_same_seed_produces_identical_degraded_audio(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """A degraded artefact is only evidence if it can be reproduced."""
        payloads = []
        for _ in range(2):
            suite, scenario = _make_scenario(db_session)
            engine = _engine(
                db_session,
                pipeline_settings,
                store,
                bot=ScriptedBotAdapter(list(bot_wavs), exhausted_is_error=False),
                transcription=_SequencedTranscription(COOPERATIVE),
            )
            report = _run(
                engine,
                suite,
                scenario,
                RunConfig(
                    mode=ExecutionMode.AUDIO_FIXTURE_TEST,
                    noise_profile=NoiseProfile.HEAVY_BACKGROUND_NOISE,
                    seed=4242,
                ),
            )
            first = next(a for a in report.artefacts if a.variant == "degraded")
            payloads.append(store.read(first.reference))
        assert payloads[0] == payloads[1]

    def test_a_different_seed_produces_different_audio(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        payloads = []
        for seed in (1, 2):
            suite, scenario = _make_scenario(db_session)
            engine = _engine(
                db_session,
                pipeline_settings,
                store,
                bot=ScriptedBotAdapter(list(bot_wavs), exhausted_is_error=False),
                transcription=_SequencedTranscription(COOPERATIVE),
            )
            report = _run(
                engine,
                suite,
                scenario,
                RunConfig(
                    mode=ExecutionMode.AUDIO_FIXTURE_TEST,
                    noise_profile=NoiseProfile.HEAVY_BACKGROUND_NOISE,
                    seed=seed,
                ),
            )
            first = next(a for a in report.artefacts if a.variant == "degraded")
            payloads.append(store.read(first.reference))
        assert payloads[0] != payloads[1]

    def test_the_original_audio_is_never_overwritten(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_SequencedTranscription(COOPERATIVE),
        )
        report = _run(
            engine,
            suite,
            scenario,
            RunConfig(
                mode=ExecutionMode.AUDIO_FIXTURE_TEST,
                noise_profile=NoiseProfile.HEAVY_BACKGROUND_NOISE,
                seed=5,
            ),
        )
        degraded = next(a for a in report.artefacts if a.variant == "degraded")
        original = store.read(degraded.derived_from or "")
        assert original
        # Heavily degraded 8 kHz audio cannot equal its 8 kHz original.
        assert original != store.read(degraded.reference)


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class _FailingSpeech:
    def __init__(self) -> None:
        self.capabilities = None

    async def synthesise(self, *_: object, **__: object) -> SpeechResult:
        raise SpeechProviderUnavailableError("synthesis is down", provider="fake")

    async def close(self) -> None:
        return None


class _FailingTranscription:
    async def transcribe_batch(self, *_: object, **__: object) -> TranscriptionResult:
        raise ProviderUnavailableError("transcription is down", provider="fake")


class _RejectingTranscription:
    async def transcribe_batch(self, *_: object, **__: object) -> TranscriptionResult:
        raise InvalidAudioError("the audio is not decodable", provider="fake")


class TestFailurePaths:
    def test_a_refusing_bot_ends_the_run_as_a_refusal(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_SequencedTranscription(
                ["I cannot help with that.", "I have no record of your claim."]
            ),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.outcome is RunOutcome.BOT_REFUSED
        assert not report.goal_achieved

    def test_an_evasive_bot_ends_the_run_as_no_progress(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_SequencedTranscription(
                ["Our office is in Chennai.", "The weather is fine.", "Have a nice day."]
            ),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.outcome is RunOutcome.NO_PROGRESS

    def test_a_synthesis_failure_is_a_provider_error_not_a_bot_finding(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Blaming the bot for our outage would corrupt every aggregate built
        on these runs."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, speech=_FailingSpeech())
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.status is PipelineStatus.FAILED
        assert report.outcome is RunOutcome.PROVIDER_ERROR
        assert report.outcome not in {RunOutcome.BOT_REFUSED, RunOutcome.NO_PROGRESS}

    def test_a_synthesis_failure_records_the_stage_that_broke(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, speech=_FailingSpeech())
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        failed = [e for e in report.events if e.status == "failed"]
        assert failed
        assert any(e.stage == "caller_synthesis" for e in failed)

    def test_a_transcription_outage_does_not_fail_the_run(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """Phase 6 records a null-content turn and carries on, which is right:
        losing one transcript is not losing the conversation."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_FailingTranscription(),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.bot_transcripts_failed >= 1
        assert report.bot_transcripts_succeeded == 0
        assert any(e.stage == "bot_transcription" and e.status == "failed" for e in report.events)

    def test_undecodable_bot_audio_fails_as_audio_validation(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """Not as a bot refusal: the audio was unusable, which is our problem
        or the transport's, not a statement about the bot."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_RejectingTranscription(),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.status is PipelineStatus.FAILED
        assert report.outcome is RunOutcome.AUDIO_VALIDATION_FAILED

    def test_bot_audio_that_is_not_audio_fails_validation(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """And must never be stored as a successful turn."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter([b"this is not audio at all"]),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.outcome is RunOutcome.AUDIO_VALIDATION_FAILED
        assert any(
            e.stage == "bot_audio_validation" and e.status == "failed" for e in report.events
        )

    def test_empty_bot_audio_fails_validation(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, bot=ScriptedBotAdapter([b""]))
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.outcome is RunOutcome.AUDIO_VALIDATION_FAILED

    def test_an_adapter_failure_is_recorded_as_the_bot_being_unavailable(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter((), failures=[BotTimeoutError("no reply", adapter="scripted")]),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.outcome is RunOutcome.EXTERNAL_BOT_UNAVAILABLE
        assert any(e.stage == "bot_exchange" and e.status == "failed" for e in report.events)

    def test_the_turn_budget_bounds_the_run(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """A bot that keeps asking questions must not produce an endless run."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs * 20, exhausted_is_error=False),
            transcription=_SequencedTranscription(["And your name?"] * 50),
        )
        report = _run(
            engine,
            suite,
            scenario,
            RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST, max_turns=3),
        )
        assert report.turn_budget == 3
        assert report.caller_turns <= 3
        # And it closed itself rather than being cut off with no outcome.
        assert report.outcome is not None
        assert report.status is PipelineStatus.COMPLETED

    def test_a_failed_run_row_carries_a_redacted_error(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        class _LeakySpeech:
            async def synthesise(self, *_: object, **__: object) -> SpeechResult:
                raise SpeechProviderUnavailableError(
                    "upstream said Authorization: Bearer sk-live-abcdef123456",
                    provider="fake",
                )

            async def close(self) -> None:
                return None

        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, speech=_LeakySpeech())
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.error is not None
        assert "sk-live-abcdef123456" not in report.error
        for event in report.events:
            assert "sk-live-abcdef123456" not in (event.detail or "")


# ---------------------------------------------------------------------------
# Cancellation and lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_a_run_can_be_cancelled(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        engine.cancel(run.id)
        report = engine.report(run.id)
        assert report.status is PipelineStatus.CANCELLED
        assert report.outcome is RunOutcome.CANCELLED

    def test_cancelling_is_not_recorded_as_a_failure(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """An operator stopping a run is not a finding about the bot."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        engine.cancel(run.id)
        stored = repo.get_run(db_session, run.id)
        assert stored is not None
        assert stored.status is RunStatus.CANCELLED

    def test_cancelling_twice_is_refused(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        engine.cancel(run.id)
        with pytest.raises(RunNotActiveError):
            engine.cancel(run.id)

    def test_a_finished_run_accepts_no_further_turns(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=ScriptedBotAdapter(bot_wavs, exhausted_is_error=False),
            transcription=_SequencedTranscription(COOPERATIVE),
        )
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST))
        assert report.status is PipelineStatus.COMPLETED
        with pytest.raises(RunNotActiveError):
            asyncio.run(engine.run_to_completion(report.run_id))

    def test_reporting_an_unknown_run_is_not_found(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        engine = _engine(db_session, pipeline_settings, store)
        with pytest.raises(NotFoundError):
            engine.report(uuid.uuid4())

    def test_a_created_run_reports_no_outcome(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """A run that has not executed has no result, and reporting one would
        be a fabricated figure."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        report = engine.report(run.id)
        assert report.status is PipelineStatus.CREATED
        assert report.outcome is None
        assert report.caller_turns == 0


class TestManualAdapter:
    def test_a_run_waits_for_externally_supplied_audio(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Waiting is healthy, not a failure: the run stays running and says
        which turn it wants audio for."""
        suite, scenario = _make_scenario(db_session)
        adapter = ManualBotAdapter()
        engine = _engine(db_session, pipeline_settings, store, bot=adapter)
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.EXTERNAL_BOT_TEST))
        assert report.status is PipelineStatus.RUNNING
        assert report.outcome is None
        assert any(e.stage == "bot_exchange" and e.status == "pending" for e in report.events)

    def test_the_callers_audio_is_stored_while_waiting(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """So an operator has something to play to their bot."""
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store, bot=ManualBotAdapter())
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.EXTERNAL_BOT_TEST))
        caller_audio = [a for a in report.artefacts if a.speaker == "caller"]
        assert caller_audio
        assert all(store.exists(a.reference) for a in caller_audio)

    def test_supplied_audio_lets_the_run_continue(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        adapter = ManualBotAdapter()
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=adapter,
            transcription=_SequencedTranscription(COOPERATIVE),
        )
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.EXTERNAL_BOT_TEST),
        )
        asyncio.run(engine.run_to_completion(run.id))
        assert adapter.awaiting_turn is not None

        adapter.supply(bot_wavs[0])
        report = asyncio.run(engine.run_to_completion(run.id))
        assert report.bot_turns >= 1
        assert report.bot_transcripts_succeeded >= 1

    def test_externally_supplied_audio_is_recorded_as_such(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """The only path by which a run may claim an external bot test."""
        suite, scenario = _make_scenario(db_session)
        adapter = ManualBotAdapter()
        engine = _engine(
            db_session,
            pipeline_settings,
            store,
            bot=adapter,
            transcription=_SequencedTranscription(COOPERATIVE),
        )
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.EXTERNAL_BOT_TEST),
        )
        asyncio.run(engine.run_to_completion(run.id))
        adapter.supply(bot_wavs[0])
        report = asyncio.run(engine.run_to_completion(run.id))
        assert report.bot_audio_externally_received is True


class TestOfflineSimulationMode:
    def test_an_offline_run_moves_no_audio(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION))
        assert report.artefacts == ()
        assert report.mode is ExecutionMode.OFFLINE_SIMULATION

    def test_an_offline_run_still_produces_a_caller_turn(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        report = _run(engine, suite, scenario, RunConfig(mode=ExecutionMode.OFFLINE_SIMULATION))
        assert report.caller_turns >= 1
        assert report.bot_audio_externally_received is False


class TestNoNewTables:
    def test_the_pipeline_added_no_table(self, db_session: Session) -> None:
        """Phase 7 reuses the Phase 2 schema, so there is no migration."""
        from sqlalchemy import inspect

        tables = set(inspect(db_session.get_bind()).get_table_names())
        assert tables == {
            "alembic_version",
            "call_sessions",
            "conversation_turns",
            "scenarios",
            "test_runs",
            "test_suites",
        }

    def test_a_run_is_a_test_run_row(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        suite, scenario = _make_scenario(db_session)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        conversation = db_session.get(CallSession, repo.conversation_of(db_session, run.id).id)
        assert conversation is not None
        assert conversation.test_run_id == run.id


# ---------------------------------------------------------------------------
# A scenario's declared SNR and packet loss are applied - measured, not trusted
# ---------------------------------------------------------------------------


def _pcm(audio: bytes) -> tuple[array.array, int]:
    """Decode a 16-bit mono WAV into samples and its rate."""
    with wave.open(io.BytesIO(audio)) as reader:
        rate = reader.getframerate()
        samples = array.array("h", reader.readframes(reader.getnframes()))
    return samples, rate


def _rms_of(values: list[int]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def _declared_run(
    db_session: Session,
    settings: Settings,
    store: AudioArtefactStore,
    bot_wavs: list[bytes],
    *,
    audio: dict[str, Any],
    noise_profile: NoiseProfile = NoiseProfile.CLEAN,
    drop_request: bool = False,
) -> tuple[RunReport, dict[str, Any]]:
    spec = {**SPEC, "audio": audio}
    suite, scenario = _make_scenario(db_session, spec=spec)
    engine = _engine(
        db_session,
        settings,
        store,
        bot=ScriptedBotAdapter(bot_wavs * 4),
        transcription=_SequencedTranscription(COOPERATIVE),
    )
    run = engine.create(
        suite_id=suite.id,
        scenario_id=scenario.id,
        config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST, noise_profile=noise_profile),
    )
    if drop_request:
        # A run created before requests were recorded has no entry at all.
        meta = dict(repo.pipeline_metadata_of(run))
        meta.pop("degradation_requested")
        repo.update_pipeline_metadata(db_session, run, meta)
    report = asyncio.run(engine.run_to_completion(run.id))
    return report, dict(repo.pipeline_metadata_of(run))


def _degraded(report: RunReport) -> list[Any]:
    found = [a for a in report.artefacts if a.variant == "degraded"]
    assert found, "the run produced no degraded artefact to measure"
    return found


RURAL_DECLARED = {"noise_profile": "rural", "snr_db": 10.0, "packet_loss_percent": 8.0}


class TestDeclaredScenarioAudioIsApplied:
    def test_the_request_is_recorded_with_its_source(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, meta = _declared_run(
            db_session, pipeline_settings, store, bot_wavs, audio=RURAL_DECLARED
        )

        assert meta["degradation_requested"] == {
            "source": "scenario",
            "snr_db": 10.0,
            "packet_loss_percent": 8.0,
        }
        assert report.degradation_requested == meta["degradation_requested"]
        for artefact in _degraded(report):
            assert artefact.degradation_parameters["requested_from"] == "scenario"
            assert artefact.degradation_parameters["snr_db"] == 10.0
            assert artefact.degradation_parameters["packet_loss_percent"] == 8.0
            assert "packet_loss" in artefact.transformations

    def test_the_achieved_snr_measured_from_the_bytes_matches_the_declaration(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """Re-derive the noise from the stored files rather than trusting a field.

        The channel steps (mono, resample, band-pass) are deterministic, so
        degrading the original with noise and loss switched off reproduces the
        clean channel exactly; the difference to the stored degraded file is
        the noise that was added. Dropped packets are silent and excluded.
        """
        report, meta = _declared_run(
            db_session, pipeline_settings, store, bot_wavs, audio=RURAL_DECLARED
        )
        channel_only = replace(
            profile_config(NoiseProfile(meta["noise_profile"]), seed=meta["degradation_seed"]),
            snr_db=None,
            packet_loss_percent=0.0,
        )

        for artefact in _degraded(report):
            original = store.read(str(artefact.derived_from))
            clean, _ = _pcm(degrade(original, channel_only).audio)
            noisy, rate = _pcm(store.read(artefact.reference))
            window = max(int(rate * 0.020), 1)
            kept_clean: list[int] = []
            kept_noise: list[int] = []
            for start in range(0, len(noisy), window):
                block = noisy[start : start + window]
                if not any(block):
                    continue  # a dropped packet
                kept_clean.extend(clean[start : start + window])
                kept_noise.extend(
                    n - c for n, c in zip(block, clean[start : start + window], strict=True)
                )
            measured = 20.0 * math.log10(_rms_of(kept_clean) / _rms_of(kept_noise))

            assert abs(measured - 10.0) < 0.5, measured
            assert abs(artefact.degradation_parameters["snr_db_achieved"] - 10.0) < 0.5

    def test_the_realised_packet_loss_is_visible_in_the_bytes(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        """Count silent 20 ms packets in each stored file; it must equal the
        recorded drop count, and the run as a whole must actually drop some."""
        report, _ = _declared_run(
            db_session, pipeline_settings, store, bot_wavs, audio=RURAL_DECLARED
        )

        total_dropped = 0
        for artefact in _degraded(report):
            samples, rate = _pcm(store.read(artefact.reference))
            window = max(
                int(rate * artefact.degradation_parameters["packet_duration_ms"] / 1000), 1
            )
            silent = sum(
                1
                for start in range(0, len(samples), window)
                if not any(samples[start : start + window])
            )
            params = artefact.degradation_parameters
            assert silent == params["packets_dropped"]
            assert params["packet_loss_realised_percent"] == round(
                100.0 * params["packets_dropped"] / params["packets_total"], 2
            )
            total_dropped += silent

        assert total_dropped > 0

    def test_an_explicit_operator_profile_wins(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, meta = _declared_run(
            db_session,
            pipeline_settings,
            store,
            bot_wavs,
            audio=RURAL_DECLARED,
            noise_profile=NoiseProfile.LIGHT_BACKGROUND_NOISE,
        )

        assert meta["degradation_requested"] == {
            "source": "operator",
            "snr_db": 25.0,
            "packet_loss_percent": 0.0,
        }
        for artefact in _degraded(report):
            assert artefact.degradation_parameters["snr_db"] == 25.0
            assert abs(artefact.degradation_parameters["snr_db_achieved"] - 25.0) < 0.5
            assert "packet_loss" not in artefact.transformations

    def test_a_clean_scenario_adds_no_noise_but_keeps_its_packet_loss(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, meta = _declared_run(
            db_session,
            pipeline_settings,
            store,
            bot_wavs,
            audio={"noise_profile": "clean", "snr_db": 34.0, "packet_loss_percent": 10.0},
        )

        assert meta["degradation_requested"]["snr_db"] is None
        for artefact in _degraded(report):
            assert "add_noise" not in artefact.transformations
            assert "packet_loss" in artefact.transformations

    def test_a_run_created_before_requests_were_recorded_keeps_its_preset(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, _ = _declared_run(
            db_session,
            pipeline_settings,
            store,
            bot_wavs,
            audio=RURAL_DECLARED,
            drop_request=True,
        )

        assert report.degradation_requested is None
        for artefact in _degraded(report):
            assert artefact.degradation_parameters["snr_db"] == 25.0
            assert "packet_loss" not in artefact.transformations
            assert "requested_from" not in artefact.degradation_parameters


# ---------------------------------------------------------------------------
# Settings a scenario declares and the run does not enforce
# ---------------------------------------------------------------------------

CONSTRAINED_SPEC: dict[str, Any] = {
    **SPEC,
    "constraints": {
        "max_silence_seconds": 3.0,
        "allow_interruptions": True,
        "required_phrases": ["claim number"],
        "forbidden_phrases": ["I am a bot"],
    },
    "code_mixing": {
        "primary": "ta-IN",
        "secondary": ["en-IN"],
        "expected": True,
        "switch_triggers": ["numbers"],
    },
}


def _unenforced(
    db_session: Session,
    settings: Settings,
    store: AudioArtefactStore,
    *,
    mode: ExecutionMode,
    spec: dict[str, Any],
) -> dict[str, Any]:
    suite, scenario = _make_scenario(db_session, spec=spec)
    engine = _engine(db_session, settings, store)
    run = engine.create(suite_id=suite.id, scenario_id=scenario.id, config=RunConfig(mode=mode))
    report = engine.report(run.id)
    assert report.settings_not_enforced is not None
    return {entry["setting"]: entry for entry in report.settings_not_enforced}


class TestSettingsNotEnforced:
    def test_interruptions_and_silence_are_always_listed(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Nothing in the pipeline handles either, so no run may imply it did."""
        found = _unenforced(
            db_session,
            pipeline_settings,
            store,
            mode=ExecutionMode.AUDIO_FIXTURE_TEST,
            spec=CONSTRAINED_SPEC,
        )

        assert found["constraints.allow_interruptions"]["declared"] is True
        assert found["constraints.max_silence_seconds"]["declared"] == 3.0
        assert "Phase 9" in found["constraints.allow_interruptions"]["reason"]

    def test_declared_phrases_code_mixing_and_style_are_listed(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        found = _unenforced(
            db_session,
            pipeline_settings,
            store,
            mode=ExecutionMode.AUDIO_FIXTURE_TEST,
            spec=CONSTRAINED_SPEC,
        )

        assert found["constraints.required_phrases"]["declared"] == ["claim number"]
        assert found["constraints.forbidden_phrases"]["declared"] == ["I am a bot"]
        assert found["code_mixing"]["declared"]["secondary"] == ["en-IN"]
        assert found["persona.speaking_style"]["declared"] == "confused"
        assert found["persona.traits"]["declared"] == ["unfamiliar with insurance terminology"]

    def test_empty_phrase_lists_and_unexpected_mixing_are_not_listed(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Only what is actually declared: an empty list asks for nothing."""
        found = _unenforced(
            db_session,
            pipeline_settings,
            store,
            mode=ExecutionMode.AUDIO_FIXTURE_TEST,
            spec=SPEC,
        )

        assert "constraints.required_phrases" not in found
        assert "constraints.forbidden_phrases" not in found
        assert "code_mixing" not in found

    def test_an_audio_run_does_not_list_audio_but_an_offline_run_does(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Declared audio is applied to audio runs now; offline moves none."""
        audio_run = _unenforced(
            db_session,
            pipeline_settings,
            store,
            mode=ExecutionMode.AUDIO_FIXTURE_TEST,
            spec=SPEC,
        )
        offline_run = _unenforced(
            db_session,
            pipeline_settings,
            store,
            mode=ExecutionMode.OFFLINE_SIMULATION,
            spec=SPEC,
        )

        assert "audio" not in audio_run
        assert offline_run["audio"]["declared"]["noise_profile"] == "clean"

    def test_a_run_created_before_the_record_reports_none(
        self, db_session: Session, pipeline_settings: Settings, store: AudioArtefactStore
    ) -> None:
        """Unknown, which is not the same as "everything was enforced"."""
        suite, scenario = _make_scenario(db_session, spec=SPEC)
        engine = _engine(db_session, pipeline_settings, store)
        run = engine.create(
            suite_id=suite.id,
            scenario_id=scenario.id,
            config=RunConfig(mode=ExecutionMode.AUDIO_FIXTURE_TEST),
        )
        meta = dict(repo.pipeline_metadata_of(run))
        meta.pop("settings_not_enforced")
        repo.update_pipeline_metadata(db_session, run, meta)

        assert engine.report(run.id).settings_not_enforced is None
