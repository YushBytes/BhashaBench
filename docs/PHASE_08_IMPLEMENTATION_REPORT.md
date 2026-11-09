# Phase 8 — Operator workspace and public site

**Status:** Implemented.
**Branch:** `main`
**Started from:** `2e18864`

Phase 8 gives BhashaBench a face: a public site that explains what the
instrument measures, and an operator workspace that actually drives it. Two
backend endpoints were added because the workspace could not be built
honestly without them.

---

## 1. What was built

| Deliverable | Where |
|---|---|
| Public marketing site | `/` |
| Operator workspace shell | `/app` (sidebar, mobile drawer, skip link) |
| Overview | `/app` |
| Run history with filters | `/app/runs` |
| Conversation inspector | `/app/runs/[runId]` |
| New-test workflow | `/app/new-test` |
| Scenario library | `/app/scenarios` |
| Provider status | `/app/providers` |
| Design system | `components/ui/`, `app/globals.css` |
| Typed API client | `lib/api/` |
| Run listing endpoint | `GET /api/v1/test-runs` |
| Artefact audio endpoint | `GET /api/v1/test-runs/{id}/artifacts/{turn}/audio` |

Six scenario files from `scenarios/` were loaded into the development
database and four runs were executed through the real pipeline to verify the
workspace against real data. No fixture or sample data is compiled into the
frontend.

---

## 2. Architecture decisions

### 2.1 Two surfaces, one visual system, separate chrome

The root layout carries only the document and the fonts. The public site
supplies its own header and footer; the workspace supplies a persistent rail.
Neither lives in the root layout, because a marketing header above an
operator dashboard is the thing that makes an app feel like a brochure.

### 2.2 Server components by default

Every page and almost every component is a server component. Five modules are
client components, each for a specific reason:

| Client module | Why |
|---|---|
| `shell/nav.tsx` | `usePathname` for the current item, drawer state |
| `marketing/chrome.tsx` | Mobile section disclosure |
| `domain/run-filters.tsx` | Pushes filters into the URL |
| `domain/new-test-form.tsx` | Form state and the create/start calls |
| `domain/audio-player.tsx` | Fetch, decode and draw the waveform |

A badge, a table row and a panel have no behaviour, so they cost nothing on
the client. This is why the whole workspace ships ~138 KB of JavaScript —
most of it the React and Next runtime.

### 2.3 No component library

Dependencies remain exactly three: `next`, `react`, `react-dom`. The brief
suggested Radix "or an equivalent established library"; this is the
deviation, and the reasoning is:

- The hard primitives to get right by hand are focus trapping and overlay
  positioning. The design avoids both: there are **no modals** (the Operate
  guidance is explicit that a modal is usually laziness), the new-test flow is
  a page, and the mobile drawer is a focus-managed overlay rather than a
  dialog needing a library.
- `<select>` is native. It is keyboard accessible for free and becomes the
  platform picker on a phone, which no custom dropdown matches.
- Disclosures are `<details>`/`<summary>`.

If a future surface genuinely needs a positioned popover or a focus-trapped
dialog, that is the point to add one headless library — not before.

### 2.4 Cache Components

`next.config.ts` has `cacheComponents: true`, which is **incompatible with
`export const dynamic = "force-dynamic"`**. Following the migration guide
bundled in `node_modules/next/dist/docs/`, the config was removed and every
route's data access moved behind `<Suspense>` with a skeleton shaped like the
content it replaces.

The result is better than the original intent: the shell prerenders as static
HTML and live state streams in.

```
Route (app)
┌ ○ /                     Static
├ ○ /_not-found           Static
├ ◐ /app                  Partial Prerender
├ ◐ /app/new-test         Partial Prerender
├ ◐ /app/providers        Partial Prerender (1h revalidate on the catalogue)
├ ◐ /app/runs             Partial Prerender
├ ◐ /app/runs/[runId]     Partial Prerender
└ ◐ /app/scenarios        Partial Prerender
```

`usePathname()` in the sidebar also blocked prerendering, so the nav is split:
`SidebarChrome` takes the current path as a prop and renders with nothing
highlighted as the Suspense fallback. The only thing that streams in is which
item is lit.

### 2.5 Directory structure

```
frontend/
  app/
    layout.tsx            document + fonts only
    page.tsx              public site
    app/
      layout.tsx          workspace shell
      page.tsx            overview
      runs/, new-test/, scenarios/, providers/
  components/
    ui/                   primitives, status vocabulary, loading states
    shell/                sidebar, drawer, page header, wordmark
    domain/               runs table, conversation, audio, stage timeline,
                          evidence, filters, new-test form
    marketing/            public header/footer, pipeline diagram
  lib/
    api/client.ts         the only place the frontend calls the API
    api/types.ts          response shapes, transcribed from the Pydantic models
    format.ts             measurement formatting
    content.ts            public-site copy and phase status
```

---

## 3. Design-system decisions

### 3.1 Tokens

A single dark palette, defined once in `app/globals.css` and exposed through
Tailwind v4's `@theme inline`. Three rules hold it together:

1. **Accent is for the primary action, the current selection and focus.**
   Never decoration, never an inactive state.
2. **Status hues are fixed vocabulary.** A hue never means two things.
3. **No status is carried by colour alone.** Every badge pairs its hue with a
   word; the run-status badge adds a glyph. The run table reads correctly in
   greyscale.

The brief's starting palette was used with one change: muted text moved from
`#778392` to `#808C9B`. The original measured **4.39:1 on the elevated
surface**, failing AA for body text by a margin too small to see and too real
to keep. The replacement clears 4.9:1 on every surface it appears on. This is
the direct fix for the audit's largest accessibility finding.

### 3.2 The status vocabulary was split

The audit found one `StatusPill` carrying four meanings. It is now five
components with distinct jobs: `RunStatusBadge`, `OutcomeBadge`, `ModeBadge`,
`AvailabilityBadge`, `SelectedBadge`.

`OutcomeBadge` encodes a judgement worth stating: only `goal_achieved` is
green, and `provider_error` / `audio_validation_failed` are red **because
they are our failures, not the bot's**. Colouring them like a bot failure
would misattribute the fault.

### 3.3 Typography

One family (Geist), fixed rem scale, no fluid headings. Mono is reserved for
machine values — ids, references, durations, seeds, sample rates, language
tags — because they are compared character by character, not because mono
looks technical. `font-variant-numeric: tabular-nums` so columns align.

### 3.4 Browser surfaces

Selection colour, caret, scrollbars, focus ring, underline offset and the
`<dialog>` backdrop are all themed from the palette. Left at their defaults
these are the cheapest signal that a page was assembled rather than built.

### 3.5 Motion

150–200 ms, ease-out, and only to convey state: hover, focus, drawer, skeleton
pulse, and one breathing dot on a running run. `prefers-reduced-motion`
neutralises all of it.

---

## 4. Backend changes

Two endpoints, no schema change. `alembic check` reports **no new upgrade
operations**.

### 4.1 `GET /api/v1/test-runs`

Runs were addressable only by id, so a history view had nothing to read.

Filters: `suite_id`, `status`, `mode`, `language`, `outcome`, `scenario`
(case-insensitive substring). Paged through the existing `Page[T]` envelope,
`limit` capped at 100.

Three decisions:

- **Only runs carrying pipeline metadata are listed.** A `TestRun` is also the
  parent of a Phase 6 caller conversation; those record no pipeline metadata,
  so listing them would produce rows whose detail view is empty.
- **`duration_seconds` is null until a run has both a start and a finish.** An
  elapsed-so-far figure in a duration column would be read as a duration.
- **Turn counts come from one grouped query**, not a query per row and not a
  default. `turn_counts_for_runs` omits runs with no turns rather than mapping
  them to zero.

The scenario filter escapes `%` and `_` before building the `ILIKE` pattern,
so a wildcard narrows to nothing instead of matching every row.

### 4.2 `GET /api/v1/test-runs/{run_id}/artifacts/{turn_index}/audio`

**This reverses a deliberate Phase 7 decision, and the reversal is documented
rather than quiet.** That module's docstring said artefacts are listed and not
served, because who may hear a recorded conversation is an authorisation
decision with no identity to make it against.

That reasoning still holds. What changed is that the conversation inspector
cannot work without playback, and withholding the route never created an
authorisation model — it only put the recording out of reach of the one
operator entitled to it. The docstring and `docs/PIPELINE.md` now carry the
new decision and the reasoning for it.

The route ships under three constraints:

- **No client string reaches the filesystem.** The artefact is addressed by
  run, turn index and variant — a UUID, a non-negative integer and a two-value
  enum. The stored reference is looked up in the run's own record.
  `AudioArtefactStore` refuses anything resolving outside its root besides.
- **Off where it would be reachable.** Staging and production refuse with 403
  unless `PIPELINE_SERVE_ARTEFACTS=true`. 403, not 404: the recording exists
  and this environment declines, and "no such artefact" would be a lie about
  what is on disk.
- **It claims no authorisation.** A run id is an identifier, not a credential.
  Real access control arrives with authentication in Phase 15.

It resolves through the engine's own artefact store (newly exposed as a
property) rather than building a second one from settings. Those look
equivalent and are not: whoever built the engine may have pointed it
elsewhere, and a reader that guessed would report a present recording as
missing — which is exactly how the first version of this failed its tests.

Range support is one range, `bytes=` only, so a player can seek.

### 4.3 Configuration

| Change | Why |
|---|---|
| `PIPELINE_SERVE_ARTEFACTS` added | Gates the artefact route in deployed environments |
| `CORS_ORIGINS` documented in `.env.example` | It was a real setting and undocumented; a dashboard on another port fails as an opaque console error |
| Duplicate `PIPELINE_*` block removed | The whole block appeared twice |

---

## 5. API integration

`lib/api/client.ts` is the only place the frontend calls the API.

- One `request` function owns timeouts (15 s default, 120 s for `start`),
  the error envelope, and query serialisation that drops undefined rather
  than sending the string `"undefined"`.
- `ApiError` separates three failures that look alike in a `catch` and need
  different words on screen: `http`, `network`, `timeout`.
- **There is no mock mode and no fallback data.** A failed call surfaces as
  an error state. The overview detects the case where *every* call failed the
  same way and says the API is unreachable once, rather than showing six
  empty panels.

`lib/api/types.ts` is transcribed from the Pydantic models field for field.
No field appears there that the API does not return.

**A real bug this caught:** the scenario search parameter is `name`, not
`name_contains`. A misspelled filter is not rejected by FastAPI — it is
ignored, so the page would have shown every scenario while appearing to have
searched. Verified against the generated OpenAPI document before shipping.

---

## 6. Honesty mechanisms

The API carries fields that exist so a client cannot overclaim. These are
rendered structurally, not as copy, so a new page cannot forget:

| Field | Rendered as |
|---|---|
| `uses_language_model` | "The caller is a rule engine, not a language model" |
| `bot_audio_externally_received` | `RunEvidence` — and when it contradicts an `external_bot_test` label, a **caution**, plus an "unverified" marker in the run list |
| `measurement_note` | Printed verbatim under every count |
| `evon_status` | Verbatim on the overview and providers pages |
| `telephony_status` | Verbatim on the providers page and in the new-test form |
| `selected: "fake"` | "test double" badge plus a warning that such runs establish nothing |
| `confidence: null` | "not reported", never a number |

Three failure modes the backend deliberately keeps apart are rendered as three
different things, because merging them would attribute our failure to the
system under test:

- `text: ""` → **Silence.** "The bot said nothing — a finding about the bot."
- `text: null` + `transcription_error` → **Not transcribed.** "This is our
  failure, not the bot's."
- `audio_validation_failed` → a run-level failure on the header.

**The waveform is drawn from the audio or not at all.** Bytes are fetched,
decoded with the Web Audio API and reduced to per-block peaks. There is no
synthetic fallback: if decoding fails the component says so and still offers
playback. A generated waveform would be a picture of a sound that does not
exist.

---

## 7. Security decisions

| Decision | Detail |
|---|---|
| Artefact addressing | By run + turn + variant. No client-supplied path, ever. |
| Containment | Reuses `AudioArtefactStore`, which resolves and refuses anything outside the root. |
| Environment gate | Staging/production refuse unless explicitly enabled. |
| Access model | **Documented, not invented.** There is no authentication in this application; the route is as open as every other one, and a UUID is not a credential. |
| Secrets | No credential value appears in any response or page. Provider `unavailable_reason` names the missing setting, never its value. |
| `.env` | Not modified. |
| Error text | Provider error strings reach the UI only through the backend's existing `redact` path. |

Tested: a traversal attempt through the turn index (`..%2F..%2Fetc%2Fpasswd`)
returns 404/422 and no file content; no response contains the storage root.

---

## 8. Performance

Measured in the browser against the production build (`next start`), not
estimated.

| Route | JS (KB) | CSS (KB) | Fonts (KB) | Requests | DCL (ms) |
|---|---|---|---|---|---|
| `/` | 138 | 8 | 51 | 10 | 46 |
| `/app` | 138 | 8 | 51 | 10 | 130 |
| `/app/runs` | 139 | 8 | 51 | 11 | 96 |
| `/app/new-test` | 144 | 8 | 51 | 11 | 109 |

Total static output: 863 KB across 12 chunks.

How it stays small:

- Zero runtime dependencies beyond React.
- No charting library. The stage timeline is CSS bars; the waveform is inline
  SVG from decoded audio.
- Fonts self-hosted and subset by `next/font`, `display: swap`.
- **Audio is decoded lazily** via `IntersectionObserver`, so a twenty-turn run
  does not fetch forty artefacts to draw thumbnails nobody scrolled to.

**No Lighthouse score is quoted, because none was run.**

---

## 9. Accessibility

Measured in-browser on the built app.

| Check | Before (audit) | Now |
|---|---|---|
| Contrast failures | 27 | **0** |
| Mobile navigation | absent below 768 px | drawer (workspace) + disclosure (public) |
| Skip link | absent | present, first in tab order |
| Horizontal overflow | none | none, verified across 24 viewport × route combinations |
| `aria-current` on nav | n/a | present |
| Reduced motion | handled | handled |
| Focus ring | global | global, plus `:focus:not(:focus-visible)` so a mouse press leaves no ring |

Other properties: landmarks on every page, heading order with no skipped
levels, zero images without `alt`, decorative SVG `aria-hidden`, every form
control labelled, status never by colour alone.

**`lang` on Indian-language text.** `langAttr()` sets `lang` on every
transcript, endonym and language tag. A screen reader handed Devanagari
inside `lang="en"` pronounces it with English phonetics — the audit called
this the single most important accessibility decision for this product, and
it is designed in rather than retrofitted.

### Remaining gaps

- The wordmark links are 44 px tall but their *text* is shorter; the hit area
  meets the target, the visual does not fill it.
- No automated accessibility test runs in CI. The measurements above were
  taken by hand through Playwright and are not regression-protected.

---

## 10. Defects found and fixed during implementation

Each was found by looking at the rendered result, not by reading the code.

| Defect | Cause | Fix |
|---|---|---|
| Horizontal overflow on every workspace route at 390 px (858 px vs 380 px) | Grid/flex children default to `min-width: auto`, so a panel holding a `min-w-max` table inflated its own track | `min-w-0` on `Panel` and explicit `grid-cols-[minmax(0,1fr)]` |
| Public header overflowed 9 px at 360 px | `buttonClass` hardcodes `inline-flex`; a sibling `hidden` utility of equal specificity lost on stylesheet order, so the desktop CTA never hid | Wrapped the link in `<span className="hidden sm:block">` |
| Waveform reported "cannot decode" on a valid WAV | The `idle` state (not yet scrolled into view) fell through to the undecodable branch | `idle` renders the skeleton |
| Artefact route 404'd in tests on a present file | The route built its own store from settings instead of using the engine's | Engine exposes `artefact_store`; the route uses it |
| Duplicate "New test" button, empty 56 px desktop topbar | Topbar repeated what the page header carried | Topbar is mobile-only |
| Panel header actions wrapped below the title | Title block had no `flex-1` | Added |

---

## 11. Test results

| Gate | Result |
|---|---|
| `pytest` | **1949 passed, 41 skipped** (3m 28s) |
| `alembic check` | No new upgrade operations |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 233 files formatted |
| `tsc --noEmit` | Clean |
| `eslint .` | Clean |
| `next build` | Succeeds; 10 pages generated |
| `docker compose config` | Valid |

The 41 skips are the opt-in billable live-provider tests. **No Gnani API call
was made and no credits were consumed.** No test was modified or weakened; 33
new backend tests were added in the previous commit for the two endpoints.

### Exercised in the browser

| Capability | Result |
|---|---|
| Public site, desktop + mobile | Renders; disclosure nav works |
| Mobile workspace drawer | Opens, lists all routes, closes |
| Run history filters | Apply and clear via URL |
| **New-test workflow, end to end** | Selected a scenario, chose a mode, clicked Start → run created, started, navigated to its inspector |
| Conversation inspector | Real transcript, real stage timings, real failure |
| **Audio playback and waveform** | Both artefacts fetched, decoded, drawn — the degraded waveform visibly differs from the original |
| Error states | Verified by stopping the API |
| Empty states | Verified against an empty database |

---

## 12. Screenshots

In `docs/phase-08-ui/screenshots/`, from the production build:

| File | What |
|---|---|
| `01-landing-desktop-1440.png` | Public site, full page |
| `02-landing-mobile-390.png` | Public site, mobile |
| `03-overview-desktop-1440.png` | Overview with real health and runs |
| `04-run-history-desktop-1440.png` | Run history with filters |
| `05-new-test-desktop-1440.png` | New-test workflow, full page |
| `06-conversation-inspector-1440.png` | Inspector with waveforms |
| `07-scenarios-desktop-1440.png` | Scenario library with endonyms |
| `08-providers-desktop-1440.png` | Provider capabilities and limits |
| `09-overview-mobile-390.png` | Overview, mobile |
| `10-inspector-mobile-390.png` | Inspector, mobile |

---

## 13. Known limitations

**1. `audio_fixture_test` cannot succeed through the API.** Found by running
it. `build_adapter("scripted")` is constructed with no replies, so the first
turn fails with `the scripted bot has no reply for turn 0`. The mode is only
usable from tests, which inject audio. Fixing it means shipping a fixture
audio asset or changing adapter construction — a third backend change beyond
the two this phase authorised, so it is **reported, not fixed**.

**2. `offline_simulation` never reaches a terminal status.** It produces the
caller's opening turn and stays `running`: no audio moves, so nothing supplies
a bot reply. Pre-existing pipeline behaviour, surfaced by the workspace.

**3. The screenshots show a flat caller waveform.** The configured TTS is the
offline test double, which emits a constant 0.2-amplitude tone. Verified by
decoding the PCM: every block peak is exactly 0.200. The renderer is correct;
the audio is flat. With Timbre configured it would show a speech envelope.

**4. No frontend test suite.** Type checking, linting and a production build
run; there are no component or end-to-end tests. The browser verification
above was manual.

**5. No run auto-refresh.** A `running` run does not update until reloaded.
Polling versus SSE was raised as an open question in the audit and is still
open.

**6. Scenario detail, suite management and the audio lab are not built.** The
library lists and filters; it does not open a scenario or edit one.

**7. The workspace has no authentication**, like the rest of the application.

---

## 14. Commits

| Hash | Subject |
|---|---|
| `9b7c559` | `feat(api): list runs and serve stored artefact audio` |
| *(this)* | `feat(frontend): build the operator workspace and public site` |

---

## 15. Development data

Six scenarios from `scenarios/` and four runs were created in the
**development** database to verify the workspace. They are not fixtures, are
not committed, and the test suite uses its own `bhashabench_test` database.
Two runs failed for the real reasons in §13.
