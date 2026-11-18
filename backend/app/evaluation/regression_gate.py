"""The CI regression gate (Phase 14): compare a benchmark's verdicts with the
committed baseline, and say exactly what got worse.

A benchmark result maps each scenario to its verdict. Verdicts are ranked
`pass` > `undetermined` > `fail` > `not_runnable`; a scenario whose verdict
ranks below its baseline is a **regression** and fails the build. A scenario
missing from the result is a regression too - a deleted scenario must not
silently improve the score. A scenario new since the baseline is reported,
not failed: it has nothing to regress from.

The benchmark is deterministic - the rule-based caller against the scripted
reference bot - so the same code produces the same verdicts, and any change
is caused by the code, never by chance. It says nothing about a real bot.
"""

from __future__ import annotations

from dataclasses import dataclass

RANK = {"pass": 3, "undetermined": 2, "fail": 1, "not_runnable": 0}


@dataclass(frozen=True, slots=True)
class GateReport:
    regressions: list[str]
    improvements: list[str]
    new: list[str]

    @property
    def passed(self) -> bool:
        return not self.regressions

    def summary(self) -> str:
        lines = [f"REGRESSION {r}" for r in self.regressions]
        lines += [f"improved   {i}" for i in self.improvements]
        lines += [f"new        {n}" for n in self.new]
        return "\n".join(lines) or "no change from the baseline"


def compare(baseline: dict[str, str], current: dict[str, str]) -> GateReport:
    unknown = {v for v in (*baseline.values(), *current.values()) if v not in RANK}
    if unknown:
        raise ValueError(f"unknown verdicts {sorted(unknown)}; expected one of {sorted(RANK)}")
    regressions, improvements = [], []
    for name, before in sorted(baseline.items()):
        after = current.get(name)
        if after is None:
            regressions.append(f"{name}: {before} -> missing from the benchmark")
        elif RANK[after] < RANK[before]:
            regressions.append(f"{name}: {before} -> {after}")
        elif RANK[after] > RANK[before]:
            improvements.append(f"{name}: {before} -> {after}")
    new = [f"{name}: {current[name]}" for name in sorted(set(current) - set(baseline))]
    return GateReport(regressions, improvements, new)


__all__ = ["RANK", "GateReport", "compare"]
