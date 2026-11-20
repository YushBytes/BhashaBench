# Execution checkpoint

The resume point for continuous execution of the remaining phases, under the
owner's standing authorisation of 2026-11-16 (see `CLAUDE.md`, "Phase
discipline"). Updated as units land. Phase numbers are the original ones.

**To resume:** read this file, run `git status`, confirm
`git rev-parse HEAD` equals `git rev-parse origin/main`, check the latest
GitHub Actions run, then start the first unchecked task below. Never trust a
figure here over the repository: re-measure it.

## Hard limits (unchanged by the authorisation)

- No live provider call (Sarvam, Gnani, telephony) in tests, CI or by hand.
- No spending: no paid infrastructure, domain, subscription, credits or number.
- Never read, print or edit `.env`.
- The `GNANI_API_KEY` exposed in a session transcript on 2026-11-16 is treated
  as compromised. Rotation is the owner's manual task.

## Execution order

Dependencies decide the order: evaluation needs the conversation evidence,
reporting needs evaluation, tenancy must exist before the frontend's
project pages, and deployment needs everything.

1. Early Phase 9 prerequisite — HTTP reference bot and adapter (text only).
2. Phase 7 — remaining audio conditions reachable from a scenario.
3. Phase 11 — deterministic evaluation (WER/CER, task completion, latency),
   judge abstraction with an offline fake.
4. Phase 12 — analytics, run comparison, regression, CSV/JSON export.
5. Phase 14 (part 1) — users, sessions, workspaces, projects, authorisation.
6. Phase 10 — storage abstraction, recordings, retention and deletion.
7. Phase 8 — telephony abstraction, mocked provider, signed webhooks.
8. Phase 9 — background execution, latency evidence, recovery.
9. Phase 13 — frontend against the real API.
10. Phase 14 (part 2) — security scanning, headers, rate limits, CI gates.
11. Phase 15 — production images, configuration, runbooks, deployment plan.

## Progress

| Unit | Commit | CI |
|------|--------|----|
| Hide exported provider credentials from offline tests | `b1e1c26` | ✅ 43897753071 |
| Hold the Gnani key as a masked `SecretStr` | `007e283` | ✅ 43911871562 |
| Record the owner's authorisation and this checkpoint | `33091ee` | ✅ |
| Outbound-request guard against SSRF | `02b1ff7` | ✅ 43913687809 |
| Reference text bot and `bhashabench-text-bot/1` | `b98b944` | ✅ 43915170226 |
| HTTP text bot adapter | `f9eed46` | ✅ 43916620115 |
| `text_bot_test` runs through the adapter, engine and API | `47b61eb` | ✅ 43920069081 |

**Early Phase 9 prerequisite: complete.** Text only; verified against the
reference bot on localhost.

| Phase 7 unit | Commit | CI |
|------|--------|----|
| Jitter, dropout, truncation and silence transformations | `a74ce2b` | ✅ 43921296391 |
| Scenario-declared channel conditions and per-run overrides | `a47c3b3` | ✅ 43922977070 |
| Exact G.711 codec; Phase 7 closed | `7825496` | ✅ 43924088839 |

**Phase 7: complete** (synthetic noise; no recorded noise beds).

| Phase 11 unit | Commit | CI |
|------|--------|----|
| Normalisation, WER/CER, metric registry | `git log --grep "normalisation, WER"` | ✅ 43925429634 |
| Append-only evaluations and references (migration `1c40c48f72cf`) | see log | ✅ 43927628576 |
| Evaluator with reasoned verdict | see log | ✅ 43928854156 |
| Evaluation API | see log | ✅ 43930963986 |
| Offline LLM judge; Phase 11 closed | see log | ✅ 43932115730 |

**Phase 11: complete** (deterministic; judge offline-only, not validated
against human labels).

| Phase 12 unit | Commit | CI |
|------|--------|----|
| Index test runs for reporting (migration `6c64d84df105`) | `32e66f2` | ✅ 44056197928 (pushed with the next unit) |
| Aggregates, comparison, regression, trend, export | `37e8ec9` | ✅ 44056197928 |

**Phase 12: complete** (signed artefact URLs moved to Phase 10; no PDF).

| Phase 10 unit | Commit | CI |
|------|--------|----|
| Blob storage contract and local adapter; `.gitignore` anchored | `b32f5bf` | ✅ |
| Full-conversation recording linked to turn artefacts | `519e40e` | ✅ |
| Run deletion and the retention sweep | `a56b132` | ✅ |
| Signed expiring audio links; `PIPELINE_SERVE_ARTEFACTS` retired; Phase 10 closed | `1541ab2` | see log |

**Phase 10: complete** (local filesystem only; recordings assembled, not
captured live; the sweep is not scheduled).

| Phase 8 unit | Commit | CI |
|------|--------|----|
| Provider contract, guardrails, signed webhooks, mock provider | `6f5bf8c` | see log |
| `telephony_calls` (migration `bcf146f6c696`), event handling, webhook and call listing | `97a5b0c` | see log |

**Phase 8: partial by rule** (no real call is authorised).

| Phase 9 unit | Commit | CI |
|------|--------|----|
| Background execution, crash finishing, automatic recovery; `bbs_` token redaction | `b3ea14a` | see log |
| Streaming voice protocol, `ws_voice` adapter, reference bot voice endpoint; Phase 9 closed | `2660aa1` | see log |

**Phase 9: complete** (STT/TTS per utterance; energy VAD; reference bot only).

| Phase 13 unit | Commit | CI |
|------|--------|----|
| Analytics, compare and workspace pages; run page evaluation, recording and auto-refresh | `6342a93` | ✅ |
| `node --test` suite for `lib/` in CI; redirect guard tightened | `016c7f8` | see log |
| Suite and scenario authoring; Phase 13 closed | `e8d8050` | see log |

| Phase 14.2 unit | Commit | CI |
|------|--------|----|
| Rate limits and security headers | `1ce0df6` | ✅ (with `60791b4`) |
| Dependency audits and a full-history secret scan in CI | `78476d8` | ✅ |
| Regression gate over the reference scenarios; Phase 14 closed | `142d3dc` | ✅ |

| Phase 15 unit | Commit | CI |
|------|--------|----|
| Production images, prod compose, startup refusals, backup/restore (rehearsed locally), deployment plan | `84e5cd5` | see log |
| Request ids and JSON logs | `ed82e3a` | ✅ |
| Token-protected `/metrics` | `a9edb87` | see log |
| Load test script and a recorded local run | this commit | see log |

| Local delivery unit (2026-11-19) | Commit | CI |
|------|--------|----|
| Workspace slugs allocated by the unique constraint; sign-up never joins an existing workspace | `78c7156` | ✅ 44398495799 |
| `BOT_HTTP_ALLOW_PLAIN_PRIVATE` (plain http/ws to a private bot; development only) | `b1530f9` | ✅ 44398495799 |
| WebSocket adapter refuses redirects (token could follow a 3xx to an unchecked host) | `cfe7c60` | ✅ 44396925791 |
| Text logs redacted; `websockets`/`httpcore`/`hpack` held at INFO | `c7fcf71` | ✅ 44398495799 |
| Zero-cost local stack, `local_e2e.py`, authenticated `demo.py`, Windows guide | `2180a1e` | ✅ 44398495799 |
| Local stack's allowed origins follow `FRONTEND_HOST_PORT` | `508b5e8` | ✅ 44398495799 |

**Local deployment: complete and verified.** `docker-compose.local.yml`
(`docs/LOCAL_DEPLOYMENT.md`) runs everything on one Windows machine with no
keys, no `.env` and no spending. Measured on 2026-11-19 against a fresh clone
of `508b5e8`:

- `scripts/local_e2e.py --restart`: **74 passed, 0 failed**, on the default
  ports with existing data, and on 3100/8100 with empty volumes.
- Backend suite: 3045 collected; 3003 passed, 42 skipped on Windows (41 live,
  1 symlink). Frontend: 24/24 unit tests, typecheck and lint clean.
- Gitleaks (`dir` mode, the pinned CI image) over the tree: no leaks.
- The backend log of a full run contains no `Authorization` header.

| Frontend audit unit (2026-11-19) | Commit | CI |
|------|--------|----|
| Landing page status derived from the phase table, drift-tested against README; audit recorded in `docs/FRONTEND_AUDIT.md` | `14dc76f` | ✅ |
| Run filters (a 422 on "Created"), text bot runs, current run caveats | `50ad6a8` | ✅ 44406328402 |
| Reference transcripts on bot turns | `132572a` | ✅ |
| Evaluation metrics on the run page | `cb239db` | ✅ |
| Report and silence wording | `23e337a` | ✅ 44408020950 |
| Shipped scenario library (`GET /scenario-library`) in the editor | `81c4932` | ❌ 44409453524, fixed by the CI-fix row |
| Run response returns channel conditions and their source | `94d4864` | ✅ (with the fix) |
| Channel conditions on New test | `be6e134` | ✅ (with the fix) |
| Second documented-paths list updated (CI fix) | see log | ✅ 44411607156 |
| Comparison by picking runs; metric names in words | `b974da8`, `e36838a` | see log |

Each frontend unit was checked in a browser against the rebuilt local stack:
a reference transcript produced WER 38.5% on the run page, a reference
scenario was picked, validated and added, a run started from the form
applied a G.711 codec and 40 ms jitter (recorded as operator-set and
measured in the artefacts), and two runs were compared from the pickers.

Build the images from a clone **outside OneDrive**: in the OneDrive tree,
many backend files are cloud placeholders that Docker reports as
`invalid file request`.

**Phase 13: complete** (no component tests; the UI deletes runs, since `c8935d5`, but not suites or scenarios).

**Phase 14: complete.**

**Phase 15: everything buildable without spending is done.** It stays 🟡:
its exit criterion (a week unattended with alerting, a restore rehearsed on
the deployment) needs a host, which needs the owner's purchase.

| Completion round (2026-11-19) | Commit | CI |
|------|--------|----|
| Scenario archival; DELETE with recorded runs was a 500, now a 409 (migration `92a1fdd146b8`) | `729f50a` | ✅ |
| Scenario edit/duplicate/archive/delete and suite rename/delete in the UI | `075d332` | ✅ 44470765603 |
| Accent as a requested dimension, recorded as applied or not (spec v3) | `d26d720` | ✅ 44472010431 |
| Code-mixing as script switching; `wer_by_script`; evaluator `bb-eval-2` | `1ce426e` | ✅ 44473994594 |
| Caller barge-in on `ws_voice`; yield window 500 ms with its stated limit | `50f21ea`, `df91c7c` | ✅ 44475965436 |
| PDF via print stylesheet; project and suite in run exports | `39888ce` | ✅ 44477267229 |
| Component tests (vitest, jsdom, Testing Library) in CI | `200ee49` | ✅ 44477876319 |

Measured at `200ee49`: backend 3084 collected, 3042 passed, 42 skipped on
Windows (41 opt-in live, 1 symlink); frontend 50 unit + 14 component tests,
typecheck, lint and build pass; `local_e2e.py --restart` 74/74 from a fresh
clone with an empty database (all 8 migrations) on 3100/8100, and on the
running stack. On the running stack an accented scenario recorded
`applied: null` with its reason, and a `ws_voice` run with caller barge-in
recorded the interruption (the reference bot's 600 ms reply ended within the
500 ms window - the case the evidence's `limitation` names).

Not done in this round, each for the reason given:
- **Comparing more than two runs** at once: comparison is pairwise; groups
  are compared by the regression check on Analytics.
- **Accent actually rendered**: no speech provider documents an accented
  voice; the architecture is ready for one that does.
- **Code-mixed caller generation**: the caller's phrase tables are
  monolingual; writing mixed tables needs a reviewer fluent in each pair.
- **Semantic correctness, context retention, response relevance, language
  quality**: need the LLM judge, which is offline-only and not validated
  against human labels; reported as unavailable, never scored.
- **Live provider, telephony and public deployment verification**: need the
  owner's authorisation, credentials and spending. Unchanged below.
- **Load testing at scale**: only the recorded local run exists.

## Frontend replacement (started 2026-11-19)

Owner brief: replace the frontend with a new design and information
architecture, keeping the backend, API contracts and honesty rules intact.

**Audit findings.** 66 paths / 83 operations. The brief asks for screens the
API does not back, so each is built honestly or not at all:
- Bot integrations: no CRUD. Adapters are a fixed, server-configured
  catalogue chosen per run (`GET /test-runs/bot-adapters/available`). The
  page is a read-only catalogue with each adapter's real availability.
- No password recovery, invitations or notifications endpoints. Sign-in says
  reset is unavailable; members are added by the email of an existing account.
- Comparison is pairwise; groups go through the regression check.
- Reports are run reports (JSON, CSV, print-to-PDF), the runs CSV and the
  comparison page; there is no stored report entity.

**Design.** Reference: `awesome-design-md/vercel` (monochrome, hairlines,
mono for measurements) with the owner's electric blue as the single accent.
Type dealt by design-taste-frontend: Host Grotesk + JetBrains Mono. Lucide
icons. 21st.dev MCP is not installed in this environment.

**Kept:** `lib/` (API client, types, formatters, conditions, filters,
redirect guard, evaluation rows) and its tests - integration and honesty
logic, not presentation. **Replaced:** `app/`, `components/`, `globals.css`.
Old routes redirect (`/app/new-test`, `/app/providers`, `/app/workspace`).

| Frontend unit | Commit | CI |
|------|--------|----|
| Plan, `lib/` additions with tests (client endpoints, content, script runs, password rule, scenario draft) | see log | |
| New design system and every route (phases B-H); component tests | see log | |

**Phases A-H done.** Measured on 2026-11-20: 62 unit and 36 component tests
pass (14 component tests before); typecheck, lint and production build clean;
`npm audit --omit=dev` 0 vulnerabilities; no backend URL in the client
bundle. `scripts/local_e2e.py` through the new production frontend: 70
passed, 0 failed. Playwright (one headless browser, scripted): sign-up,
suite creation, a scenario built from the Tamil template and validated by the
server, a fixture run started and followed, every route captured at 1440,
768 and 390 with no horizontal overflow after the `TableScroll` fix.

**Frontend replacement: complete.** Commits `60f79c9` and `ba2a014`, CI
44701201446 green (all five jobs). The local Docker frontend was rebuilt from
the `C:\dev\BhashaBench` clone at `ba2a014` and is healthy on port 3000. The
project's next task below is unchanged.

## Round of 2026-11-20 (bring your own bot and hardening)

Pushed and CI-green up to `d6e0296`, then the commits after it:
DNS-rebinding fix (pinned connections); bring-your-own-bot backend
(encrypted integrations, real connection check, runs by `bot_integration_id`)
and the "Connect your chatbot" frontend; a nonce-based frontend CSP (pages now
render per request); a hydration fix (one date locale); per-request
project-scope cache (statements down; throughput unchanged at about 106 req/s
for one process, 263 with four workers); a caller fix for read-back
contradictions; unreviewed Bengali, Marathi and Telugu phrase tables with
`docs/PHRASE_REVIEW.md`; LLM-judge validation tooling with
`docs/JUDGE_VALIDATION.md` (nothing validated); and `bot_integration` on run,
listing and comparison responses.

Finished afterwards: the run and compare pages name the connected bot; the
README and CLAUDE.md test counts were regenerated (3169 collected across 78
modules); `docs/FRONTEND_AUDIT.md` updated; the `C:\dev\BhashaBench` clone
fast-forwarded. Component tests exist (47). Not done: a fresh-clone rehearsal
beyond what CI's clean checkout already does.

## Next task

**Blocked on the owner.** Choose and pay for a VM and a domain
(`docs/DEPLOYMENT.md` lists them with indicative prices), rotate the Gnani
key, and create `.env.production` on the host. Then: deploy with the
runbook, rehearse a restore there, add external uptime alerting and a
`/metrics` scraper, re-run the load test on the VM, run a week unattended,
and only then cut `1.0.0`.

Not blocked, if wanted meanwhile: a fluent-speaker review of the Bengali,
Marathi and Telugu phrase tables (`docs/PHRASE_REVIEW.md`), and a decision
on the worker count for the chosen VM (`docs/DEPLOYMENT.md`, load test). The
earlier list here (phrase tables, frontend CSP, component tests, address
pinning, scope caching) was done on 2026-11-20.

## Outstanding issues

- Phase 6 cannot close until a live, cost-bounded call is authorised.
- Phase 8 cannot close without an authorised real call.
- Deployment target: none provisioned; anything paid needs the owner.
- A local smoke-test account `e2e-smoke@example.test` (workspace `e2e-smoke`,
  no data) exists in the developer database from the 2026-11-17 check.
- The `bhashabench-local` Docker volumes hold throwaway `e2e-*@example.test`
  accounts and runs from the 2026-11-19 checks. `down -v` clears them.
