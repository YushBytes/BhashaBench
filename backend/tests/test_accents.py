"""Accent profiles: a second dimension beside language, never claimed.

A scenario may request an accent; a run applies it only when the speech
provider genuinely renders that profile. No configured provider does, so
every run must report it as requested and not applied - and say why.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import accents, languages
from app.pipeline import engine
from app.schemas.scenario_spec import ScenarioSpec
from app.speech.providers import fake, timbre
from tests.test_pipeline_api import SPEC

EN = {
    **copy.deepcopy(SPEC),
    "name": "accented_english",
    "language": "en-IN",
}
EN["persona"] = {**EN["persona"], "accent": "en-IN.south"}
EN.pop("code_mixing", None)


class TestCatalogue:
    def test_every_profile_is_a_variety_of_a_catalogue_language(self) -> None:
        codes = {language.code for language in languages.CATALOGUE}
        assert accents.CATALOGUE and all(p.language in codes for p in accents.CATALOGUE)
        assert len(accents.BY_KEY) == len(accents.CATALOGUE), "keys are unique"
        assert all(p.key.startswith(f"{p.language}.") for p in accents.CATALOGUE)

    def test_the_language_endpoint_lists_each_languages_profiles(self, client: TestClient) -> None:
        body = client.get("/api/v1/languages").json()
        by_code = {entry["code"]: entry for entry in body["languages"]}
        assert {a["key"] for a in by_code["en-IN"]["accents"]} == {
            p.key for p in accents.for_language("en-IN")
        }
        assert by_code["or-IN"]["accents"] == [], "no profile is invented for a language"


class TestScenarioValidation:
    def test_a_profile_of_the_scenarios_language_validates(self) -> None:
        assert ScenarioSpec.model_validate(EN).persona.accent == "en-IN.south"

    @pytest.mark.parametrize(
        ("accent", "message"),
        [("en-IN.martian", "unknown accent"), ("ta-IN.kongu", "variety of ta-IN, not")],
    )
    def test_an_unknown_or_foreign_profile_is_refused(self, accent: str, message: str) -> None:
        doc = copy.deepcopy(EN)
        doc["persona"]["accent"] = accent
        with pytest.raises(ValidationError, match=message):
            ScenarioSpec.model_validate(doc)


class TestEvidence:
    spec = ScenarioSpec.model_validate(EN)

    def test_no_provider_today_renders_any_accent(self) -> None:
        # The honest default: neither adapter documents an accented voice.
        assert fake.RENDERED_ACCENTS == frozenset() == timbre.RENDERED_ACCENTS

    def test_requested_with_the_fake_provider_is_not_applied_and_says_why(self) -> None:
        evidence = engine.accent_evidence(self.spec, uses_audio=True, tts_provider="fake")
        assert evidence is not None
        assert (evidence["requested"], evidence["applied"]) == ("en-IN.south", None)
        assert "documents no voice with this accent" in evidence["reason"]

    def test_a_mode_without_audio_cannot_apply_it(self) -> None:
        evidence = engine.accent_evidence(self.spec, uses_audio=False, tts_provider=None)
        assert evidence is not None and evidence["applied"] is None
        assert "moves no audio" in evidence["reason"]

    def test_it_is_applied_only_when_the_provider_declares_the_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(engine, "rendered_accents", lambda name: frozenset({"en-IN.south"}))
        evidence = engine.accent_evidence(self.spec, uses_audio=True, tts_provider="future")
        assert evidence is not None
        assert (evidence["applied"], evidence["reason"]) == ("en-IN.south", None)

    def test_a_scenario_without_an_accent_has_no_evidence(self) -> None:
        plain = ScenarioSpec.model_validate({**EN, "persona": {"identity": "A caller"}})
        assert engine.accent_evidence(plain, uses_audio=True, tts_provider="fake") is None
