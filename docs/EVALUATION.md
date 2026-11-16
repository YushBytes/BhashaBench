# Evaluation methodology (Phase 11)

How BhashaBench turns a run's stored evidence into results, and what those
results can and cannot tell you. The code is `backend/app/evaluation/`; the
metric definitions served by the API are `registry.py`, verbatim.

## Principles

- **Deterministic first.** Every metric here is computed from stored evidence
  by a fixed formula. Re-running an evaluation on the same evidence with the
  same `evaluator_version` gives the same numbers.
- **Missing is not zero.** A metric whose evidence is absent is `null` or
  "not evaluated", with the reason. An unfinished run, or one that ended for
  a reason that says nothing about the bot, is *undetermined*, never failed.
- **No composite score.** Task completion, phrase compliance, error rates and
  latency are different quantities. A weighted sum would let a fast bot that
  fails the task outrank a slow one that succeeds. The verdict is instead a
  conjunction of named pass/fail criteria, each with its reasoning.
- **Our faults are not the bot's.** Outcomes in `OUR_FAULT_OUTCOMES`
  (`provider_error`, `audio_validation_failed`, `external_bot_unavailable`,
  `abandoned`) and `cancelled` make task completion undetermined, and the
  transcription failure rate is reported but never part of the bot's verdict.

## Text normalisation — `bb-norm-1`

Applied identically to reference and hypothesis before any comparison:

1. Unicode NFC (canonically equivalent spellings, such as a precomposed nukta
   letter and base plus nukta, compare equal). Not NFKC.
2. Remove ZWJ and ZWNJ, except for Urdu, where ZWNJ separates morphemes.
3. Case-fold (Latin only — relevant to code-mixed speech).
4. Punctuation and symbols, including the danda and double danda, to spaces.
5. Every Unicode decimal digit to its ASCII value (४ and 4 are one token).
6. Collapse whitespace.

**Not applied**, deliberately: number words to digits ("four" ≠ "4"), and
transliteration (Latin script for a Devanagari reference is wrong). Both
would hide genuine recognition errors.

## Error rates

WER and CER are `(substitutions + deletions + insertions) / reference length`,
from a deterministic minimum-edit alignment. Every result carries the counts,
both lengths and the normalisation version, so it can be recomputed by hand.
WER can exceed 1. An empty reference has no rate (`null`).

CER counts grapheme clusters — a base character and its combining marks — so a
wrong vowel sign is one error, as a reader perceives it. Conjuncts joined by a
virama are not merged into aksharas; that approximation is stated.

Error rates need **reviewed reference transcripts**. None ship with the
fixtures, and no rate is ever estimated without one.

## Metrics

| Metric | Better | Missing data |
|--------|--------|--------------|
| `task_completion` | pass | undetermined when unfinished or ended by our fault |
| `required_phrases` | pass | not evaluated when none declared |
| `forbidden_phrases` | pass | not evaluated when none declared |
| `expected_outcome_keyword_coverage` | higher | not evaluated when none declared; never in the verdict |
| `wer`, `cer` | lower | null without reviewed references |
| `bot_response_latency_ms` | lower | null without measured latencies |
| `transcription_failure_rate` | lower | not evaluated in text modes; never in the verdict |

Full definitions, formulas, evidence and limitations: `registry.py`, or
`GET /api/v1/evaluation/metrics`.
