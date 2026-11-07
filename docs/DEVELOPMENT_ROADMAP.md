# BhashaBench — Development Roadmap

BhashaBench is being built in 15 controlled phases. Each phase is a reviewable
increment: it ends with working code, passing tests and updated documentation.
A phase is not started until the previous one is approved.

**Current status: Phases 1, 2 and 3 complete. Phases 4–15 not started.**

Nothing in phases 4–15 is implemented. Where this document describes a
component in the present tense, read it as the *intended* design for that
phase, not as existing behaviour.

---

## Phase status

| # | Phase | Status |
|---|-------|--------|
| 1 | Project Foundation | ✅ Complete |
| 2 | Database & Scenario Engine | ✅ Complete |
| 3 | Scenario Library & Tooling | ✅ Complete |
| 4 | Gnani Prisma — Speech to Text | ⬜ Not started |
| 5 | Gnani Timbre — Text to Speech | ⬜ Not started |
| 6 | AI Caller Simulation (Gnani Evon) | ⬜ Not started |
| 7 | Audio Degradation Pipeline | ⬜ Not started |
| 8 | Twilio Telephony & Media Streaming | ⬜ Not started |
| 9 | Conversation Orchestration Engine | ⬜ Not started |
| 10 | Automated Evaluation & Scoring | ⬜ Not started |
| 11 | Multilingual Benchmarking | ⬜ Not started |
| 12 | Results API & Reporting | ⬜ Not started |
| 13 | React Dashboard | ⬜ Not started |
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
- 551 tests, up from 246.

**Exit criteria — met.** A directory of scenario files can be validated
offline (`for f in scenarios/*.yaml; do bhashabench validate "$f"; done`) and
a whole suite imported in one command, with a dry run first.

**Deliberately not in this phase.** No Gnani Prisma, Timbre or Evon
integration, no telephony, no audio processing and no scoring. The scenario
library is now complete enough to drive those.

---

## Phase 4 — Gnani Prisma (Speech to Text)

- Thin client around the Prisma STT API, isolated behind a
  `TranscriptionProvider` protocol.
- Streaming and batch transcription paths.
- Language and code-mixing configuration per scenario.
- Retry with backoff, typed errors, and redaction of credentials from logs.
- Tests against recorded fixtures — no network calls in CI.

**Exit criteria.** A fixture audio file transcribes end to end, and the
provider can be swapped for a fake in tests.

---

## Phase 5 — Gnani Timbre (Text to Speech)

- `SynthesisProvider` client for Timbre TTS.
- Voice, language and prosody selection driven by the scenario persona.
- Audio caching keyed by text and voice, so repeated runs do not
  re-synthesise.
- Output normalised to the sample rate and encoding telephony requires.

**Exit criteria.** A persona utterance synthesises to a playable, correctly
formatted audio artefact.

---

## Phase 6 — AI Caller Simulation (Gnani Evon)

- Caller agent driven by Evon reasoning: it pursues the scenario objective
  rather than replaying a fixed script.
- Persona conditioning: patience, verbosity, accent, interruption behaviour.
- Turn-level state machine with a hard turn budget.
- Deterministic replay mode for regression testing.

**Exit criteria.** The simulated caller completes a multi-turn conversation
against the local sample bot without human input.

---

## Phase 7 — Audio Degradation Pipeline

Real Indian phone calls are not studio recordings.

- Composable degradations: additive background noise (traffic, market, fan),
  packet loss, jitter, codec simulation (G.711/AMR-NB), clipping, reverb.
- Named severity profiles: `clean`, `urban`, `rural`, `worst_case`.
- Seeded via `NOISE_MASTER_SEED`, so every run is reproducible.
- Objective verification of each stage's effect on the signal.

**Exit criteria.** The same seed and profile produce byte-identical output.

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
