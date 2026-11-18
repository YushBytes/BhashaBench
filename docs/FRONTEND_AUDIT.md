# Frontend audit, 2026-11-19

Requested by the owner after the local stack's landing page showed
"Phase 8 of 15 · no telephone call placed yet". Every route was fetched as a
signed-in user of a fresh workspace on the local Docker stack, and a run page
and a comparison were read with real evaluated runs. Status key:
**1** working · **2** implemented but incomplete · **3** UI without backend ·
**4** not implemented. The *Fix* column records what was changed afterwards.

## The phase badge

`frontend/lib/content.ts` hard-coded `currentPhase = 8`, last edited on
2026-11-09, in the competition's renumbered scheme, where 8 was the operator
workspace. Nothing connected it to project progress, so it did not move when
Phases 9 to 14 closed. The phase table, capabilities and limitations on the
same page were frozen at that date. They listed evaluation, reporting, CI and
hardening as planned, said no external bot existed, and said nothing was a
score. "No telephone call placed" was, and is, true: it describes Phase 8
(telephony) in the original numbering, not overall progress.

## Routes

All return 200 to a member and read the real API. There is no sample data.
`/app` without a session redirects to `/login`; an unknown route is a 404.
Both landing buttons ("Explore the test bench", "Open the workspace") go to
`/app`.

`/` · `/login` · `/signup` · `/app` · `/app/runs` · `/app/runs/[runId]` ·
`/app/new-test` · `/app/scenarios` · `/app/analytics` · `/app/compare` ·
`/app/workspace` · `/app/providers`

## Feature status

| Feature | Found | Fix |
|---|---|---|
| Overview, health, configured providers | 1 | — |
| Workspaces, projects, members, roles | 1 | — |
| Sign-up, sign-in, tenant isolation | 1 | — |
| Suites | 1 (no delete in the UI) | — |
| Scenario creation | 2: YAML paste only; the shipped reference scenarios cannot be loaded | fixed: "Start from a reference scenario" in the editor, served by `GET /api/v1/scenario-library` |
| Bot adapter selection | 1 (reference bot only, by design) | — |
| Language | 1, through the scenario's language | — |
| Accent | 4: no accent parameter exists anywhere in the product | not in scope: no model for it |
| Noise profile and seed | 1 | — |
| Channel conditions (codec, jitter, dropout, gain, clipping, truncation, silence) | 2: accepted by the API per run, absent from the UI; and the run response dropped `conditions`/`condition_sources`, so nobody could see what applied | fixed: a "Channel conditions" section on New test (bounds tested against the backend), returned by the API and shown on the run page with each value's source |
| Interruptions | 2: bot barge-in detected only by `ws_voice`; the caller never interrupts | stated, not changed |
| Code-mixing | 2: authorable; the deterministic caller does not honour it and the run says so | stated, not changed |
| Execution and live progress | 1 | — |
| Recordings and playback | 1 | — |
| Evaluation verdict | 1 | — |
| WER / CER | 2: needs a reference transcript per bot turn; no way to enter one in the UI. And the Evaluation panel rendered criteria only, so a computed WER never appeared on the run page | fixed: references recorded per bot turn (`132572a`); the panel lists every metric, "not reported" with the evaluator's reason when unmeasured |
| Analytics | 1 | — |
| Comparison | 2: works, but needs two typed run ids | fixed: baseline and candidate are picked from the 100 most recent completed runs; ids remain the fallback |
| Exports | 1 | — |
| Run filters | 2: the "Created" status sent `created`, which the API refuses (422), so the history failed to load; `text_bot_test` and four outcomes were missing | fixed: values come from `lib/run-filters.ts`, tested against the backend enums |
| Text bot runs | 2: `types.ts` lacked `text_bot_test` and the `bot_text_*` fields, so such a run was captioned "No external bot was contacted" | fixed: transcribed fields, own caveat and mislabel check |

## Copy that contradicted the product

- The landing page, as above.
- The run page caveat "evaluation is a later phase", rendered under the
  Evaluation panel. Fixed; a run on the offline fakes now also says so.
- The Providers page: every result comes "from audio moved inside this
  process or handed to it by an operator", false since `ws_voice`. Fixed.
- The backend's unenforced-settings note: "interruption handling is
  Phase 9", which is complete. Fixed: it now says the caller never talks
  over the bot and only `ws_voice` detects a barge-in.
