"""The judge's validation arithmetic, checked against values worked by hand.

No real labels exist, so every set here is constructed. The point is that
the day labels exist, the numbers computed from them are right and the
acceptance rule refuses what it should.
"""

from __future__ import annotations

import pytest

from app.evaluation.judge import DEFAULT_RUBRIC
from app.evaluation.judge_validation import (
    LabelledItem,
    Thresholds,
    cohen_kappa,
    items_from_rows,
    report_criterion,
    validate,
)

CRITERIA = [c.id for c in DEFAULT_RUBRIC.criteria]


def _items(criterion: str, spec: dict[tuple[str, str], int], repeat_same: bool = True) -> list:
    """`{(human, judge): count}` -> items, with an agreeing repeat run by default."""
    out = []
    for (human, judge), count in spec.items():
        for n in range(count):
            out.append(
                LabelledItem(
                    item_id=f"{criterion}-{human}-{judge}-{n}",
                    criterion_id=criterion,
                    human=human,
                    judge=judge,
                    judge_repeat=judge if repeat_same else ("fail" if judge == "pass" else "pass"),
                )
            )
    return out


class TestCohenKappa:
    def test_matches_a_value_worked_by_hand(self) -> None:
        # 20 pass/pass, 5 pass/fail, 10 fail/pass, 15 fail/fail (n = 50).
        # p_o = 35/50 = 0.70; p_e = (25*30 + 25*20)/2500 = 0.50; kappa = 0.40.
        pairs = [("pass", "pass")] * 20 + [("pass", "fail")] * 5
        pairs += [("fail", "pass")] * 10 + [("fail", "fail")] * 15
        assert cohen_kappa(pairs) == pytest.approx(0.40)

    def test_perfect_agreement_is_one_and_an_always_pass_judge_scores_zero_or_less(self) -> None:
        assert cohen_kappa([("pass", "pass"), ("fail", "fail")] * 10) == pytest.approx(1.0)
        always_pass = [("pass", "pass")] * 90 + [("fail", "pass")] * 10
        # 90% raw agreement, and no better than chance.
        assert cohen_kappa(always_pass) == pytest.approx(0.0)

    def test_undefined_is_none_never_a_number(self) -> None:
        assert cohen_kappa([]) is None
        assert cohen_kappa([("pass", "pass")] * 5) is None


class TestCriterionReport:
    def test_rates_count_abstentions_separately(self) -> None:
        items = _items(
            "answered_objective",
            {("pass", "pass"): 60, ("pass", "fail"): 6, ("fail", "fail"): 28,
             ("fail", "pass"): 2, ("pass", "uncertain"): 4},
        )  # fmt: skip
        report = report_criterion("answered_objective", items, Thresholds())
        assert report.items == 100 and report.decided == 96
        assert report.false_pass_rate == pytest.approx(2 / 30)
        assert report.false_fail_rate == pytest.approx(6 / 66)
        assert report.abstention_rate == pytest.approx(0.04)
        assert report.agreement == pytest.approx(88 / 96)
        assert report.confusion["pass"]["uncertain"] == 4
        # 96 decided items is below the default bar of 100.
        assert any("decided items" in f for f in report.failures)

    def test_a_judge_that_disagrees_with_itself_fails_consistency(self) -> None:
        items = _items(
            "factually_consistent", {("pass", "pass"): 70, ("fail", "fail"): 40}, repeat_same=False
        )
        report = report_criterion("factually_consistent", items, Thresholds())
        assert report.consistency == 0.0
        assert any("consistency" in f for f in report.failures)


class TestValidate:
    def test_a_good_judge_on_enough_items_is_validated(self) -> None:
        items = []
        for criterion in CRITERIA:
            items += _items(
                criterion,
                {
                    ("pass", "pass"): 70,
                    ("pass", "fail"): 4,
                    ("fail", "fail"): 34,
                    ("fail", "pass"): 2,
                },
            )
        result = validate(items, CRITERIA)
        assert result.validated, result.reasons

    def test_no_labels_is_not_validated_and_says_why(self) -> None:
        result = validate([], CRITERIA)
        assert not result.validated
        assert any("0 decided items" in r for r in result.reasons)
        assert any("unmeasured" in r for r in result.reasons)

    def test_one_weak_criterion_fails_the_whole_judge(self) -> None:
        items = []
        for criterion in CRITERIA[:-1]:
            items += _items(criterion, {("pass", "pass"): 70, ("fail", "fail"): 40})
        # The last criterion passes nearly everything a human failed.
        items += _items(
            CRITERIA[-1], {("pass", "pass"): 70, ("fail", "pass"): 30, ("fail", "fail"): 10}
        )
        result = validate(items, CRITERIA)
        assert not result.validated
        assert all(r.startswith(f"{CRITERIA[-1]}:") for r in result.reasons)

    def test_labels_for_an_unknown_criterion_are_reported(self) -> None:
        items = _items("politeness", {("pass", "pass"): 1})
        assert any("not in the rubric" in r for r in validate(items, CRITERIA).reasons)


class TestLabels:
    def test_a_human_cannot_label_uncertain(self) -> None:
        with pytest.raises(ValueError, match="excluded from the set"):
            LabelledItem("i", "answered_objective", human="uncertain", judge="pass")

    def test_rows_parse_case_insensitively_with_an_optional_repeat(self) -> None:
        rows = [
            {"item_id": "a", "criterion_id": "answered_objective",
             "human": "PASS", "judge": "Fail"},
            {"item_id": "b", "criterion_id": "answered_objective", "human": "fail",
             "judge": "fail", "judge_repeat": "fail"},
        ]  # fmt: skip
        parsed = items_from_rows(rows)
        assert parsed[0].human == "pass" and parsed[0].judge == "fail"
        assert parsed[0].judge_repeat is None and parsed[1].judge_repeat == "fail"
