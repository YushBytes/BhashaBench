# BhashaBench — Development Roadmap

BhashaBench is built in **15 phases** — the original plan, restored. Each phase
is a reviewable increment that ends with working code, passing tests and
updated documentation.

**Current status: Phases 1–5 complete; Phase 6 partially complete (a
deterministic caller is delivered and a Sarvam language-model caller is
implemented and tested offline, with live calls neither authorised nor
verified; Evon itself remains blocked); Phases 7, 9, 10, 12, 13 and 15
partially complete; Phases 8, 11 and 14 not started. Phase 0 — a baseline and
defect-remediation pass before new functionality — is complete: approved by
the owner, pushed, and green in CI. A closing audit of Phase 1 on 2026-11-15
found its criteria met with no new work.**

Where this document describes an unfinished phase in the present tense, read
it as the intended design, not as existing behaviour.

---

## Why the numbering changed back

During the competition the work was accelerated and rearranged: telephony was
deferred, the operator workspace was built early, and the phases were
renumbered in flight ("competition numbering"). That made it impossible to
tell from a phase number what had actually been delivered. The original
numbering is restored below. The competition history is preserved, not
rewritten: the delivered-work sections in Part A keep their original text, and
the reports in `docs/` (`PHASE_08_*`, `COMPETITION_*`, `docs/competition/`)
keep the numbering they were written in. Use this table to translate.

| Original phase | Where the work happened (competition numbering) |
|---|---|
| 1 Project Foundation | Phase 1 |
| 2 Database & Scenario Engine | Phase 2 |
| 3 Scenario Library & Tooling | Phase 3 |
| 4 Gnani Prisma STT | Phase 4 |
| 5 Gnani Timbre TTS | Phase 5 |
| 6 AI Caller Simulation — Evon | Phase 6 (deterministic substitute); LLM caller under the original numbering |
| 7 Audio Degradation Engine | Phase 7 |
| 8 Telephony Integration | planned as "Phase 9 — Twilio" |
| 9 Real-Time Conversation Engine | Phases 7 and 7.1 (sequential loop, concurrency); planned as "Phase 10" |
| 10 Recording & Transcription | Phases 6–7 (per-turn artefacts and transcripts) |
| 11 Evaluation & Judge Engine | planned as "Phase 11" (unchanged) and part of "Phase 12 — Multilingual Benchmarking" |
| 12 Reporting & Analytics Backend | Phase 8 run list/report endpoints; planned as "Phase 13 — Results API" |
| 13 Frontend Dashboard | Phase 8 (operator workspace and public site) |
| 14 CI/CD & Safety | planned as "Phase 14" (unchanged) |
| 15 Production Readiness & Competition Demo | competition submission; planned as "Phase 15" |

## Phase status

| # | Phase | Status |
|---|-------|--------|
| 0 | Baseline & defect remediation | ✅ Complete |
| 1 | Project Foundation | ✅ Complete |
| 2 | Database & Scenario Engine | ✅ Complete |
| 3 | Scenario Library & Tooling | ✅ Complete |
| 4 | Gnani Prisma — Speech to Text | ✅ Complete (batch live-verified; streaming not live-verified) |
| 5 | Gnani Timbre — Text to Speech | ✅ Complete (batch; streaming not implemented) |
| 6 | AI Caller Simulation — Evon | 🟡 Partial — rule engine delivered; Sarvam LLM caller implemented and tested offline, live calls not authorised or verified; Evon blocked |
| 7 | Audio Degradation Engine | ✅ Complete (synthetic noise; no recorded noise beds) |
| 8 | Telephony Integration | 🟡 Partial — provider abstraction, guardrails, signed webhooks and a mocked provider; no real call placed or authorised |
| 9 | Real-Time Conversation Engine | ✅ Complete (streaming turn-taking and recovery verified against the reference bot; STT/TTS still per utterance; energy VAD) |
| 10 | Recording & Transcription | ✅ Complete (local filesystem storage; recordings assembled from turn audio, not captured live) |
| 11 | Evaluation & Judge Engine | ✅ Complete (deterministic; LLM judge offline-only, not validated against human labels) |
| 12 | Reporting & Analytics Backend | ✅ Complete (comparison, regression, aggregates, export; signed artefact URLs moved to Phase 10; no PDF) |
| 13 | Frontend Dashboard | ✅ Complete (analytics, comparison, workspace, authoring and live run views on the real API; lib/ unit-tested, components not) |
| 14 | CI/CD & Safety | ✅ Complete (auth, tenancy, rate limits, headers, dependency and secret scanning, regression gate; no nightly run) |
| 15 | Production Readiness & Competition Demo | 🟡 Partial — production images, compose, startup refusals, backup/restore (rehearsed locally) and a priced plan; not deployed, no week unattended |

---

## Phase 0 — Baseline & defect remediation ✅

A pass before any new functionality, so later phases build on a repository
that is honest about itself.

- Commit the approved demo polish in concern-sized commits.
- Restore the original phase numbering (this document) and a main-only Git
  workflow.
- A CI foundation: Ruff, pytest against a real PostgreSQL that may not be
  skipped, Alembic drift checks, frontend typecheck, lint and production
  build, and Compose validation.
- Fix four defects: the per-run bot adapter was ignored after creation;
  `offline_simulation` had no reply source and never terminated; nothing
  recovered abandoned runs; a scenario's declared SNR and packet loss were
  ignored. Report the scenario settings that are still declared but not
  enforced.

**Exit criteria.** Each defect has a test that fails before its fix and
passes after; CI is green locally; the status tables in this file, README and
CLAUDE.md agree.

**Delivered.** All four defects fixed with fail-before tests; the declared-
but-not-enforced settings reported per run; an explicit, dry-run-first
`bhashabench runs recover-stale` (never applied to the two historical runs,
which it permanently excludes by id);
`.github/workflows/ci.yml` green on GitHub. 2073 tests collected,
2032 pass, 41 opt-in live tests skipped; API 36 paths / 44 operations.

**What the first CI run found.** The first run on GitHub (on `60e7b3e`)
failed its frontend job: `tsc --noEmit` could not find `LayoutProps`, a
type Next.js generates into the git-ignored `.next/types/`. The local
typecheck had passed only because an earlier build left those files on
disk. `5452fdc` runs `next typegen` first, verified in a clean clone, and
all three jobs passed on it. Approved by the owner and pushed on
2026-11-14.

---

# Part A — Delivered work (historical record)

The sections below are the records written as each piece of work closed, kept
as written. **Phase numbers inside them use the competition numbering**; the
heading of each states the original phase it belongs to.

## Phase 1 — Project Foundation ✅

**Goal.** A monorepo that runs, lints, tests and builds, so later phases add
features instead of plumbing.

**Delivered.**

- Monorepo layout: `backend/`, `frontend/`, `scenarios/`, `benchmarks/`,
  `sample_bot/`, `scripts/`, `docs/`, `.github/workflows/`.
- FastAPI backend with `GET /`, `GET /health`, `GET /api/v1/health`.
- Configuration via `pydantic-settings`, with validation and a fail-fast check
  on the placeholder `SECRET_KEY`.
- Uniform JSON error envelope and OpenAPI documentation.
- Next.js App Router frontend (TypeScript, Tailwind, ESLint) with a dark-first
  status shell.
- Docker Compose stack: backend, frontend and PostgreSQL with a health check
  and a persistent volume.
- Ruff and pytest configuration; 35 backend tests.
- `README.md`, `ARCHITECTURE.md`, `CONTRIBUTING.md` and this roadmap.

**Explicitly out of scope.** No database tables, no provider API calls, no
telephony, no scenario execution.

---

## Phase 2 — Database & Scenario Engine ✅

**Delivered.** Define the durable shape of a test run, and the scenario
authoring format.

- SQLAlchemy 2.0-style typed models: `TestSuite`, `Scenario`, `TestRun`,
  `CallSession`, `ConversationTurn`. UUID keys, `timestamptz`, explicit
  `ondelete` on every foreign key, CHECK-constrained status columns.
- Alembic migrations with the initial revision checked in, a verified
  downgrade, and `alembic check` for drift.
- Synchronous engine and session dependency with pooling. (Synchronous, not
  async — see `app/db/session.py` for why.)
- The `database` health component now runs a real `SELECT 1` probe, reporting
  `ok` or `unavailable` instead of a hardcoded `degraded`.
- Repository and service layers; 246 tests, with the database ones running
  against a real PostgreSQL.

**Also delivered, moved forward from Phase 3:** the scenario YAML format and
its strict validation, plus suite and scenario CRUD endpoints. The schema and
the authoring format are two halves of the same decision, and splitting them
would have meant storing documents whose shape was not yet defined.

**Exit criteria — met.** `alembic upgrade head` succeeds against the Compose
database, the downgrade is reversible, and `/api/v1/health` reports the
database honestly.

---

## Phase 3 — Scenario Library & Tooling ✅

**Delivered.** Make a scenario collection navigable, editable and portable.
The scenario *format*, its validation and its CRUD endpoints arrived in
Phase 2; this phase is everything around them.

- **Library search.** `GET /api/v1/scenarios` across every suite, filtering by
  suite, exact language, name substring and repeatable tags, ordered by name
  then id so paging stays stable. Tag filtering is a JSONB containment test
  served by a new GIN index on `scenarios.spec` (migration `4997650a09c8`).
- **Suite editing.** `PATCH` for name and description, distinguishing an
  omitted field from an explicit null; `DELETE` that refuses a non-empty suite
  unless `?cascade=true`, because the foreign key cascades and a bare delete
  would take every scenario with it.
- **Copy and move.** Copy gives the new scenario a fresh id and re-validates
  the spec; move preserves the id so existing references stay valid.
- **Language catalogue.** 13 Indian languages in `app/core/languages.py` as
  the single source of truth, with endonym, ISO 15924 script and POSIX locale,
  readable at `GET /api/v1/languages`.
- **Code-mixing annotations.** A structured, optional `code_mixing` block —
  primary and secondary languages, switch triggers, expected ratio, sample
  utterances — plus `expected: false` to assert a monolingual caller. Scenario
  spec version 2; v1 documents still validate unchanged.
- **Bundles.** One YAML document holding a suite and its scenarios.
  Import collects every entry error rather than stopping at the first, and is
  atomic by default with a dry-run mode. Export is deterministic and
  round-trippable: ordered by name, defaults materialised, no ids or
  timestamps.
- **The `bhashabench` CLI.** Validation and the catalogue work offline so CI
  can reject a malformed scenario before any service exists; suite, scenario,
  import and export commands reuse the same services the API calls.
  Distinguished exit codes (0/1/2/3) and `--json` on every command.
- **Reference scenarios.** Six languages in `scenarios/`, each stressing a
  different failure mode, with a generated bundle and tests that fail if they
  drift from the schema.
- 561 tests, up from 246.

**Exit criteria — met.** A directory of scenario files can be validated
offline (`for f in scenarios/*.yaml; do bhashabench validate "$f"; done`) and
a whole suite imported in one command, with a dry run first.

**Deliberately not in this phase.** No Gnani Prisma, Timbre or Evon
integration, no telephony, no audio processing and no scoring. The scenario
library is now complete enough to drive those.

---

## Phase 4 — Gnani Prisma (Speech to Text) ✅

**Status: complete. Approved by the owner on 2026-11-07.**

**Delivered.**

- **Provider-independent interface.** `TranscriptionProvider` protocol with
  `ProviderCapabilities` as declared metadata, so a limitation is published
  rather than discovered from a failed request. Nothing above
  `app/transcription/providers/` references a vendor field name.
- **Gnani Prisma adapter.** Batch (`POST /stt/v3`, multipart) and streaming
  (`wss://.../stt/v3/stream`, 1024-byte PCM frames), built against the
  contract published at docs.gnani.ai and isolated in
  `providers/prisma_contract.py`.
- **Offline fake provider.** Implements the same interface and can be scripted
  into every failure the real adapter produces. The default test suite needs
  no credential and makes no network call.
- **Audio validation.** Container identified from content, not from a declared
  MIME type or extension; WAV headers parsed with the standard library; size,
  duration, sample-rate and channel limits. No decoding and no conversion —
  resampling belongs to Phase 7.
- **Bounded retry.** Exponential backoff with full jitter, a ceiling that also
  bounds a provider's `Retry-After`, and permanent failures never retried.
  Streaming is never retried automatically.
- **Credential redaction** in the adapters and again at the HTTP and WebSocket
  boundaries. Structured logging that records transcript *length*, never
  transcript text.
- **Three endpoints**: `POST /api/v1/transcription`,
  `GET /api/v1/transcription/providers`, and the
  `/api/v1/transcription/stream` WebSocket.
- 964 tests, up from 561. 15 of them are opt-in live provider tests.
  (1327 after Phase 5; 1669 after Phase 6; 1907 after Phase 7; 1957 after
  Phase 7.1; 1990 collected after Phase 8.)

**Verified language support.** Prisma documents ten of BhashaBench's thirteen
catalogue languages. Urdu, Odia and Assamese have no speech model: a scenario
may be authored in them and no transcript can be produced. The request is
refused explicitly rather than transcribed as a neighbouring language.

**Exit criteria.** A fixture audio file transcribes end to end through the
provider interface, and the provider can be swapped for a fake in tests —
**met against the fake and against the documented contract**. Not yet met
against the live service: see below.

**Live verification, 2026-11-07.** Three real calls were made against
`api.vachana.ai` with a real key. Verified live: **authentication**, a **real
batch request**, and **response parsing** into a `TranscriptionResult` with a
provider `request_id`.

Still **not verified**: real streaming transcription, and streaming provider
behaviour - the WebSocket adapter has never spoken to Gnani, and its framing
and event mapping rest on the vendor's published example alone.

**Recognition accuracy is not independently benchmarked**, and no test here
claims otherwise. The committed fixtures are synthesised tones with no reviewed
ground truth, so the live result means "the pipe works", not "the model is
good". Quality benchmarking is Phase 11 and needs licensed, transcribed
speech. Per-capability detail is in `docs/PROVIDERS.md`.

**Deliberately not in this phase.** Prisma's asynchronous batch-jobs pipeline
for long or many files; the three output modes whose literal wire values the
vendor does not publish; automatic language detection; any persistence of
transcripts.

---

## Phase 5 — Gnani Timbre (Text to Speech) ✅

**Status: complete. Approved by the owner on 2026-11-07, after live verification.**

**Delivered.**

- **Provider-independent interface.** `SynthesisProvider` protocol with
  `SynthesisCapabilities` as declared metadata, mirroring Phase 4. Nothing
  above `app/speech/providers/` references a vendor field name.
- **Gnani Timbre adapter.** `POST /api/v1/tts/inference`, built against the
  contract published at docs.gnani.ai and isolated in `timbre_contract.py`.
  Handles a **binary** response: a 200 with an empty body or a JSON error is
  caught rather than handed on as audio.
- **13 documented voices** with the character each is catalogued for, so a
  voice can be matched to a scenario persona rather than guessed from a name.
- **Offline fake provider** that returns a real, parsable WAV - not a
  placeholder byte string, so the measurement path is actually exercised.
- **Audio verification.** Sample rate, channels and duration are read from the
  returned audio, never echoed back from the request, and the requested rate is
  retained alongside so a provider that ignored it is visible.
- **Bounded retry**, reusing Phase 4's policy; 400/401/402/403 never retried.
- **Serialised calls.** The owner reports a one-active-request limit; it is not
  in any vendor page consulted, so the adapter serialises conservatively.
- **Two endpoints**: `POST /api/v1/speech/generate` (returns binary audio with
  `X-Speech-*` metadata headers) and `GET /api/v1/speech/providers`.
- 1327 tests, up from 964. 26 of the new ones are opt-in live tests.

**Verified language support.** The same ten languages Prisma recognises, plus
`auto` and `hi-en`. Urdu, Odia and Assamese cannot be spoken, and there is no
Tamil-English code-mixed value - `hi-en` is the only one documented.

**Live verification, 2026-11-07. Two real calls, both informative.**

Verified live: authentication, that the shared key carries the TTS scope, that
the request is accepted, that the audio is decodable - 8 kHz mono 16-bit PCM,
4.400 s, requested rate honoured - and, after the fix below, that the **full
adapter path** returns a valid result.

The first call found a bug no mock could: Timbre writes a *streaming* WAV header
with `0xFFFFFFFF` size fields, which our Phase 4 truncation check read as a
damaged file and rejected. The inspector now separates that sentinel from a
plausible-but-short declaration, so a genuinely truncated file is still refused -
checked in both directions against the real artefact. The second call confirmed
the corrected path end to end.

**Not evaluated.** Pronunciation, prosody and intelligibility. The generated
WAV was saved locally for listening, but nobody has listened to it, and no
automated test can judge it. "Synthesis verified" means the pipe works and the
audio is well-formed - not that the Tamil sounds right.

**Exit criteria.** A persona utterance synthesises to a playable, correctly
formatted audio artefact - **met**, against the live service and against the
fake.

**Deliberately not in this phase.** Timbre's SSE and WebSocket streaming
transports; voice cloning; audio caching (nothing repeats a request until
Phase 9 drives a conversation); the three output modes whose literal wire
values the vendor does not publish; any persistence of generated audio.

---

## Phase 6 — AI Caller Simulation: deterministic substitute delivered, Evon ⛔ blocked

*Competition Phase 6. The LLM caller remains open — see Part B.*

**Phase 6 uses deterministic, rule-based caller orchestration. Official Gnani
Evon integration is deferred until documented access and credentials are
available.**

**Evon integration is NOT implemented or verified in this phase.**

### Why the scope changed

A feasibility gate ran before any implementation and did not pass. No Gnani
**text-generation** endpoint is published — the documented surface is
recognition (Prisma) and synthesis (Timbre) — and the released model
`gnani/gnani-evon-v3.3-30B-A3B` has no hosted inference provider advertised.
There is therefore no base URL, no request schema and no response schema to
transcribe into a contract module, and this repository does not add a provider
constant it cannot cite.

The owner authorised a deterministic caller as an explicitly temporary
stand-in. It is named for what it is: `CALLER_PROVIDER=deterministic`,
`uses_language_model: false` on every API response, and an `evon_status` field
on `GET /api/v1/caller/providers` saying the integration is not implemented.
`evon` is **not** a registered provider; configuring it fails with an error
that explains why. No stub adapter exists, because one that raised on every
call would have advertised Evon as a configurable option.

### Delivered

- `CallerProvider` protocol, `CallerCapabilities`, a registry of factories and
  an offline-only provider — the same shape as the Prisma and Timbre
  subsystems, so an Evon adapter slots in without touching anything above it.
- An explicit nine-state machine with a table of every permitted transition.
  Every non-terminal state can reach a terminal one, so a runaway conversation
  is impossible by construction rather than only by the turn counter.
- Eleven ordered rules over signals extracted from the bot's transcript. The
  same scenario against a bot that asks for a reference, refuses, mishears,
  misquotes a fact or answers produces five different conversations.
- A transcript analyser that normalises NFKC, maps nine Indic digit ranges to
  ASCII and unions English keywords into every language, because the
  code-switching this project measures means an Indian-language bot says
  "reference number" in English.
- Decision validation before synthesis: length and transition limits, nine
  instruction-leak patterns, and rejection of any identifier-shaped number not
  traceable to a known fact. Written for the model provider that replaces the
  rule engine, which will need them.
- Conversation persistence on the Phase 2 schema. **No new tables and no
  migration**; `alembic check` reports no drift.
- Seven endpoints under `/api/v1/caller`, and an offline `simulate()` that
  drives a whole conversation against a scripted bot with no provider, no
  credential and no telephony.
- 342 offline tests.

### Three defects the tests found

Worth recording, because each was invisible by inspection:

- **`caller.confirmed_close` was effectively unreachable.** It sat below
  `bot.confirmed`, so a bot answering a read-back with "yes, that is correct"
  drove `confirming -> confirming`, which the state machine forbids — the
  conversation died on the most ordinary turn in the script. Found by a sweep
  of every state against every shape of reply.
- **`ALLOWED[INTRODUCING]` omitted `CONFIRMING`.** A bot that answered the
  objective in its first reply — a helpline that recognises the caller's
  number does exactly that — had the caller's read-back rejected.
- **Provider error text reached the database and the API unredacted.** Both
  the transcription and synthesis failure paths interpolated the raw exception
  into `turn_metadata`, which is also returned on the wire. The same class of
  defect Phase 4 fixed twice.

A fourth, smaller one: the invented-identifier threshold was four digits while
its own comment claimed "2019" would pass. It is now five, so a caller can say
the year it registered a holding.

### Not verified

| | |
|---|---|
| Gnani Evon API access | Not available. Nothing was called |
| Conversation quality / naturalness | Not evaluated. A rule engine composing from fixed phrase tables |
| Behaviour against a real voice bot | Not verified. Nothing here has had a conversation with one |
| Code-mixed caller speech | Not generated. A scenario may declare it; the caller will not produce it |
| Languages beyond `ta-IN`, `hi-IN`, `en-IN` | No reviewed phrase table. Such a scenario is refused, not answered in English |

**Exit criteria.** The simulated caller completes a multi-turn conversation
without human input — **met** offline, against a scripted bot and against
supplied bot replies through the API. **Not met** against the local sample bot:
`sample_bot/` is empty and was not in the authorised scope.

**Deliberately not in this phase.** Any Evon adapter, stub or otherwise;
telephony; audio degradation; a sample bot; scoring. Persona conditioning is
projected from the scenario and shapes the opening utterance, but accent and
interruption behaviour belong to Phases 7 and 9, where the audio and the call
exist.

---

## Phases 7, 9 and 10 (partial) — End-to-End Voice Pipeline & Audio Degradation

*Competition Phase 7. The degradation engine is original Phase 7; the
sequential turn loop and per-turn artefacts are the delivered part of
original Phases 9 and 10.*

The phase that connects the previous three. A scenario becomes a multi-turn
conversation with real audio: the Phase 6 caller decides, Timbre synthesises,
the degradation engine makes it sound like a phone call, a bot adapter carries
it, and Prisma transcribes the reply.

### Delivered

- **A run engine** (`app/pipeline/engine.py`), free of FastAPI so it is
  testable without it. Three statuses beyond the database's five live in
  `run_metadata`, and nine outcomes separate what the bot did from what we
  broke.
- **Execution modes.** `offline_simulation`, `audio_fixture_test` and
  `external_bot_test` are usable; `telephony_test` exists in the vocabulary and
  is refused, because no telephony exists. Every run records its mode and every
  report repeats it.
- **The audio degradation engine** (`app/pipeline/degradation.py`): channel
  conversion, resampling, a cascaded one-pole bandpass, noise at a target SNR,
  level, clipping and whole-packet loss, in a fixed order that mirrors a real
  path. Five named profiles, and the six acoustic environments the Phase 2
  scenario schema declared with the note "Phase 7 implements these" now map
  onto them.
- **Bot adapters** (`app/pipeline/bots/`): a scripted offline adapter and a
  manual adapter that stores the caller's audio and waits for an operator to
  post the bot's reply. Neither opens a socket, and the default is the one that
  sends audio nowhere.
- **Artefact handling.** Both the original and the degraded audio survive every
  turn, the processed file names its source, and every path component is
  generated or whitelisted.
- **Nine endpoints** under `/api/v1/test-runs` as delivered here; Phase 8
  added two more, for eleven operations across ten paths. 238 offline tests.
- **No new table and no migration.** `alembic check` reports no drift.

### Pure Python DSP, deliberately

The repository has no numpy, scipy, soundfile or pydub, and `audioop` was
removed from the standard library in Python 3.13. One utterance is a few
seconds of 8 kHz mono, so the hundred-odd lines of integer arithmetic these
transformations need run in about 30 ms - and a scientific stack carried for
that would be the overengineering this phase was told to avoid. Only 16-bit PCM
WAV is accepted; guessing at other widths without a decoder is how a bench
starts reporting on audio it did not understand.

### Four defects the tests found

- **`conversation.scenario` was reached on a freshly created row.** The
  relationship is `lazy="raise_on_sql"`, so it resolved from the identity map
  until something committed - which made it a 500 that appeared only behind the
  HTTP layer, never in the engine tests.
- **The turn loop allowed `budget + 1` turns** and left a truncated run
  `running` with no outcome. A narrower `max_turns` now reaches the caller's own
  metadata, so Phase 6's budget rule closes the conversation gracefully.
- **A malformed upload killed the run.** On the manual endpoint that is the
  operator's mistake, not a reason to discard a conversation; it is now refused
  with a 4xx and the run stays waiting so they can retry.
- **A fresh run reported itself `running`.** Phase 6's `create_run` marks a run
  running with a start time because it creates and uses one immediately; a
  pipeline run is created and started separately, so it is reset to `pending`.

A fifth, smaller: the scenario noise vocabulary was assumed rather than read.
The schema's six environments are `clean`, `urban`, `rural`, `market`,
`indoor_fan` and `worst_case`, and the mapping now covers all of them.

### Not verified

| | |
|---|---|
| A live Gnani call through the pipeline | Not made. None was authorised, and none is needed for an offline run |
| A real voice bot conversation | Not tested. No external bot endpoint was available; the `manual` adapter is the path for when one is |
| Telephony | Not implemented. A run in that mode is refused |
| Recognition accuracy under degradation | Not measured. The fixtures contain no speech with reviewed ground truth |
| Conversation quality | Not evaluated. A successful transcription means the pipeline worked, not that the bot answered well |

**Simulated noise is shaped white noise at a stated signal-to-noise ratio over
a band-limited channel.** It is not a field recording, this repository contains
no environmental recordings, and the profiles are named for severity because
severity is what they control.

**Exit criteria.** The same seed and profile produce byte-identical output -
**met**, asserted for every profile. A multi-turn audio workflow executes
offline - **met**. A genuine external voice-bot conversation - **not met**, and
not claimed.

### Competition Phase 7.1 — concurrency enforcement (original Phase 9)

`PIPELINE_MAX_CONCURRENT_RUNS` shipped in Phase 7 as a documented number that
nothing read: the setting existed, the run metadata recorded it, and no code
consulted it. The gap was reported in the Phase 7 close-out and is now closed.

A process-wide counting guard admits at most the configured number of
concurrently executing runs and refuses the rest with **503** rather than
queueing them - a request parked behind an unbounded line has no bound on its
own latency, and the refused run is untouched so retrying is safe. The slot is
held by an `async with`, so completion, exception, cancellation and timeout all
release through the same `finally`, and admission is re-entrant per engine so
`supply_bot_audio` cannot refuse itself against its own slot.

Deliberately not an `asyncio.Semaphore`: one that waits holds waiters bound to
the loop that created them, which raises intermittently when a process-wide
instance is awaited from another loop. A non-blocking counter has no loop
affinity. 50 tests, with the overlap forced by `asyncio.Event` gates rather
than timed, so they cannot flake.

**Deliberately not in this phase.** Telephony or SIP; jitter and codec
simulation beyond band-limiting (G.711 and AMR-NB need a codec this project
does not carry); reverb, which needs an impulse response nobody has measured;
any accuracy or quality score; serving stored audio over HTTP, which is an
authorisation decision with no identity to make it against until Phase 15.
(Phase 8 revisited the last of these: the route ships, environment-gated and
claiming no authorisation. Real access control is still Phase 15.)

---

## Phases 13 and 12 (partial) — Operator Workspace & Public Site

*Competition Phase 8. The workspace is the delivered part of original
Phase 13; its run list and report endpoints are the delivered part of
original Phase 12.*

The phase that gave the instrument a face. Building it early was deliberate:
driving the pipeline through a UI is what made two of its own gaps visible,
and that is worth more before telephony than after it.

### Delivered

- **A public site** at `/` explaining what the instrument measures, and an
  **operator workspace** at `/app` that drives it: overview, run history with
  filters, a conversation inspector, the new-test workflow, the scenario
  library and provider status.
- **Two backend endpoints**, added because the workspace could not be built
  honestly without them. `GET /api/v1/test-runs` pages the run history with
  filters on suite, status, mode, language, outcome and scenario name.
  `GET /api/v1/test-runs/{run_id}/artifacts/{turn_index}/audio` serves stored
  turn audio with single-range `bytes=` support so a player can seek.
- **Audio playback with waveforms drawn from the decoded bytes** - or not
  drawn at all. There is no synthetic fallback, because a generated waveform
  is a picture of a sound that does not exist.
- **A design system built by hand** (`components/ui/`): dependencies remain
  exactly `next`, `react` and `react-dom`. No component library, because the
  design avoids the two primitives that are genuinely hard - focus trapping
  and overlay positioning - by having no modals.
- **No mock mode and no fallback data.** `lib/api/client.ts` is the only
  module that calls the API; a failed call renders an error state. Returning
  plausible data when the backend is down makes a broken deployment look like
  a working one.
- **The honesty fields rendered structurally rather than as copy.**
  `uses_language_model`, `bot_audio_externally_received`, `measurement_note`,
  `evon_status` and `telephony_status` exist so a client cannot overclaim, and
  `RunEvidence` derives its caveats from the run rather than from the mode
  label - which is what makes a mislabelled `external_bot_test` visible.

### Superseded decisions

Phase 7 listed "serving stored audio over HTTP" as deliberately out of scope
until Phase 15, on the grounds that who may hear a recorded conversation is an
authorisation decision with no identity to make it against. That reasoning
still holds, and the route ships anyway under three constraints: no
client-supplied string reaches the filesystem, staging and production refuse
with **403** unless `PIPELINE_SERVE_ARTEFACTS` is set, and it claims no
authorisation - a run id is an identifier, not a credential. Withholding the
route never created an authorisation model; it only put the recording out of
reach of the one operator entitled to it. Real access control is still
Phase 15.

The old Phase 13 "React dashboard" is absorbed here.

**Exit criteria.** The workspace drives a real run end to end and renders its
transcript, stage timings and stored audio - **met**, exercised in the browser
against the real pipeline. A run is inspectable without reading the database -
**met**. Testing a real voice bot through it - **not met**, and not claimed.

### Reported, not fixed

*Historical. `audio_fixture_test` was fixed in commit `527bc3a`;
`offline_simulation` is addressed in Phase 0.*

Running the workspace surfaced two pipeline defects. Both are **still
unresolved** and are not frontend bugs:

- **`audio_fixture_test` cannot succeed through the API.** The route builds
  the scripted adapter with no replies, so the first turn fails with "the
  scripted bot has no reply for turn 0". The mode is usable only from tests,
  which inject audio. Fixing it means shipping a fixture audio asset or
  changing adapter construction - a design decision, not a typo.
- **`offline_simulation` does not reach a terminal status.** It produces the
  caller's opening turn and stays `running`: no audio moves, so nothing
  supplies a bot reply and the caller never becomes terminal.

**Deliberately not in this phase.** Telephony; a frontend test suite (type
checking, linting and a production build run, but the browser verification was
manual); run auto-refresh, where polling versus SSE is still an open question;
scenario detail, suite management and the audio lab; and authentication, which
remains Phase 15 for the whole application.

---

# Part B — Remaining work, by original phase

## Phase 6 — AI Caller Simulation 🟡 (LLM caller)

**Implemented offline on 2026-11-15; awaiting the owner's acceptance.**

- A provider-independent contract (`LlmClient`) and a model-backed caller
  strategy with bounded retry and deterministic fallback.
- Sarvam clients for `sarvam-105b` and `sarvam-105b-conversations`, from the
  published documentation, tested against a mock transport.
- Per-turn generation evidence, and `uses_language_model` derived from it.
- Per-turn token limits, a per-run cost limit, and a durable global budget
  capped at ₹100.
- No table, no column, no migration.

**Not done, and not to be claimed:** no live call has been made. Live testing
is not authorised; the ₹100 figure is a ceiling for later. The Sarvam contract
is transcribed from documentation and unconfirmed. No model has generated a
caller turn, so `uses_language_model` has never been `true` on a real run.
The plan for a first live test is in `docs/PROVIDERS.md`.


Blocked for **Evon specifically**: no Gnani text-generation endpoint is
published and the released model has no hosted provider (see Part A). The
approved route is a provider-independent caller architecture with a
documented alternative LLM provider as the first real integration, labelled
as what it is — never as Evon — with the deterministic caller retained and
Evon addable when a legitimate API or self-hosting route exists.

**Exit criteria.** A caller adapter against a published, documented endpoint,
live-verified with a cost-bounded call; every turn passes the existing
validation gate; `uses_language_model` is true and accurate; the
deterministic caller remains selectable; no invented provider constant.

---

## Phase 7 — Audio Degradation Engine ✅

**Complete on 2026-11-16.** The DSP existed (Part A) and Phase 0 made runs
apply a scenario's declared SNR and packet loss. Delivered since: jitter
under-runs, dropouts, truncation and silence padding; an exact G.711 μ-law
and A-law round trip; and all ten channel conditions declarable by a scenario
and overridable per run, field by field, with the source and the measured
achieved value recorded on every artefact.

**Not delivered, and not claimed:** per-language noise beds (they need
licensed field recordings this project does not have — the noise is synthetic
and is never described as a recording), speech-rate change (needs a
pitch-preserving time-stretch) and overlapping speech (needs a second voice
source). Neither of the last two can be declared.

**Exit criteria.** Every declared audio condition is applied or rejected,
never silently ignored, and the achieved values are recorded per artefact and
asserted in tests.

---

## Phase 8 — Telephony Integration 🟡

**Partial, 2026-11-18.** Delivered against a provider abstraction and a
mocked provider only (`docs/TELEPHONY.md`): E.164 numbers, every guardrail
checked before dialling, signed webhooks with replay protection, provider
statuses that can only move a call forward and are the only route to
`DIALING`, `NO_ANSWER` and `BUSY`, the `telephony_calls` table (migration
`bcf146f6c696`), and the mock labelled mocked in every record.

**Not delivered, and not claimed:** any real call, a Twilio (or other
vendor) adapter, media streaming, and `TELEPHONY_TEST` as a run mode. The
exit criterion below needs a real call and a paid number, neither
authorised, so the phase stays partial.

The first phase that can place a real call, and therefore spend real money.
It follows the documented HTTP/WebSocket bot protocol and the reference
sample bot, which come first.

- Outbound calls via the Twilio REST API; bidirectional media over Twilio
  Media Streams (WebSocket).
- Guardrails enforced *before* dialling: `ALLOWED_BOT_NUMBERS`,
  `MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`, `MAX_CONCURRENT_CALLS`.
- Webhook signature verification.

**Exit criteria.** A call to an allow-listed number streams audio both ways,
a call to any other number is refused before dialling, and `DIALING`,
`NO_ANSWER` and `BUSY` are only ever set by a real call.

---

## Phase 9 — Real-Time Conversation Engine ✅

Delivered: a sequential, request-driven turn loop with a process-wide
concurrency limit (Part A, competition Phases 7 and 7.1).

Delivered 2026-11-16, as the approved early prerequisite: the text protocol
`bhashabench-text-bot/1` (`docs/BOT_PROTOCOL.md`), a reference bot that
implements it (`backend/reference_bot/`), an outbound guard against SSRF, and
the `http` adapter behind a new `text_bot_test` mode. Verified over real
localhost sockets against the reference bot only; no third-party bot has been
tested, and the exchange is text, never audio.

**Complete on 2026-11-18** against its exit criteria: a streaming
conversation with the reference bot over `bhashabench-voice-bot/1` handles
barge-in (the caller yields), silence timeouts (an empty bot turn) and
per-turn deadlines, records each turn's measured bot latency on the
`bot_exchange` event, and a crashed run is closed by the background worker
while a run whose process died is closed by the automatic recovery sweep.
Delivered: background execution (`start?background=true`), the
`RecoveryLoop`, the streaming turn-taking module, the `ws_voice` adapter and
the reference bot's voice endpoint.

**Not delivered, and not claimed:** streaming speech-to-text and
text-to-speech inside the loop (both still run per utterance), a learned
voice-activity detector (energy only, threshold recorded), and any
third-party voice bot (only the reference bot has been driven).

**Exit criteria.** A streaming conversation with the reference bot handles
barge-in, silence timeouts and deadlines, records per-turn bot latency, and a
crashed or cancelled run reaches a terminal state on its own.

---

## Phase 10 — Recording & Transcription ✅

**Complete on 2026-11-17** against its exit criteria: every terminal run
stores a full-conversation recording whose segments link to the per-turn
artefacts (`GET /test-runs/{id}/recording`), and a retention period is
enforced by `bhashabench runs purge`, with deletion of runs, evidence and
audio tested through the API and the CLI. Also delivered: a `BlobStore`
contract with a local filesystem adapter, signed expiring audio links
(moved here from Phase 12), and the retirement of `PIPELINE_SERVE_ARTEFACTS`.
Earlier parts: per-turn original and degraded audio with provenance,
per-turn transcripts, the three failure modes kept distinct; transcript
export shipped with Phase 12. Design: `docs/STORAGE.md`.

**Not delivered, and not claimed:** object storage (no paid bucket is
authorised; `STORAGE_BACKEND` accepts `local` only), a recording captured
live off a line (the recording is assembled after the run, without the
inter-turn gaps), and a scheduled retention sweep (the sweep runs when
invoked; scheduling it belongs to the deployment).

**Exit criteria.** Full-conversation and per-turn audio stored and linked;
a retention period enforced and deletion tested.

---

## Phase 11 — Evaluation & Judge Engine ✅

**Complete on 2026-11-17** against its exit criteria: a completed run yields a
reproducible pass/fail with per-criterion reasoning (`POST
/test-runs/{id}/evaluations`, fingerprinted and append-only), and WER and CER
are computed against reviewed references recorded per bot turn. Methodology:
`docs/EVALUATION.md`.

**Not delivered, and not claimed:** a live LLM judge (the interface and its
validation exist and are tested with the scripted client; no model has judged
anything, because live calls are not authorised) and agreement checks against
a human-labelled set (none exists). Latency is the HTTP exchange only;
interruption counts need Phase 9's streaming.

Original scope:

- Deterministic metrics: word and character error rate against reviewed
  references with per-language normalisation, latency percentiles,
  interruption counts, task completion.
- An LLM judge behind the same provider-independent interface as the caller,
  with rubric versioning; `JUDGE_RETRIES` and `PASS_THRESHOLD` are applied
  here.
- Agreement checks against a human-labelled set.

**Exit criteria.** A completed run yields a reproducible pass/fail with
per-criterion reasoning, and WER is computed against reviewed references.

---

## Phase 12 — Reporting & Analytics Backend ✅

**Complete on 2026-11-17** against its exit criteria: two evaluated runs are
diffed by `GET /analytics/compare` (verdict change, per-metric deltas,
comparability warnings), and a regression between two groups of runs is
identified by `GET /analytics/regressions` (Fisher's exact test, p < 0.05 and
at least five decided runs a side, otherwise `insufficient_evidence`). Also
delivered: aggregates grouped by language, scenario, adapter, mode, outcome
or suite with Wilson intervals, day/week trends, and CSV/JSON export with
formula-injection neutralisation. Contract: `docs/REPORTING.md`.

**Not delivered, and not claimed:** artefacts served with signed, expiring
URLs — moved to Phase 10, because signing belongs to the storage abstraction
that phase introduces; and PDF export, which needs a rendering dependency.

**Exit criteria.** Two runs can be diffed and a regression identified.

---

## Phase 13 — Frontend Dashboard ✅

Delivered: the operator workspace and public site (Part A, competition
Phase 8).

**Complete on 2026-11-18** against its exit criteria: every metric shown is
measured and read from the API - pass rates always with their Wilson
interval and n, "no decided runs" never shown as 0% - and the comparison
and regression views read the Phase 12 endpoints and show their conclusions
verbatim. Also delivered: sign-in, workspace and member management, suite
and scenario authoring with server validation, run auto-refresh, the
evaluation and full-recording panels, and a `node --test` suite for `lib/`
run in CI.

**Not delivered, and not claimed:** component or browser tests (pages are
checked by typecheck, lint, build and an end-to-end pass against the running
API), and deletion controls for suites, scenarios and runs (the API routes
exist; the UI does not offer them yet).

**Exit criteria.** Every metric shown is measured, never sampled or
estimated, and comparison views read the Phase 12 API.

---

## Phase 14 — CI/CD & Safety ✅

**Part 1 delivered on 2026-11-17** (authentication and authorisation,
scheduled here by the execution checkpoint): accounts with scrypt passwords,
server-side sessions with an HttpOnly cookie or a bearer token, workspaces,
projects and four roles, every existing route authenticated and scoped to
the caller's workspace, migrations `05f303520380` and `b588560f044d`, the
frontend signing in through a same-origin proxy, and an OpenAPI-driven test
that fails when a route is added without a check. Design: `docs/AUTH.md`.

**Part 2 delivered on 2026-11-18**, closing the phase against its exit
criterion - a deliberately introduced regression fails CI
(`backend/tests/test_benchmark_gate.py`, `benchmarks/`): per-client and
per-email rate limits, security headers, pip-audit and npm audit gates on
runtime dependencies, and a gitleaks scan of the full history.

**Not delivered, and not claimed:** a scheduled nightly benchmark and
published score artefacts (the gate runs on every push instead), secrets
in GitHub Environments (CI needs none), multi-factor authentication,
password reset by email (the application sends no email), and a
Content-Security-Policy for the frontend pages.

Phase 0 adds the foundation (lint, tests against a required PostgreSQL,
migration drift, frontend build, Compose validation). Remaining: a nightly
benchmark against the reference bot, scores published as build artefacts,
pull requests failing on regression beyond a threshold, secrets supplied via
GitHub Environments, and cost guardrails.

**Exit criteria.** A deliberately introduced regression fails CI.

---

## Phase 15 — Production Readiness & Competition Demo 🟡

Delivered: the competition demonstration and its materials.

Delivered 2026-11-18 (`docs/DEPLOYMENT.md`): production images (non-root,
health-checked, the frontend's backend address compiled in),
`docker-compose.prod.yml` with a one-shot migration and no published database
port, startup refusal of the placeholder secret, database password and a
localhost-only CORS list, backup, restore and restore-rehearsal scripts (a
rehearsal passed locally, 14 tables identical), runbooks, and a deployment
plan with every paid item priced and left for the owner. Authentication,
tenancy, rate limits and retention arrived with Phases 10 and 14.

Remaining: a deployment (needs the owner's purchase), alerting and log
shipping against it, a metrics endpoint, a load test, a restore rehearsed on
the deployed host, and a versioned `1.0.0` release once the exit criterion
holds. No `1.0.0` is cut before then.

**Exit criteria.** The platform runs unattended for a week with alerting and
no manual intervention, and a restore from backup has been rehearsed.

---

## Conventions across phases

- A phase ships only what it claims. Unimplemented dependencies are reported
  as `degraded` with a reason, never as healthy.
- No provider request shape is written until the phase that integrates it.
- Every phase keeps Ruff, pytest, ESLint and `next build` green.
- Guardrails land in the same phase as the capability they bound, never later.
