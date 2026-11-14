"""The recorded demonstration's scenario, `scenarios/demo/tamil_crop_insurance.yaml`.

The reference-scenario tests glob `scenarios/*.yaml` only, so without this
module nothing would notice the demo file drifting out of the schema - and it
is the one file a viewer of the demo actually hears.

The deterministic caller speaks `persona.identity` and `goal.objective`
verbatim in its opening. Both were once English authoring notes, so the Tamil
opening read "வணக்கம், நான் Smallholder paddy farmer near Thanjavur. Find out
whether..." aloud. The checks below pin the fix: the opening is Tamil, its only
English words are the code-mixed terms the scenario itself declares, it passes
the same validation gate as every live turn, and it is reproducible.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from app.caller.providers.deterministic import DeterministicCallerProvider
from app.caller.schemas import CallerContext, CallerDecision, CallerIntent, CallerPersona
from app.caller.service import CallerService
from app.caller.state import CallerState
from app.core.config import AppEnv, Settings
from app.schemas.scenario_spec import ScenarioSpec
from app.services.scenario_loader import spec_from_file

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCENARIO = REPO_ROOT / "scenarios" / "demo" / "tamil_crop_insurance.yaml"

# English a Thanjavur farmer would genuinely say mid-sentence: the season name
# and the scheme vocabulary, matching the scenario's `switch_triggers`
# (`technical_terms`). Anything else in Latin script means authoring text has
# leaked into speech again.
ALLOWED_ENGLISH = frozenset({"samba", "season", "crop", "insurance", "claim", "assess", "amount"})

_TAMIL_LETTER = re.compile(r"[஀-௿]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_LATIN_WORD = re.compile(r"[A-Za-z]+")


@pytest.fixture(scope="module")
def spec() -> ScenarioSpec:
    return spec_from_file(DEMO_SCENARIO)


def _settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        app_env=AppEnv.TEST,
        secret_key="test-secret-key-not-used-for-anything",
        caller_audio_storage_dir=str(tmp_path / "caller-audio"),
        _env_file=None,
    )


def _opening_context(spec: ScenarioSpec) -> CallerContext:
    """The context the orchestrator builds for turn 0, projected from the spec."""
    return CallerContext(
        scenario_id="00000000-0000-0000-0000-000000000000",
        scenario_name=spec.name,
        objective=spec.goal.objective,
        persona=CallerPersona(
            identity=spec.persona.identity,
            speaking_style=str(spec.persona.speaking_style),
            traits=tuple(spec.persona.traits),
            language=spec.language,
        ),
        known_facts=dict(spec.known_facts),
        state=CallerState.INITIAL,
        turn_index=0,
        turns_remaining=spec.goal.max_turns,
    )


def _open(spec: ScenarioSpec) -> CallerDecision:
    return asyncio.run(DeterministicCallerProvider().decide(_opening_context(spec)))


class TestTheDemoScenarioFile:
    def test_validates_against_the_schema(self, spec: ScenarioSpec) -> None:
        assert spec.name == "tamil_crop_insurance"
        assert spec.language == "ta-IN"

    def test_the_marking_criteria_and_facts_are_unchanged(self, spec: ScenarioSpec) -> None:
        """Rewording the opening must not move what the run is marked against."""
        assert spec.known_facts == {
            "policy_number": "PMFBY2026114827",
            "registered_name": "Ramasamy Durai",
            "survey_number": "142/3B",
            "crop": "paddy",
            "sowing_season": "Samba",
        }
        assert spec.expected_outcomes == [
            "Confirm the policy number back to the caller",
            "State the claim status",
            "State the assessed payout amount",
            "State when the payment will arrive",
        ]


class TestTheSpokenOpening:
    def test_is_produced_by_the_opening_rule(self, spec: ScenarioSpec) -> None:
        decision = _open(spec)

        assert decision.rule_ids == ("open.introduce",)
        assert decision.intent is CallerIntent.OPEN
        assert decision.next_state is CallerState.INTRODUCING

    def test_passes_the_caller_validation_gate(self, spec: ScenarioSpec, tmp_path: Path) -> None:
        """The same check every live turn goes through before synthesis."""
        service = CallerService(DeterministicCallerProvider(), settings=_settings(tmp_path))

        service.validate(_open(spec), _opening_context(spec))  # raises on any violation

    def test_is_deterministic(self, spec: ScenarioSpec) -> None:
        """Two independent providers, same scenario: the same words."""
        assert _open(spec).message == _open(spec).message

    def test_is_tamil_with_only_the_declared_english_terms(self, spec: ScenarioSpec) -> None:
        message = _open(spec).message

        english = {word.lower() for word in _LATIN_WORD.findall(message)}
        unexpected = english - ALLOWED_ENGLISH
        assert not unexpected, f"unexpected English in the opening: {unexpected}"
        assert len(_TAMIL_LETTER.findall(message)) > 2 * len(_LATIN_LETTER.findall(message))

    def test_does_not_speak_authoring_notes(self, spec: ScenarioSpec) -> None:
        """The specific phrasing that used to be read aloud."""
        message = _open(spec).message.lower()

        for leaked in ("smallholder", "farmer", "find out", "thanjavur"):
            assert leaked not in message
