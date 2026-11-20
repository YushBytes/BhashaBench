"""Measure an LLM judge against human labels before anyone trusts it.

The judge (`app/evaluation/judge.py`) scores each rubric criterion `pass`,
`fail` or `uncertain`. Nothing about it is trusted until this module says the
evidence supports it, and today it cannot: no human-labelled set exists and no
model judgement has ever been produced (live calls are not authorised). This
module is the measurement, ready for the data; `docs/JUDGE_VALIDATION.md` is
the protocol for producing the data.

What is measured, per criterion, over items both a human and the judge scored:

- **Agreement** (observed) and **Cohen's kappa** (agreement beyond chance,
  so a judge that says `pass` to everything on a set that is mostly `pass`
  does not look good).
- **False pass rate**: of the items a human failed, the share the judge
  passed. The costly error - it hides a broken bot - so it has its own bar.
- **False fail rate**: of the items a human passed, the share the judge failed.
- **Abstention**: the share the judge scored `uncertain`. Reported, never
  counted as agreement.
- **Consistency**: agreement between two judge runs over the same items,
  because a judge that disagrees with itself cannot agree with people.

`validate` applies the acceptance rule in `Thresholds` and returns `False`,
with every reason, unless each criterion clears every bar on enough items.
There is no partial credit and no override: an unvalidated judge stays
supplementary, as it already is.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

LABELS = ("pass", "fail", "uncertain")


@dataclass(frozen=True, slots=True)
class LabelledItem:
    """One conversation's score on one criterion, from a human and the judge."""

    item_id: str
    criterion_id: str
    human: str
    judge: str
    judge_repeat: str | None = None
    """The judge's score on a second, independent run, for consistency."""
    language: str | None = None
    """The conversation's language tag, for the per-language breakdown."""

    def __post_init__(self) -> None:
        for name in ("human", "judge"):
            if getattr(self, name) not in LABELS:
                raise ValueError(f"{name} label must be one of {LABELS}")
        if self.human == "uncertain":
            raise ValueError(
                "a human label must be pass or fail; an item no annotator can "
                "decide is excluded from the set, not scored uncertain"
            )
        if self.judge_repeat is not None and self.judge_repeat not in LABELS:
            raise ValueError(f"judge_repeat must be one of {LABELS}")


@dataclass(frozen=True, slots=True)
class Thresholds:
    """The acceptance rule. Each criterion must clear every bar."""

    min_items: int = 100
    """Decided items per criterion. Below this, no rate is stable enough to trust."""
    min_kappa: float = 0.6
    """Cohen's kappa over decided items; 0.6 is the conventional floor for
    substantial agreement."""
    max_false_pass_rate: float = 0.10
    max_false_fail_rate: float = 0.20
    max_abstention_rate: float = 0.25
    min_consistency: float = 0.9
    """Agreement between two judge runs, where repeats were collected."""


@dataclass(frozen=True, slots=True)
class CriterionReport:
    criterion_id: str
    items: int
    decided: int
    """Items the judge scored pass or fail."""
    agreement: float | None
    kappa: float | None
    false_pass_rate: float | None
    false_fail_rate: float | None
    abstention_rate: float | None
    consistency: float | None
    confusion: dict[str, dict[str, int]]
    """human label -> judge label -> count."""
    failures: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ValidationReport:
    validated: bool
    criteria: tuple[CriterionReport, ...]
    reasons: tuple[str, ...]


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters over the same items; `None` when undefined.

    Undefined (rather than 0 or 1) when there are no items, or when chance
    agreement is total - both raters used one label throughout - because then
    agreement beyond chance has no meaning.
    """
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    left = Counter(a for a, _ in pairs)
    right = Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in set(left) | set(right)) / (n * n)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1 - expected)


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def report_criterion(
    criterion_id: str, items: Sequence[LabelledItem], thresholds: Thresholds
) -> CriterionReport:
    confusion = {h: dict.fromkeys(LABELS, 0) for h in ("pass", "fail")}
    for item in items:
        confusion[item.human][item.judge] += 1
    decided_pairs = [(i.human, i.judge) for i in items if i.judge != "uncertain"]
    human_fail = confusion["fail"]["pass"] + confusion["fail"]["fail"]
    human_pass = confusion["pass"]["pass"] + confusion["pass"]["fail"]
    repeats = [(i.judge, i.judge_repeat) for i in items if i.judge_repeat is not None]

    agreement = _rate(sum(1 for h, j in decided_pairs if h == j), len(decided_pairs))
    kappa = cohen_kappa(decided_pairs)
    false_pass = _rate(confusion["fail"]["pass"], human_fail)
    false_fail = _rate(confusion["pass"]["fail"], human_pass)
    abstention = _rate(sum(1 for i in items if i.judge == "uncertain"), len(items))
    consistency = _rate(sum(1 for a, b in repeats if a == b), len(repeats))

    failures: list[str] = []
    if len(decided_pairs) < thresholds.min_items:
        failures.append(
            f"{len(decided_pairs)} decided items; at least {thresholds.min_items} are needed"
        )
    if kappa is None or kappa < thresholds.min_kappa:
        failures.append(f"kappa {_fmt(kappa)} is below {thresholds.min_kappa}")
    if false_pass is None or false_pass > thresholds.max_false_pass_rate:
        failures.append(
            f"false pass rate {_fmt(false_pass)} exceeds {thresholds.max_false_pass_rate}"
            if false_pass is not None
            else "no human-failed items, so the false pass rate is unmeasured"
        )
    if false_fail is None or false_fail > thresholds.max_false_fail_rate:
        failures.append(
            f"false fail rate {_fmt(false_fail)} exceeds {thresholds.max_false_fail_rate}"
            if false_fail is not None
            else "no human-passed items, so the false fail rate is unmeasured"
        )
    if abstention is not None and abstention > thresholds.max_abstention_rate:
        failures.append(
            f"abstention rate {_fmt(abstention)} exceeds {thresholds.max_abstention_rate}"
        )
    if consistency is None:
        failures.append("no repeated judge runs, so consistency is unmeasured")
    elif consistency < thresholds.min_consistency:
        failures.append(f"consistency {_fmt(consistency)} is below {thresholds.min_consistency}")

    return CriterionReport(
        criterion_id=criterion_id,
        items=len(items),
        decided=len(decided_pairs),
        agreement=agreement,
        kappa=kappa,
        false_pass_rate=false_pass,
        false_fail_rate=false_fail,
        abstention_rate=abstention,
        consistency=consistency,
        confusion=confusion,
        failures=tuple(failures),
    )


def validate(
    items: Iterable[LabelledItem],
    criteria: Sequence[str],
    thresholds: Thresholds | None = None,
) -> ValidationReport:
    """Whether the judge may be trusted on every criterion in `criteria`."""
    thresholds = thresholds or Thresholds()
    by_criterion: dict[str, list[LabelledItem]] = {c: [] for c in criteria}
    unknown: set[str] = set()
    for item in items:
        if item.criterion_id in by_criterion:
            by_criterion[item.criterion_id].append(item)
        else:
            unknown.add(item.criterion_id)
    reports = tuple(report_criterion(c, by_criterion[c], thresholds) for c in criteria)
    reasons = [f"{r.criterion_id}: {f}" for r in reports for f in r.failures]
    if unknown:
        reasons.append(f"labels for criteria not in the rubric: {sorted(unknown)}")
    return ValidationReport(validated=not reasons, criteria=reports, reasons=tuple(reasons))


def by_language(
    items: Iterable[LabelledItem],
    criteria: Sequence[str],
    thresholds: Thresholds | None = None,
) -> dict[str, ValidationReport]:
    """The same validation per language.

    A judge can agree with people in Hindi and not in Tamil. Each language is
    held to the same bars, so a language with too few labels reports that
    rather than borrowing the pooled result. Items with no language are
    grouped under `unknown`.
    """
    grouped: dict[str, list[LabelledItem]] = {}
    for item in items:
        grouped.setdefault(item.language or "unknown", []).append(item)
    return {lang: validate(group, criteria, thresholds) for lang, group in sorted(grouped.items())}


def items_from_rows(rows: Iterable[Mapping[str, str]]) -> list[LabelledItem]:
    """Parse rows with item_id, criterion_id, human, judge and optional
    judge_repeat and language."""
    return [
        LabelledItem(
            item_id=row["item_id"],
            criterion_id=row["criterion_id"],
            human=row["human"].strip().lower(),
            judge=row["judge"].strip().lower(),
            judge_repeat=(row.get("judge_repeat") or "").strip().lower() or None,
            language=(row.get("language") or "").strip() or None,
        )
        for row in rows
    ]


def _fmt(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.2f}"


__all__ = [
    "LABELS",
    "CriterionReport",
    "LabelledItem",
    "Thresholds",
    "ValidationReport",
    "by_language",
    "cohen_kappa",
    "items_from_rows",
    "report_criterion",
    "validate",
]
