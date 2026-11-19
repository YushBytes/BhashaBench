"""Script segmentation and the code-mixing metrics built on it.

Script switching is what a transcript shows of code-mixing; these pin both
what it measures and what it cannot (romanised Hindi is Latin).
"""

from __future__ import annotations

import copy
from typing import Any

from app.evaluation import scripts
from app.evaluation.evaluator import evaluate_evidence
from tests.test_evaluation_evaluator import BASE

TAMIL_MIXED = "வணக்கம், Samba season-ல மழையால பயிர் சேதமாச்சு, crop insurance claim போட்டிருக்கேன்."


class TestSegments:
    def test_a_code_mixed_sentence_splits_where_the_script_changes(self) -> None:
        segs = scripts.segments(TAMIL_MIXED)
        assert [s.script for s in segs] == ["Taml", "Latn", "Taml", "Latn", "Taml"]
        assert scripts.switches(TAMIL_MIXED) == 4
        assert sum(s.words for s in segs) == len(TAMIL_MIXED.split())

    def test_words_without_letters_join_their_segment(self) -> None:
        assert [(s.script, s.text) for s in scripts.segments("12 नमस्ते 34 जी")] == [
            ("Deva", "12 नमस्ते 34 जी")
        ]
        assert scripts.segments("42 ?") == [] and scripts.segments("") == []

    def test_romanised_hindi_is_latin_the_stated_limitation(self) -> None:
        assert [s.script for s in scripts.segments("aapka policy number batayiye")] == ["Latn"]

    def test_every_catalogue_script_is_recognised(self) -> None:
        samples = {
            "Deva": "नमस्ते", "Beng": "নমস্কার", "Guru": "ਸਤਿ", "Gujr": "નમસ્તે",
            "Orya": "ନମସ୍କାର", "Taml": "வணக்கம்", "Telu": "నమస్కారం", "Knda": "ನಮಸ್ಕಾರ",
            "Mlym": "നമസ്കാരം", "Arab": "سلام", "Latn": "hello",
        }  # fmt: skip
        for code, word in samples.items():
            assert scripts.word_script(word) == code, word

    def test_words_in_script_keeps_order(self) -> None:
        assert scripts.words_in_script(TAMIL_MIXED, "Latn") == "Samba season-ல crop insurance claim"


def _evidence(**changes: Any) -> dict[str, Any]:
    evidence = copy.deepcopy(BASE)
    evidence.update(changes)
    return evidence


class TestMetrics:
    def test_script_mixing_describes_both_sides(self) -> None:
        metrics = evaluate_evidence(
            _evidence(language="ta-IN", caller_texts=[TAMIL_MIXED, "சரி, நன்றி."])
        ).results["metrics"]
        caller = metrics["script_mixing"]["caller"]
        assert (caller["turns"], caller["turns_with_switching"], caller["switches"]) == (2, 1, 4)
        assert metrics["script_mixing"]["bot"]["words_by_script"] == {"Latn": 6}
        assert metrics["script_mixing"]["measures"] == "script switching, not language switching"

    def test_wer_by_script_isolates_where_code_mixed_words_were_lost(self) -> None:
        turn = {
            "turn_index": 1,
            "text": "உங்கள் பாலிசி confirmed",
            "latency_ms": None,
            "transcription_failed": False,
            "reference": "உங்கள் பாலிசி number confirmed",
        }
        metrics = evaluate_evidence(_evidence(language="ta-IN", bot_turns=[turn])).results[
            "metrics"
        ]
        by_script = metrics["wer_by_script"]["value"]
        assert by_script["Taml"]["value"] == 0.0  # both Tamil words survived
        assert by_script["Latn"]["value"] == 0.5  # "number" was lost: 1 of 2
        assert metrics["wer"]["value"] == 0.25  # the pooled figure hides where

    def test_wer_by_script_is_null_with_a_reason_without_references(self) -> None:
        metric = evaluate_evidence(_evidence()).results["metrics"]["wer_by_script"]
        assert metric["value"] is None and "reference" in metric["reason"]

    def test_an_older_evidence_document_without_caller_texts_still_evaluates(self) -> None:
        metrics = evaluate_evidence(_evidence()).results["metrics"]
        assert metrics["script_mixing"]["caller"]["turns"] == 0
