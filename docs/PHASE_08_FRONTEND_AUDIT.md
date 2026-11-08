# Phase 8 — Frontend Audit, Design Preparation & Tooling Verification

**Status:** Audit only. No frontend implementation has been performed.
**Date:** 2026-11-08
**Branch:** `main`
**Commit audited:** `6bb9104c420456141808d959383cc2111fefddf4`

> This document is a baseline record, not a design proposal that has been
> approved. No visual reference has been supplied yet, so no palette, type
> scale or component design is committed here. Everything in sections 16–17 is
> a recommendation awaiting approval.

---

## 1. Executive summary

BhashaBench has a substantial, carefully-built backend and an almost non-existent
frontend. The gap between the two is the headline finding.

The backend exposes **34 paths / 42 operations** across suites, scenarios,
transcription, speech, the caller engine and the pipeline. Its response schemas
are unusually honest: `evon_status`, `telephony_status`,
`bot_audio_externally_received`, `uses_language_model` and `measurement_note`
are fields that exist specifically to stop a client overclaiming. A frontend
built on this API can be truthful almost for free, because the truth is already
in the payloads.

The frontend is **one static marketing route** (`/`) with six presentational
components, no API client, no data fetching, no state management and no tests.
It renders a hand-maintained constant file, not the product.

Five findings matter most:

1. **The landing copy is factually stale and now contradicts itself on screen.**
   The page tells visitors "The Phase 1 backend is a running FastAPI service.
   These three endpoints work" (42 operations exist) and "no speech is
   processed" (Phases 4, 5 and 7 process speech), while two cards directly above
   are badged **Partial**. See §12.1. This is the inverse of the usual honesty
   risk — it *understates* — but it is still the UI stating something untrue.
2. **There is no way to retrieve a stored audio artefact.** `ArtefactResponse`
   returns a storage-relative `reference`, but there is no download route and no
   `StaticFiles` mount anywhere in the backend. The audio-centric conversation
   inspector that is the natural centre of this product **cannot be built**
   without a new endpoint. See §19.1.
3. **The Docker backend has been failing for 34 hours** on a stale image
   (`ModuleNotFoundError: No module named 'websockets'`). The dependency is
   correctly declared; the image predates it. See §9.
4. **Mobile navigation does not exist.** Below 768 px the entire `<nav>` leaves
   the accessibility tree with no replacement control. See §18.2.
5. **The `--text-tertiary` token fails WCAG AA** for normal text on every
   surface it is used on (measured 3.79–4.25 against a 4.5 requirement),
   affecting 27 distinct text runs. See §18.1.

Design tooling is in better shape than expected: all three requested design
skills are present on disk, Figma MCP authenticates, and Playwright drove the
real browser for every measurement in this report.

---

## 2. Repository state and current commit

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `6bb9104c420456141808d959383cc2111fefddf4` |
| HEAD subject | `fix(pipeline): enforce the concurrent-run limit that nothing was reading` |
| Remote | `https://github.com/YushBytes/BhashaBench.git` |
| Working tree | Clean except untracked tooling (below) |

Verified — the commit named in the brief **is** still HEAD.

Untracked before this audit: `.agents/`, `.claude/`, `skills-lock.json`
(design-skill installation, not project code). This audit adds
`docs/PHASE_08_FRONTEND_AUDIT.md` and `docs/phase-08-audit/screenshots/`.

Quality gates re-run at this commit:

| Gate | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | 232 files already formatted |
| `npx tsc --noEmit` (frontend) | exit 0, no errors |
| `npx eslint .` (frontend) | exit 0, no findings |
| `pytest` | **1916 passed, 41 skipped, 0 failed** (79 s) |

---

## 3. Frontend architecture

Everything below was read from source, not assumed.

| Aspect | Finding |
|---|---|
| Framework | Next.js **16.4.3** |
| React | **19.3.0** |
| Router | **App Router** (`frontend/app/`). No `pages/` directory exists. |
| Language | TypeScript 5, `strict: true` |
| Styling | **Tailwind CSS v4**, CSS-first config via `@theme inline` in `app/globals.css`. **There is no `tailwind.config.js`** — v4 declares the theme in CSS. |
| Build | Turbopack, with an explicit `@tailwindcss/turbopack` CSS loader rule in `next.config.ts` |
| Next flags | `cacheComponents: true`, `partialPrefetching: true` |
| Fonts | `Geist` and `Geist_Mono` via `next/font/google`, bound to `--font-geist-sans` / `--font-geist-mono` |
| Icon library | **None.** The only vector is an inline 4-rect SVG wordmark in `site-header.tsx` |
| Charting library | **None** |
| State management | **None** |
| Data fetching / API client | **None.** No `fetch`, no client, no SWR/React Query |
| Auth | **None** |
| Client components | **None.** There is no `"use client"` anywhere; every component is a Server Component |
| Tests | **None.** No test runner, no test files in `frontend/` |
| Path alias | `@/*` → `./*` |

**Dependency list is three packages** (`next`, `react`, `react-dom`) plus dev
tooling. Nothing has been added speculatively — which is good discipline, and
also means the entire dashboard dependency set is still an open decision.

### 3.1 Design tokens

`app/globals.css` is the single token source. The product deliberately commits
to **one dark theme** (`color-scheme: dark`) rather than following the system —
the comment in the file explains this is a developer tool meant to sit beside a
terminal, and one palette keeps status colours unambiguous.

| Group | Tokens |
|---|---|
| Surfaces | `--surface-base #07090d`, `--surface-raised #0d1118`, `--surface-overlay #121823` |
| Borders | `--border-subtle #1b2230`, `--border-strong #2a3444` |
| Text | `--text-primary #e7eaf0`, `--text-secondary #9aa4b6`, `--text-tertiary #6b7488` |
| Accent | `--accent #7f9cff`, `--accent-strong #9db1ff`, `--accent-dim #1d2740` |
| Status | `--status-live #4ade80`, `--status-partial #fbbf24`, `--status-planned #64748b` |

The status vocabulary is fixed and documented in the CSS: `live` = verified
working today, `partial` = exists but intentionally incomplete, `planned` = not
built. **This vocabulary is an asset and should survive the redesign.**

Two global behaviours already exist and are correct: a single
`:focus-visible` ring (2 px accent, 2 px offset), and a
`prefers-reduced-motion` block that neutralises animation and transition
duration.

### 3.2 Responsive breakpoints

Tailwind defaults only — `sm` 640, `md` 768, `lg` 1024. Used sparingly:

- `sm:` — type scale bumps, section padding, footer direction, header phase chip
- `md:` — the **only** thing controlling nav visibility (`hidden md:flex`)
- `lg:` — the capability grid's third column

Layout container is `max-w-6xl` (1152 px) with `px-6`. Hero text is capped at
`max-w-3xl` (768 px), body copy at `max-w-2xl`.

---

## 4. Existing route inventory

| Route | File | Type | Notes |
|---|---|---|---|
| `/` | `app/page.tsx` | Static Server Component | The only route in the application |

Supporting files: `app/layout.tsx` (root layout), `app/globals.css`,
`app/favicon.ico`.

**Absent:** `loading.tsx`, `error.tsx`, `not-found.tsx`, `template.tsx`, route
groups, dynamic segments, parallel/intercepting routes, route handlers,
middleware, `sitemap.ts`, `robots.ts`, `opengraph-image`.

The four header "nav" items are **in-page anchors** (`#overview`, `#test-suite`,
`#api`, `#roadmap`), not routes. The application has no client-side navigation
of any kind.

---

## 5. Existing component inventory

Six components, all server-rendered, all presentational.

| Component | Props | Purpose | Reusable in a dashboard? |
|---|---|---|---|
| `status-pill.tsx` | `status: "live" \| "partial" \| "planned"`, `label?` | Status chip with fixed colour semantics | **Yes — highest value.** The vocabulary maps directly onto run status, provider availability and mode honesty |
| `section.tsx` | `id`, `eyebrow`, `title`, `intro?`, `children` | Titled page section with consistent heading hierarchy and `aria-labelledby` | Partly — it is a marketing section, but the eyebrow/title/intro rhythm is worth keeping |
| `capability-card.tsx` | `capability: Capability` | Card with title + status pill + summary | Pattern yes, content no |
| `roadmap-list.tsx` | none (reads `phases`) | Zebra-striped ordered list of the 15 phases | Pattern only |
| `site-header.tsx` | none | Sticky header, wordmark, anchor nav, GitHub link | Needs replacement for an app shell |
| `site-footer.tsx` | none | Phase/version footer | Minor |

### 5.1 The content module

`lib/content.ts` is a typed constant file holding `site`, `apiBaseUrl`,
`phases`, `capabilities`, `endpoints` and `navigation`. Its header comment is
explicit that this is deliberate:

> Kept as typed constants rather than fetched from the API on purpose: the
> endpoints that would serve roadmap and capability data do not exist yet, and
> inventing a client for them would mean shipping a fake integration.

That reasoning was sound when written. It is now **partly obsolete** — the
`endpoints` constant lists 3 endpoints when the API serves 42, and
`GET /api/v1/health` could supply real subsystem status today. See §12.1.

`apiBaseUrl` reads `NEXT_PUBLIC_API_BASE_URL` with a `http://localhost:8000`
fallback, and is used **only** to build two outbound links. Nothing fetches.

---

## 6. Design skills verification

All three requested skills are **present on disk**. Only one is **registered
with this Claude Code session**. That distinction matters and is reported
separately rather than collapsed.

| Skill | On disk | Path | Registered this session | Invocable as |
|---|---|---|---|---|
| **Impeccable Design** | ✅ Yes | `.claude/skills/impeccable/` | ✅ **Yes** | `/impeccable` |
| **Emil Design Engineering** | ✅ Yes | `.agents/skills/emil-design-eng/SKILL.md` | ❌ **No** | — (readable as a file only) |
| **Taste / design-taste-frontend** | ✅ Yes | `.agents/skills/design-taste-frontend/` | ❌ **No** | — (readable as a file only) |

**Why two are not registered:** Claude Code discovers project skills under
`.claude/skills/`. The installer placed Emil and Taste under `.agents/skills/`,
which Claude Code does not scan. `skills-lock.json` records both as installed —
which is exactly the "selected during an installer process" claim the brief
warned against trusting. They are installed; they are not *loaded*.

Their content is still fully usable: I read both SKILL.md files directly from
disk and applied their principles in §12 and §16. The practical losses are (a)
no `/emil-design-eng` or `/design-taste-frontend` invocation, and (b) the
Taste skill's declared `Stop` gate hook (`scripts/gate.mjs`) **does not run**.

**Impeccable is active and hooked.** `.claude/settings.local.json` registers
three hooks (`SessionStart`, `PostToolUse` on Edit|Write, `Stop`) that run
`.claude/skills/impeccable/scripts/impeccable hook`, and
`.impeccable/config.local.json` records `"consent": "accepted"`. Its
reference library is complete (41+ reference documents including
`operate.md`, `mode-operate.md`, `craft-floor.md`, `audit.md`, `critique.md`).
Four Impeccable subagents are registered in `.claude/agents/`.

### 6.1 Which skill fits this work

Worth stating, because they are not interchangeable:

- **Impeccable** is the right primary skill. It has an explicit **Operate** mode
  ("the visitor completes a task… app UI, dashboards, editors, admin, settings,
  tools") with dedicated references. A test-bench dashboard is Operate work.
- **Taste (`design-taste-frontend`)** is a *marketing-site* skill — its own
  description targets landing pages and company sites, and its house rules
  ("one section per screen", "12 to 20 photographs", hero entrances, dealt
  moments) are Persuade-mode rules that would actively damage a dense
  operator dashboard. It is the right tool **only** if a public BhashaBench
  landing page is also wanted. It also requires Node 22+ and Chrome; Node
  24.18.1 is present.
- **Emil Design Engineering** is a philosophy/polish layer (craft, motion
  judgement, invisible detail), not a workflow. Best applied as a review lens
  over whatever Impeccable produces.

**Recommendation:** fix the skill paths before implementation begins — copy or
symlink the two `.agents/skills/` entries into `.claude/skills/` so they can be
invoked. Awaiting your approval (Q6, §21).

---

## 7. Figma MCP verification

**Status: authenticated and working (read-only tested).**

Verified by invoking the read-only `whoami` capability. No file was created,
edited or published.

| Field | Value |
|---|---|
| Server | `plugin:figma:figma` v2.2.157 |
| Handle | Ayush Bidwai |
| Plan | `Ayush Bidwai's team` |
| Tier | **starter** |
| Seat | **View** |
| Role | admin |
| `code_layers_enabled` | true |
| `specs_enabled` | true |

**Material limitation:** the seat is **View**, on a **starter** tier. A View
seat is read-only. Write-path tools (`use_figma`, `create_new_file`,
`generate_figma_design`, `html_to_figma`) are very likely to fail on permission,
and starter tier constrains shared libraries and branching.

I did **not** test a write call, because the brief forbids creating or editing
Figma files. So this is stated as *expected from the seat type*, not as a
measured failure.

**Consequence for Phase 9:** do not plan a Figma-first workflow (design in
Figma → `get_design_context` → code). Plan a **code-first** workflow and use
Figma for reading any reference file you supply. If you want Figma as the
source of truth, the seat needs upgrading first (Q5, §21).

---

## 8. Playwright MCP verification

**Status: fully working. Every measurement in §10, §11, §12 and §18 came from
the real browser, not from reading CSS.**

Exercised and confirmed: `browser_navigate`, `browser_resize`,
`browser_take_screenshot` (viewport + `fullPage`), `browser_snapshot`
(accessibility tree), `browser_console_messages`, `browser_evaluate`,
`browser_close`.

Playwright writes scratch files to `.playwright-mcp/` in the workspace root;
these were removed after the audit and are not part of the commit.

### 8.1 Chrome automation (`claude-in-chrome`)

**Not used.** Playwright covered every requirement, and the brief says to use
Chrome automation only if genuinely necessary. Its tools were never loaded, so
this report makes **no claim** about whether that server is operational.

---

## 9. Application startup results

### 9.1 Docker — backend is broken

Three project containers were already running (34 h uptime):

| Container | State | Port |
|---|---|---|
| `bhashabench-db` | Up, **healthy** | 5434→5432 |
| `bhashabench-backend` | Up, **unhealthy** (3589 consecutive failures) | 8000 |
| `bhashabench-frontend` | Up | 3000 |

`GET http://localhost:8000/health` returns nothing. Root cause from
`docker logs`:

```
File "/app/app/transcription/providers/prisma.py", line 25, in <module>
    from websockets.asyncio.client import connect as ws_connect
ModuleNotFoundError: No module named 'websockets'
```

Uvicorn cannot import the ASGI app, so the process crash-loops.

**This is a stale image, not a missing declaration.** `backend/requirements.txt`
declares `websockets~=17.4` with an explicit comment about why it is pinned
directly. The running image was built 6 days ago, before that dependency landed
in the image layer. The local venv has `websockets 17.4` and works fine.

**Fix (not applied — outside audit scope):** `docker compose build backend`,
then `docker compose up -d backend`.

### 9.2 Local backend — works

Started from the existing venv without modifying anything:

```
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Port 8001 was used deliberately to leave the crash-looping container's port
binding untouched.

`GET /api/v1/health` →

```json
{
  "status": "ok", "service": "BhashaBench", "version": "0.1.0",
  "api_version": "v1", "environment": "development",
  "components": [
    {"name": "api",           "status": "ok", "detail": "FastAPI application is serving requests."},
    {"name": "configuration", "status": "ok", "detail": "Settings loaded for environment 'development'; .env file present, DATABASE_URL default."},
    {"name": "database",      "status": "ok", "detail": "Connected; SELECT 1 succeeded."}
  ]
}
```

Database connectivity confirmed. `DATABASE_URL`'s port and `POSTGRES_HOST_PORT`
**agree** (both 5434) — the mismatch trap called out in `CLAUDE.md` is not
present. No secret values are reproduced in this report.

### 9.3 Frontend — works

`npx next dev --port 3001` → ready in 2.1 s, `GET / 200`. Port 3001 to avoid the
container on 3000. All screenshots in this report are of **current `main`
source**, not the 6-day-old container image.

Browser console on the rendered page: **zero application errors.** The only
console output is Next.js dev-server HMR WebSocket handshake noise, which is a
dev-only artefact and absent from a production build.

### 9.4 Test suite

`ruff check` and `ruff format --check` pass (232 files). Frontend `tsc --noEmit`
and `eslint` both exit 0 with no findings.

The full backend suite passes at this commit:

```
1916 passed, 41 skipped in 79.45s
```

Total 1957, matching the count documented in `CLAUDE.md`. All 41 skips are the
**opt-in billable live-provider tests** — 26 in `test_speech_live.py` (gated on
`SPEECH_LIVE_TESTS`) and 15 in `test_transcription_live.py` (gated on
`TRANSCRIPTION_LIVE_TESTS`). They are correctly skipped: running them would
make real, billable calls to Gnani Timbre and Prisma, which the brief forbids.
No other test skipped, and **no test was modified or weakened by this audit.**

### 9.5 Runtime configuration observed

| Observation | Detail |
|---|---|
| Selected STT provider | **`fake`** — `.env` does not set `TRANSCRIPTION_PROVIDER`, so the default applies |
| Selected TTS provider | **`fake`** — same, for `SPEECH_PROVIDER` |
| Selected caller provider | `deterministic` |
| Selected bot adapter | `scripted` |
| Database contents | **Empty** — 0 suites, 0 scenarios |
| Scenario files on disk | 6 YAML scenarios + 1 bundle, none loaded into the DB |

The database being empty is important for design: **the first thing a new user
sees is every empty state at once.** Empty states are not a polish item on this
product; they are the default screen. The DB was deliberately **not** seeded by
this audit.

That `fake` is selected is also a design input: the UI must surface the selected
provider prominently, because a run executed against `fake` establishes nothing.
`GET /api/v1/transcription/providers` already returns `selected`, so this is
free.

---

## 10. Desktop baseline screenshots

Saved to `docs/phase-08-audit/screenshots/`. No pre-existing screenshot was
overwritten — the directory was created by this audit.

| File | Viewport | Capture |
|---|---|---|
| `desktop-1440x900-viewport.png` | 1440 × 900 | Above the fold |
| `desktop-1440x900-fullpage.png` | 1440 × 900 | Full page (2994 px tall) |
| `desktop-1920x1080-viewport.png` | 1920 × 1080 | Above the fold |
| `desktop-1920x1080-fullpage.png` | 1920 × 1080 | Full page |

**These are baseline captures of the current implementation. They are not
proposed designs.**

A note on method: an early 1440 capture landed on `#test-suite` instead of the
hero. I verified on a clean load that `scrollY` is 0 with no hash — the jump was
scroll-state carried over from my own `resize` call inside the same browser
session, **not** a product defect. The baseline was re-captured from the top.

---

## 11. Mobile baseline screenshots

| File | Viewport | Capture |
|---|---|---|
| `mobile-390x844-viewport.png` | 390 × 844 (iPhone 14/15) | Above the fold |
| `mobile-390x844-fullpage.png` | 390 × 844 | Full page |
| `mobile-375x812-viewport.png` | 375 × 812 (iPhone X/11 Pro) | Above the fold |
| `mobile-375x812-fullpage.png` | 375 × 812 | Full page |

**No horizontal page overflow at either width** — measured
`documentElement.scrollWidth === clientWidth` (375 = 375). Confirmed clean.

---

## 12. Current UX and design problems

Ordered by severity. Every item was observed in the rendered browser.

### 12.1 Critical — the page states things that are not true

Three rendered strings are now false, and one directly contradicts a badge
sitting a few pixels away.

| Location | Rendered text | Why it is wrong |
|---|---|---|
| Hero caveat, `app/page.tsx` | "This is the foundation release… **No calls are placed, no speech is processed and no scores are produced yet.**" | Phases 4, 5 and 7 process speech. Prisma transcribes, Timbre synthesises, the pipeline runs both end to end. Only "no calls are placed" and "no scores" remain true. |
| API section intro | "The **Phase 1 backend** is a running FastAPI service. **These three endpoints work; everything else returns 404** until a later phase adds it." | The API serves **34 paths / 42 operations**. The claim is wrong by an order of magnitude. |
| Test-suite intro | "These are the capabilities the platform is being built to exercise — **none of them are implemented yet**…" | Self-contradicting: two cards in the grid directly beneath are badged **Partial**, and the roadmap below marks Phases 1–5 **Live**. |
| `endpoints` in `lib/content.ts` | 3 entries | Stale by 39 operations |

`CLAUDE.md`'s first rule is "never claim something works when it does not." This
is the mirror image — the UI claims things *do not* work when they do — but the
rule's purpose (the interface tells the truth about the system) is broken either
way, and the self-contradiction is visible on a single screen.

Note this is a *copy* defect, not a status-data defect: `lib/content.ts`'s
`phases` array is correctly maintained (1–5 `live`, 6–7 `partial`, 8–15
`planned`), and the deliberate choice to mark 6 and 7 `partial` rather than
`complete` — because Evon is not integrated and no live bot has been tested —
is **more** conservative than the docs' "✅ Complete (Evon not integrated)". That
judgement is good and should be preserved.

### 12.2 High — the layout does not use a desktop screen

Measured at a 1425 px viewport: the `h1` occupies **768 px, leaving 46 % of the
viewport width empty**. The container caps at `max-w-6xl` (1152 px) and centres;
the content inside caps at `max-w-3xl` / `max-w-2xl` and left-aligns. At
1920 px the dead space is larger still.

The page does not scale up — it centres a mobile-width column in a desktop
window. For a marketing page this is a defensible (if conservative) choice. For
the data-dense operator UI this product needs, the pattern is unusable and must
be replaced by a real application shell.

### 12.3 High — content density is far below what the product needs

The whole page is 2994 px tall and communicates roughly four facts. The backend
can answer questions about runs, turns, artefacts, stage timings, state
transitions, provider capabilities and 13 languages. The current layout rhythm
(large section padding `py-14 sm:py-20`, `max-w-2xl` prose) is a *reading*
rhythm. An Operate surface needs a scanning rhythm.

### 12.4 Medium — capability cards stretch unevenly

The grid uses `h-full` cards in a 3-column layout, so each card stretches to its
row's tallest sibling. With uneven copy length ("Live telephony" is short,
"Simulated callers" is long) the short cards carry a large block of empty space
under the text. Visible in `desktop-1440x900-viewport.png`. Two card titles also
wrap to a second line at 1440 ("Multilingual benchmarks", "Regression testing in
CI"), which misaligns the pill baselines across the row.

### 12.5 Medium — the status pill carries two meanings

`StatusPill` is used for both *phase delivery status* (roadmap) and *capability
maturity* (cards), and in the roadmap the label is overridden to "Complete"
while the colour still says `live`. The same chip in the API table means
"endpoint responds". Three meanings, one visual. In a dashboard this will
collide with run status (`completed`/`failed`/`cancelled`/`timed_out`) and
needs to be split into distinct, named components.

### 12.6 Low — no loading, error or empty states exist anywhere

There is nothing to load, so there is nothing to show. Worth stating explicitly
because, as noted in §9.5, **empty is the default state of this product** on a
fresh database, and the backend has rich failure semantics (see §13.4) that
currently have no visual vocabulary at all.

### 12.7 What is genuinely good and should be kept

Stated so the redesign does not throw it away:

- **The typography is strong.** Geist at `text-4xl → text-6xl`,
  `leading-[1.1]`, `tracking-tight` gives a confident, modern hero. The mono
  eyebrow at `tracking-[0.18em]` is a nice technical signal.
- **The token architecture is correct** — semantic names (`surface-raised`, not
  `gray-900`), a fixed status vocabulary with documented meaning, single source
  in CSS.
- **Semantics are clean.** Correct landmarks (`header`/`nav`/`main`/`footer`),
  heading order h1 → h2 → h3 with **no skips**, every `section` carries
  `aria-labelledby`, the decorative SVG is `aria-hidden`, zero images missing
  `alt`.
- **The wide table is handled correctly** — `overflow-x-auto` on the wrapper
  with `min-w-[34rem]` on the table, so the table scrolls inside its own
  container and the page body never scrolls horizontally. This is the right
  pattern and should be the template for every dashboard table.
- **`:focus-visible` and `prefers-reduced-motion` are already handled globally.**
- **The honesty instinct is already in the UI** — the amber "Phase 7 of 15 — no
  calls placed yet" chip in the hero, and the Evon disclaimer written into the
  "Simulated callers" card.

---

## 13. Backend API inventory

34 paths, 42 operations, read from the generated OpenAPI document (not grepped).

### 13.1 Core

| Method | Path | Returns |
|---|---|---|
| GET | `/` | `ServiceIdentity` |
| GET | `/health` | `HealthResponse` (liveness) |
| GET | `/api/v1/health` | `ApiHealthResponse` — per-subsystem `components[]` |
| GET | `/api/v1/languages` | `LanguageCatalogue` — 13 languages |

### 13.2 Suites & scenarios

| Method | Path | Returns |
|---|---|---|
| POST / GET | `/api/v1/suites` | `SuiteRead` / `Page[SuiteSummary]` |
| GET / PATCH / DELETE | `/api/v1/suites/{suite_id}` | `SuiteRead` / `SuiteDeleteResult` |
| POST / GET | `/api/v1/suites/{suite_id}/scenarios` | `ScenarioRead` / scenario list |
| POST | `/api/v1/suites/{suite_id}/scenarios/import` | `BundleImportResponse` |
| GET | `/api/v1/suites/{suite_id}/scenarios/export` | `BundleExportResponse` |
| POST | `/api/v1/scenarios/validate` | `ScenarioValidateResponse` |
| GET | `/api/v1/scenarios` | `Page[ScenarioSummary]` (search) |
| GET / PUT / DELETE | `/api/v1/scenarios/{scenario_id}` | `ScenarioRead` |
| POST | `/api/v1/scenarios/{scenario_id}/copy` · `/move` | `ScenarioRead` |

### 13.3 Speech subsystems

| Method | Path | Returns |
|---|---|---|
| POST | `/api/v1/transcription` | `TranscriptionResponse` (multipart upload) |
| GET | `/api/v1/transcription/providers` | `ProviderListResponse` |
| POST | `/api/v1/speech/generate` | **binary audio** + `X-Speech-*` headers |
| GET | `/api/v1/speech/providers` | `SpeechProviderListResponse` |

### 13.4 Caller engine & pipeline

| Method | Path | Returns |
|---|---|---|
| POST | `/api/v1/caller/conversations` | `ConversationResponse` |
| POST | `…/{id}/turns` · `/bot-text` · `/bot-audio` · `/terminate` | `ConversationResponse` |
| GET | `…/{id}` · `…/{id}/turns` | `ConversationResponse` / `ConversationTurnsResponse` |
| GET | `/api/v1/caller/providers` | `CallerProviderListResponse` + `evon_status` |
| POST | `/api/v1/test-runs` | `RunResponse` |
| POST | `…/{run_id}/start` · `/cancel` | `RunResponse` |
| POST | `…/{run_id}/bot-audio` | `BotAudioResponse` |
| GET | `…/{run_id}` · `/turns` · `/artifacts` · `/report` | run state / turns / artefacts / full evidence |
| GET | `/api/v1/test-runs/bot-adapters/available` | `BotAdapterListResponse` + `telephony_status` |

### 13.5 Enumerations the UI must render

| Enum | Values |
|---|---|
| `ExecutionMode` | `offline_simulation`, `audio_fixture_test`, `external_bot_test`, `telephony_test` *(refused)* |
| `PipelineStatus` | `created`, `initializing`, `running`, `completed`, `failed`, `cancelled`, `timed_out` |
| `RunOutcome` | `goal_achieved`, `bot_refused`, `bot_unintelligible`, `no_progress`, `turn_budget_exhausted`, `provider_error`, `audio_validation_failed`, `external_bot_unavailable`, `cancelled` |
| `CallerState` | `initial`, `introducing`, `awaiting_information`, `providing_details`, `seeking_clarification`, `confirming`, `goal_achieved`, `failed`, `terminated` |
| `CallerIntent` | `open`, `ask`, `provide_fact`, `clarify`, `repeat_request`, `correct`, `decline_unknown`, `confirm`, `close` |
| `TerminationReason` | 8 values incl. `operator_terminated` |
| `NoiseProfile` | `clean`, `light_background_noise`, `moderate_background_noise`, `heavy_background_noise`, `telephony_bandwidth` |
| `TranscriptionMode` | `verbatim`, `transcribe`, `code_mix`, `transliterate` |

That is **9 run outcomes, 7 statuses and 9 caller states** needing distinct,
non-confusable visual treatment. This is the hardest visual-design problem in
the product and it should drive the colour system — not the other way round.

### 13.6 The honesty fields

The API already carries the fields a truthful UI needs. These are not
decorative; each must be rendered somewhere:

| Field | On | Must drive |
|---|---|---|
| `uses_language_model` | `RunResponse`, `ConversationResponse` | "Rule-based caller" label — never "AI caller" |
| `bot_audio_externally_received` | `RunResponse` | Whether a run may be described as testing a real bot |
| `evon_status` | `CallerProviderListResponse` | Explicit "Evon not integrated" statement |
| `telephony_status` | `BotAdapterListResponse` | Explicit "no telephony" statement |
| `execution_modes` | `BotAdapterListResponse` | Only offerable modes (excludes `telephony_test`) |
| `contacts_external_system` | `BotAdapterResponse` | Whether anything left the process |
| `measurement_note` | `RunReportResponse` | Mandatory caption on any counts display |
| `outcomes_observed` | `ConversationResponse` | Label as *keyword indicator*, never a score |
| `selected` | all provider lists | Whether `fake` is in use |
| `available` + `unavailable_reason` | provider lists | Why a provider cannot run |
| `confidence` / `segments` = `null` | `TranscriptionResponse` | Render "not reported", never 100 % |
| `empty` | `TranscriptionResponse` | Distinguish silence from failure |

---

## 14. API-to-frontend mapping

For each proposed feature: the endpoint that supports it, the fields available,
what is missing, and whether backend work is required.

| # | UI feature | Endpoint(s) | Key fields available | Missing | Implementable today? |
|---|---|---|---|---|---|
| 1 | System status panel | `GET /api/v1/health` | `status`, `components[].{name,status,detail}`, `version`, `environment`, `uptime_seconds` | — | ✅ **Yes** |
| 2 | Language coverage matrix | `GET /api/v1/languages` + the 3 provider endpoints | `code`, `name`, `endonym`, `script`, `locale`; per provider `languages[]`, `unsupported_catalogue_languages[]` | — | ✅ **Yes** — the 13×(STT/TTS/caller) grid is fully derivable |
| 3 | Provider capability explorer | `GET /api/v1/{transcription,speech,caller}/providers`, `GET /api/v1/test-runs/bot-adapters/available` | `selected`, `available`, `unavailable_reason`, `notes[]`, `voices[]`, `modes[]`, `evon_status`, `telephony_status`, `execution_modes[]` | — | ✅ **Yes** — unusually rich |
| 4 | Scenario library (browse/search) | `GET /api/v1/scenarios`, `GET /api/v1/suites` | `Page[ScenarioSummary]`: `id`, `name`, `language`, `description`, timestamps, `total/limit/offset` | — | ✅ **Yes** |
| 5 | Scenario detail / YAML editor | `GET|PUT /api/v1/scenarios/{id}`, `POST /api/v1/scenarios/validate` | full `ScenarioSpec`, `spec_version`; validate returns field-level errors | — | ✅ **Yes** — validate-before-save works |
| 6 | Suite management + import/export | suites CRUD, `/scenarios/import`, `/scenarios/export` | `scenario_count`, `SuiteDeleteResult`, `BundleEntryErrorRead` | — | ✅ **Yes** (note the `cascade=true` remedy phrasing) |
| 7 | New-run wizard | `POST /api/v1/test-runs` | `CreateRunRequest`: `suite_id`, `scenario_id`, `mode`, `noise_profile`, `seed`, `max_turns`, `degrade_caller_audio`, `bot_adapter` | — | ✅ **Yes** — gate the mode list on `execution_modes` |
| 8 | Run list / history | — | — | **No list endpoint.** `GET /api/v1/test-runs/{id}` is by id only; there is no `GET /api/v1/test-runs` | ❌ **No — backend required** |
| 9 | Run detail header | `GET /api/v1/test-runs/{run_id}` | 28 fields incl. `status`, `outcome`, `mode`, `caller_state`, turn counts, `bot_transcripts_{succeeded,failed}`, `total_audio_seconds`, `awaiting_bot_audio_for_turn`, timestamps, `error` | — | ✅ **Yes** |
| 10 | Conversation transcript | `GET /api/v1/test-runs/{run_id}/turns` | per turn: `index`, `speaker`, `text`, `intent`, `state_before/after`, `rule_ids[]`, `audio_reference`, `transcription_error`, `synthesis_error` | — | ✅ **Yes** (text only) |
| 11 | **Audio playback of a turn** | `GET …/artifacts` gives `reference` | `reference`, `size_bytes`, `content_type`, `sample_rate_hz`, `channels`, `duration_seconds` | **No route serves the bytes.** No download endpoint, no `StaticFiles` mount | ❌ **No — backend required** |
| 12 | **Waveform visualisation** | — | — | Needs the audio bytes (#11); no precomputed peaks exist | ❌ **No — depends on #11** |
| 13 | Degradation evidence (original vs degraded) | `GET …/artifacts` | `variant` (`original`/`degraded`), `derived_from`, `transformations[]`, `degradation_parameters`, `seed` | Achieved SNR is asserted in tests but **not exposed** in `ArtefactResponse` | ⚠️ **Partly** — metadata yes, A/B listening no (#11), measured SNR no |
| 14 | Pipeline event timeline | `GET …/report` | `events[]`: `turn_index`, `stage`, `status`, `duration_ms`, `detail` (redacted) | — | ✅ **Yes** — 6 stages with measured timings |
| 15 | Caller state-machine trace | `GET …/report` | `state_transitions[]`, plus per-turn `state_before/after` and `rule_ids[]` | — | ✅ **Yes** — a genuinely novel view |
| 16 | Failure explanation | `RunResponse.error`, `RunOutcome`, `StageEventResponse.detail`, per-turn `transcription_error`/`synthesis_error` | all redacted | — | ✅ **Yes** |
| 17 | Ad-hoc TTS preview | `POST /api/v1/speech/generate` | binary audio + `X-Speech-*` headers | — | ✅ **Yes** — returns playable bytes directly |
| 18 | Ad-hoc STT check | `POST /api/v1/transcription` | `text`, `language`, `latency_ms`, `attempts`, `empty`, `confidence` (null), `segments` (null) | — | ✅ **Yes** |
| 19 | Manual bot-audio submission | `POST /api/v1/test-runs/{run_id}/bot-audio` | `BotAudioResponse`; `awaiting_bot_audio_for_turn` signals readiness | — | ✅ **Yes** |
| 20 | Evaluation / scoring / WER | — | — | **Phase 10.** No endpoint, no data. `outcomes_observed` is a keyword indicator and must not be shown as a score | ❌ **Out of scope by phase** |
| 21 | Cross-run aggregates & trends | — | — | **Phase 12.** Needs #8 first | ❌ **Out of scope by phase** |

**Score: 15 of 21 features are fully implementable against today's backend.**
Two need new endpoints (#8, #11), one is partial (#13), and two are correctly
deferred by phase discipline (#20, #21).

---

## 15. Proposed information architecture

Deliberately **7 sections, not 11.** Three of the brief's candidates are
rejected below with reasons — a sidebar padded to look impressive is the
failure mode the brief warned about.

| # | Section | Purpose | Primary data | Implementable? |
|---|---|---|---|---|
| 1 | **Overview** | Does the system work right now, and what ran recently | `GET /api/v1/health`, provider `selected`/`available`, recent runs | ⚠️ Health + providers yes; "recent runs" needs the list endpoint (#8) |
| 2 | **Test runs** | The spine of the product: list → run detail → conversation → evidence | run list (#8), `/{id}`, `/turns`, `/artifacts`, `/report` | ⚠️ Detail fully; **list needs backend** |
| 3 | **New run** | Configure and launch — scenario, mode, noise profile, seed, adapter | `CreateRunRequest`, `execution_modes`, scenario search | ✅ Yes |
| 4 | **Scenarios** | Author, validate, organise, import/export; suites live here as a filter, not a page | scenarios + suites CRUD, `/validate`, bundle import/export | ✅ Yes |
| 5 | **Audio lab** | Ad-hoc Timbre synthesis, degradation preview, Prisma transcription — without creating a run | `/speech/generate`, `/transcription` | ✅ Yes (degradation preview needs a backend hook — see §19.3) |
| 6 | **Coverage** | The 13 × provider language matrix, honestly marked | `/languages` + 3 provider endpoints | ✅ Yes |
| 7 | **Providers & system** | Capabilities, limitations, `notes[]`, `evon_status`, `telephony_status`, health detail | all provider endpoints + `/health` | ✅ Yes |

### 15.1 Sections deliberately **not** proposed

| Rejected | Why |
|---|---|
| **Evaluation results** | Phase 10. No scoring data exists. A page here would have to invent numbers — exactly what rule one forbids. |
| **Reports** | Phase 12. Needs cross-run aggregation that does not exist. |
| **Settings** | All configuration is environment variables read at startup. A settings page implies runtime mutability the backend does not offer, and would be a credential-handling surface for no gain. |
| **Conversation explorer** (standalone) | Folded into Test runs → run detail. A conversation without its run is missing its mode, noise profile and adapter — i.e. missing the evidence that makes it meaningful. |
| **Suites** (standalone) | Folded into Scenarios as a grouping/filter. A suite is a container with a name and a count; it does not earn top-level navigation. |

---

## 16. Recommended design direction

**No palette, type scale or visual theme is committed here.** This section
records *principles and patterns* for discussion, pending your reference.

### 16.1 Mode

Per Impeccable's taxonomy this is **Operate**: the visitor completes a task.
Ambition shows as precision and restraint, not expression. Familiar patterns
earn their place. Brand lives in details — the status system, the data density,
the transitions — not in decoration.

If a public landing page is wanted later, that is a separate **Persuade**
surface and the Taste skill becomes appropriate there.

### 16.2 What to take from the reference products

| Product | Take | Do **not** take |
|---|---|---|
| **Linear** | Keyboard-first interaction, instant view switching, restrained monochrome with colour reserved for state, dense lists that stay scannable | Its opinionated issue-tracker IA |
| **Vercel** | Deployment-log and build-timeline patterns — near-perfect analogue for the **pipeline event timeline** (stage, status, duration) | Marketing gradients |
| **Sentry** | Error-detail hierarchy: headline failure → structured context → raw evidence. Maps exactly onto run → stages → artefacts | Alert-fatigue density |
| **Stripe** | Reference-grade API docs, and the request/response inspector pattern for `X-Speech-*` headers and provider `notes[]` | Consumer-payment polish |

### 16.3 Structural recommendations

1. **Replace the centred marketing column with a persistent app shell** —
   fixed left nav (collapsible), content area that uses the full width. Directly
   addresses §12.2.
2. **Build the colour system around the state enums first** (§13.5), not around
   a brand hue. 9 outcomes × 7 statuses must stay non-confusable; that
   constraint should be solved before anything decorative. Never rely on hue
   alone — pair every state with an icon or text label.
3. **Keep and extend the existing semantic token architecture.** It is already
   correct. Fix `--text-tertiary` (§18.1) rather than replacing the system.
4. **Split `StatusPill` into distinct components** — `RunStatusBadge`,
   `OutcomeBadge`, `ProviderAvailability`, `PhaseStatus` — so one chip stops
   carrying four meanings (§12.5).
5. **Keep the dark-only commitment.** It is justified in writing, and a single
   palette keeps status colours unambiguous. Revisit only if you ask for it.
6. **Monospace for all machine values** — ids, references, durations, seeds,
   language tags, rule ids. Geist Mono is already loaded.
7. **Design the empty state as a primary screen, not a fallback** (§9.5).
8. **Honesty affordances are components, not copy.** A `ModeBadge` that reads
   `offline_simulation` differently from `external_bot_test`, and an
   `EvidenceNotice` fed by `measurement_note` — so truthfulness is structural
   and cannot be forgotten on a new page.

### 16.4 Interaction and motion (Emil principles applied)

- Motion must be functional: state transitions, list reordering, disclosure.
  No decorative animation on an Operate surface.
- Keep durations short (~150–200 ms) with ease-out for entrances.
- `prefers-reduced-motion` is already handled globally — preserve it.
- Optimistic UI is wrong here. A run's state is authoritative server state;
  showing a hopeful status would be a small lie.
- Invest in the details that compound: focus rings, hover feedback on every
  interactive row, consistent disabled states, sensible tab order.

---

## 17. Signature BhashaBench experience

The differentiating view is the **Run Evidence Inspector** — one screen that
makes an 11-step audio pipeline legible. Nothing else in this product category
shows caller state, audio degradation and transcription failure in one place.

Proposed structure (three columns at ≥1280, stacked below):

```
┌─ Run header ────────────────────────────────────────────────────────┐
│ scenario · language · ModeBadge · RunStatus · Outcome               │
│ ⚠ rule-based caller (uses_language_model=false)                     │
│ ⚠ no external bot audio (bot_audio_externally_received=false)       │
│ caller_provider · stt_provider · tts_provider · bot_adapter         │
│ noise_profile (+ scenario_noise_profile if different) · seed        │
├──────────────┬──────────────────────────────┬───────────────────────┤
│ STAGE        │ CONVERSATION                 │ EVIDENCE              │
│ TIMELINE     │                              │                       │
│              │ turn 0  CALLER  intent=open  │ artefact              │
│ caller_turn  │   "..."  rule_ids[]          │  original / degraded  │
│   12 ms ok   │   introducing → awaiting_... │  44 KB · 8 kHz · 1 ch │
│ synthesis    │   ▸ audio  1.4 s             │  2.1 s                │
│   310 ms ok  │                              │  transformations[]    │
│ degradation  │ turn 1  BOT                  │  derived_from         │
│   28 ms ok   │   ⚠ transcription_error      │  seed                 │
│ bot_exchange │   (text = null, not silence) │                       │
│   5 ms ok    │                              │  measurement_note     │
│ transcription│ turn 2  CALLER …             │                       │
│   890 ms ✗   │                              │                       │
└──────────────┴──────────────────────────────┴───────────────────────┘
```

### 17.1 Feature-by-feature backing

| Element | Supported today? | Source |
|---|---|---|
| Caller/bot turn thread | ✅ | `GET …/turns` |
| Transcribed text per turn | ✅ | `RunTurnResponse.text` |
| **Null vs empty distinction** | ✅ | `text: null` + `transcription_error` vs `""` — must be rendered as *two different things* |
| Caller intent + rule ids | ✅ | `intent`, `rule_ids[]` |
| State transition per turn | ✅ | `state_before` → `state_after` |
| Language indicator | ✅ | `RunResponse.language` |
| Noise profile + seed | ✅ | `noise_profile`, `scenario_noise_profile`, `degradation_seed` |
| Stage execution status | ✅ | `events[].{stage,status}` — 6 stages |
| Measured stage timings | ✅ | `events[].duration_ms` ("measured, not estimated") |
| Failure explanation | ✅ | `events[].detail`, `error`, per-turn errors — all redacted |
| Artefact metadata | ✅ | `size_bytes`, `sample_rate_hz`, `channels`, `duration_seconds` |
| Original ↔ degraded lineage | ✅ | `variant`, `derived_from`, `transformations[]` |
| **Audio playback** | ❌ | **Needs a download endpoint — §19.1** |
| **Waveform** | ❌ | **Depends on playback** |
| **Achieved SNR in dB** | ❌ | Computed and asserted in Phase 7, not exposed — §19.2 |
| Scores / WER / accuracy | ❌ | **Phase 10. Must not appear.** |

### 17.2 Honesty rules binding on this view

1. Never render a run as "bot tested" unless `bot_audio_externally_received`
   is `true`.
2. Always render the caller as rule-based while `uses_language_model` is
   `false`.
3. Display `measurement_note` wherever counts appear.
4. `outcomes_observed` is labelled a keyword indicator, never a score.
5. `confidence: null` renders "not reported", never a number.
6. Visually separate the three failure modes the backend deliberately keeps
   apart: **bot said nothing** (empty string), **we could not transcribe it**
   (`null` + `transcription_error`), **audio was not decodable** (run fails
   `audio_validation_failed`). Collapsing these would undo a deliberate design.
7. Degraded audio is labelled *simulated*, never "field recording".

---

## 18. Accessibility and responsive audit

All figures measured in-browser via Playwright. **No code was changed.**

### 18.1 Colour contrast — 27 failures, one root cause

`--text-tertiary: #6b7488` fails WCAG AA (4.5:1) for normal-size text on every
surface it appears on.

| Element | Size / weight | Measured | Required | Verdict |
|---|---|---|---|---|
| "Planned · Phase N" pills | 12 px / 500 | **3.79** | 4.5 | ✗ |
| Table headers (METHOD/PATH/RETURNS/STATUS) | 12 px / 500 | **3.79** | 4.5 | ✗ |
| Roadmap numerals 01–15 | 12 px / 400 | **4.03 / 4.25** | 4.5 | ✗ |
| Hero caveat paragraph | 14 px / 400 | **4.25** | 4.5 | ✗ |
| Footer text | 14 px / 400 | **4.25** | 4.5 | ✗ |
| Footer version line | 12 px / 400 | **4.25** | 4.5 | ✗ |

Darkest case is the `planned` pill: tertiary text on `--surface-overlay`.
Single-token fix — lightening `--text-tertiary` to roughly `#8891a5` clears AA
on all three surfaces. `--text-primary` and `--text-secondary` pass comfortably.

### 18.2 Responsive navigation — fails on mobile

Measured focusable elements:

| Viewport | Focusables | Items |
|---|---|---|
| 1425 × 900 | **8** | wordmark, Overview, Test suite, API, Roadmap, GitHub, Open API docs, View source |
| 375 × 812 | **4** | wordmark, GitHub, Open API docs, View source |

`site-header.tsx` uses `hidden items-center gap-1 md:flex`. Below 768 px the
`<nav aria-label="Sections">` is removed from the accessibility tree entirely
(confirmed in the Playwright snapshot) **with no hamburger, drawer or any
replacement**. All four section links are unreachable on a phone.

The `Phase 7/15` indicator also disappears below 640 px (`hidden sm:inline`),
though it is duplicated in the footer, so that one is acceptable.

### 18.3 Touch targets — every interactive element is undersized

WCAG 2.5.5 asks for 44 × 44 px. Measured:

| Element | Size | Short by |
|---|---|---|
| Wordmark link | 125 × **23** | 21 px height |
| Nav links (Overview/Test suite/API/Roadmap) | ~85 × **32** | 12 px height |
| GitHub button | 70 × **34** | 10 px height |
| Open API docs | 130 × **40** | 4 px height |
| View source | 113 × **42** | 2 px height |

**0 of 8 interactive elements meet the target.** Mostly a padding adjustment.

### 18.4 Keyboard navigation

| Check | Result |
|---|---|
| Focus order matches visual order | ✅ Yes, at both widths |
| Focus indicator present | ✅ Global `:focus-visible`, 2 px accent, 2 px offset |
| Keyboard traps | ✅ None |
| **Skip-to-content link** | ❌ **Absent** — low cost now, higher once a persistent sidebar exists |
| Interactive elements reachable | ⚠️ Desktop yes; mobile nav unreachable (§18.2) |

### 18.5 Semantic HTML and screen readers

| Check | Result |
|---|---|
| Landmarks | ✅ `header`, `nav[aria-label="Sections"]`, `main`, `footer` |
| Heading hierarchy | ✅ h1 → h2 → h3, **no skipped levels** |
| Section labelling | ✅ Every `section` has `aria-labelledby` |
| Images without `alt` | ✅ 0 (the wordmark SVG is correctly `aria-hidden`) |
| Decorative pill dot | ✅ `aria-hidden="true"` |
| `<html lang>` | ⚠️ `"en"` — correct today, **but see below** |
| Table semantics | ✅ `<thead>`, `<th scope="col">` |

**Forward-looking `lang` issue:** the product renders 13 languages including
Devanagari, Bengali, Tamil, Telugu, Gujarati, Kannada, Odia, Malayalam,
Gurmukhi and Arabic scripts. Once transcripts and endonyms are displayed, each
element must carry its own `lang` attribute (`lang="hi-IN"`, `lang="ta-IN"`…) or
screen readers will pronounce Indian-language text with English phonetics.
`LanguageRead` already returns `code`, `script` and `locale`, so this is free if
designed in from the start — and expensive to retrofit. **This is the single
most important accessibility decision for an Indian-language product.**

### 18.6 Responsive layout

| Check | Result |
|---|---|
| Horizontal page overflow at 375 px | ✅ **None** (`scrollWidth` 375 = `clientWidth` 375) |
| Horizontal page overflow at 390 px | ✅ None |
| Wide table handling | ✅ **Correct** — `overflow-x-auto` wrapper, table scrolls in its own container |
| Capability grid reflow | ✅ 1 → 2 (`sm`) → 3 (`lg`) columns |
| Desktop width usage | ❌ 46 % of a 1425 px viewport unused (§12.2) |
| Mobile navigation | ❌ Missing (§18.2) |
| Touch targets | ❌ All undersized (§18.3) |

---

## 19. Missing capabilities and backend dependencies

Ordered by how much they block the proposed UI.

### 19.1 BLOCKER — no endpoint serves a stored audio artefact

`ArtefactResponse.reference` is a storage-root-relative path (deliberately not
absolute, to avoid disclosing server layout). But:

- there is **no** `GET /api/v1/test-runs/{run_id}/artifacts/{...}` download route;
- there is **no** `StaticFiles` mount anywhere (`grep` for
  `StaticFiles|FileResponse|StreamingResponse|mount(` across `backend/app/`
  returns nothing);
- audio lives under `storage/caller-audio`, which is git-ignored and not served.

**Nothing in the audio-centric inspector — playback, waveform, original-vs-
degraded A/B — can be built until this exists.** It is the single highest-value
backend addition for Phase 9.

Design notes for whoever adds it: resolve the reference *server-side* from the
run id (never accept a client-supplied path), keep the existing
whitelist-suffix discipline, support HTTP range requests so `<audio>` can seek,
and set the correct `Content-Type`.

### 19.2 Achieved SNR is measured but not exposed

Phase 7 scales noise from the signal's own RMS and asserts the achieved ratio to
better than 0.5 dB — a genuinely strong honesty property. But
`ArtefactResponse` returns only `degradation_parameters` and `seed`; the
*achieved* dB figure is not in the payload. Surfacing "requested 20 dB,
achieved 19.8 dB" would be a visible proof of rigour. Small additive change.

### 19.3 No preview-degradation endpoint

The Audio lab (§15, #5) wants "apply this noise profile to this audio and let me
hear it" without creating a run. `degrade()` exists internally and writes
nothing, but no route exposes it. Optional; the lab works without it.

### 19.4 No run list endpoint

`GET /api/v1/test-runs` does not exist — runs are addressable only by id. A run
history page (the spine of §15, #2) cannot be built. Needs pagination plus
filters on `status`, `outcome`, `mode`, `language` and `scenario_id`; the
`Page[T]` envelope already used for suites and scenarios is the obvious shape.

### 19.5 Frontend-side gaps

| Gap | Note |
|---|---|
| No API client | Needs a typed client. **Recommend generating from the OpenAPI document** rather than hand-writing — 81 schemas, and generation keeps the honesty fields from being dropped |
| No data-fetching strategy | Polling vs. SSE for `running` runs is an open decision (Q3, §21) |
| No icon library | None installed |
| No charting library | None installed. Much of the proposed UI needs none; the stage timeline is better as CSS bars than a chart library |
| No audio/waveform library | Needed once #19.1 lands |
| No component primitives | No dialog, dropdown, tooltip, tabs, toast |
| No test infrastructure | No runner, no Playwright config committed |
| No `loading`/`error`/`not-found` boundaries | None of the App Router convention files exist |

### 19.6 Configuration and documentation defects

Found incidentally; all are small and none were fixed.

| Defect | Detail | Impact |
|---|---|---|
| **Stale Docker image** | `bhashabench-backend` crash-looping 34 h on missing `websockets`; declared correctly in `requirements.txt` | Backend unusable via `docker compose` until rebuilt |
| **`CORS_ORIGINS` missing from `.env.example`** | It is a real setting (default `["http://localhost:3000"]`) but undocumented | A dashboard on any other port is silently blocked by CORS. Directly affects Phase 9 |
| **5 duplicated keys in `.env.example`** | `PIPELINE_BOT_ADAPTER`, `PIPELINE_MAX_CONCURRENT_RUNS`, `PIPELINE_NOISE_PROFILE`, `PIPELINE_NOISE_SEED`, `PIPELINE_RUN_TIMEOUT_SECONDS` each appear twice | Confusing; last value silently wins |
| Three settings undocumented | `APP_NAME`, `APP_TAGLINE`, `API_V1_PREFIX` absent from `.env.example` | Minor — arguably internal |
| Design skills in a non-scanned directory | Emil and Taste under `.agents/skills/` | Not invocable (§6) |

`CLAUDE.md` requires `.env.example` to be updated when any configuration
variable is added or renamed, so the first three rows are genuine
documentation-sync defects.

---

## 20. Recommended implementation order

Sequenced so each step is independently reviewable and nothing speculative is
built. **Nothing here starts without your approval.**

**Step 0 — Unblock (before any design work)**
1. Rebuild the backend image (`docker compose build backend`); confirm healthy.
2. Fix `.env.example`: add `CORS_ORIGINS`, remove the 5 duplicate keys.
3. Move/symlink the two design skills into `.claude/skills/`.

(The test suite is already confirmed green — §9.4 — so it is not a blocker.)

**Step 1 — Correct the lie already on screen** *(can ship independently, tiny
diff)*
Fix the three stale strings and the `endpoints` constant in §12.1. This is
worth doing **before** the redesign, because it is a truthfulness defect and the
redesign may be weeks away.

**Step 2 — Design foundation** *(requires your visual reference)*
Tokens, type scale, spacing, the full state-colour system for 9 outcomes ×
7 statuses × 9 caller states, and the app shell. Fix `--text-tertiary` and the
touch targets here.

**Step 3 — Component primitives**
Split `StatusPill` into four honest badges; build table, empty state, loading
skeleton, error boundary, dialog, tabs. Add the skip link and per-element `lang`
support.

**Step 4 — API client**
Generate typed client from OpenAPI; set up fetching, error handling and the
`ErrorResponse` envelope.

**Step 5 — Read-only surfaces first** *(no backend changes needed)*
Overview, Coverage, Providers & system. These are fully implementable today and
prove the design system against real data.

**Step 6 — Scenarios & suites**
Library, search, detail, validate-before-save, import/export.

**Step 7 — Backend additions** *(parallel with 5–6)*
Artefact download (§19.1), run list (§19.4), achieved SNR (§19.2).

**Step 8 — Runs**
New-run wizard, then run detail: header, conversation, stage timeline, state
trace, evidence panel.

**Step 9 — The signature inspector**
Audio playback and waveform, original-vs-degraded A/B. Depends on Step 7.

**Step 10 — Audio lab**, then accessibility and responsive hardening, then
frontend tests.

Steps 5, 6 and 8 deliver user-visible value without any backend change, which
is why they come before the harder work.

---

## 21. Questions requiring your approval

**Q1 — Is this a dashboard replacing the landing page, or an addition?**
Does the marketing page at `/` survive (and the dashboard live at `/app` or
similar), or is the whole thing replaced by an operator tool? This changes the
IA, the routing and whether the Taste skill is relevant at all.

**Q2 — Should Step 1 (fixing the stale copy) ship now, separately?**
It is a small, safe, independently-valuable commit that removes a factual error
from the live UI. I recommend yes, and I have **not** done it, since the brief
forbids frontend changes.

**Q3 — Live updates for a running run: polling or SSE?**
Runs move through `initializing → running → completed`. Polling is simple and
needs no backend change; SSE is better UX and needs one. The sessions are
synchronous by deliberate design (`app/db/session.py`), which argues for
polling.

**Q4 — Confirm the backend additions in §19.1/19.2/19.4 are in scope for
Phase 9.**
The artefact download endpoint in particular. Without it the signature
experience cannot be built — but it is backend work and may belong to a
different phase under your phase discipline.

**Q5 — Figma: upgrade the seat, or stay code-first?**
The current **View** seat on **starter** tier is read-only (§7). Code-first with
Figma as a reference reader works fine. Figma as source of truth needs an
upgrade.

**Q6 — May I move the two design skills into `.claude/skills/`?**
A file move, no code change — but it touches tooling config, so I have not done
it.

**Q7 — Component library: build from scratch, or adopt headless primitives?**
Current dependencies are exactly three packages. Options: hand-build (full
control, slower, best craft ceiling), Radix/Base UI (accessible primitives,
unstyled), or shadcn/ui (fastest, but a recognisable house style that may fight
a distinctive direction). Brief says no new dependencies without approval.

**Q8 — Should the dark-only commitment hold?**
It is well-reasoned and documented. I recommend keeping it unless your reference
implies otherwise.

**Q9 — Seeding for development.**
The database is empty and 6 scenario YAMLs sit unused on disk. May I load them
into the dev database so the UI can be built against realistic data? (Dev data
only, no schema change.)

---

## 22. Tested vs. inspected

Required by the brief. **Tested** = executed and observed. **Inspected** =
read from source or documentation without execution.

### Actually tested

| Capability | How | Result |
|---|---|---|
| Repository state | `git log`, `rev-parse`, `status` | HEAD = `6bb9104`, confirmed |
| Backend startup (local) | `uvicorn` on :8001 | ✅ Started, serving |
| Backend startup (Docker) | `docker logs`, `docker inspect`, `curl` | ❌ Crash-loop, root cause identified |
| Database connectivity | `GET /api/v1/health` | ✅ `SELECT 1 succeeded` |
| OpenAPI generation | Imported `create_app().openapi()` | ✅ 34 paths, 42 ops, 81 schemas |
| Provider capability endpoints | `curl` ×4 | ✅ All responded with real payloads |
| Language catalogue | `curl` | ✅ 13 languages with endonyms/scripts |
| Suite & scenario listing | `curl` | ✅ Responded; both empty (total 0) |
| Frontend dev server | `next dev` on :3001 | ✅ Ready in 2.1 s |
| Frontend rendering | Playwright, 4 viewports | ✅ 8 screenshots captured |
| Browser console | `browser_console_messages` | ✅ 0 application errors |
| Contrast ratios | In-page WCAG computation | ✅ 27 failures found |
| Touch-target sizes | `getBoundingClientRect()` | ✅ 8/8 undersized |
| Horizontal overflow | `scrollWidth` vs `clientWidth` | ✅ None at 375/390 |
| Focus order & count | DOM query, both widths | ✅ 8 desktop / 4 mobile |
| Accessibility tree | `browser_snapshot` | ✅ Mobile nav absence confirmed |
| Scroll-on-load behaviour | `browser_evaluate` after clean load | ✅ No defect (initial reading corrected) |
| Figma MCP auth | `whoami` | ✅ Authenticated, View seat |
| Playwright MCP | 7 tools exercised | ✅ All working |
| Ruff lint + format | `ruff check` / `format --check` | ✅ Pass, 232 files |
| Frontend typecheck | `tsc --noEmit` | ✅ exit 0 |
| Frontend lint | `eslint .` | ✅ exit 0 |
| **Backend test suite** | `pytest` | ✅ **1916 passed, 41 skipped, 0 failed** |
| Skill presence on disk | `find`, `cat` on all three SKILL.md | ✅ All 3 present; 2 unregistered |
| `.env.example` completeness | Diffed against `config.py` fields | ✅ 4 missing, 5 duplicated |
| Audio-serving routes | `grep` for `StaticFiles\|FileResponse\|mount(` | ✅ Confirmed absent |

### Inspected only (not executed)

| Item | Why not executed |
|---|---|
| **Gnani Prisma live STT** | Would consume API credits — explicitly forbidden |
| **Gnani Timbre live TTS** | Same |
| Caller conversation endpoints | Would write `TestRun`/`CallSession`/`ConversationTurn` rows to the dev DB |
| Pipeline run creation & execution | Same; also needs a suite and scenario that do not exist |
| Manual bot-audio submission | Requires an active run |
| Audio degradation engine | No route exposes it; reachable only in-process |
| Concurrency limiter (Phase 7.1) | Needs concurrent real runs |
| CLI (`bhashabench`) | Out of scope for a frontend audit |
| Scenario import/export | Would mutate the database |
| 41 live-provider tests | Opt-in and billable; correctly skipped (§9.4) |
| Figma write operations | Forbidden by the brief; View seat makes failure likely |
| `claude-in-chrome` MCP | Not needed; **no claim made about its status** |
| Production frontend build | `next build` not run; only dev server verified |
| Streaming transcription | Needs live provider credentials |

### Claims deliberately not made

- That the pipeline works end to end — I inspected its code and schemas; I did
  not run a pipeline.
- That Prisma or Timbre work against live endpoints — never called. The suite
  passing does **not** establish this: the 41 tests that would have is exactly
  the set that was skipped.
- That `claude-in-chrome` is operational — never loaded.
- That Figma writes fail — inferred from the seat type, not measured.

---

*Prepared as a Phase 8 preparation artefact. No application code, styling,
schema, test or configuration was modified. Awaiting the visual reference and
explicit approval before any implementation begins.*
