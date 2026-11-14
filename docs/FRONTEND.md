# The frontend

Two surfaces built from one visual system: a public site at `/` that explains
what the instrument measures, and an operator workspace at `/app` that drives
it.

Design decisions and the measurements behind them are in
[`PHASE_08_IMPLEMENTATION_REPORT.md`](PHASE_08_IMPLEMENTATION_REPORT.md).
This file is the working reference.

---

## Routes

| Route | Rendering | Reads |
|---|---|---|
| `/` | Static | nothing — `lib/content.ts` |
| `/app` | Partial prerender | health, 4 provider endpoints, run list |
| `/app/runs` | Partial prerender | run list with filters |
| `/app/runs/[runId]` | Partial prerender | run report, run turns, artefact audio |
| `/app/new-test` | Partial prerender | scenarios, bot adapters |
| `/app/scenarios` | Partial prerender | scenarios, languages |
| `/app/providers` | Partial prerender | 4 provider endpoints, languages |

Every workspace route is a static shell with live data streamed in behind a
`<Suspense>` boundary.

---

## Cache Components

`next.config.ts` sets `cacheComponents: true`. Two consequences:

**`export const dynamic`, `revalidate` and `fetchCache` are forbidden** — a
route segment that exports one fails the build. Uncached `fetch` and
request-time APIs already run at request time.

**Uncached data must sit inside `<Suspense>`.** Anything else fails the
prerender with `blocking-prerender-dynamic`. The pattern throughout:

```tsx
export default function Page() {
  return (
    <>
      <PageHeader title="…" />            {/* prerenders */}
      <PageBody>
        <Suspense fallback={<TableSkeleton />}>
          <Data />                         {/* async, fetches */}
        </Suspense>
      </PageBody>
    </>
  );
}
```

`usePathname()` is subject to the same rule, which is why `Sidebar` takes the
current path as a prop and is wrapped in `<Suspense>` with a version that
highlights nothing.

The migration guide is bundled at
`node_modules/next/dist/docs/01-app/02-guides/migrating-to-cache-components.md`.

---

## Design tokens

Defined once in `app/globals.css` and exposed through Tailwind v4's
`@theme inline`. One dark palette, not a theme switch.

| Group | Tokens |
|---|---|
| Surfaces | `--bg`, `--surface`, `--surface-raised`, `--surface-inset`, `--chrome` |
| Lines | `--line`, `--line-strong` |
| Text | `--text`, `--text-dim`, `--text-muted` |
| Accent | `--accent`, `--accent-strong`, `--accent-dim`, `--accent-line`, `--accent-alt` |
| Status | `--state-ok`, `--state-warn`, `--state-bad`, `--state-idle`, `--state-busy` (each with a `-dim` ground) |

Three rules:

1. **Accent is for the primary action, the current selection and focus.**
   Never decoration, never an inactive state.
2. **A status hue never means two things.**
3. **No status is colour alone.** Every badge carries a word.

`--text-muted` is `#808C9B`, not the `#778392` the competition Phase 8 brief proposed:
that value measured 4.39:1 on `--surface-raised` and failed AA for body text.
Any change to it must be re-measured on all three surfaces.

---

## Components

| Module | Holds |
|---|---|
| `ui/primitives.tsx` | `Button`, `Panel`, `PanelHeader`, `Fact`, `NotReported`, `EmptyState`, `ErrorState`, `TableScroll`, `Th`, `Td`, `Skeleton` |
| `ui/status.tsx` | `RunStatusBadge`, `OutcomeBadge`, `ModeBadge`, `HealthBadge`, `AvailabilityBadge`, `SelectedBadge` |
| `ui/loading.tsx` | Suspense fallbacks shaped like the content they replace |
| `shell/` | `Sidebar`, `MobileNav`, `PageHeader`, `PageBody`, `Wordmark` |
| `domain/` | `RunsTable`, `Conversation`, `AudioArtefactPlayer`, `StageTimeline`, `RunEvidence`, `RunFilters`, `NewTestForm` |
| `marketing/` | `SiteHeader`, `SiteFooter`, `PipelineDiagram` |

**Five modules are client components** — nav, marketing chrome, run filters,
the new-test form and the audio player. Everything else is server-rendered,
which is why the workspace ships ~138 KB of JavaScript.

**There is no component library.** Dependencies are `next`, `react`,
`react-dom`. No modals, native `<select>`, `<details>` disclosures. Add a
headless library only when a surface genuinely needs a positioned popover or
a focus-trapped dialog.

### `min-w-0` is load-bearing

A grid or flex child defaults to `min-width: auto`, so a `Panel` holding a
`min-w-max` table inflates its own track and scrolls the whole page sideways.
`Panel` carries `min-w-0`, and grid containers declare
`grid-cols-[minmax(0,1fr)]` explicitly. This caused a 858 px-wide page on a
380 px screen before it was fixed.

### Display utilities do not override each other reliably

`buttonClass()` hardcodes `inline-flex`. Adding `hidden` alongside it is
resolved by stylesheet order, not attribute order, and the button wins. Wrap
the element in a `<span className="hidden sm:block">` instead. A `sm:hidden`
variant is safe — variants sort after base utilities.

---

## The API client

`lib/api/client.ts` is the only module that calls the API.

- One `request` function: timeouts (15 s, 120 s for `start`), the error
  envelope, query serialisation that drops `undefined`.
- `ApiError.kind` is `http`, `network` or `timeout` — three failures that
  look alike in a `catch` and need different words on screen.
- **No mock mode, no fallback data.** A failed call renders an error state.

`lib/api/types.ts` is transcribed from the backend's Pydantic models field
for field. **Never add a field the API does not return.** Where the API
returns `null` because a provider does not report something, the type is
`| null` and the UI renders `NotReported`, never a number.

Verify query-parameter names against the generated OpenAPI document. FastAPI
*ignores* an unknown query parameter rather than rejecting it, so a misspelled
filter makes a search box appear to work while returning everything.

---

## Honesty rules

The API publishes fields specifically so a client cannot overclaim. These are
rendered structurally, so a new page cannot forget them.

| Field | Must drive |
|---|---|
| `uses_language_model` | "rule engine", never "AI caller" |
| `bot_audio_externally_received` | whether a run may be described as testing a bot |
| `measurement_note` | printed verbatim wherever counts appear |
| `evon_status`, `telephony_status` | printed verbatim; never paraphrased |
| `settings_not_enforced` | each declared-but-unenforced setting listed with its reason; `null` shown as "not recorded", never as "all enforced" |
| `degradation_requested` | the run's *Noise applied* as requested SNR and packet loss, not a preset name |
| `selected: "fake"` | a visible warning that such runs establish nothing |
| `confidence: null` | "not reported" |

`RunEvidence` derives its caveats **from the run, never from the mode label**.
A run created as `external_bot_test` whose replies were fixtures reports
`bot_audio_externally_received: false`, and the component says so.

### Three failure modes stay three things

| Backend state | Rendered as |
|---|---|
| `text: ""` | **Silence** — the bot said nothing. A finding about the bot. |
| `text: null` + `transcription_error` | **Not transcribed** — our failure, not the bot's. |
| run outcome `audio_validation_failed` | a run-level failure on the header |

Merging any two attributes our fault to the system under test.

### The waveform

Drawn from bytes fetched and decoded with the Web Audio API, reduced to
per-block peaks, normalised within one artefact. **There is no synthetic
fallback**: if decoding fails the component says so and still offers playback.
Decoding is lazy via `IntersectionObserver`.

Amplitude is normalised per artefact, so two waveforms are not comparable by
height — which is why no amplitude figure is printed beside one.

---

## Accessibility

Non-negotiable, and verified in the browser rather than assumed:

- Contrast ≥ 4.5:1 for body text on every surface it appears on.
- A skip link first in tab order on both surfaces.
- Real mobile navigation: a drawer in the workspace, a disclosure on the
  public site.
- No horizontal page overflow at 360 px. Wide tables scroll inside
  `TableScroll`.
- No status by colour alone.
- `langAttr()` sets `lang` on every transcript, endonym and language tag. A
  screen reader handed Devanagari inside `lang="en"` pronounces it with
  English phonetics.

---

## Commands

```bash
cd frontend
npm run dev        # development server
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
npm run build      # production build - the real check for prerender errors
npm run start      # serve the production build
```

`NEXT_PUBLIC_API_BASE_URL` points the browser at the API (default
`http://localhost:8000`). The workspace calls the API **from the browser** for
audio, so the origin the frontend is served from must appear in the backend's
`CORS_ORIGINS` — otherwise audio fails as an opaque console error.

Browsing the dev server by IP rather than `localhost` trips Next's
cross-origin dev-resource block, which silently prevents hydration. Use
`localhost`, or set `allowedDevOrigins`.
