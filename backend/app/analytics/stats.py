"""Small-sample statistics, chosen so that a handful of runs cannot overclaim.

Benchmark comparisons here are usually a few runs a side, where the normal
approximation is wrong and a difference of one run can look like a trend.
So: a Wilson score interval for a pass rate (well-behaved at 0, 1 and small
n), and Fisher's exact test for a difference between two pass rates (exact
at any n). Both are stdlib-only and checked against published values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z_95 = 1.959963984540054
ALPHA = 0.05
MIN_SAMPLE_PER_GROUP = 5
"""Below this many decided runs in either group, no difference is called
significant whatever the p-value says: an exact test on three runs can reach
p < 0.05 only in the most extreme split, and a reader would take that as a
general finding."""


@dataclass(frozen=True, slots=True)
class Proportion:
    successes: int
    n: int
    rate: float | None
    low: float | None
    high: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "successes": self.successes,
            "n": self.n,
            "rate": self.rate,
            "ci95_low": self.low,
            "ci95_high": self.high,
            "interval": "wilson",
        }


def wilson(successes: int, n: int, *, z: float = Z_95) -> Proportion:
    """Wilson score interval. `None` throughout when `n` is 0."""
    if n < 0 or not 0 <= successes <= n:
        raise ValueError("need 0 <= successes <= n")
    if n == 0:
        return Proportion(successes, 0, None, None, None)
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return Proportion(
        successes,
        n,
        round(p, 6),
        round(max(0.0, centre - margin), 6),
        round(min(1.0, centre + margin), 6),
    )


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided p-value for the 2x2 table [[a, b], [c, d]].

    Sums the hypergeometric probabilities of every table with the same margins
    that is no more likely than the observed one (the conventional two-sided
    definition, as in R's fisher.test), with a small relative tolerance so
    floating-point ties are counted as ties.
    """
    if min(a, b, c, d) < 0:
        raise ValueError("counts must be non-negative")
    row1, col1, n = a + b, a + c, a + b + c + d
    if n == 0:
        return 1.0

    def probability(x: int) -> float:
        return math.comb(col1, x) * math.comb(n - col1, row1 - x) / math.comb(n, row1)

    observed = probability(a)
    low, high = max(0, row1 + col1 - n), min(row1, col1)
    total = sum(p for x in range(low, high + 1) if (p := probability(x)) <= observed * (1 + 1e-7))
    return min(1.0, total)


def nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(percentile / 100 * len(ordered)), 1) - 1]


__all__ = [
    "ALPHA",
    "MIN_SAMPLE_PER_GROUP",
    "Proportion",
    "fisher_exact",
    "nearest_rank",
    "wilson",
]
