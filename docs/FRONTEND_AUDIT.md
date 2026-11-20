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
| Suites | 1 (no delete in the UI) | fixed: rename and delete per suite; a suite holding scenarios asks again before deleting them too, and one whose scenarios have runs is refused |
| Scenario edit, duplicate, delete | 4: API only; and DELETE of a scenario with runs was a 500 | fixed: `/app/scenarios/[id]`; delete-with-history is a 409 and archival is offered |
| Scenario creation | 2: YAML paste only; the shipped reference scenarios cannot be loaded | fixed: "Start from a reference scenario" in the editor, served by `GET /api/v1/scenario-library` |
| Bot adapter selection | 1 (reference bot only, by design) | 2026-11-20: users can now connect their own bot (Bots → Connect your chatbot), check it through the run's adapter, and pick it on New test; the run and comparison name it |
| Language | 1, through the scenario's language | — |
| Accent | 4: no accent parameter exists anywhere in the product | implemented as a requested dimension: `persona.accent` from a catalogue (`app/core/accents.py`), validated against the language, recorded per run with `applied` null and the reason, because no speech provider documents an accented voice. Shown on the run and scenario pages |
| Noise profile and seed | 1 | — |
| Channel conditions (codec, jitter, dropout, gain, clipping, truncation, silence) | 2: accepted by the API per run, absent from the UI; and the run response dropped `conditions`/`condition_sources`, so nobody could see what applied | fixed: a "Channel conditions" section on New test (bounds tested against the backend), returned by the API and shown on the run page with each value's source |
| Interruptions | 2: bot barge-in detected only by `ws_voice`; the caller never interrupts | caller barge-in implemented on `ws_voice` (per run, from New test): the caller talks over the bot and the run measures whether and how fast it stopped; shown on the stage timeline. Other adapters refuse it |
| Code-mixing | 2: authorable; the deterministic caller does not honour it and the run says so | measured: each turn's script segments shown in the conversation; `script_mixing` and `wer_by_script` in evaluations (`bb-eval-2`). Script, not language, stated everywhere. Caller generation is still monolingual |
| Execution and live progress | 1 | — |
| Recordings and playback | 1 | — |
| Evaluation verdict | 1 | — |
| WER / CER | 2: needs a reference transcript per bot turn; no way to enter one in the UI. And the Evaluation panel rendered criteria only, so a computed WER never appeared on the run page | fixed: references recorded per bot turn (`132572a`); the panel lists every metric, "not reported" with the evaluator's reason when unmeasured |
| Analytics | 1 | — |
| Comparison | 2: works, but needs two typed run ids | fixed: baseline and candidate are picked from the 100 most recent completed runs; ids remain the fallback |
| Exports | 1 | plus *Print / save as PDF* on run and comparison pages, and project and suite named in the run JSON export |
| Run filters | 2: the "Created" status sent `created`, which the API refuses (422), so the history failed to load; `text_bot_test` and four outcomes were missing | fixed: values come from `lib/run-filters.ts`, tested against the backend enums |
| Text bot runs | 2: `types.ts` lacked `text_bot_test` and the `bot_text_*` fields, so such a run was captioned "No external bot was contacted" | fixed: transcribed fields, own caveat and mislabel check |

Component-level tests were absent at the audit. There are now 47, in
`frontend/tests/components/`, run in CI (`npm run test:components`),
alongside 84 unit tests (`npm test`).

## Since the audit (2026-11-20)

- **Connect your chatbot** (`/app/bots/connect`, `/app/bots/[id]`): status
  1, walked in a browser against the reference bot.
- **Content-Security-Policy**: nonce-based on every page; verified with the
  policy enforced in Chromium (no violations on 15 signed-in pages, an
  injected inline script blocked). Pages now render per request.
- **Hydration**: the overview and analytics pages threw React #418 once a run
  existed (dates formatted in two locales); fixed.
- **Caller language caveat**: runs in Bengali, Marathi or Telugu show that the
  caller's phrases are unreviewed.

## Browser walk of the whole journey (2026-11-20, local Docker stack)

An 18-step Playwright script, run in Chromium with CSP enforced against the
rebuilt local stack (`localhost:3000`), signed up a fresh account and went
through suite, scenario from the library, connecting bots (success, wrong
token, unreachable host, malformed URL, voice bot), the bot list, two runs
against the connected text bot, evaluation, comparison, JSON and CSV export,
analytics, a second tenant, and deleting the bot. Final result: **18 of 18
passed, no console or page errors**. It found two real defects, both fixed:

- **A text-bot run's page said "This run could not be loaded."** The report
  endpoint answered 500 for every finished `text_bot_test` since the text
  protocol shipped: the session-close event was stored with turn index -1,
  which the response schema refused. Fixed in `46cc0bd`; older runs read the
  -1 as "whole run".
- **Two shipped scenarios could not be created from the library**
  (`english_insurance_claim`, `bengali_balance_enquiry`): the builder wrote
  YAML 1.2, and the server's YAML 1.1 parser read their dates as dates.
  Fixed in `a37c43f`.

Checked and found correct: a fully loaded run page has one `<main>`
landmark (two appear only while streamed content swaps in); the connected
bot is named on the run page and on both sides of a comparison; WER and CER
show "not reported", never 0; a deleted bot's runs stay readable with their
bot record; another tenant gets 404 for the bot. No token appeared in any
page, export or backend log line.

A voice run was also driven over the API against the connected voice bot:
`external_bot_test`, `ws_voice`, completed, with `bot_audio_externally_received:
true` and its report loading. Its transcripts come from the local stack's
offline fake, so it shows the audio path works, not recognition quality.

Not covered: PDF output itself (the print control is present; printing is
the browser's), and the analytics regression check with enough runs to decide.

## Copy that contradicted the product

- The landing page, as above.
- The run page caveat "evaluation is a later phase", rendered under the
  Evaluation panel. Fixed; a run on the offline fakes now also says so.
- The Providers page: every result comes "from audio moved inside this
  process or handed to it by an operator", false since `ws_voice`. Fixed.
- The backend's unenforced-settings note: "interruption handling is
  Phase 9", which is complete. Fixed: it now says the caller never talks
  over the bot and only `ws_voice` detects a barge-in.
