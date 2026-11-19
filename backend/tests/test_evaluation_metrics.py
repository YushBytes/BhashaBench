"""Error-rate metrics and the normalisation they rest on, on synthetic ground truth."""

from __future__ import annotations

import random

import pytest

from app.evaluation.metrics import align, character_error_rate, word_error_rate
from app.evaluation.registry import BY_NAME, METRICS
from app.evaluation.text import graphemes, normalise, words


class TestAlignment:
    @pytest.mark.parametrize(
        ("ref", "hyp", "counts"),
        [
            ("a b c", "a b c", (0, 0, 0, 3)),
            ("a b c", "a x c", (1, 0, 0, 2)),
            ("a b c", "a c", (0, 1, 0, 2)),
            ("a b c", "a b c d", (0, 0, 1, 3)),
            ("a b c", "", (0, 3, 0, 0)),
            ("", "a b", (0, 0, 2, 0)),
            ("a b c d", "x b y d z", (2, 0, 1, 2)),
        ],
    )
    def test_breakdown(self, ref: str, hyp: str, counts: tuple[int, int, int, int]) -> None:
        result = align(ref.split(), hyp.split())
        assert (result.substitutions, result.deletions, result.insertions, result.hits) == counts

    def test_errors_equal_the_levenshtein_distance_on_random_input(self) -> None:
        rng = random.Random(4)

        def distance(a: list[str], b: list[str]) -> int:
            row = list(range(len(b) + 1))
            for i, x in enumerate(a, 1):
                prev, row[0] = row[0], i
                for j, y in enumerate(b, 1):
                    prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
            return row[-1]

        for _ in range(200):
            a = [rng.choice("abcd") for _ in range(rng.randrange(0, 9))]
            b = [rng.choice("abcd") for _ in range(rng.randrange(0, 9))]
            result = align(a, b)
            assert result.errors == distance(a, b)
            assert result.hits + result.substitutions + result.deletions == len(a)
            assert result.hits + result.substitutions + result.insertions == len(b)


class TestWordErrorRate:
    def test_perfect(self) -> None:
        result = word_error_rate("मेरा दावा मंजूर हुआ", "मेरा दावा मंजूर हुआ", language="hi-IN")
        assert result.value == 0.0

    def test_partial(self) -> None:
        result = word_error_rate("मेरा दावा मंजूर हुआ", "मेरा दावा हुआ", language="hi-IN")
        assert (result.value, result.deletions) == (0.25, 1)

    def test_insertions_can_take_it_above_one(self) -> None:
        result = word_error_rate("हाँ", "हाँ जी बिल्कुल ठीक", language="hi-IN")
        assert result.value == 3.0

    def test_an_empty_reference_has_no_rate(self) -> None:
        result = word_error_rate("", "anything")
        assert result.value is None
        assert result.insertions == 1

    def test_punctuation_and_dandas_do_not_count(self) -> None:
        assert word_error_rate("ठीक है।", "ठीक है", language="hi-IN").value == 0.0
        assert word_error_rate("Yes, it's done!", "yes it s done").value == 0.0

    def test_code_mixed_case_is_folded(self) -> None:
        assert word_error_rate("मेरा OTP भेजो", "मेरा otp भेजो", language="hi-IN").value == 0.0

    def test_indic_and_ascii_numerals_are_one_token(self) -> None:
        assert word_error_rate("दावा ०४७१८८३", "दावा 0471883", language="hi-IN").value == 0.0
        assert word_error_rate("எண் ௪௫", "எண் 45", language="ta-IN").value == 0.0

    def test_number_words_are_not_folded_and_score_as_errors(self) -> None:
        """Hiding this would hide a real class of recognition error."""
        assert word_error_rate("four five", "45").value == 1.0

    def test_another_script_is_fully_wrong(self) -> None:
        assert word_error_rate("मेरा दावा", "mera dava", language="hi-IN").value == 1.0

    def test_the_result_names_its_normalisation(self) -> None:
        assert word_error_rate("a", "a").normalisation == "bb-norm-1"


class TestNormalisation:
    def test_canonically_equivalent_nukta_spellings_compare_equal(self) -> None:
        precomposed = "ज़"  # DEVANAGARI LETTER ZA
        decomposed = "ज़"  # JA + NUKTA
        assert normalise(precomposed) == normalise(decomposed)

    def test_zero_width_joiners_are_removed_except_for_urdu(self) -> None:
        text = "क्‍ष"
        assert "‍" not in normalise(text, language="hi-IN")
        assert "‌" in normalise("می‌خواهم", language="ur-IN")

    def test_whitespace_is_collapsed(self) -> None:
        assert words("  a \t b\n c ") == ["a", "b", "c"]


class TestCharacterErrorRate:
    def test_a_vowel_sign_is_part_of_its_consonant(self) -> None:
        assert graphemes("कि") == ["कि"]
        # One wrong vowel sign is one cluster substituted, not one code point.
        result = character_error_rate("किताब", "कुताब", language="hi-IN")
        # कि + ता + ब: three clusters.
        assert (result.substitutions, result.reference_length) == (1, 3)

    def test_spaces_are_excluded(self) -> None:
        assert character_error_rate("ab cd", "abcd").value == 0.0


class TestRegistry:
    def test_every_metric_documents_itself_completely(self) -> None:
        for metric in METRICS:
            for field in ("definition", "formula", "evidence", "missing_data"):
                assert getattr(metric, field).strip(), (metric.name, field)
            assert metric.better in {"lower", "higher", "pass", "neither"}
            assert metric.limitations

    def test_names_are_unique(self) -> None:
        assert len(BY_NAME) == len(METRICS)
