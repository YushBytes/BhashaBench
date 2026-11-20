# Caller phrase review

The deterministic caller speaks from fixed phrase tables
(`backend/app/caller/providers/deterministic.py`). A table is either
**reviewed** (a fluent speaker has checked it) or **unreviewed**
(machine-written). Both run. Every run records which in
`caller_phrase_review`, and the run page shows an unreviewed table as a
caution: a bot that misunderstands an unreviewed phrase may be failing the
caller, not the language.

| Language | Status | Since |
|----------|--------|-------|
| Tamil (`ta-IN`) | reviewed | Phase 6 |
| Hindi (`hi-IN`) | reviewed | Phase 6 |
| English (`en-IN`) | reviewed | Phase 6 |
| Bengali (`bn-IN`) | **unreviewed** | 2026-11-20 |
| Marathi (`mr-IN`) | **unreviewed** | 2026-11-20 |
| Telugu (`te-IN`) | **unreviewed** | 2026-11-20 |

No fluent speaker has reviewed the Bengali, Marathi or Telugu tables. They
were written to be plain, polite and neutral in register, but that is a
claim about intent, not a validation.

## What a table holds

Ten slots, the only ones the rules fill. `{identity}` and `{objective}` come
from the scenario's persona and goal; `{fact}` is always one of the
scenario's `known_facts`, so a phrase can never invent a fact. Complaints,
transactions and appointments are not separate phrases: they are what a
scenario's objective and facts say. Interruptions are audio (caller
barge-in on a streaming bot), not wording.

| Slot | Used when | English reference |
|------|-----------|-------------------|
| `opening` | first turn | Hello, I am {identity}. {objective} |
| `ask` | the caller asks for information | Could you tell me about that, please? |
| `provide_fact` | the bot asks for something the caller knows | Yes, it is {fact}. |
| `clarify` | the bot's reply cannot be used | Sorry, I did not quite follow that. Could you explain it more clearly? |
| `repeat_request` | the bot's reply was empty or unclear | Sorry, could you say that again? |
| `correct` | the bot stated a known fact wrongly | No, that is not right. The correct detail is {fact}. |
| `decline_unknown` | the bot asks for something not in the facts | Sorry, I do not know that. |
| `confirm` | reading back what the bot said | Right, so you are saying it is {fact} - is that correct? |
| `close_success` | the goal was reached | Thank you, I have got what I needed. |
| `close_failure` | giving up | All right, thank you. I will try again later. |

## The unreviewed tables, verbatim

`backend/tests/test_caller_phrases.py` fails if a phrase below differs from
the code, so this list is always what the caller actually says.

### Bengali (`bn-IN`)

| Slot | Phrase |
|------|--------|
| `opening` | নমস্কার, আমি {identity}। {objective} |
| `ask` | এ বিষয়ে একটু বলতে পারবেন? |
| `provide_fact` | হ্যাঁ, সেটা {fact}। |
| `clarify` | দুঃখিত, ঠিক বুঝতে পারলাম না। আর একটু পরিষ্কার করে বলবেন? |
| `repeat_request` | দুঃখিত, আর একবার বলবেন? |
| `correct` | না, ওটা ঠিক নয়। সঠিক তথ্য হল {fact}। |
| `decline_unknown` | দুঃখিত, সেটা আমি জানি না। |
| `confirm` | আচ্ছা, আপনি বলছেন সেটা {fact}, তাই তো? |
| `close_success` | ধন্যবাদ, আমার যা দরকার ছিল পেয়ে গেছি। |
| `close_failure` | ঠিক আছে, ধন্যবাদ। আমি পরে আবার চেষ্টা করব। |

### Marathi (`mr-IN`)

| Slot | Phrase |
|------|--------|
| `opening` | नमस्कार, मी {identity}. {objective} |
| `ask` | याबद्दल थोडं सांगू शकाल का? |
| `provide_fact` | हो, ते {fact} आहे. |
| `clarify` | माफ करा, मला नीट समजलं नाही. जरा स्पष्ट सांगाल का? |
| `repeat_request` | माफ करा, पुन्हा एकदा सांगाल का? |
| `correct` | नाही, ते बरोबर नाही. योग्य माहिती {fact} आहे. |
| `decline_unknown` | माफ करा, ते मला माहीत नाही. |
| `confirm` | ठीक आहे, म्हणजे ते {fact} आहे, बरोबर? |
| `close_success` | धन्यवाद, मला हवी असलेली माहिती मिळाली. |
| `close_failure` | ठीक आहे, धन्यवाद. मी नंतर पुन्हा प्रयत्न करेन. |

### Telugu (`te-IN`)

| Slot | Phrase |
|------|--------|
| `opening` | నమస్కారం, నేను {identity}. {objective} |
| `ask` | దాని గురించి కొంచెం చెప్పగలరా? |
| `provide_fact` | అవును, అది {fact}. |
| `clarify` | క్షమించండి, నాకు సరిగ్గా అర్థం కాలేదు. ఇంకొంచెం స్పష్టంగా చెప్పగలరా? |
| `repeat_request` | క్షమించండి, మళ్ళీ ఒకసారి చెప్పగలరా? |
| `correct` | కాదు, అది సరైనది కాదు. సరైన వివరం {fact}. |
| `decline_unknown` | క్షమించండి, అది నాకు తెలియదు. |
| `confirm` | సరే, అది {fact} అని చెబుతున్నారు, అంతేనా? |
| `close_success` | ధన్యవాదాలు, నాకు కావలసిన సమాచారం దొరికింది. |
| `close_failure` | సరే, ధన్యవాదాలు. నేను తర్వాత మళ్ళీ ప్రయత్నిస్తాను. |

## Review sheets

`docs/phrase-review/bn-IN.csv`, `mr-IN.csv` and `te-IN.csv` are the sheets a
reviewer fills in, one row per phrase: the phrase, its English reference, when
it is used, and empty `decision`, `suggested_phrase`, `reviewer`,
`reviewed_on` and `notes` columns. Every row's `status` is `pending`. They
are generated from the code (`python scripts/phrase_review_sheet.py`) and a
test fails if they go stale.

**Mechanical checks done (2026-11-20, no fluent speaker involved):** every
slot filled with exactly the placeholders its rule supplies; each table
entirely in its own script (the shared danda aside); no two slots in a table
identical; every phrase except the opening ends as a sentence. None of this
says the phrases are natural or correct. **No reviewer has been supplied, so
no phrase is recorded as reviewed.**

## How a fluent speaker reviews a table

1. For each phrase, check against the English reference and the slot's use:
   - Does it mean the same thing, and would a caller on a helpline say it?
   - Is the register polite and neutral, neither stiff nor overly casual?
   - Does the sentence still read correctly with a number, a name or a date
     put in place of `{fact}`, and with an English `{identity}`?
   - Is it gender-neutral, or does it assume the caller's gender? (The
     Hindi table's "कोशिश करूँगा" is masculine; note any such choice.)
   - Is the script correct (no mixed scripts, correct conjuncts and vowel
     signs)?
2. Edit the phrase in `deterministic.py` and in the table above together.
3. When every phrase is accepted, move the language from
   `_UNREVIEWED_LANGUAGES` to `_REVIEWED_LANGUAGES`, change its row in the
   status table to "reviewed" with the date, and record who reviewed it in
   the commit message. That move is the sign-off, and nothing else is.
4. Run `pytest backend/tests/test_caller_phrases.py`.

Reviewing the bot-side keyword lexicons in `backend/app/caller/analysis.py`
(how the caller recognises a refusal, a confirmation or a question) is a
separate check, and those lexicons are not claimed as reviewed either.
