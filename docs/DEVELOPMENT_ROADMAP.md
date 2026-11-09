# BhashaBench — Development Roadmap

BhashaBench is being built in 15 controlled phases. Each phase is a reviewable
increment: it ends with working code, passing tests and updated documentation.
A phase is not started until the previous one is approved.

**Current status: Phases 1–5 complete. Phases 6–15 not started.**

Nothing in phases 6–15 is implemented. Where this document describes a
component in the present tense, read it as the *intended* design for that
phase, not as existing behaviour.

---

> **Phase 8 renumbered the tail.** The React dashboard was Phase 13 and the
> operator workspace was not a phase at all. Building the workspace early
> made the pipeline's own gaps visible — `audio_fixture_test` cannot succeed
> through the API, and an offline run never terminates — which is worth more
> before telephony than after it. Telephony moved from 8 to 9 and everything
> below it shifted by one; the old Phase 13 is absorbed into Phase 8.

## Phase status

| # | Phase | Status |
|---|-------|--------|
| 1 | Project Foundation | ✅ Complete |
| 2 | Database & Scenario Engine | ✅ Complete |
| 3 | Scenario Library & Tooling | ✅ Complete |
| 4 | Gnani Prisma — Speech to Text | ✅ Complete |
| 5 | Gnani Timbre — Text to Speech | ✅ Complete |
| 6 | Caller Simulation — deterministic engine | ✅ Complete (Evon **not** integrated) |
| 7 | End-to-End Voice Pipeline & Audio Degradation | ✅ Complete (no live call, no real bot) |
| 7.1 | Concurrency Enforcement | ✅ Complete |
| 8 | Operator Workspace & Public Site | ✅ Complete (no live bot, no telephony) |
| 9 | Twilio Telephony & Media Streaming | ⬜ Not started |
| 10 | Conversation Orchestration Engine | ⬜ Not started |
| 11 | Automated Evaluation & Scoring | ⬜ Not started |
| 12 | Multilingual Benchmarking | ⬜ Not started |
| 13 | Results API & Reporting | ⬜ Not started |
| 14 | CI Regression Testing (GitHub Actions) | ⬜ Not started |
| 15 | Hardening, Observability & Release | ⬜ Not started |

---

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
  Phase 7.1.)

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

## Phase 6 — Caller Simulation (deterministic engine) ✅

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
interruption behaviour belong to Phases 7 and 8, where the audio and the call
exist.

---

## Phase 7 — End-to-End Voice Pipeline & Audio Degradation ✅

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
- **Nine endpoints** under `/api/v1/test-runs`, and 238 offline tests.
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

### Phase 7.1 — concurrency enforcement

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

---

## Phase 8 — Twilio Telephony & Media Streaming

The first phase that can place a real call, and therefore spend real money.

- Outbound calls via the Twilio REST API.
- Bidirectional media over Twilio Media Streams (WebSocket).
- Barge-in and interruption handling.
- Guardrails enforced *before* dialling: `ALLOWED_BOT_NUMBERS`,
  `MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`, `MAX_CONCURRENT_CALLS`.
- Webhook signature verification.

**Exit criteria.** A call to an allow-listed number streams audio both ways,
and a call to any other number is refused before dialling.

---

## Phase 9 — Conversation Orchestration Engine

Binds phases 4–8 into one run loop.

- Run lifecycle: queued → running → completed/failed, with cancellation.
- Barge-in, silence timeouts and per-turn deadlines.
- Full transcript, timing and audio artefacts persisted per turn.
- Bounded concurrency across calls.

**Exit criteria.** `POST /api/v1/runs` executes a scenario end to end and
stores a complete, inspectable transcript.

---

## Phase 10 — Automated Evaluation & Scoring

- LLM-as-judge evaluation via Evon against the scenario's success criteria.
- Deterministic metrics alongside the judge: latency percentiles, word error
  rate, interruption count, task completion.
- `JUDGE_RETRIES` and `PASS_THRESHOLD` are applied here.
- Rubric versioning, so a score is interpretable months later.
- Agreement checks against a human-labelled set.

**Exit criteria.** A completed run yields a reproducible pass/fail with
per-criterion reasoning.

---

## Phase 11 — Multilingual Benchmarking

- Curated suites across Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi,
  Bengali, Gujarati, Punjabi and Indian English.
- Code-mixing (Hinglish and friends) as a first-class test axis.
- Per-language normalisation for fair word error rate.
- Suite definitions versioned in `benchmarks/`.

**Exit criteria.** One command runs a language suite and emits comparable
per-language scores.

---

## Phase 12 — Results API & Reporting

- Aggregate query endpoints: per-run, per-scenario, per-language, over time.
- Run comparison and regression detection against a baseline.
- Export to JSON, CSV and a static HTML report.
- Audio and transcript artefacts served with signed, expiring URLs.

**Exit criteria.** Two runs can be diffed and a regression identified.

---

## Phase 13 — React Dashboard

Replaces the Phase 1 status shell with the real product surface.

- Run history, live run progress, transcript playback with aligned audio.
- Score breakdowns and latency distributions.
- Scenario editor with inline validation.
- Language comparison views.

**Exit criteria.** Every Phase 12 endpoint is reachable from the UI, with no
placeholder or fabricated data anywhere in it.

---

## Phase 14 — CI Regression Testing

- GitHub Actions: Ruff, pytest, ESLint, `next build` and a Compose smoke test
  on every pull request.
- Nightly benchmark run against the sample bot.
- Scores published as build artefacts; pull requests fail on regression beyond
  a threshold.
- Secrets supplied via GitHub Environments, never committed.

**Exit criteria.** A deliberately introduced regression fails CI.

---

## Phase 15 — Hardening, Observability & Release

- Structured JSON logging with request correlation IDs.
- Metrics and tracing; dashboards for latency and provider error rates.
- Authentication and authorisation on the API.
- Rate limiting, cost accounting and budget alerts.
- Production Compose/Kubernetes manifests, backup and restore procedure.
- Security review, load test, and a versioned `1.0.0` release.

**Exit criteria.** The platform runs unattended for a week with alerting and
no manual intervention.

---

## Conventions across phases

- A phase ships only what it claims. Unimplemented dependencies are reported
  as `degraded` with a reason, never as healthy.
- No provider request shape is written until the phase that integrates it.
- Every phase keeps Ruff, pytest, ESLint and `next build` green.
- Guardrails land in the same phase as the capability they bound, never later.
