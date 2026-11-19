"""Writing-system segmentation of a transcript: observable code-switching.

Indian callers switch languages inside a sentence - "Samba season-ல மழையால
பயிர் சேதமாச்சு, crop insurance claim போட்டிருக்கேன்". What a transcript can
show deterministically is the *script* of each word, and where it changes.
This module splits text into runs of one script (ISO 15924 codes: `Taml`,
`Latn`, `Deva`, ...) and counts the switches between them.

**Script is not language, and this says so.** Hindi, Marathi and Nepali all
use Devanagari, so a Hindi-Marathi switch is invisible here; romanised Hindi
("aapka policy number") is `Latn`, indistinguishable from English; and a
transcriber that writes an English loanword in Tamil script hides that
switch. What is measured is script switching, named as such, and every
consumer repeats the caveat. It is still the most useful deterministic
signal available without a language-identification model, which this
project does not have: it shows whether code-mixed speech survived
transcription in the form it was spoken, and lets error rates be split by
script.

Words with no letters (numbers, punctuation) belong to no script and join
the segment they sit in.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass

# Unicode block ranges for the scripts of the language catalogue, plus Latin.
_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x097F, "Deva"),
    (0x0980, 0x09FF, "Beng"),
    (0x0A00, 0x0A7F, "Guru"),
    (0x0A80, 0x0AFF, "Gujr"),
    (0x0B00, 0x0B7F, "Orya"),
    (0x0B80, 0x0BFF, "Taml"),
    (0x0C00, 0x0C7F, "Telu"),
    (0x0C80, 0x0CFF, "Knda"),
    (0x0D00, 0x0D7F, "Mlym"),
    (0x0600, 0x06FF, "Arab"),
    (0x0750, 0x077F, "Arab"),
    (0xA8E0, 0xA8FF, "Deva"),
)


def char_script(char: str) -> str | None:
    """ISO 15924 code of one character, or None for a non-letter."""
    point = ord(char)
    for low, high, code in _RANGES:
        if low <= point <= high:
            return code
    if char.isalpha() and unicodedata.name(char, "").startswith("LATIN"):
        return "Latn"
    return None


def word_script(word: str) -> str | None:
    """The script most of `word`'s letters are in; None if it has no letters."""
    counts = Counter(code for code in map(char_script, word) if code is not None)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


@dataclass(frozen=True, slots=True)
class Segment:
    script: str
    text: str
    words: int


def segments(text: str) -> list[Segment]:
    """Consecutive words of one script, in order. Empty text gives []."""
    out: list[tuple[str, list[str]]] = []
    pending: list[str] = []  # script-less words before the first lettered one
    for word in text.split():
        code = word_script(word)
        if code is None:
            if out:
                out[-1][1].append(word)
            else:
                pending.append(word)
            continue
        if out and out[-1][0] == code:
            out[-1][1].append(word)
        else:
            out.append((code, [*pending, word] if not out else [word]))
            pending = []
    return [Segment(code, " ".join(words), len(words)) for code, words in out]


def switches(text: str) -> int:
    """How many times the script changes. 0 for single-script or empty text."""
    return max(len(segments(text)) - 1, 0)


def words_in_script(text: str, script: str) -> str:
    """Only the words of `text` written in `script`, in order, space-joined."""
    return " ".join(word for word in text.split() if word_script(word) == script)


def summary(texts: list[str]) -> dict[str, object]:
    """Script mixing over several utterances, for an evaluation metric."""
    nonempty = [t for t in texts if t and t.strip()]
    per_text = [segments(t) for t in nonempty]
    words: Counter[str] = Counter()
    for segs in per_text:
        for seg in segs:
            words[seg.script] += seg.words
    return {
        "turns": len(nonempty),
        "turns_with_switching": sum(1 for segs in per_text if len(segs) > 1),
        "switches": sum(max(len(segs) - 1, 0) for segs in per_text),
        "words_by_script": dict(sorted(words.items())),
    }


__all__ = [
    "Segment",
    "char_script",
    "segments",
    "summary",
    "switches",
    "word_script",
    "words_in_script",
]
