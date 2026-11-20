# The frontend

Two surfaces built from one visual system: a public site at `/` that says
what BhashaBench tests and what it does not, and an operator workspace at
`/app` that drives it. Replaced on 2026-11-20 with a new design system and
information architecture; the API client and the honesty rules carried over
unchanged. This file is the working reference.

---

## Design

**Direction.** Monochrome rigour: white canvas, ink text, hairline borders,
mono type for every measured value, and one electric-blue accent. The
reference was `awesome-design-md/vercel` (a developer platform's black-and-ink
system), adapted to the owner's black-and-white-with-electric-blue brief. The
public hero and footer use a dark "instrument" surface; the workspace is light.

**Type.** Host Grotesk for text and headings, JetBrains Mono for figures,
ids and code, both through `next/font` (dealt by the design-taste-frontend
skill for a calm, exact software page). Indic scripts fall back to the
system's Nirmala UI / Noto Sans and get extra line height through `:lang()`.

**Icons.** Lucide (`lucide-react`), one stroke family everywhere.

### Tokens

Defined once in `app/globals.css` and exposed through Tailwind v4's
`@theme inline`.

| Group | Tokens |
|---|---|
| Grounds | `--bg` #fff, `--bg-soft` #fafafa, `--bg-sunk` #f4f4f5 |
| Lines | `--line`, `--line-strong` |
| Text | `--text` #0a0a0a, `--text-2`, `--text-3` |
| Accent | `--accent` #0a4bff, `--accent-hover`, `--accent-soft`, `--accent-line` |
| Status | `--ok`, `--warn`, `--bad`, `--busy`, `--idle`, each with a `-soft` ground |
| Instrument | `--night`, `--night-2`, `--night-3`, `--night-line`, `--night-text`, `--night-muted`, `--night-accent` |
| Radius | 4, 6, 8, 12 px |

Every text colour was measured against all three light grounds; the lowest
pairing is `--busy` on `--bg-sunk` at 5.19:1 (AA needs 4.5:1). Re-measure if
a value changes.

Three rules:

1. **Blue means action, selection or focus.** Never decoration, never a
   status. External-bot modes are drawn in solid ink, not blue.
2. **A status hue never means two things.**
3. **No status is colour alone.** Every badge carries a word, most a glyph.

### Charts

`components/charts/`: the verdict trend (stacked bars) and pass rate by
group (dot with its Wilson 95% interval). Verdicts are statuses, so they use
the reserved status colours in the order pass, undetermined, fail, which the
dataviz skill's validator passed for colour-vision deficiency only with red
and green kept apart; fail also carries a hatch. Each chart has a legend, a
hover and focus tooltip and a table view. No chart draws data it was not
given: an empty period has no bar, an undecided group has no dot.

---

## Routes

| Route | Reads |
|---|---|
| `/` | Nothing at request time: `lib/content.ts` (phase table and language list drift-tested against README.md and `app/core/languages.py`) and the shipped Tamil scenario quoted in the hero preview |
| `/login`, `/signup` | `POST /auth/login`; `GET /auth/options`, `POST /auth/signup`. No password reset exists, and the page says so |
| `/app` | Analytics summary and trend, runs, suites and scenarios totals, health. A getting-started list computed from what exists |
| `/app/projects`, `/app/projects/[id]` | Projects per workspace with suite counts; one project's suites and recent runs; rename, describe, delete (admin+, 409 while it holds suites) |
| `/app/runs` | Runs with status, mode, outcome, language and scenario filters, pagination, CSV |
| `/app/runs/new` | Scenarios, suites, bot adapters. Creates then starts in the background |
| `/app/runs/[id]` | Report, turns, evaluations, recording manifest, metric catalogue, suite. Tabs: conversation, evaluation, evidence and setup, recording and audio, stages. Follows a live run every 3 s; sends the bot's reply for a paused run; evaluate, export, PDF, cancel, delete |
| `/app/scenarios` | Search by name, language, tag, archived; the shipped reference library as templates |
| `/app/scenarios/new`, `/app/scenarios/[id]/edit` | The builder (guided sections plus YAML source), validated by the server before every save |
| `/app/scenarios/[id]` | The specification read back, its runs; duplicate, archive or restore, delete (refused with the server's reason when runs use it) |
| `/app/suites`, `/app/suites/[id]` | Suites by project with counts; a suite's scenarios, run history, move, bundle import (dry run first) and export, rename, delete |
| `/app/bots` | Bot adapters, speech and caller providers, `telephony_status` and `evon_status` verbatim. Read-only: adapters are configured on the server |
| `/app/analytics` | Summary, trend and regression with the endpoints' own filters; pass rate by group; CSV |
| `/app/compare` | Two runs picked by search, then `GET /analytics/compare`. Pairwise only |
| `/app/reports` | Finished runs with JSON, CSV and PDF; the all-runs CSV; links to comparison |
| `/app/settings`, `/settings/team`, `/settings/account` | Current workspace and health; members, roles and the permission matrix from docs/AUTH.md; profile, password change |

Old paths redirect: `/app/new-test` → `/app/runs/new`, `/app/providers` →
`/app/bots`, `/app/workspace` → `/app/settings/team`.

Every `/app` route needs a session. `proxy.ts` redirects to `/login?next=...`
when the `bb_session` cookie is absent; the API decides on every request, and
a page that gets a 401 redirects through `signInAgainIfExpired`.

### What is not built, because the API does not back it

- Bot-integration CRUD: adapters are a server-configured catalogue.
- Password recovery, email invitations, notifications.
- Renaming or deleting a workspace; editing your name or email.
- Comparing more than two runs; suite-wide execution; reordering scenarios.
- Semantic correctness, context retention, response relevance and language
  quality: listed as unavailable on every evaluation, never scored.

---

## Cache Components

`next.config.ts` sets `cacheComponents: true`, so `export const dynamic`,
`revalidate` and `fetchCache` are forbidden, and uncached data must sit inside
`<Suspense>`. Every workspace route is a static shell (the page header
prerenders) with its data streamed in behind a skeleton shaped like it.

`usePathname()` is request-time data too: the shell reads it in a tiny
component inside its own Suspense boundary (`PathAware` in
`components/shell/sidebar.tsx`) so the rest of the chrome prerenders.

Server data comes through `loadContext()` (`lib/api/context.ts`): the user,
their workspaces and every workspace's projects with the caller's role,
deduplicated per request with React's `cache()`. Roles there only decide
which controls are shown; the API checks every action again. The selected
workspace is a preference cookie (`bb_workspace`), not an access control.

---

## Components

| Directory | Holds |
|---|---|
| `components/ui/` | `primitives.tsx` (buttons, panels, facts, `NotReported`, `Stat`, states, tables, skeletons), `field.tsx` (labelled controls with error wiring), `status.tsx` (the status vocabulary), `interactive.tsx` (native-dialog `Dialog`, in-page `ConfirmAction`, ARIA `Tabs`, `PrintButton`, `useAction`) |
| `components/shell/` | sidebar, mobile drawer and Ctrl/⌘ K command menu; page header; account and workspace switcher |
| `components/marketing/` | header, footer, the hero's product preview |
| `components/auth/` | sign-in, sign-up, password field |
| `components/scenario/` | the builder and the scenario actions |
| `components/runs/` | conversation inspector, audio player, reference editor, evidence, evaluation view, stage timeline, run controls, new-run form, compare picker |
| `components/domain/` | runs table, project and suite controls |
| `components/settings/` | team controls, password form, settings nav |
| `components/charts/` | verdict trend, pass-rate intervals |

**Dialogs are native `<dialog>` with `showModal()`**: the browser supplies the
focus trap, the inert background, Escape and focus return. Destructive actions
confirm in the page; `window.confirm()` would block the tab.

**`TableScroll` is `relative` on purpose.** An absolutely positioned
descendant (a screen-reader-only header label) escapes an overflow container
that is not positioned, and once widened the Team page by 187 px at 390 px.

**`min-w-0` on grid and flex children is load-bearing**, as before: without it
a panel holding a wide table inflates its own track.

---

## The API client

`lib/api/client.ts` is the only module that calls the API. One `request`
function owns the timeout, the error envelope, query serialisation (empty
values dropped) and, since 2026-11-20, multipart bodies: a `FormData` body is
sent as is so the browser sets the boundary (used only by `supplyBotAudio`).

The browser calls only its own origin: `/api/v1/*` is rewritten to
`BACKEND_URL`, so the HttpOnly session cookie is first-party.
`lib/api/server.ts` reads the cookie for server components and passes it in.
No script can read the token. There is no mock mode and no fallback data.

`lib/api/types.ts` is transcribed from the backend's schemas. Never add a
field the API does not return. Verify query-parameter names and `limit` caps
against the OpenAPI document: an unknown parameter is ignored, not refused,
and every listing caps `limit` at 100 (a 200 once broke the suite page).

---

## Honesty rules

| Field | Must drive |
|---|---|
| `uses_language_model` | "rule engine", never "AI caller" |
| `bot_audio_externally_received`, `bot_text_externally_received` | whether a run may be described as testing a bot; derived from replies, never the mode |
| `measurement_note` | printed verbatim wherever counts appear |
| `evon_status`, `telephony_status` | printed verbatim |
| `settings_not_enforced` | each setting with its reason; `null` shown as "not recorded" |
| `stt_provider: "fake"` | a caution above the run's tabs and on the adapters page |
| a metric's `value: null` | "Not reported" with the evaluator's reason, never 0 |

`caveatsFor(run)` in `components/runs/evidence.tsx` is the single derivation:
the cautions banner above a run's tabs and the full evidence list read it.

**Three failure modes stay three things**: `text: ""` is Silence (the bot),
`text: null` plus `transcription_error` is Not transcribed (us), and
`audio_validation_failed` is a run-level failure. **The waveform is drawn
from decoded audio or not at all**, and decoding is lazy. Stage events are
shown under the turn index the backend recorded, never re-attributed.

The scenario builder emits only fields the specification declares and omits
optional blocks the author left empty (`lib/scenario-draft.ts`); the server is
the only validator and runs before every save.

---

## Accessibility

Verified in a browser, not assumed: a skip link first in tab order; visible
focus everywhere; labels on every control with errors tied by
`aria-describedby`; native selects; ARIA tabs with arrow keys; `lang` on every
transcript, endonym and script sample; no status by colour alone; reduced
motion respected; touch targets of 44 px on phone chrome; no horizontal page
overflow at 390 px.

---

## Commands and tests

```bash
cd frontend
npm run dev               # development server
npm run typecheck         # next typegen && tsc --noEmit
npm run lint              # eslint
npm run build             # production build - the real check for prerender errors
npm test                  # node --test: lib/ units and drift tests
npm run test:components   # vitest + jsdom + Testing Library
```

Unit tests cover the formatters, the redirect guard, the API client, metric
rows, barge-in wording, run filters, channel conditions, the script splitter,
the password rule and the scenario draft. Drift tests read the backend:
README's phase table, `languages.py`, `passwords.py`, the scenario
specification's enumerations, and the run-filter enums.

Component tests drive components as a user does, with only the API client and
the router mocked: the builder's validate-before-save and field errors, the
run form's create-then-start and orphaned-run paths, scenario and suite
actions, the reference editor, sign-in and sign-up, the bot reply, the
evidence caveats and the evaluation view's not-reported state.

The dev server sometimes omits Tailwind classes unique to a newly created
file; the production build does not. Review visuals against `next build` and
`next start`.
