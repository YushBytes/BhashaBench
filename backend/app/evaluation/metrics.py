"""Error-rate metrics over normalised text, with their full working shown.

A score without its counts cannot be checked, so every result carries the
substitutions, deletions and insertions behind it, the lengths, and the
normalisation version - enough to recompute it by hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

from app.evaluation.text import NORMALISATION_VERSION, graphemes, words


@dataclass(frozen=True, slots=True)
class Alignment:
    substitutions: int
    deletions: int
    insertions: int
    hits: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions


def align(reference: Sequence[str], hypothesis: Sequence[str]) -> Alignment:
    """Minimum-edit alignment, Levenshtein with unit costs.

    Ties are broken toward hits, then substitutions, then deletions, then
    insertions, so the reported breakdown is deterministic. O(n*m) time and
    O(m) memory per row of back-pointers kept as counts.
    """
    m = len(hypothesis)
    # Each cell: (cost, subs, dels, ins, hits) for the best path to it.
    previous = [(j, 0, 0, j, 0) for j in range(m + 1)]
    for i in range(1, len(reference) + 1):
        current = [(i, 0, i, 0, 0)]
        for j in range(1, m + 1):
            same = reference[i - 1] == hypothesis[j - 1]
            diag = previous[j - 1]
            options = [
                (diag[0] + (0 if same else 1), 0 if same else 1, diag, "diag", same),
                (previous[j][0] + 1, 2, previous[j], "del", False),
                (current[j - 1][0] + 1, 3, current[j - 1], "ins", False),
            ]
            cost, _, base, kind, hit = min(options, key=lambda o: (o[0], o[1]))
            _, s, d, n, h = base
            if kind == "diag":
                current.append((cost, s + (0 if hit else 1), d, n, h + (1 if hit else 0)))
            elif kind == "del":
                current.append((cost, s, d + 1, n, h))
            else:
                current.append((cost, s, d, n + 1, h))
        previous = current
    _, s, d, n, h = previous[m]
    return Alignment(substitutions=s, deletions=d, insertions=n, hits=h)


@dataclass(frozen=True, slots=True)
class ErrorRate:
    """WER or CER with its working.

    `value` is `None` when the reference is empty: an error rate divides by
    the reference length, and inventing 0 or 1 there would be a measurement
    of nothing.
    """

    metric: str
    value: float | None
    substitutions: int
    deletions: int
    insertions: int
    hits: int
    reference_length: int
    hypothesis_length: int
    normalisation: str = NORMALISATION_VERSION

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _rate(metric: str, reference: list[str], hypothesis: list[str]) -> ErrorRate:
    alignment = align(reference, hypothesis)
    value = round(alignment.errors / len(reference), 6) if reference else None
    return ErrorRate(
        metric=metric,
        value=value,
        substitutions=alignment.substitutions,
        deletions=alignment.deletions,
        insertions=alignment.insertions,
        hits=alignment.hits,
        reference_length=len(reference),
        hypothesis_length=len(hypothesis),
    )


def word_error_rate(reference: str, hypothesis: str, *, language: str | None = None) -> ErrorRate:
    """(S + D + I) / N over normalised words. Can exceed 1 when the
    hypothesis inserts more words than the reference holds."""
    return _rate("wer", words(reference, language=language), words(hypothesis, language=language))


def character_error_rate(
    reference: str, hypothesis: str, *, language: str | None = None
) -> ErrorRate:
    """(S + D + I) / N over grapheme clusters, spaces excluded."""
    return _rate(
        "cer", graphemes(reference, language=language), graphemes(hypothesis, language=language)
    )


__all__ = ["Alignment", "ErrorRate", "align", "character_error_rate", "word_error_rate"]
