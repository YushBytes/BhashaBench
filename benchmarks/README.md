# Benchmarks - the CI regression gate

`baseline.json` records the verdict each committed reference scenario
(`scenarios/*.yaml`) earns as a `text_bot_test` against the reference bot
running `reference_bot_script.json`. `backend/tests/test_benchmark_gate.py`
re-runs them on every CI build and fails if any verdict ranks lower than its
baseline (`pass` > `undetermined` > `fail` > `not_runnable`), or a scenario
disappears. A test also proves a deliberately broken bot trips the gate.

**What it measures: this pipeline, not any bot.** The caller is the rule
engine and the bot is scripted to satisfy the reference scenarios, so the
result is deterministic and any change comes from the code. All six
reference scenarios run and pass (baseline regenerated 2026-11-20). The
Bengali, Marathi and Telugu runs use the caller's **unreviewed**
phrase tables (`docs/PHRASE_REVIEW.md`); a pass here says the pipeline
completes those conversations against a scripted stub, nothing about how
natural the caller sounds. Making them runnable also exposed a caller defect:
a correctly read-back number was taken as contradicting a different numeric
fact, so the Bengali scenario looped until its budget ran out (fixed in
`app/caller/analysis.py`, with a regression test).

To accept an intended change, regenerate the baseline and commit it with the
change that explains it:

```bash
BENCHMARK_UPDATE_BASELINE=1 pytest backend/tests/test_benchmark_gate.py
```
