"""Text normalisation and tokenisation for scoring transcripts.

Normalisation is where an error-rate metric can quietly lie: fold too much
and genuine recognition errors vanish, fold too little and formatting
differences are scored as mistakes. So every step is named, versioned, and
applied identically to the reference and the hypothesis, and anything not
listed here is **not** folded.

Applied, in order (`NORMALISATION_VERSION` names this exact list):

1. Unicode NFC. Canonically equivalent spellings - a Devanagari letter with a
   precomposed nukta and the same letter as base plus U+093C - compare equal.
   NFC, not NFKC: compatibility folding would also rewrite ligatures and
   width variants in ways that can change a word.
2. Remove zero-width joiner and non-joiner (U+200D, U+200C). In Indic scripts
   they select a rendering (a half form, an explicit virama) without changing
   the word, and recognisers emit them inconsistently. **Not removed for Urdu
   (`ur-*`)**, where ZWNJ separates morphemes.
3. Case-fold. Affects Latin script only; Indic scripts have no case. Matters
   for code-mixed speech, where "OTP" and "otp" are the same word.
4. Punctuation to spaces: Unicode categories P* and S*, which includes the
   danda (U+0964) and double danda (U+0965).
5. Digits: every Unicode decimal digit (Devanagari ४, Tamil ௪, ...) becomes its
   ASCII value, so a numeral written in either script is one token. Number
   **words** ("four", "चार") are not converted to digits: doing that well needs
   per-language number grammars, and doing it badly would hide errors. A
   reference written in words scored against a hypothesis in digits is
   therefore an error, and the metric's limitations say so.
6. Collapse whitespace.

Not applied: transliteration between scripts. A hypothesis in Latin script
for a Hindi reference in Devanagari scores as fully wrong, because the
recogniser did produce the wrong script.
"""

from __future__ import annotations

import unicodedata

NORMALISATION_VERSION = "bb-norm-1"
_ZERO_WIDTH = {"‌", "‍"}


def normalise(text: str, *, language: str | None = None) -> str:
    """Apply the steps above. `language` is a BCP 47 tag, used only for Urdu."""
    value = unicodedata.normalize("NFC", text)
    if not (language or "").lower().startswith("ur"):
        value = "".join(ch for ch in value if ch not in _ZERO_WIDTH)
    value = value.casefold()
    out: list[str] = []
    for ch in value:
        category = unicodedata.category(ch)
        if category[0] in {"P", "S"}:
            out.append(" ")
        elif category == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return " ".join("".join(out).split())


def words(text: str, *, language: str | None = None) -> list[str]:
    """Whitespace tokens of the normalised text.

    Whitespace segmentation is correct for every catalogue language: all of
    them separate words with spaces. It would be wrong for Thai or Chinese,
    which are not in the catalogue.
    """
    return normalise(text, language=language).split()


def graphemes(text: str, *, language: str | None = None) -> list[str]:
    """Approximate user-perceived characters of the normalised text, without spaces.

    A cluster is a base character followed by its combining marks (categories
    Mn, Mc, Me), so a consonant and its vowel sign are one unit, as a reader
    sees them. Conjuncts joined by a virama are **not** merged into one
    akshara: segmenting aksharas correctly needs script-specific rules, and
    this approximation is stated rather than hidden. Character error rate is
    computed over these clusters, not over raw code points, which would count
    a wrong vowel sign and a wrong consonant differently for no reason.
    """
    clusters: list[str] = []
    for ch in normalise(text, language=language).replace(" ", ""):
        if clusters and unicodedata.category(ch) in {"Mn", "Mc", "Me"}:
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return clusters


__all__ = ["NORMALISATION_VERSION", "graphemes", "normalise", "words"]
