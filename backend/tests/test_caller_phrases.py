"""The caller's phrase tables: complete, in the right script, honestly labelled.

Three tables (Bengali, Marathi, Telugu) are machine-written and unreviewed.
These tests keep that status visible end to end - in the capabilities, the
provider listing, each run's record - and keep `docs/PHRASE_REVIEW.md`, the
document a fluent reviewer works from, identical to what the caller says.
"""

from __future__ import annotations

import re
import string
import subprocess
import sys
import uuid
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.caller.providers import deterministic
from app.caller.providers.deterministic import DeterministicCallerProvider
from app.models import Scenario
from app.models.suite import TestSuite as SuiteModel
from tests.test_pipeline_api import SPEC, pipeline_client  # noqa: F401 - fixture

REVIEW_DOC = Path(__file__).resolve().parents[2] / "docs" / "PHRASE_REVIEW.md"

SCRIPTS = {
    "bn-IN": (0x0980, 0x09FF),  # Bengali
    "mr-IN": (0x0900, 0x097F),  # Devanagari
    "te-IN": (0x0C00, 0x0C7F),  # Telugu
    "ta-IN": (0x0B80, 0x0BFF),  # Tamil
    "hi-IN": (0x0900, 0x097F),  # Devanagari
}
ALLOWED_PLACEHOLDERS = {"identity", "objective", "fact"}
SLOT_PLACEHOLDERS = {
    "opening": {"identity", "objective"},
    "provide_fact": {"fact"},
    "correct": {"fact"},
    "confirm": {"fact"},
}

CAPS = DeterministicCallerProvider().capabilities


def _slots(language: str) -> dict[str, str]:
    table = deterministic._TABLES[language]
    return {f.name: getattr(table, f.name) for f in fields(table)}


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


class TestTables:
    @pytest.mark.parametrize("language", sorted(deterministic._TABLES))
    def test_every_slot_is_filled_with_only_the_placeholders_its_rule_supplies(
        self, language: str
    ) -> None:
        for slot, text in _slots(language).items():
            assert text.strip(), (language, slot)
            used = _placeholders(text)
            assert used <= ALLOWED_PLACEHOLDERS, (language, slot, used)
            assert used == SLOT_PLACEHOLDERS.get(slot, set()), (language, slot, used)

    @pytest.mark.parametrize("language", sorted(SCRIPTS))
    def test_each_table_is_written_in_its_own_script(self, language: str) -> None:
        low, high = SCRIPTS[language]
        for slot, text in _slots(language).items():
            letters = re.sub(r"\{[a-z]+\}", "", text)
            # The danda (U+0964/0965) is shared punctuation, encoded once in
            # the Devanagari block and used by Bengali too.
            letters = letters.replace("।", "").replace("॥", "")
            letters = [c for c in letters if c.isalpha() or 0x0900 <= ord(c) <= 0x0DFF]
            stray = [c for c in letters if not low <= ord(c) <= high]
            assert letters and not stray, (language, slot, "".join(stray))


class TestMechanicalReview:
    """What can be checked without a fluent speaker. Meaning, register and
    naturalness cannot, and are left to the review sheet."""

    @pytest.mark.parametrize("language", sorted(deterministic._TABLES))
    def test_no_two_slots_say_the_same_thing(self, language: str) -> None:
        phrases = list(_slots(language).values())
        assert len(set(phrases)) == len(phrases), language

    @pytest.mark.parametrize("language", sorted(deterministic._TABLES))
    def test_every_phrase_ends_as_a_sentence(self, language: str) -> None:
        for slot, text in _slots(language).items():
            if slot == "opening":
                continue  # ends with the scenario's own objective
            assert text.rstrip()[-1] in ".?!।", (language, slot)

    def test_the_review_sheets_match_the_code(self) -> None:
        root = REVIEW_DOC.parents[1]
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "phrase_review_sheet.py"), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr


class TestReviewStatusIsHonest:
    def test_the_new_tables_are_declared_unreviewed_and_never_reviewed(self) -> None:
        assert CAPS.unreviewed_languages == {"bn-IN", "mr-IN", "te-IN"}
        assert not CAPS.unreviewed_languages & CAPS.languages
        assert set(deterministic._TABLES) == CAPS.languages | CAPS.unreviewed_languages

    def test_review_status_per_language(self) -> None:
        assert CAPS.phrase_review("ta-IN") == "reviewed"
        assert CAPS.phrase_review("bn-IN") == "unreviewed"
        assert CAPS.phrase_review("kn-IN") is None
        assert CAPS.supports_language("te-IN") and not CAPS.supports_language("kn-IN")

    def test_the_provider_listing_reports_both_lists(self, api_client: TestClient) -> None:
        listed = api_client.get("/api/v1/caller/providers").json()["providers"]
        rule_engine = next(p for p in listed if p["name"] == "deterministic")
        assert rule_engine["unreviewed_languages"] == ["bn-IN", "mr-IN", "te-IN"]
        assert "bn-IN" not in rule_engine["languages"]


class TestTheReviewDocumentIsTheCode:
    @pytest.mark.parametrize("language", sorted(CAPS.unreviewed_languages))
    def test_every_unreviewed_phrase_appears_verbatim(self, language: str) -> None:
        doc = REVIEW_DOC.read_text(encoding="utf-8")
        section = doc.split(f"(`{language}`)\n", 2)[-1].split("\n### ", 1)[0]
        for slot, text in _slots(language).items():
            assert f"| `{slot}` | {text} |" in section, (language, slot)

    def test_the_status_table_matches_the_capabilities(self) -> None:
        doc = REVIEW_DOC.read_text(encoding="utf-8")
        for language in CAPS.unreviewed_languages:
            assert re.search(rf"\(`{language}`\) \| \*\*unreviewed\*\*", doc), language
        for language in CAPS.languages:
            assert re.search(rf"\(`{language}`\) \| reviewed", doc), language


class TestEveryRunRecordsIt:
    @pytest.mark.parametrize(
        ("language", "expected"), [("bn-IN", "unreviewed"), ("ta-IN", "reviewed")]
    )
    def test_a_run_says_whether_its_caller_phrases_were_reviewed(
        self,
        pipeline_client: TestClient,  # noqa: F811 - the imported fixture
        db_session: Session,
        language: str,
        expected: str,
    ) -> None:
        suite = SuiteModel(name=f"phrases-{uuid.uuid4().hex[:6]}")
        db_session.add(suite)
        db_session.flush()
        spec: dict[str, Any] = {**SPEC, "name": f"phrases_{language[:2]}", "language": language}
        scenario = Scenario(
            suite_id=suite.id, name=spec["name"], description=spec["description"],
            language=language, spec=spec, spec_version=1,
        )  # fmt: skip
        db_session.add(scenario)
        db_session.flush()
        created = pipeline_client.post(
            "/api/v1/test-runs",
            json={
                "suite_id": str(suite.id),
                "scenario_id": str(scenario.id),
                "mode": "offline_simulation",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["caller_phrase_review"] == expected
        listed = pipeline_client.get("/api/v1/test-runs", params={"suite_id": str(suite.id)}).json()
        assert listed["items"][0]["caller_phrase_review"] == expected
