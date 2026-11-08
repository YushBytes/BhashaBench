"""Reading what the bot actually said.

This is where a deterministic caller earns the word "responsive". The rule
engine in `providers/deterministic.py` only picks between branches; this module
decides which branches are open, by extracting signals from the transcript.

§6C asks for something better than substring matching, and the reason is
concrete. A Prisma transcript of an Indian-language call is not clean text: it
arrives in the scenario's script, digits may come back as Tamil numerals or as
English words, an account number spoken "zero four seven, one eight eight
three" may be transcribed with spaces, hyphens or nothing between the groups,
and punctuation is unreliable. `"0471883" in transcript` fails on all of those
while a human would have understood perfectly.

So the approach is:

* **Normalise before comparing.** Unicode NFKC, case folding, Indic digits
  mapped to ASCII, punctuation stripped, whitespace collapsed.
* **Match digit sequences separately from words.** A reference number is
  compared as a digit string with all separators removed, so grouping cannot
  defeat it.
* **Use per-language keyword lexicons**, not English keywords applied to Tamil
  text. A Tamil bot asking for a number does not use the word "number"... except
  that in practice it very often does, because that is exactly the
  code-switching this project exists to measure. Both are covered.
* **Report signals, not a single verdict.** Several can be true at once - a bot
  can confirm one thing and ask for another in the same breath - and a caller
  that collapsed that to one label would lose the half it did not pick.

Everything here is pure and synchronous, so each signal is directly testable
against a transcript string.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Indic digit ranges mapped to ASCII. Covers the scripts in the BhashaBench
# catalogue; a digit outside these is left alone rather than guessed at.
_DIGIT_MAP = {
    # Devanagari (Hindi, Marathi)
    **{chr(0x0966 + n): str(n) for n in range(10)},
    # Bengali / Assamese
    **{chr(0x09E6 + n): str(n) for n in range(10)},
    # Gurmukhi (Punjabi)
    **{chr(0x0A66 + n): str(n) for n in range(10)},
    # Gujarati
    **{chr(0x0AE6 + n): str(n) for n in range(10)},
    # Oriya
    **{chr(0x0B66 + n): str(n) for n in range(10)},
    # Tamil
    **{chr(0x0BE6 + n): str(n) for n in range(10)},
    # Telugu
    **{chr(0x0C66 + n): str(n) for n in range(10)},
    # Kannada
    **{chr(0x0CE6 + n): str(n) for n in range(10)},
    # Malayalam
    **{chr(0x0D66 + n): str(n) for n in range(10)},
}

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_DIGIT_RUN = re.compile(r"\d[\d\s\-/]*\d|\d")

# English number words, so "four seven one" is recognised as digits. Stops at
# nine deliberately: this is for reading out reference numbers digit by digit,
# which is how they are actually spoken, not for parsing arbitrary quantities.
_NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "double": "",
    "triple": "",  # consumed; the repeat is handled by context
}


def normalise(text: str) -> str:
    """Fold a transcript into a comparable form.

    NFKC first, so a composed and a decomposed Tamil vowel sign compare equal
    and full-width Latin digits become ordinary ones. Then Indic digits to
    ASCII, case folding, punctuation out, whitespace collapsed.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = "".join(_DIGIT_MAP.get(ch, ch) for ch in folded)
    folded = folded.casefold()
    folded = _PUNCTUATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def digit_sequences(text: str) -> tuple[str, ...]:
    """Every digit run in `text`, separators removed.

    Both the raw runs and a spoken-digits reconstruction are returned, so
    "0471883", "047 1883" and "zero four seven one eight eight three" all
    produce the comparable form `0471883`.
    """
    normalised = normalise(text)
    found: list[str] = []

    for match in _DIGIT_RUN.finditer(normalised):
        compact = re.sub(r"\D", "", match.group())
        if compact:
            found.append(compact)

    # Runs of English digit words, collapsed into one sequence each.
    spoken: list[str] = []
    for token in normalised.split():
        mapped = _NUMBER_WORDS.get(token)
        if mapped is not None:
            spoken.append(mapped)
        elif spoken:
            joined = "".join(spoken)
            if joined:
                found.append(joined)
            spoken = []
    if spoken and (joined := "".join(spoken)):
        found.append(joined)

    # Concatenate adjacent short runs too: a bot reading "047 1883" produces
    # two runs, and the caller needs to recognise the whole.
    if len(found) > 1:
        found.append("".join(found))

    return tuple(dict.fromkeys(found))


def mentions_value(text: str, value: str) -> bool:
    """Whether `text` contains `value`, compared appropriately for its shape.

    A value that is all digits is compared as a digit sequence, so grouping and
    spelling-out cannot defeat it. Anything else is compared as whole words
    after normalisation, so "Meena" does not match inside "Meenakshi".
    """
    target = normalise(value)
    if not target:
        return False

    compact_target = re.sub(r"\D", "", target)
    if compact_target and not re.search(r"[^\d\s]", target):
        return any(compact_target in seq for seq in digit_sequences(text))

    haystack = f" {normalise(text)} "
    return f" {target} " in haystack


# -- Keyword lexicons -------------------------------------------------------
#
# Per signal, per language, plus an English set that applies everywhere -
# because a Tamil or Hindi bot routinely says "reference number", "status" and
# "confirm" in English. That is the code-switching this project measures, not
# an accident, so matching only the regional form would miss the common case.

_ASK_FOR_IDENTIFIER = {
    "en": (
        "reference number",
        "claim number",
        "policy number",
        "application number",
        "account number",
        "consumer number",
        "order number",
        "registered number",
        "may i have",
        "can you provide",
        "could you tell me your",
        "please provide",
        "what is your",
        "share your",
        "confirm your",
    ),
    "ta": ("எண்", "என்ன", "சொல்லுங்க", "தெரியுமா", "கொடுங்க"),
    "hi": ("नंबर", "बताइए", "बताएं", "क्या है", "दीजिए"),
    "bn": ("নম্বর", "বলুন", "কি"),
    "te": ("నంబర్", "చెప్పండి", "ఏమిటి"),
    "mr": ("नंबर", "सांगा", "काय"),
    "kn": ("ಸಂಖ್ಯೆ", "ಹೇಳಿ", "ಏನು"),
    "ml": ("നമ്പർ", "പറയുക", "എന്ത്"),
    "gu": ("નંબર", "કહો", "શું"),
    "pa": ("ਨੰਬਰ", "ਦੱਸੋ", "ਕੀ"),
}

_CONFIRMATION = {
    "en": (
        "confirmed",
        "has been confirmed",
        "approved",
        "successful",
        "completed",
        "thank you for confirming",
        "that is correct",
        "yes that is right",
        "i have updated",
        "your request has been",
    ),
    "ta": ("உறுதி", "சரி", "முடிந்த", "ஆமாம்"),
    "hi": ("पुष्टि", "सही", "हो गया", "स्वीकृत"),
    "bn": ("নিশ্চিত", "ঠিক", "হয়ে গেছে"),
    "te": ("నిర్ధారణ", "సరైన", "పూర్తి"),
    "mr": ("पुष्टी", "बरोबर", "झाले"),
    "kn": ("ದೃಢ", "ಸರಿ", "ಆಗಿದೆ"),
    "ml": ("സ്ഥിരീകരി", "ശരി", "പൂർത്തി"),
    "gu": ("પુષ્ટિ", "સાચું", "થઈ ગયું"),
    "pa": ("ਪੁਸ਼ਟੀ", "ਸਹੀ", "ਹੋ ਗਿਆ"),
}

_REFUSAL = {
    "en": (
        "i cannot",
        "i can not",
        "i am unable",
        "not able to",
        "cannot help",
        "no information",
        "not available",
        "do not have access",
        "unable to find",
        "no record",
        "cannot disclose",
        "not permitted",
        "i do not know",
        "system is down",
        "try again later",
        "contact our branch",
    ),
    "ta": ("முடியாது", "தெரியவில்லை", "இல்லை"),
    "hi": ("नहीं कर सकता", "उपलब्ध नहीं", "जानकारी नहीं", "पता नहीं"),
    "bn": ("পারছি না", "নেই", "জানি না"),
    "te": ("సాధ్యం కాదు", "లేదు", "తెలియదు"),
    "mr": ("शकत नाही", "नाही", "माहिती नाही"),
    "kn": ("ಸಾಧ್ಯವಿಲ್ಲ", "ಇಲ್ಲ", "ಗೊತ್ತಿಲ್ಲ"),
    "ml": ("കഴിയില്ല", "ഇല്ല", "അറിയില്ല"),
    "gu": ("શકતો નથી", "નથી", "ખબર નથી"),
    "pa": ("ਨਹੀਂ ਸਕਦਾ", "ਨਹੀਂ", "ਪਤਾ ਨਹੀਂ"),
}

_REPEAT_REQUEST = {
    "en": (
        "could you repeat",
        "say that again",
        "i did not catch",
        "i didnt catch",
        "pardon",
        "sorry what",
        "come again",
        "one more time",
    ),
    "ta": ("மறுபடி", "திரும்ப", "புரியவில்லை"),
    "hi": ("दोहराइए", "फिर से", "समझ नहीं"),
    "bn": ("আবার বলুন", "বুঝতে পারিনি"),
    "te": ("మళ్ళీ", "అర్థం కాలేదు"),
    "mr": ("पुन्हा", "समजले नाही"),
    "kn": ("ಮತ್ತೆ", "ಅರ್ಥವಾಗಿಲ್ಲ"),
    "ml": ("വീണ്ടും", "മനസ്സിലായില്ല"),
    "gu": ("ફરીથી", "સમજ્યો નથી"),
    "pa": ("ਦੁਬਾਰਾ", "ਸਮਝ ਨਹੀਂ"),
}

_QUESTION_MARKERS = {
    "en": (
        "what",
        "which",
        "when",
        "where",
        "who",
        "how",
        "can you",
        "could you",
        "do you",
        "may i",
    ),
    "ta": ("என்ன", "எது", "எப்போது", "எங்கே", "யார்", "எப்படி", "ஆ"),
    "hi": ("क्या", "कौन", "कब", "कहाँ", "कैसे", "कितना"),
    "bn": ("কি", "কে", "কখন", "কোথায়", "কেমন"),
    "te": ("ఏమిటి", "ఎవరు", "ఎప్పుడు", "ఎక్కడ", "ఎలా"),
    "mr": ("काय", "कोण", "कधी", "कुठे", "कसे"),
    "kn": ("ಏನು", "ಯಾರು", "ಯಾವಾಗ", "ಎಲ್ಲಿ", "ಹೇಗೆ"),
    "ml": ("എന്ത്", "ആര്", "എപ്പോൾ", "എവിടെ", "എങ്ങനെ"),
    "gu": ("શું", "કોણ", "ક્યારે", "ક્યાં", "કેવી"),
    "pa": ("ਕੀ", "ਕੌਣ", "ਕਦੋਂ", "ਕਿੱਥੇ", "ਕਿਵੇਂ"),
}


def _lexicon(table: dict[str, tuple[str, ...]], language: str) -> tuple[str, ...]:
    """The phrases for `language`, always including the English set.

    English is unioned in rather than used as a fallback, because a Tamil bot
    saying "reference number" mid-sentence is the normal case here.
    """
    subtag = language.split("-")[0].casefold()
    return tuple(table.get("en", ())) + tuple(table.get(subtag, ()))


def _contains_any(text: str, phrases: tuple[str, ...]) -> tuple[str, ...]:
    """Which of `phrases` appear in `text`, after normalisation.

    Non-Latin phrases are matched as substrings: Indic scripts are written
    without spaces between a stem and its suffixes, so a word-boundary match
    would miss the inflected forms a bot actually produces.
    """
    normalised = normalise(text)
    padded = f" {normalised} "
    hits: list[str] = []
    for phrase in phrases:
        target = normalise(phrase)
        if not target:
            continue
        is_latin = target.isascii()
        found = (
            (f" {target} " in padded) if is_latin and " " not in target else (target in normalised)
        )
        if found:
            hits.append(phrase)
    return tuple(hits)


@dataclass(frozen=True, slots=True)
class TranscriptSignals:
    """What could be established about one bot utterance.

    Several flags can hold simultaneously - a bot can confirm a name and ask
    for a number in one sentence - which is why this is a set of signals rather
    than a single classification.
    """

    raw: str
    normalised: str
    is_empty: bool
    """No usable words. Either silence or a transcription that produced nothing."""
    asks_question: bool
    asks_for_identifier: bool
    """The bot wants a reference, account, policy or claim number."""
    confirms: bool
    refuses: bool
    """The bot declined, or said it has no information."""
    requests_repeat: bool
    """The bot did not understand the caller."""
    facts_echoed: tuple[str, ...] = field(default=())
    """Known-fact keys whose value appears in the transcript."""
    facts_contradicted: tuple[str, ...] = field(default=())
    """Known-fact keys the bot stated a *different* value for.

    Only for digit-shaped facts, where "different" is decidable. Claiming a
    contradiction on free text would mean guessing at paraphrase.
    """
    matched_phrases: tuple[str, ...] = field(default=())
    digit_sequences: tuple[str, ...] = field(default=())

    @property
    def is_usable(self) -> bool:
        """Whether the caller got something it can act on."""
        return not self.is_empty and not self.requests_repeat


def analyse(
    transcript: str | None, *, language: str, known_facts: dict[str, str] | None = None
) -> TranscriptSignals:
    """Extract signals from one bot utterance.

    `transcript` may be `None` (no bot turn yet) or empty (transcription
    produced no words). Both yield `is_empty`, because the caller's response to
    silence and to an unintelligible answer is the same: ask again.
    """
    raw = transcript or ""
    normalised = normalise(raw)
    facts = known_facts or {}

    if not normalised:
        return TranscriptSignals(
            raw=raw,
            normalised="",
            is_empty=True,
            asks_question=False,
            asks_for_identifier=False,
            confirms=False,
            refuses=False,
            requests_repeat=False,
        )

    identifier_hits = _contains_any(raw, _lexicon(_ASK_FOR_IDENTIFIER, language))
    confirm_hits = _contains_any(raw, _lexicon(_CONFIRMATION, language))
    refuse_hits = _contains_any(raw, _lexicon(_REFUSAL, language))
    repeat_hits = _contains_any(raw, _lexicon(_REPEAT_REQUEST, language))
    question_hits = _contains_any(raw, _lexicon(_QUESTION_MARKERS, language))

    sequences = digit_sequences(raw)

    echoed: list[str] = []
    contradicted: list[str] = []
    for key, value in facts.items():
        if mentions_value(raw, value):
            echoed.append(key)
            continue
        # A contradiction is only decidable for digit-shaped facts: if the bot
        # quoted *a* number where this fact is a number, and it is not this
        # one, it has the wrong value. For free text, a different wording is
        # not a different fact, so nothing is claimed.
        compact = re.sub(r"\D", "", normalise(value))
        is_digit_fact = bool(compact) and not re.search(r"[^\d\s]", normalise(value))
        if (
            is_digit_fact
            and sequences
            and all(compact not in seq and seq not in compact for seq in sequences)
        ):
            contradicted.append(key)

    # A refusal wins over a confirmation when both match: "I can confirm we
    # have no record" is a refusal, and treating it as success would score a
    # failed call as a pass.
    refuses = bool(refuse_hits)
    confirms = bool(confirm_hits) and not refuses

    return TranscriptSignals(
        raw=raw,
        normalised=normalised,
        is_empty=False,
        asks_question=bool(question_hits) or raw.strip().endswith("?"),
        asks_for_identifier=bool(identifier_hits),
        confirms=confirms,
        refuses=refuses,
        requests_repeat=bool(repeat_hits),
        facts_echoed=tuple(echoed),
        facts_contradicted=tuple(contradicted),
        matched_phrases=tuple(
            dict.fromkeys(identifier_hits + confirm_hits + refuse_hits + repeat_hits)
        ),
        digit_sequences=sequences,
    )


__all__ = [
    "TranscriptSignals",
    "analyse",
    "digit_sequences",
    "mentions_value",
    "normalise",
]
