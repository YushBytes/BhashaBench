# Phase 8.1 — Post-Phase-8 Audit

| | |
|---|---|
| **Scope** | Parts A-I are the original audit, written before any change. **Part J is the reconciliation record.** |
| **Audited** | 2026-11-09, `main` @ `cea14be` |
| **Reconciled** | 2026-11-09, `main` @ `c1062a7` — see [Part J](#j-reconciliation-record) |
| **Status** | **Done and pushed.** All four findings resolved across two commits. The two deferred *pipeline* defects are deliberately **still unresolved** — see [§J.7](#j7-what-remains-unresolved). |

> **Read Parts A-I as the record of what was found, not as current state.**
> They are preserved unedited, including two claims Part J corrects. The
> present state of the repository is Part J.

> **On the name.** The roadmap's only point-release precedent is
> `7.1 | Concurrency Enforcement`, added when Phase 7 shipped a limit that
> nothing read. "Phase 8.1" is used here in that same sense: a follow-up that
> closes what Phase 8 left open. Nothing in this document should be read as a
> claim that Phase 8.1 work has been done.

---

## Contents

- [A. Verification: every gate, re-run today](#a-verification-every-gate-re-run-today)
- [B. Finding 1 — the Phase 8 renumbering was never finished](#b-finding-1--the-phase-8-renumbering-was-never-finished)
- [C. Finding 2 — the documented test counts are 33 short](#c-finding-2--the-documented-test-counts-are-33-short)
- [D. Finding 3 — the ruff format gate's scope grew silently](#d-finding-3--the-ruff-format-gates-scope-grew-silently)
- [E. Finding 4 — counting endpoints no longer works the old way](#e-finding-4--counting-endpoints-no-longer-works-the-old-way)
- [F. Phase 8's seven limitations, re-verified](#f-phase-8s-seven-limitations-re-verified)
- [G. Minor: .env.example reconciliation](#g-minor-envexample-reconciliation)
- [H. Proposed Phase 8.1 scope](#h-proposed-phase-81-scope)
- [I. What this audit did not do](#i-what-this-audit-did-not-do)
- [J. Reconciliation record](#j-reconciliation-record)

---

## A. Verification: every gate, re-run today

Every gate Phase 8 claimed was re-run on the host against `cea14be`.

| Gate | Result today | Phase 8 report | Agrees |
|---|---|---|---|
| `pytest` | **1949 passed, 41 skipped** (192.93 s) | 1949 passed, 41 skipped (3 m 28 s) | yes |
| `pytest --collect-only` | **1990 collected** | not stated | — |
| `alembic check` | No new upgrade operations detected | same | yes |
| `ruff check .` | All checks passed | same | yes |
| `ruff format --check .` | **235 files already formatted** (236 once this report existed — see §D) | 233 files | **no — see §D** |
| `tsc --noEmit` | Clean (exit 0) | Clean | yes |
| `eslint .` | Clean (exit 0) | Clean | yes |
| `next build` | Succeeds; 10 routes; TypeScript clean in 6.3 s | Succeeds; 10 pages | yes |
| Migrations on disk | 2 (`3e3312d5327a`, `4997650a09c8`) | 2 | yes |
| Test modules | 33 | 33 | yes |

**The Phase 8 report's own figures are accurate and reproducible.** Its
`1949 passed, 41 skipped` is exactly what the suite produces today. The
problems found below are in `README.md`, `CLAUDE.md` and the roadmap — not in
the Phase 8 report.

No live provider test ran. All 41 are opt-in and were skipped; **no Gnani API
call was made and no credits were consumed.**

Tracked files: 246. API surface: **35 paths, 43 operations** (§E).

---

## B. Finding 1 — the Phase 8 renumbering was never finished

**Severity: highest in this report.** `CLAUDE.md` states the rule this breaks:

> The phase-status tables in `README.md`, `CLAUDE.md` and the roadmap must
> agree — they are the first thing a reader checks to learn what actually works.

They do not agree. Phase 8 moved telephony from 8 to 9, shifted everything
below it by one, and absorbed the old Phase 13 "React dashboard" into Phase 8.
That renumbering was applied to **three** places and missed **five**.

| Surface | Renumbered |
|---|---|
| `docs/DEVELOPMENT_ROADMAP.md` phase-status table | yes |
| `CLAUDE.md` phase table + renumbering note | yes |
| `README.md` capability table (line 159) | yes |
| `README.md` phase-status table and prose | **no — §B.1** |
| `docs/DEVELOPMENT_ROADMAP.md` body sections | **no — §B.2** |
| Backend docstrings and one API error message | **no — §B.3** |
| `CLAUDE.md` prose | **no — §B.4** |
| `ARCHITECTURE.md`, `CALLER.md`, `PIPELINE.md`, `PROVIDERS.md`, `DATABASE.md` | **no — §B.5** |

The reference numbering, after Phase 8:

| # | Phase |
|---|---|
| 8 | Operator Workspace & Public Site — complete |
| 9 | Twilio Telephony & Media Streaming |
| 10 | Conversation Orchestration Engine |
| 11 | Automated Evaluation & Scoring |
| 12 | Multilingual Benchmarking |
| 13 | Results API & Reporting |
| 14 | CI Regression Testing |
| 15 | Hardening, Observability & Release |

So a pre-renumbering reference to phases 8–12 is now one too low; references to
14 and 15 are still correct, because absorbing the old Phase 13 freed the slot.

### B.1 `README.md` understates the project by three phases

| Line | Says | Should say |
|---|---|---|
| `README.md:9` | `### Project status: Phases 1–5 of 15 complete` | Phases 1–8 of 15 |
| `README.md:149` | `Phases 1 to 7 are delivered.` | Phases 1 to 8 |
| `README.md:785` | Phase 6 "AI caller simulation (Gnani Evon)" — Not started | Complete; deterministic engine, Evon **not** integrated |
| `README.md:786` | Phase 7 "Audio degradation pipeline" — Not started | Complete |
| `README.md:787` | Phase 8 "Twilio telephony & media streaming" — Not started | 8 is the operator workspace and is complete; telephony is 9 |
| `README.md:788`–`791` | phases 9–12 at the old numbering | shift by one |
| `README.md:792` | Phase 13 "React dashboard" — Not started | absorbed into Phase 8; row should go |
| `README.md` table | no `7.1` row | the roadmap has one |

`README.md` therefore **contradicts itself**: line 159 says the operator
workspace is "Done (Phase 8)" while line 787 says Phase 8 is telephony and not
started.

Two notes on severity. This errs toward *understating* what works, which is the
safe direction and not a rule-one violation — but it is still wrong, and a
reader checking the status table concludes that the caller engine, the pipeline
and the workspace do not exist. Separately, `README.md:785` names Phase 6's
deliverable as "AI caller simulation (Gnani Evon)", which is the framing
`CLAUDE.md` exists to prevent: Phase 6 shipped a deterministic rule engine
precisely because no Evon endpoint is published.

### B.2 The roadmap's body sections were never renumbered

The status table at `docs/DEVELOPMENT_ROADMAP.md:24` is correct. Every body
heading below Phase 7 is not.

| Heading on disk | Line | Table calls it |
|---|---|---|
| `## Phase 8 — Twilio Telephony & Media Streaming` | 479 | Phase 9 |
| `## Phase 9 — Conversation Orchestration Engine` | 495 | Phase 10 |
| `## Phase 10 — Automated Evaluation & Scoring` | 509 | Phase 11 |
| `## Phase 11 — Multilingual Benchmarking` | 523 | Phase 12 |
| `## Phase 12 — Results API & Reporting` | 536 | Phase 13 |
| `## Phase 13 — React Dashboard` | 547 | **absorbed into Phase 8** — should be removed |
| `## Phase 14 — CI Regression Testing` | 561 | Phase 14 — correct |
| `## Phase 15 — Hardening, Observability & Release` | 574 | Phase 15 — correct |

Also missing from the body: **a section for Phase 8** (the operator workspace —
the delivered phase has no body entry at all) and **a section for Phase 7.1**,
which the table lists as complete.

The practical effect: `## Phase 8 — Twilio Telephony & Media Streaming` opens
with "The first phase that can place a real call, and therefore spend real
money" — directly under a table saying Phase 8 is complete.

### B.3 Twenty-one backend references, and one message a user can see

Grouped by the shift each needs.

**Telephony — "Phase 8" should read Phase 9:**

| Location | Text |
|---|---|
| `backend/app/pipeline/engine.py:161` | "Telephony arrives in Phase 8; a run cannot be created in that mode until it genuinely exists." |
| `backend/app/api/v1/speech.py:7` | "a telephony stream (Phase 8)" |
| `backend/app/api/v1/transcription.py:16` | "Phase 8's Twilio Media …" |
| `backend/app/core/config.py:12` | "Twilio (Phase 8) and the run-safety limits" |
| `backend/app/core/config.py:98` | "Phase 8's Twilio settings stay in `.env.example`" |
| `backend/app/pipeline/bots/manual.py:11` | "until a bot publishes an API or Phase 8 builds telephony" |
| `backend/app/pipeline/modes.py:53` | "Declared so that the vocabulary exists and Phase 8 has …" |
| `backend/app/repositories/caller_conversations.py:36` | "so Phase 8's telephony metadata can share the column" |
| `backend/app/speech/models.py:66` | "Phase 8 will put this audio down a telephone line" |

**Orchestration — "Phase 9" should read Phase 10:**
`backend/app/repositories/pipeline_runs.py:53`,
`backend/app/services/transcription_service.py:19`,
`backend/app/speech/base.py:74`, `backend/app/speech/base.py:99`,
`backend/app/speech/providers/timbre.py:159`,
`backend/app/speech/service.py:20`.

**Evaluation — "Phase 10" should read Phase 11:**
`backend/app/api/v1/caller.py:298`, `backend/app/caller/orchestrator.py:108`,
`backend/app/pipeline/modes.py:169`, `backend/app/schemas/caller.py:133`.

**Benchmarking a second engine — "Phase 11" should read Phase 12:**
`backend/app/transcription/models.py:5`,
`backend/app/transcription/__init__.py:14`.

**Correct, leave alone:** the authentication references to Phase 15
(`backend/app/api/v1/caller.py:18`, `backend/app/api/v1/test_runs.py:9`,
`backend/app/api/v1/test_runs.py:32`) and the frontend references to Phase 8
(`frontend/components/marketing/chrome.tsx:21`,
`frontend/components/ui/status.tsx:4`, `docs/ARCHITECTURE.md:344`).

**`backend/app/pipeline/engine.py:161` is the one that matters most.** It is not
a comment — it is the body of a `PipelineConfigurationError` returned to an API
caller who requests `telephony_test`. As written it tells them telephony
arrives in a phase that is already complete. If only one item in this report is
fixed, fix that one.

### B.4 `CLAUDE.md`'s own prose

The instructions carry four stale references, having renumbered their table but
not their body:

| Line | Text | Should read |
|---|---|---|
| `CLAUDE.md:72` | "so Phase 8's telephony metadata can share the column" | Phase 9 |
| `CLAUDE.md:81` | "deciding which turn a loose transcript belongs to is orchestration (Phase 9)" | Phase 10 |
| `CLAUDE.md:149` | "what lets Phase 11 benchmark a second engine" | Phase 12 |
| `CLAUDE.md:229` | "because evaluation is Phase 10" | Phase 11 |

### B.5 The reference docs

Same classes of error: `docs/ARCHITECTURE.md:66` (diagram), `:228`, `:248`,
`:289`, `:292`, `:423`, `:470`; `docs/CALLER.md:220`, `:250`;
`docs/PIPELINE.md:132`, `:631`, `:638`; `docs/PROVIDERS.md:49`, `:127`, `:221`,
`:264`, `:569`, `:1051`, `:1054`; `docs/DATABASE.md:16`, `:334`.

`docs/PROVIDERS.md:1051` is the most compressed instance — it carries three
stale numbers in one line: "(Phase 8), orchestration (Phase 9), scoring
(Phase 10)".

---

## C. Finding 2 — the documented test counts are 33 short

`README.md`'s per-module table sums to **1957** across 33 rows. `pytest`
collects **1990**. The gap is 33, isolated to exactly one module, and fully
attributable.

| | Documented | Actual |
|---|---|---|
| `backend/tests/test_pipeline_api.py` | 64 | **97** |
| Every other one of the 33 modules | — | matches exactly |
| **Total** | **1957** | **1990** |

**Cause, confirmed in git.** Commit `9b7c559` (`feat(api): list runs and serve
stored artefact audio`) added 385 lines to `test_pipeline_api.py`, taking it
from 64 to 96 `def test_` functions. One of those carries the module's single
`@pytest.mark.parametrize` over two values (`test_pipeline_api.py:1310`), so 96
definitions collect as 97 tests — the 33 new tests that commit's own message
claims. The code and its commit message are right; the documentation was never
updated.

Everywhere the stale figure appears:

| Location | Says | Should say |
|---|---|---|
| `CLAUDE.md:412` | "whole suite (1957 tests, 41 live ones deselected)" | 1990 tests, 41 live ones skipped |
| `README.md:279` | "1957 tests across 33 modules" | 1990 tests across 33 modules |
| `README.md:551` | "The backend suite has **1957 tests** in thirty-three modules" | 1990 |
| `README.md:551`–`552` | "1916 run by default" | **1949** run by default |
| `README.md:586` | `test_pipeline_api.py` row: 64 | 97 |
| `README.md:616` | sample output "1916 passed, 41 skipped in 78.70s" | "1949 passed, 41 skipped in 192.93s" |

**The same row's description is stale too.** `README.md:586` describes
`test_pipeline_api.py` as covering "the nine test-run routes". The test-runs
router now exposes **ten paths and eleven operations** — Phase 8 added
`GET /api/v1/test-runs` and
`GET /api/v1/test-runs/{run_id}/artifacts/{turn_index}/audio` — so the count in
the prose is two short, and the list that follows it mentions neither new
route.

**A wording defect rides along with the numbers.** Both `CLAUDE.md:412` and
`README.md:552` say the live tests are *deselected*. They are not — they are
collected and **skipped**, which is why the run reports `1949 passed, 41
skipped` and why the collected total is 1990 rather than 1949. In pytest those
are different mechanisms, and the distinction matters to anyone reconciling
these counts: deselected tests would not appear in the collected total at all.

The run is also about 2.5 times slower than the figure in `README.md:616`
(192.93 s against 78.70 s). That sample predates phases 6–8; it is not a
regression finding, just a stale transcript.

---

## D. Finding 3 — the `ruff format` gate's scope grew silently

`ruff format --check .` reports **235 files already formatted**; the Phase 8
report recorded 233. The delta is not new project code — **the repository
contains only 139 Python files, all tracked.** The count is inflated two ways.

**1. Ruff 0.17.3 formats Python code blocks inside Markdown.** Measured per
directory:

| Path | Files ruff counts | `.py`/`.pyi`/`.ipynb` present | `.md` present |
|---|---|---|---|
| `backend/` | 140 | 139 | — |
| `docs/` | 11 | **0** | **11** |
| `frontend/` | 1 | 0 | 1 (`AGENTS.md`) |
| `scenarios/` | 1 | 0 | 1 (`README.md`) |
| `.agents/` | **29** | **0** | many |
| `.claude/` | **50** | **0** | many |

`docs/` contributing exactly 11 — the exact number of `.md` files in it — is
what identifies the mechanism.

**2. `pyproject.toml:40`'s `extend-exclude` does not cover the agent-tooling
directories.** It lists `.venv`, `venv`, `frontend`, `__pycache__`,
`.ruff_cache`. The untracked `.agents/` (1632 files) and `.claude/` (64 files)
sit inside the repository and contribute **79 of the 235**.

Two consequences:

- A gate meant to measure this project's formatting is partly measuring
  vendored tool documentation that is not even tracked.
- The figure is **not reproducible** on a machine without those directories, so
  citing "235 files" in a report states a property of one developer's working
  tree. The project-code number is `backend/` → **140**. Writing *this report*
  took the repo-wide figure from 235 to **236**, which is the clearest possible
  illustration: a number that moves when you document it is not measuring the
  code.

`ruff check .` is unaffected — it passes, and reports no findings from those
paths. This is a reporting-hygiene defect, not a lint failure.

**It is not a hypothetical risk, and this report proved it.** The first draft of
this file contained a Python code block (§E) with three spaces before an inline
comment. `ruff format --check docs` immediately reported `1 file would be
reformatted` — a Markdown document failing the Python formatting gate, with no
Python source touched. The block was corrected to two spaces and the gate is
clean again. Any future `.md` file in a non-excluded directory can break
`ruff format --check .` the same way.

---

## E. Finding 4 — counting endpoints no longer works the old way

Not a defect; recorded so the next audit does not lose time to it.

The installed FastAPI mounts included routers lazily as internal
`_IncludedRouter` objects rather than flattening them into `app.routes`.
Walking `app.routes` now yields **7** entries — `/`, `/health` and the four
docs routes, plus one opaque `_IncludedRouter` — which would read as "the v1
API is not mounted". It is mounted; the enumeration is wrong.

The OpenAPI document is the authority:

```python
app.openapi()["paths"]  # 35 paths, 43 operations
```

Verified surface: 35 paths and 43 operations across `/`, `/health` and the
`/api/v1` routers — caller (7 paths), test-runs (10), suites (5), scenarios
(5), speech (2), transcription (2), health (1), languages (1).

---

## F. Phase 8's seven limitations, re-verified

Each of §13's items in `docs/PHASE_08_IMPLEMENTATION_REPORT.md`, checked
against the code today.

| # | Limitation | Verdict | Evidence |
|---|---|---|---|
| 1 | `audio_fixture_test` cannot succeed through the API | **Still holds** | `backend/app/api/v1/test_runs.py:124` calls `build_adapter(adapter_name or settings.pipeline_bot_adapter)` with no `replies=`. The parameter exists (`registry.py:56`) but the route never passes it, so turn 0 raises at `bots/scripted.py:88`. |
| 2 | `offline_simulation` never reaches a terminal status | **Holds, with a nuance** | `pipeline/engine.py:743` does close the run when the caller state is already terminal (`:749`–`:750`), so it is not unconditional. But offline moves no audio (`engine.py:170`, `uses_audio`), nothing supplies a bot reply, the caller never becomes terminal, and the run stays `running`. |
| 3 | Screenshots show a flat caller waveform | **Not re-verified** | Configuration-dependent and asserted in Phase 8 by decoding the PCM. This audit did **not** re-decode the artefacts and makes no claim either way. |
| 4 | No frontend test suite | **Still holds** | `frontend/package.json` has no `test` script and no `vitest`, `jest`, `playwright` or `@testing-library` dependency; zero `*.test.*` / `*.spec.*` files outside `node_modules`. Gates remain `tsc`, `eslint`, `next build`. |
| 5 | No run auto-refresh | **Still holds** | No `setInterval`, `EventSource` or `router.refresh` anywhere in `frontend/app`, `components` or `lib`. The only `revalidate` is a 3600 s cache on the languages call (`app/app/providers/page.tsx:62`, `app/app/scenarios/page.tsx:74`), visible in the build output as `/app/providers` 1 h. Polling versus SSE is still open. |
| 6 | Scenario detail, suite management and the audio lab not built | **Still holds** | `next build` emits 10 routes: `/`, `/_not-found`, `/app`, `/app/new-test`, `/app/providers`, `/app/runs`, `/app/runs/[runId]`, `/app/scenarios`. There is no `/app/scenarios/[id]` and no suite-editing route. |
| 7 | The workspace has no authentication | **Still holds** | No `HTTPBearer`, `APIKeyHeader`, `OAuth2` or auth dependency anywhere in `backend/app`. Consistent with the Phase 15 plan recorded at `api/v1/test_runs.py:32`. |

All six re-checkable limitations still hold. **Phase 8 reported its gaps
accurately.**

---

## G. Minor: `.env.example` reconciliation

Checked because `CLAUDE.md` requires `.env.example` to track configuration
changes. 40 `Settings` fields against 55 documented variables.

**Three `Settings` fields are not in `.env.example`:** `API_V1_PREFIX`,
`APP_NAME`, `APP_TAGLINE`. All three have working defaults and are branding or
routing rather than deployment configuration. **Probably deliberate — no action
proposed**, recorded only so a future audit does not re-derive it.

**Eighteen documented variables are not `Settings` fields**, and all are
accounted for:

- Future-phase placeholders held deliberately: `TWILIO_*`,
  `ALLOWED_BOT_NUMBERS`, `MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`,
  `MAX_CONCURRENT_CALLS`, `PUBLIC_BASE_URL`, `JUDGE_RETRIES`, `PASS_THRESHOLD`
  — the practice `backend/app/core/config.py:98` describes.
- Docker Compose variables, not application settings: `POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST_PORT`,
  `BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT`.
- Superseded in Phase 7 and documented as such at `README.md:475`:
  `AUDIO_STORAGE_PATH`, `NOISE_MASTER_SEED`.

No secret appears in `.env.example`. **This file is in good order.**

---

## H. Proposed Phase 8.1 scope

Offered for the owner's decision. Nothing here has been done.

### Tier 1 — documentation honesty (no behaviour change)

The case for doing this as its own increment: every item is a statement about
what works, which is rule one's subject matter, and none of it touches
behaviour, so it carries no phase-discipline risk.

1. `README.md` — rewrite the phase-status table to match the roadmap's, add the
   `7.1` row, drop the `13 React dashboard` row, fix lines 9 and 149, and
   correct the Phase 6 row so it does not name Evon as the deliverable (§B.1).
2. `docs/DEVELOPMENT_ROADMAP.md` — renumber body sections 8→9 through 12→13,
   remove `## Phase 13 — React Dashboard`, and add the two missing body
   sections for Phase 8 and Phase 7.1 (§B.2).
3. Source docstrings — the 21 references in §B.3, **`pipeline/engine.py:161`
   first**, since it is the only one an API caller can see.
4. `CLAUDE.md` — the four prose references in §B.4.
5. The five reference docs — §B.5.
6. Test counts — 1957→1990, 1916→1949, the `test_pipeline_api.py` row 64→97,
   "deselected"→"skipped", and refresh the sample output at `README.md:616`
   (§C).

A note on sequencing: items 1, 2 and 6 all touch `README.md` and the roadmap,
and `CLAUDE.md` requires the three phase tables to agree. They should land in
one commit so the tables are never momentarily inconsistent.

### Tier 2 — one small configuration fix

7. Add `.agents` and `.claude` to `extend-exclude` in `pyproject.toml`, then
   re-baseline the formatted-file count and record whether the project figure
   is cited as `backend/` (140) or repo-wide (§D).

### Tier 3 — recommend **excluding** from 8.1

These are real and already recorded in Phase 8 §13. They are listed here to
argue they do *not* belong in a documentation increment:

- **The two deferred backend fixes.** `audio_fixture_test`'s adapter
  construction (§F.1) and `offline_simulation`'s terminal status (§F.2) change
  pipeline behaviour. Phase 8 declined them as "a third backend change beyond
  the two this phase authorised". Fixing `audio_fixture_test` means shipping a
  fixture audio asset or changing adapter construction — a design decision, not
  a typo.
- **Frontend tests, auto-refresh, scenario detail, authentication.** Each is a
  feature with a phase: authentication is Phase 15 by existing decision, and
  polling-versus-SSE is an open design question from the Phase 8 audit.

Mixing Tier 3 into 8.1 would make a documentation-reconciliation commit also a
behavioural one, which is the kind of pull request `CLAUDE.md` says will be
asked to split.

---

## I. What this audit did not do

Stated plainly, because a report that omits its own limits is the failure mode
this project's first rule is about.

- **No file was modified, staged or committed.** `git status` is clean apart
  from the three untracked agent-tooling paths it started with. This report is
  the only new file.
- **No live provider call.** All 41 live tests were skipped; no Gnani credit was
  consumed.
- **Limitation 3 was not re-verified.** The flat-waveform claim needs the
  artefacts decoded; that was not done, and no verdict is offered (§F.3).
- **No browser verification.** Phase 8's manual browser checks were not
  repeated. The frontend evidence here is `tsc`, `eslint` and `next build` only
  — all clean, none of which exercises a rendered page.
- **No security review.** In particular, the untracked `.agents/` (1632 files)
  and `.claude/` (64 files) were inspected only for file extensions while
  diagnosing §D; their contents were not audited.
- **The proposed scope in §H is a proposal.** Phase 8.1 is not defined in the
  roadmap, and defining it is the owner's decision.

---

# J. Reconciliation record

Phase 8.1 was scoped as **documentation and quality-gate reconciliation
only**. No pipeline behaviour, feature, endpoint, schema or migration was
changed. The record below is actual command output, not a restatement of
intent.

| | |
|---|---|
| **Commits** | `e09b7fb` (Tier 1), `c1062a7` (Tier 2), plus the commit adding this record |
| **Branch** | `main` — no new branch, no force-push, no history rewritten |
| **Pushed** | `cea14be..c1062a7  main -> main`; `HEAD` = `origin/main` = `c1062a7`, 0 ahead / 0 behind |
| **Live Gnani calls** | **None.** All 41 live tests stayed opt-in and skipped; no credit consumed |
| **`.env`** | Untouched. No secret added, moved or logged |

## J.1 The four findings and what resolved each

| # | Finding | Resolution | Where |
|---|---|---|---|
| 1 | Phase numbering inconsistent across README, roadmap, backend and CLAUDE.md | README status table rewritten and prose corrected; roadmap body renumbered 8→9 … 12→13 with the absorbed Phase 13 removed and the missing Phase 8 section written; 21 backend references, 2 test docstrings and 4 CLAUDE.md prose references corrected; five reference docs corrected | both commits |
| 2 | Documented test counts 33 short (`test_pipeline_api.py` 64 vs 97 collected) | Row corrected to 97; the table now sums to 1990, matching collection exactly; headline figures restated as 1990 collected / 1949 passing / 41 skipped; "deselected" corrected to "skipped" | `e09b7fb` |
| 3 | Ruff gate counted Markdown code blocks and untracked tooling, so it did not measure tracked Python | `include` set without `*.md`; `.agents`/`.claude` excluded. Gate now reports 140 files and its scope is *provably* the tracked set | `c1062a7` |
| 4 | Endpoint counting via `app.routes` unreliable under lazy router inclusion | `scripts/api_surface.py` derives the figures from the OpenAPI schema; README and CLAUDE.md document the method and the reason | both commits |

## J.2 Two corrections to this report's own audit

Parts A–I are left unedited, so the two places they were wrong are recorded
here instead.

**§B.2 was wrong that Phase 7.1 had no body section.** It has one, as
`### Phase 7.1 — concurrency enforcement`, nested inside Phase 7 rather than
standing as its own `##` section. That is the right placement for a point
release, and nothing was restructured. Only the Phase 8 section was genuinely
missing.

**The audit missed the largest user-facing defect of all.** `main.py`'s
`DESCRIPTION` constant is passed to `FastAPI(description=...)`, so it is the
landing text at `/docs` and in `/openapi.json`. It listed implemented work
only as far as Phase 6 and then asserted that "Telephony, audio degradation
and automated evaluation are **not** implemented" — and Phase 7 shipped audio
degradation. That is a false statement about our own capability, in the
understating direction, served to every API consumer. Phases 7, 7.1 and 8 are
now listed, and the not-implemented line names only telephony and automated
evaluation.

The audit found this nowhere because §B.3 was assembled by grepping source for
`Phase N` and classifying each hit, which finds stale *numbers* and not absent
*phases*. Generating the OpenAPI document and grepping that is what found it,
and is the better check: it enumerates exactly what a client can read.

## J.3 Verification — actual output

Every figure below was produced after the final edit.

| Gate | Command | Result |
|---|---|---|
| Collection | `pytest --collect-only -q` | **1990 tests collected** |
| Full suite | `pytest -q` | **1949 passed, 41 skipped, 0 failed** (185.77 s) |
| Deselected | — | **0** — the live tests are collected and skipped, never deselected |
| Lint | `ruff check .` | **All checks passed!** |
| Format | `ruff format --check .` | **140 files already formatted** |
| Migrations | `alembic check` | **No new upgrade operations detected.** |
| API surface | `python scripts/api_surface.py` | **35 paths, 43 operations** |
| Frontend types | `npx tsc --noEmit` | Clean, exit 0 |
| Frontend lint | `npx eslint .` | Clean, exit 0 |
| Whitespace | `git diff --check` | Clean |

**The test figures reconcile exactly**: 1990 collected = 1949 passed + 41
skipped, and the README per-module table now also sums to 1990. Before this
work the table summed to 1957 and no documented figure matched any other.

### The Ruff scope is now provable, not approximate

The gate's file count is no longer a number to be trusted on assertion:

```
ruff scope: 141   tracked .py: 140
in ruff but untracked:    ['pyproject.toml']
tracked but outside ruff: (none)
```

`ruff check . --show-files` returns exactly the 140 files `git ls-files "*.py"`
reports, plus `pyproject.toml`, which Ruff lints for schema validity by
design. Nothing untracked is in scope; nothing tracked is omitted. That
equality is the invariant to re-check if the configuration is ever touched,
and it is written into both `README.md` and `CLAUDE.md`.

The scope is fixed in `pyproject.toml` rather than by narrowing the command,
so the documented local command and any future CI job share one scope by
construction. There is no second invocation to drift, and no check was
disabled. **No file count is hardcoded in any tooling** — `api_surface.py`
derives its figures, and the Ruff invariant is checked against `git ls-files`.

> There is no CI workflow yet: `.github/workflows/` holds only `.gitkeep`,
> because CI is Phase 14. "CI and local use the same scope" therefore means
> the configuration makes divergence impossible, not that a pipeline was
> verified.

### The three phase tables agree, checked by parsing

Not by reading. Parsing the tables out of all three files and comparing every
phase number they share:

```
roadmap rows : ['1','2','3','4','5','6','7','7.1','8','9','10','11','12','13','14','15']
README  rows : ['1','2','3','4','5','6','7','7.1','8','9','10','11','12','13','14','15']
CLAUDE  rows : ['1','2','3','4','5','6','7','7.1','8']      # then "9-15 | Not started"

DISAGREEMENTS: 0
```

`CLAUDE.md` deliberately collapses the unstarted tail into one row; the 7.1
row it was missing has been added so all three carry it.

## J.4 Files changed

26 files across the two commits, plus this report.

| Area | Files |
|---|---|
| User-facing strings | `backend/app/main.py` (the `/docs` description), `pipeline/engine.py` (the returned error), `api/v1/caller.py`, `schemas/caller.py` (both OpenAPI descriptions) |
| Backend comments and docstrings | `api/v1/speech.py`, `api/v1/transcription.py`, `caller/orchestrator.py`, `core/config.py`, `pipeline/bots/manual.py`, `pipeline/modes.py`, `repositories/caller_conversations.py`, `repositories/pipeline_runs.py`, `services/transcription_service.py`, `speech/base.py`, `speech/models.py`, `speech/providers/timbre.py`, `speech/service.py`, `transcription/__init__.py`, `transcription/models.py` |
| Test docstrings | `test_caller_api.py`, `test_caller_orchestrator.py` |
| Project docs | `README.md`, `CLAUDE.md`, `docs/DEVELOPMENT_ROADMAP.md`, `docs/ARCHITECTURE.md`, `docs/CALLER.md`, `docs/DATABASE.md`, `docs/PIPELINE.md`, `docs/PROVIDERS.md` |
| Configuration | `pyproject.toml` (Ruff scope only) |
| New | `scripts/api_surface.py` |

**Every backend change is a comment or a docstring.** Verified by extracting
each changed line from `git diff backend/`: all of them are prose differing
only in a phase number. No exception type, control-flow branch, signature,
default or constant changed.

Deliberately **not** staged: `.agents/`, `.claude/`, `skills-lock.json`. They
remain untracked local tooling. Nothing was staged with `git add .`.

## J.5 What was deliberately left alone

Correcting a reference that is already right would have been the same class of
error in the other direction.

- **Phase 15 authentication references** (`api/v1/caller.py:18`,
  `api/v1/test_runs.py:9`, `:32`) — authentication is still Phase 15.
- **Phase 8 references that mean the frontend** — `docs/ARCHITECTURE.md:344`,
  `docs/PIPELINE.md:326`, `docs/FRONTEND.md:85`, two frontend component
  comments and two test comments.
- **`frontend/lib/content.ts` needed no change at all.** It already carried
  the post-renumbering list and `currentPhase = 8`. The frontend was the one
  surface that got the renumbering right.
- **`docs/PHASE_08_FRONTEND_AUDIT.md` keeps its 1916-test and 34-path
  figures.** It is a dated audit and those were true when it was written.
  Rewriting history to match the present would destroy the record.
- **The roadmap's "Nine endpoints under `/api/v1/test-runs`"** is kept as a
  statement about what Phase 7 delivered, annotated with what Phase 8 added,
  rather than silently overwritten.
- **`.env.example`** — §G found it already in good order.

## J.6 One superseded decision, now recorded

Phase 7 listed "serving stored audio over HTTP" as out of scope until
Phase 15, because who may hear a recorded conversation is an authorisation
decision with no identity to make it against. Phase 8 shipped that route
anyway, gated on `PIPELINE_SERVE_ARTEFACTS` and refusing with 403 in staging
and production.

The roadmap asserted the Phase 7 position while the code did the Phase 8
thing. Both places now record the supersession, and that real access control
remains Phase 15. No behaviour changed — only the documentation stopped
contradicting the code.

## J.7 What remains unresolved

**Both deferred pipeline defects are still open. Neither was touched, and
nothing in these commits should be read as fixing either.**

| Defect | Status | Evidence it still holds |
|---|---|---|
| **`AUDIO_FIXTURE_TEST` cannot complete through the API** | **Unresolved** | `api/v1/test_runs.py:124` still calls `build_adapter(adapter_name or settings.pipeline_bot_adapter)` with no `replies=`, so the scripted adapter has no replies and turn 0 raises at `bots/scripted.py:88` |
| **`OFFLINE_SIMULATION` does not terminate correctly** | **Unresolved** | Offline moves no audio (`engine.py:170`), nothing supplies a bot reply, the caller never reaches a terminal state, and the run stays `running` |

Both now appear in three places that previously omitted them: the README's
Phase 8 status block, the new roadmap Phase 8 section under "Reported, not
fixed", and this report. Fixing either changes pipeline behaviour and is out
of scope for a documentation increment — `audio_fixture_test` in particular
needs a fixture audio asset or a change to adapter construction, which is a
design decision.

Also still open, each a feature with a phase rather than a defect: no frontend
test suite, no run auto-refresh (polling versus SSE is undecided), no scenario
detail or suite-management UI, and no authentication anywhere in the
application.

## J.8 Limitations of this reconciliation

- **No browser verification.** The frontend evidence is `tsc` and `eslint`
  only. Neither renders a page, and `next build` was not re-run after the
  final edits because no frontend file changed in either commit.
- **Part F.3 is still unverified.** The flat-caller-waveform claim needs the
  artefacts decoded; that was not done, and no verdict is offered.
- **The untracked tooling directories were not audited.** `.agents/` (1632
  files) and `.claude/` (64 files) were inspected only for file extensions
  while diagnosing Finding 3. They are now excluded from Ruff, which reduces
  the gate's exposure to them but is not a review of their contents.
- **No security review was run** as part of this work.
- **The phase-table agreement check is a script run once, not a test.**
  Nothing in the suite fails if the three tables drift apart again. Making
  that a real test would be a worthwhile small addition, and is not part of
  this increment.
