# Reporting and analytics (Phase 12)

Read-only views over stored runs and their latest evaluations. Code:
`backend/app/analytics/` and `backend/app/repositories/analytics.py`.

## Rules that keep the numbers honest

1. **Latest evaluation per run.** Each run contributes the newest of its
   evaluations (`DISTINCT ON`), so re-evaluating never double-counts. A run
   never evaluated is counted as `not_evaluated`, never dropped.
2. **Pass rate = pass / (pass + fail).** `undetermined` (unfinished, or ended
   by our fault) and `not_evaluated` runs are reported beside it and never in
   the denominator: an outage is not a failure, and an unscored run is not a
   pass.
3. **Every rate carries its n and a Wilson 95% interval**, which behaves at
   0%, 100% and small n where the normal approximation does not.
4. **Mixed evaluator versions are flagged** in `warnings`; scores under
   different versions are not comparable.
5. **Significance needs evidence.** `/regressions` uses Fisher's exact test
   (two-sided). A regression or improvement is reported only when p < 0.05
   **and** each group has at least five decided runs. Otherwise the
   conclusion is `insufficient_evidence` or `no_significant_difference`,
   however large the point difference.
6. **Aggregation happens in PostgreSQL.** No handler loads every run to count
   it. Filter values are bound parameters; the grouping dimension comes from a
   fixed list.
7. **WER is pooled**, total errors over total reference words, not a mean of
   per-run rates. Latency is reported as the distribution of each run's own
   median, and labelled so — per-run percentiles cannot be pooled.

## Endpoints

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/v1/analytics/summary` | Verdict counts, pass rate with interval, pooled WER and the latency distribution; `group_by` one of `language`, `scenario_name`, `bot_adapter`, `mode`, `outcome`, `suite_id` |
| `GET` | `/api/v1/analytics/compare?baseline=&candidate=` | Two evaluated runs: verdict change, per-metric deltas with direction, and warnings when scenario, language, mode or evaluator version differ. 409 if either is unevaluated. Makes no statistical claim |
| `GET` | `/api/v1/analytics/regressions` | Two groups chosen by `baseline_*` and `candidate_*` filters; Fisher's exact test and a conclusion with its reason |
| `GET` | `/api/v1/analytics/trend?bucket=day\|week` | Verdict counts and pass rate per period |
| `GET` | `/api/v1/analytics/runs.csv` | One row per run with its latest verdict and key metrics (`limit` ≤ 10 000) |
| `GET` | `/api/v1/test-runs/{id}/export?format=json\|csv` | One run: stored metadata, every turn with its reference, and the latest evaluation with its fingerprint. CSV is one row per turn |

Filters on every aggregate: `suite_id`, `mode`, `language`, `scenario_name`,
`bot_adapter`, `created_after`, `created_before`. A misspelled filter is
ignored by FastAPI rather than rejected — check the echoed `filter` in the
response.

## Exports

- **CSV injection is neutralised.** A cell beginning with `=`, `+`, `-`, `@`,
  a tab or a carriage return is prefixed with an apostrophe, so a bot reply
  such as `=HYPERLINK(...)` cannot execute in a spreadsheet. JSON is exported
  unaltered.
- **Provenance.** A JSON export names its format version, export time, the
  current evaluator version, and the evaluation's version and fingerprint, so
  a file can be shown to be current or stale against the stored run.
- **Not implemented: PDF.** It needs a rendering dependency this project does
  not carry. Export JSON or CSV and render from those.

## Indexes

`ix_test_runs_created_at` serves ordering and trend bucketing;
`ix_test_runs_run_metadata_gin` serves the `has_key('pipeline')` test. The
value filters (`->>` equality) are not index-served; see migration
`6c64d84df105` for why that is deferred until a measured plan needs it.
