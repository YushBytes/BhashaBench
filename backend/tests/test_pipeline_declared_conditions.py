"""Channel conditions declared by a scenario or overridden by an operator,
applied in real audio runs against PostgreSQL, measured per artefact.

The rule under test: every declared condition is applied or reported as not
enforced, never silently ignored, and the achieved value is recorded on the
artefact it produced, beside who asked for it.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.caller.artefacts import AudioArtefactStore
from app.core.config import AppEnv, Settings
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.degradation import DegradationConfig, Transformation, with_conditions
from app.pipeline.engine import RunConfig, RunReport
from app.pipeline.modes import ExecutionMode, PipelineStatus
from app.repositories import pipeline_runs as repo
from app.schemas.scenario_spec import AudioConfig, ScenarioSpec
from tests.test_pipeline_engine import (
    COOPERATIVE,
    SPEC,
    _engine,
    _make_scenario,
    _SequencedTranscription,
    _wav,
)


@pytest.fixture
def pipeline_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "audio"),
        caller_synthesise_audio=True,
        _env_file=None,
    )


@pytest.fixture
def store(pipeline_settings: Settings) -> AudioArtefactStore:
    return AudioArtefactStore(pipeline_settings.caller_audio_root)


@pytest.fixture
def bot_wavs(pipeline_settings: Settings) -> list[bytes]:
    return [_wav(pipeline_settings, seconds=0.5 + 0.1 * n) for n in range(4)]


CONDITIONS: dict[str, Any] = {
    "gain_db": -6.0,
    "clip_threshold": 0.4,
    "sample_rate_hz": 8000,
    "jitter_ms": 120.0,
    "dropout_count": 1,
    "dropout_ms": 100.0,
    "leading_silence_ms": 200.0,
    "trailing_silence_ms": 100.0,
}


def _run(
    db_session: Session,
    settings: Settings,
    store: AudioArtefactStore,
    bot_wavs: list[bytes],
    *,
    audio: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    degrade: bool = True,
) -> tuple[RunReport, dict[str, Any]]:
    suite, scenario = _make_scenario(db_session, spec={**SPEC, "audio": audio})
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
        config=RunConfig(
            mode=ExecutionMode.AUDIO_FIXTURE_TEST,
            audio_overrides=overrides,
            degrade_caller_audio=degrade,
            seed=7,
        ),
    )
    report = asyncio.run(engine.run_to_completion(run.id))
    return report, dict(repo.pipeline_metadata_of(run))


def _degraded(report: RunReport) -> list[Any]:
    return [a for a in report.artefacts if a.variant == "degraded"]


class TestTheSpecification:
    def test_undeclared_conditions_stay_absent_from_a_dump(self) -> None:
        """So every existing scenario and bundle serialises byte-for-byte as before."""
        dumped = AudioConfig().model_dump(mode="json", exclude_none=True)
        assert set(dumped) == {"noise_profile", "snr_db", "packet_loss_percent"}

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("gain_db", 3.0),
            ("gain_db", -41.0),
            ("clip_threshold", 0.01),
            ("sample_rate_hz", 11025),
            ("jitter_ms", 301.0),
            ("dropout_count", 21),
            ("dropout_ms", 10.0),
            ("truncate_after_seconds", 0.1),
            ("leading_silence_ms", 6000.0),
        ],
    )
    def test_out_of_range_declarations_are_refused(self, field: str, value: float) -> None:
        with pytest.raises(ValidationError, match=field):
            ScenarioSpec.model_validate({**SPEC, "audio": {field: value}})


class TestTheMapping:
    def test_gain_becomes_an_amplitude_scale(self) -> None:
        config = with_conditions(DegradationConfig(), {"gain_db": -20.0})
        assert config.amplitude_scale == pytest.approx(0.1)

    def test_a_sample_rate_forces_mono(self) -> None:
        config = with_conditions(DegradationConfig(), {"sample_rate_hz": 16000})
        assert (config.target_sample_rate_hz, config.force_mono) == (16000, True)

    def test_nothing_declared_changes_nothing(self) -> None:
        base = DegradationConfig(snr_db=20, seed=1)
        assert with_conditions(base, {}) is base


class TestDeclaredConditionsAreApplied:
    def test_every_declared_condition_reaches_the_artefact_with_its_achieved_value(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, meta = _run(
            db_session, pipeline_settings, store, bot_wavs, audio={**SPEC["audio"], **CONDITIONS}
        )
        assert report.status is PipelineStatus.COMPLETED, report.error
        requested = meta["degradation_requested"]
        assert requested["conditions"] == CONDITIONS
        assert set(requested["condition_sources"].values()) == {"scenario"}

        degraded = _degraded(report)
        assert degraded
        for artefact in degraded:
            steps = set(artefact.transformations)
            assert {
                Transformation.RESAMPLE.value,
                Transformation.REDUCE_AMPLITUDE.value,
                Transformation.CLIP.value,
                Transformation.JITTER.value,
                Transformation.DROPOUT.value,
                Transformation.PAD_SILENCE.value,
            } <= steps
            params = artefact.degradation_parameters
            assert artefact.sample_rate_hz == 8000
            assert params["gain_db_achieved"] == pytest.approx(-6.0, abs=0.2)
            assert params["clip_threshold"] == 0.4
            assert params["dropout_silenced_ms_achieved"] == pytest.approx(100.0, abs=1)
            assert "jitter_silence_inserted_ms" in params
            assert params["leading_silence_ms"] == 200.0
            assert artefact.derived_from

    def test_an_operator_value_wins_and_the_source_is_recorded(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, meta = _run(
            db_session,
            pipeline_settings,
            store,
            bot_wavs,
            audio={**SPEC["audio"], "gain_db": -6.0, "clip_threshold": 0.5},
            overrides={"gain_db": -18.0},
        )
        requested = meta["degradation_requested"]
        assert requested["conditions"] == {"gain_db": -18.0, "clip_threshold": 0.5}
        assert requested["condition_sources"] == {
            "gain_db": "operator",
            "clip_threshold": "scenario",
        }
        for artefact in _degraded(report):
            assert artefact.degradation_parameters["gain_db_achieved"] == pytest.approx(
                -18.0, abs=0.2
            )

    def test_truncation_shortens_the_caller_audio(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, _ = _run(
            db_session,
            pipeline_settings,
            store,
            bot_wavs,
            audio={**SPEC["audio"], "truncate_after_seconds": 0.5},
        )
        for artefact in _degraded(report):
            assert artefact.duration_seconds is not None
            assert artefact.duration_seconds <= 0.5 + 1e-3
            assert "truncated_seconds" in artefact.degradation_parameters

    def test_a_disabled_degradation_stage_reports_the_conditions_as_not_enforced(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        report, _ = _run(
            db_session,
            pipeline_settings,
            store,
            bot_wavs,
            audio={**SPEC["audio"], "gain_db": -6.0},
            degrade=False,
        )
        assert _degraded(report) == []
        entries = {e["setting"]: e for e in report.settings_not_enforced or []}
        assert "degrade_caller_audio is false" in entries["audio"]["reason"]

    def test_a_seeded_run_is_reproducible_end_to_end(
        self,
        db_session: Session,
        pipeline_settings: Settings,
        store: AudioArtefactStore,
        bot_wavs: list[bytes],
    ) -> None:
        audio = {**SPEC["audio"], **CONDITIONS}
        first, _ = _run(db_session, pipeline_settings, store, bot_wavs, audio=audio)
        second, _ = _run(db_session, pipeline_settings, store, bot_wavs, audio=audio)
        a = [store.read(x.reference) for x in _degraded(first)]
        b = [store.read(x.reference) for x in _degraded(second)]
        assert a and a == b
        assert not math.isnan(first.total_audio_seconds)
