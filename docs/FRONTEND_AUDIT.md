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
| Scenario creation | 2: YAML paste only; the shipped reference scenarios cannot be loaded | see checkpoint |
| Bot adapter selection | 1 (reference bot only, by design) | — |
| Language | 1, through the scenario's language | — |
| Accent | 4: no accent parameter exists anywhere in the product | not in scope: no model for it |
| Noise profile and seed | 1 | — |
| Channel conditions (codec, jitter, dropout, gain, clipping, truncation, silence) | 2: accepted by the API per run, absent from the UI | see checkpoint |
| Interruptions | 2: bot barge-in detected only by `ws_voice`; the caller never interrupts | stated, not changed |
| Code-mixing | 2: authorable; the deterministic caller does not honour it and the run says so | stated, not changed |
| Execution and live progress | 1 | — |
| Recordings and playback | 1 | — |
| Evaluation verdict | 1 | — |
| WER / CER | 2: needs a reference transcript per bot turn; no way to enter one in the UI | see checkpoint |
| Analytics | 1 | — |
| Comparison | 2: works, but needs two typed run ids | see checkpoint |
| Exports | 1 | — |
| Run-list mode filter | 2: `text_bot_test` missing | see checkpoint |

## Copy that contradicted the product

- The landing page, as above.
- The run page caveat "evaluation is a later phase", rendered under the
  Evaluation panel.
- The Providers page: every result comes "from audio moved inside this
  process or handed to it by an operator", false since `ws_voice`.
- The backend's unenforced-settings note: "interruption handling is
  Phase 9", which is complete.
