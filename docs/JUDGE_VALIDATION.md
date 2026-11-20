# Validating the LLM judge

**Status: not validated.** No human-labelled set exists and no model
judgement has ever been produced: the only model client is Sarvam's, and
live calls are not authorised (`LIVE_CALLS_AUTHORISED = False`). Semantic
correctness and context retention therefore remain "unavailable" on every
evaluation, and the judge, when it is run, stays `supplementary` and never
moves a verdict. This document is the protocol that would change that, and
`backend/app/evaluation/judge_validation.py` is the measurement, tested
against hand-worked values (`backend/tests/test_judge_validation.py`).

## What would be validated

The judge scores each criterion of `DEFAULT_RUBRIC` (version `1`) as `pass`,
`fail` or `uncertain`, citing turns:

| Criterion | Question |
|-----------|----------|
| `answered_objective` | Did the bot address the caller's objective? |
| `factually_consistent` | Are the bot's statements consistent with each other? |
| `appropriate_refusal` | If the bot refused, was the refusal appropriate? |

Validation applies to one rubric version, one prompt version
(`bb-judge-prompt-1`) and one model. Changing any of them starts again.

## The dataset

- **Source.** Recorded runs, exported with `GET /test-runs/{id}/export`.
  The judge sees what `JudgeInput` holds (language, objective, expected
  outcomes, turns) and the annotators see the same, nothing more: no
  deterministic verdict, no bot name.
- **Size.** At least 100 *decided* items per criterion (the default
  `Thresholds.min_items`). Plan for about 150 conversations, because some
  will be excluded and `appropriate_refusal` only applies where a bot
  refused.
- **Balance.** Every catalogue language that runs, both outcomes, and at
  least 30 human `fail` labels per criterion, or the false pass rate cannot be
  measured. Include deliberately broken bots (the refusing reference bot, a
  bot that contradicts itself) so failures exist.
- **Split.** Keep 30% aside, untouched, for the final measurement. Prompt
  changes are made against the rest only.

## Annotation

- **Annotators.** Two per item, fluent in the conversation's language,
  working independently. Disagreements go to a third, whose label stands.
  Record inter-annotator kappa before adjudication: if humans agree below
  0.6, the criterion is ambiguous and the rubric is rewritten before the
  judge is measured.
- **Labels.** `pass` or `fail` only. An item no annotator can decide is
  **excluded**, not labelled `uncertain`: `uncertain` is a judge output,
  reported as abstention, never counted as agreement.
- **Guidance per criterion.**
  - `answered_objective`: pass if the bot dealt with what the caller asked
    for (gave the information, did the task, or correctly said it could not),
    even if the caller's turn budget ended first. Fail if the bot ignored,
    misunderstood or deflected the objective.
  - `factually_consistent`: fail if any two bot statements contradict each
    other, or a bot statement contradicts a fact the caller gave and the bot
    did not correct. Repetition is not inconsistency.
  - `appropriate_refusal`: only for conversations where the bot refused. Pass
    if the refusal was warranted (the request was out of scope, or
    identity was not verified); fail if the bot refused something it should
    have handled. Exclude conversations with no refusal.
- **Format.** One row per item and criterion:
  `item_id, criterion_id, human, judge, judge_repeat`. `judge_repeat` is a
  second, independent judge run on the same item, for consistency.

## The acceptance rule

`validate()` passes only if **every** criterion clears **every** bar
(`Thresholds`):

| Measure | Bar | Why |
|---------|-----|-----|
| Decided items | ≥ 100 | Below this no rate is stable |
| Cohen's kappa (judge vs adjudicated human) | ≥ 0.6 | Agreement beyond chance; an always-`pass` judge on a mostly-pass set scores 0 |
| False pass rate (judge `pass` where human `fail`) | ≤ 0.10 | The costly error: it hides a broken bot |
| False fail rate (judge `fail` where human `pass`) | ≤ 0.20 | Wrongly blames a bot |
| Abstention (`uncertain`) | ≤ 0.25 | A judge that rarely commits is not useful |
| Consistency (two judge runs agree) | ≥ 0.90 | A judge that disagrees with itself cannot agree with people |

An unmeasurable rate (no human-failed items, no repeats) is a failure, not a
pass. The report lists every reason.

## What it would cost, and who must authorise it

Running the judge on about 150 conversations twice is about 300 model
requests. That is a live, paid call to an external provider, so it needs the
owner's explicit instruction to begin live testing, under the existing spend
ceiling and ledger (`docs/CALLER.md`). Annotation needs fluent speakers'
time. Neither is available today, and neither is simulated here.

## What validation would and would not allow

A validated judge could report its criteria as **validated supplementary**
scores beside the deterministic verdict, with the rubric, prompt and model
versions and the validation report's date. It would still not move the
verdict without a further, explicit decision, and it would be revalidated
whenever its rubric, prompt or model changes.
