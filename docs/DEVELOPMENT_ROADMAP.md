# BhashaBench — Development Roadmap

BhashaBench is being built in 15 controlled phases. Each phase is a reviewable
increment: it ends with working code, passing tests and updated documentation.
A phase is not started until the previous one is approved.

**Current status: Phase 1 complete. Phases 2–15 not started.**

Nothing in phases 2–15 is implemented. Where this document describes a
component in the present tense, read it as the *intended* design for that
phase, not as existing behaviour.

---

## Phase status

| # | Phase | Status |
|---|-------|--------|
| 1 | Project Foundation | ✅ Complete |
| 2 | Data Model & Persistence | ⬜ Not started |
| 3 | Scenario Definition Format | ⬜ Not started |
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

## Phase 2 — Data Model & Persistence

Define the durable shape of a test run.

- SQLAlchemy models: `Scenario`, `TestRun`, `Call`, `Turn`, `Evaluation`,
  `BenchmarkResult`.
- Alembic migrations, with the initial revision checked in.
- Async engine and session dependency; connection pooling.
- Replace the `database` health component's `degraded` placeholder with a real
  `SELECT 1` probe.
- Repository-level tests against a throwaway PostgreSQL container.

**Exit criteria.** `alembic upgrade head` succeeds against the Compose
database, and `/api/v1/health` reports the database honestly.

---

## Phase 3 — Scenario Definition Format

A scenario is the unit of testing: a persona, a goal and a set of
expectations.

- YAML schema with Pydantic validation: persona, language, locale, objective,
  conversation turns, success criteria, degradation profile.
- Loader with precise, line-aware error messages.
- `scenarios/` populated with reference scenarios across Indian languages.
- CRUD endpoints under `/api/v1/scenarios`.
- A scenario-validation entry point in `scripts/`.

**Exit criteria.** An invalid scenario is rejected with an actionable message;
valid scenarios round-trip through the API.

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
