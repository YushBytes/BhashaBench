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

## The verdict

`backend/app/evaluation/evaluator.py`. A conjunction of the criteria that
apply to the run:

| Criterion | Applies when | Fails when |
|-----------|--------------|------------|
| `task_completion` | always | the run finished with a bot outcome other than `goal_achieved` |
| `required_phrases` | the scenario declares some | any is missing from every bot turn |
| `forbidden_phrases` | the scenario declares some | any appears in a bot turn |

- **`pass`** — every applicable criterion passed.
- **`fail`** — at least one failed. Each criterion carries its reason, naming
  the missing or offending phrase.
- **`undetermined`** — the run is unfinished, or ended with `provider_error`,
  `audio_validation_failed`, `external_bot_unavailable`, `abandoned` or
  `cancelled`. Never counted as a failure.

Keyword coverage, error rates, latency and transcription failures are
reported beside the verdict and never move it.

## Code-mixing: script switching — `bb-eval-2`

What a transcript shows of code-mixed speech is the writing system of each
word. `app/evaluation/scripts.py` gives each word the ISO 15924 script of
most of its letters and joins consecutive words of one script into
segments (`Taml → Latn → Taml`). Words without letters join their segment.
Two metrics, both descriptive:

- **`script_mixing`** — for the caller's turns and the bot's: turns that
  switch script, total switches, words per script. Part of no verdict.
- **`wer_by_script`** — WER over only the reference words in each script,
  against only the transcript words in that script, pooled across scored
  turns. A pooled WER of 25% can be 0% on the Tamil words and 50% on the
  English ones; this says which. Null, with the reason, without references.

**Script is not language.** Hindi and Marathi share Devanagari, romanised
Hindi is Latin and indistinguishable from English, and a transcriber that
writes an English loanword in Tamil script hides that switch. A word in the
wrong script counts as a deletion in one script and an insertion in
another. The run turns API also returns each turn's `script_segments`, and
the conversation shows them; every surface repeats the caveat.

`bb-eval-1 → bb-eval-2` added these two metrics and the caller's
utterances to the evidence document, which changes its fingerprint. No
existing formula changed, but evaluations are compared only within one
version, so re-evaluate a run to compare it with a newer one.

What is **not** measured: language identification (there is no model for
it), whether the bot *understood* a mixed utterance beyond task completion
and phrases, and code-mixed *generation* by the caller, whose phrase tables
are monolingual; scenario text it quotes may be mixed, as in
`scenarios/demo/tamil_crop_insurance.yaml`.

## Reproducibility

The evaluator gathers everything it may read into one canonical evidence
document — the run's mode, status and outcome, the scenario's expected
outcomes and phrases, and each bot turn's text, measured latency,
transcription failure flag and latest reviewed reference — and stores its
SHA-256 as `evidence_fingerprint`. Every metric is a pure function of that
document, so two evaluations with the same fingerprint and evaluator version
are identical (a test asserts it). Adding or correcting a reference changes the
fingerprint, which is how a report shows that a later score rests on different
evidence.

Evaluations are append-only: re-evaluating adds a row and never replaces one.
A failed transcription with a reference is **excluded** from the error rates
and counted as excluded, not scored as deletions — that failure is ours, and is
reported under `transcription_failure_rate` instead.

## The LLM judge — supplementary, offline only

`backend/app/evaluation/judge.py`. A judge scores a versioned rubric
(`DEFAULT_RUBRIC`: did the bot address the objective, were its statements
consistent, was any refusal appropriate) as `pass`, `fail` or `uncertain`,
and **must cite the turns** each score rests on. The reply is validated
strictly: an unknown criterion, a duplicate, a score outside the three, a
citation of a turn that does not exist, a non-`uncertain` score with no
citation, or a missing explanation rejects the whole reply. Invalid output is
retried within `max_attempts` (at most 3), and every attempt is logged.

- **It never moves the verdict.** Its result is marked `supplementary`.
- **Information boundary.** `JudgeInput` holds the language, the objective,
  the expected outcomes and the turns — nothing else. The deterministic
  verdict is not shown to it, so it cannot anchor on it.
- **Versioned.** Rubric name and version, prompt version (`bb-judge-prompt-1`),
  model requested and model reported are recorded with every judgement.
- **Cost and live calls.** It speaks through the caller's `LlmClient`, so it
  inherits the code-level live gate (`LIVE_CALLS_AUTHORISED = False`), the
  worst-case costing of unknown usage, and the rule that clients never retry.

**Not wired into the API, and not validated.** The only model client is
Sarvam's, which is not authorised for live calls, so no judgement has ever
been produced by a model, and its agreement with human labels has not been
measured — no labelled set exists. It is tested end to end with the scripted
client only.

**How it would be validated.** `docs/JUDGE_VALIDATION.md` is the protocol
(dataset, annotation guide, acceptance rule) and
`app/evaluation/judge_validation.py` the measurement: per criterion, Cohen's
kappa against adjudicated human labels, false pass and false fail rates,
abstention and run-to-run consistency, each with a bar every criterion must
clear on at least 100 decided items. With no labels, `validate()` reports
`validated: false` and why; nothing is claimed until real labels clear it.
