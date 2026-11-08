# BhashaBench — Architecture

> **Status.** Phases 1, 2 and 3 of 15 are complete. This document describes
> the *planned* architecture. Only the components marked **Implemented** exist
> today; everything else is design intent, recorded so that each phase has a
> target to build against. Nothing here should be read as a claim that an
> unimplemented component is operational.
>
> Phase 2 added persistence and the scenario engine; Phase 3 added the
> scenario library, its tooling and a second front end over the same services.
> For detail see [`DATABASE.md`](DATABASE.md) (schema, ER diagram,
> migrations), [`SCENARIO_FORMAT.md`](SCENARIO_FORMAT.md) (the YAML and bundle
> formats) and [`CLI.md`](CLI.md) (the command-line tool).

---

## 1. What the system is for

A voice bot that performs well in a demo often fails on a real Indian phone
call: background noise, regional accents, code-mixed speech, packet loss and
callers who interrupt. BhashaBench exercises a voice bot the way reality
does — by calling it, speaking to it with a simulated caller, degrading the
audio realistically, and scoring the conversation automatically.

The design goal that shapes everything below: **a test result must be
reproducible and explainable.** Every run records its inputs (scenario, seed,
provider versions), its artefacts (audio, transcript, timings) and the
reasoning behind its score.

---

## 2. Component map

```
   ┌─────────────────────────┐      ┌─────────────────────────┐
   │  Next.js dashboard      │      │  bhashabench CLI        │
   │  (App Router, TS, TW)   │      │  (Typer)                │
   │  ◀── Shell only         │      │  ◀── Implemented        │
   └────────────┬────────────┘      └────────────┬────────────┘
                │ HTTPS / JSON                   │ in-process:
                │                                │ same services,
                │                                │ own session
   ┌────────────▼────────────┐                   │
   │  FastAPI backend        │                   │
   │  /  /health  /api/v1/*  │                   │
   │  ◀── Implemented        │                   │
   └────────────┬────────────┘                   │
                │                                │
   ┌────────────▼────────────────────────────────▼────────────┐
   │  services/  repositories/  models/     ◀── Implemented   │
   └────────────────────────────┬─────────────────────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
┌────────▼────────┐  ┌──────────▼─────────┐  ┌─────────▼────────┐
│  Run engine     │  │  Scenario engine   │  │  PostgreSQL 16   │
│  ◀── Phase 7    │  │  ◀── Implemented   │  │  ◀── Implemented │
└────────┬────────┘  └────────────────────┘  │  5 tables via    │
         │                                   │  Alembic         │
         │                                   └──────────────────┘
         │
         ├──────────────┬──────────────┬──────────────┬──────────────┐
         │              │              │              │              │
┌────────▼─────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐ ┌────▼──────┐
│ Caller engine│ │ Prisma STT  │ │ Timbre TTS │ │ Degradation│ │  Twilio   │
│ rule-based   │ │ (Phase 4)   │ │ (Phase 5)  │ │ (Phase 7)  │ │ (Phase 8) │
│ (Phase 6)    │ │             │ │            │ │            │ │           │
│ no Evon      │ │             │ │            │ │            │ │ not built │
└──────────────┘ └─────────────┘ └────────────┘ └────────────┘ └─────┬─────┘
                                                                     │
                                                          ┌──────────▼────────┐
                                                          │ Bot under test    │
                                                          │ (customer / local │
                                                          │  sample_bot)      │
                                                          └───────────────────┘
```

---

## 3. Implemented today (Phases 1–7)

### 3.1 Backend — `backend/app/`

A layered FastAPI application. The layering exists so that logic is testable
without HTTP and so provider integrations in phases 4–8 have an obvious home.
Phase 4 took that home: `app/transcription/` (see §3.2b).

Repositories hold every SQL statement and never commit; services own the
transaction boundary and raise domain errors (`NotFoundError`,
`ConflictError`) rather than `HTTPException`, so service code stays usable
outside a request and the HTTP mapping lives only in `main.py`.

| Layer | Package | Responsibility |
|-------|---------|----------------|
| HTTP | `api/` | Routing, status codes, dependency injection. No logic. |
| Contracts | `schemas/` | Pydantic request/response models; the API's public shape. |
| Logic | `services/` | Behaviour, callable and testable without a client. |
| Config | `core/` | Settings, validation, the language catalogue. |
| CLI | `cli/` | A second front end over `services/`. Owns only its output and exit codes. |
| Data access | `repositories/` | Every SQL statement. Takes a `Session`, never commits. |
| Persistence | `models/` | SQLAlchemy ORM — five tables, owned by Alembic. |
| Engine | `db/` | Declarative base, engine, session dependency. |
| Helpers | `utils/` | Small, dependency-free utilities. |

**Endpoints.**

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/` | Product name, tagline, version, environment, docs path |
| `GET` | `/health` | `{status, version}` — cheap liveness probe |
| `GET` | `/api/v1/health` | Per-subsystem health, uptime, UTC timestamp |
| `POST`/`GET` | `/api/v1/suites`, `/api/v1/suites/{id}` | Test suite CRUD |
| `POST`/`GET` | `/api/v1/suites/{id}/scenarios` | Scenario creation and listing |
| `GET`/`PUT`/`DELETE` | `/api/v1/scenarios/{id}` | Scenario detail, replace, delete |
| `POST` | `/api/v1/scenarios/validate` | Validate YAML without storing it |

**Design decisions.**

- **Application factory.** `create_app(settings)` builds the app, so tests can
  construct an instance against arbitrary settings without mutating globals.
  The module-level `app` is what Uvicorn imports.
- **Versioned router package.** `api/v1/` aggregates route modules into one
  `api_router`, mounted under the configurable `api_v1_prefix`. Adding an
  endpoint touches no application setup. A future `v2` is an additive change.
- **Settings as a dependency.** Handlers receive `Settings` through
  `SettingsDep` rather than importing a global, so tests can override it.
  `get_settings()` is `lru_cache`d so `.env` is parsed once.
- **Uniform error envelope.** Three exception handlers (`HTTPException`,
  `RequestValidationError`, bare `Exception`) emit the same
  `{"error": {type, message, status_code}}` shape. Clients parse one
  structure; unexpected exceptions are logged server-side and never leak
  internals to the caller.
- **Honest health reporting.** `services/health.py` probes the database with
  `SELECT 1` and reports what it finds: `ok` when reachable, `unavailable`
  when not — `unavailable` rather than `degraded`, because without the
  database every suite and scenario endpoint fails. The aggregate follows the
  worst component. A green tick the system cannot justify is worse than no
  tick.
- **The probe is injected, not imported.** `DatabaseProbe` in `api/deps.py`
  supplies it. Imported directly, the probe would always use the
  process-wide engine built from global settings, so a test overriding
  `Settings` would still report on whatever database the developer's `.env`
  pointed at — the endpoint would look healthy for the wrong reason.
- **No credentials in health output.** `describe_environment()` returns only
  whether a source is `present`/`absent` and `configured`/`default` — never a
  value. A test asserts the root payload contains neither `SECRET_KEY` nor
  `DATABASE_URL`.
- **Fail fast on misconfiguration.** Settings are resolved during the lifespan
  startup hook, so a bad `APP_ENV` or a placeholder `SECRET_KEY` in
  staging/production stops the boot rather than surfacing on first request.
  OpenAPI docs are disabled when `APP_ENV=production`.

### 3.2 Persistence and the scenario engine (Phase 2)

Five tables, created by a single Alembic migration: `test_suites`,
`scenarios`, `test_runs`, `call_sessions`, `conversation_turns`. Only the
first two are written to by the API; the other three are foundational schema
so later phases have a stable shape to write into.

The application never calls `create_all()` — Alembic owns the schema, so what
runs in development is what will run anywhere else. `alembic.ini` sits in
`backend/` so it is present inside the Docker image, and `env.py` reads the
database URL from application settings so a password never enters a committed
file.

A scenario is authored as YAML and validated against `ScenarioSpec` before
storage. The validated document is persisted as one JSONB column, with
`name`, `description` and `language` projected into real columns because those
are what the API filters, sorts and enforces uniqueness on. YAML is parsed
only with `yaml.safe_load`, under size, node-count and nesting limits.

Full detail, including the reasoning behind every schema decision, is in
[`DATABASE.md`](DATABASE.md) and [`SCENARIO_FORMAT.md`](SCENARIO_FORMAT.md).

### 3.2a The scenario library and its two front ends (Phase 3)

Phase 3 added search across suites, suite editing, copy and move, a language
catalogue, code-mixing annotations, and bundle import/export — and a second
front end over all of it.

The `bhashabench` CLI is **not** an HTTP client. It imports the same
`services/` functions the routes call and opens its own session through
`app/db/session.py`. That is the structural point: validation, uniqueness
rules, transaction boundaries and the cascade guard exist once. A CLI that
re-implemented any of them could disagree with the API about whether a
scenario is valid, which is the one failure a test-authoring tool cannot
afford.

What each front end owns is only its own surface: HTTP status codes and the
error envelope on one side, exit codes and terminal output on the other.
Where a domain error suggests a remedy, the service takes the wording from its
caller (`cascade_remedy`) so neither front end tells a user to use the other's
mechanism.

Two decisions follow from the catalogue being a single module
(`app/core/languages.py`) rather than a constant per consumer:

- A language is supported everywhere or nowhere. The spec schema, the search
  filter, the CLI and `GET /api/v1/languages` all read the same tuple.
- `UnsupportedLanguageError` is a `ValueError`, so it surfaces as a Pydantic
  validation error inside a document and needs an explicit handler for the
  one path that consults the catalogue directly — the `?language=` filter.
  Without it a bad query string would have been a 500.

Bundles are the unit of portability: one YAML document, a suite's metadata and
its scenarios, no database identifiers. Export is deterministic so a bundle
committed to git diffs cleanly, and import is atomic by default so a failed
batch never leaves a half-populated suite.

### 3.2b The transcription subsystem (Phase 4)

The first external provider integration, and the template for the four that
follow.

```
api/v1/transcription.py          HTTP + WebSocket transport
services/transcription_service.py   business rules, provider-agnostic
transcription/registry.py        which provider, built from settings
transcription/base.py            the TranscriptionProvider protocol
transcription/providers/         one adapter per vendor
```

Three decisions worth recording.

**The provider boundary is absolute.** Nothing above
`transcription/providers/` may import a vendor module or name a vendor field.
The service layer has never heard of `audio_file` or
`detected_language_code`. This is what will let Phase 11 benchmark a second
engine without touching evaluation code, and it is enforced by review rather
than by tooling, so it has to be stated.

**Capabilities are declared data, not discovered behaviour.**
`ProviderCapabilities` states which languages a provider transcribes, whether
it streams interim results, whether it reports confidence. The service refuses
an impossible request with a precise message instead of forwarding it and
translating a vendor error. Gnani Prisma covers ten of the catalogue's
thirteen languages, so Urdu, Odia and Assamese are authorable and not
transcribable — a fact the API publishes rather than discovers.

**These handlers are `async def`, and that is not a reversal of §5's
synchronous-session decision.** Database handlers stay synchronous so FastAPI
runs them in a worker thread. The transcription handlers touch no database —
Phase 4 persists nothing — and are entirely network-bound, so the event loop
is the right place for them. The streaming handler could not be synchronous at
all: it interleaves receiving client audio with forwarding provider events.

**Nothing is persisted.** Deciding which conversation turn a transcript
belongs to is orchestration (Phase 9). A table written by nothing would be
schema guesswork, so the subsystem is a pure function of its input and the
endpoints work with PostgreSQL down.

### 3.2c The speech subsystem (Phase 5)

`app/speech/` mirrors `app/transcription/` exactly — protocol, capabilities,
registry of factories, offline fake, vendor contract module, one adapter per
vendor under `providers/`. It reuses `transcription/{redaction,retry,audio}`
rather than copying them; promote those three to a shared package when a third
provider family arrives. The contract and its gaps are in
[PROVIDERS.md](PROVIDERS.md).

### 3.2d The caller engine (Phase 6)

`app/caller/` is the first subsystem that is not a vendor adapter, and it
raised three structural decisions worth recording.

**The provider pattern was kept even with one provider, and that provider
speaks to nobody.** A feasibility gate established that no Gnani
text-generation endpoint is published and the released Evon model has no
hosted inference provider, so there was nothing to adapt. Rather than guess a
wire format, Phase 6 ships a rule engine behind the same shape as Prisma and
Timbre: a `CallerProvider` protocol, a `CallerCapabilities` dataclass, a
registry of factories. The cost is one indirection nothing currently needs;
the benefit is that an Evon adapter slots in without touching the
orchestrator, the service, the API or the schema. `uses_language_model` is a
capability field precisely so that the day a model provider arrives, every
report built on a run can say whether a model wrote the caller's words.

**Validation lives in the service, not the provider.** A provider cannot be
trusted to police itself, and the rule engine is the one provider that barely
needs policing — it cannot leak a prompt it does not have, nor invent a
reference number it can only quote. The checks exist for its replacement.
Putting them above the provider boundary means a future model adapter inherits
them rather than reimplementing them, and that an invalid decision is rejected
before it reaches speech synthesis.

**No new tables.** Phase 2 created `TestRun → CallSession → ConversationTurn`
as foundational schema; a caller conversation *is* a `CallSession` and an
utterance *is* a `ConversationTurn`. The caller's evolving per-phase state
goes in the existing JSONB columns under a `caller` namespace, so Phase 8's
telephony metadata can share the column without collision. The alternative —
caller-specific tables — would have duplicated the relationships, needed a
migration, and forced Phase 9 to reconcile two conversation shapes. The
trade-off accepted is that caller state is not queryable with a typed column;
when a field earns an index it should be promoted to one.

So Phase 6 is the first phase that writes to those tables, and it writes only
conversations it ran itself. It is also the first subsystem whose endpoints
require PostgreSQL.

The states, rules and limits are in [CALLER.md](CALLER.md).

### 3.2e The voice pipeline (Phase 7)

`app/pipeline/` connects the scenario engine, the caller, Timbre and Prisma
into one multi-turn run. Four decisions worth recording.

**It wraps Phase 6 rather than extending it.** `next_caller_turn` decides and
synthesises; `submit_bot_audio` transcribes and persists. The engine owns only
the legs between them - degradation, the adapter exchange, audio validation. The
alternative, a second conversation engine that also knew about the caller state
machine, would have disagreed with the first eventually. The cost is that the
engine reads the caller's audio back off disk rather than being handed the
bytes; that keeps Phase 6's signatures and tests untouched, and the read is
local.

**The DSP is pure Python, with no numeric dependency.** There is no numpy,
scipy, soundfile or pydub in the repository, and `audioop` left the standard
library in Python 3.13. A few seconds of 8 kHz mono is tens of thousands of
samples, so the arithmetic runs in tens of milliseconds; a scientific stack
carried for that would be the dependency nobody wanted. The trade-off accepted
is a narrow input contract - 16-bit PCM WAV only - and no spectral work. A
later phase needing a measured impulse response is the point to revisit it.

**Execution mode is a recorded property, not an inferred one.** Every run
stores how it obtained the bot's side, and `bot_audio_externally_received` is
computed from the replies rather than from the requested mode, so a run
labelled as an external bot test whose replies were fixtures reports `false`.
`TELEPHONY_TEST` exists in the enum and is excluded from the usable set: an
enum member that cannot be used is a better record of the gap than a missing
one, because it sits where someone looks for it.

**Still no new tables.** A pipeline run *is* a `TestRun`, whose `run_metadata`
docstring already said it was for "execution context captured at run time: tool
versions, resolved audio profile, seed". The pipeline writes there under a
`pipeline` namespace, beside Phase 6's `caller` namespace. The database's
five-value `RunStatus` stays the coarse lifecycle and the finer pipeline status
lives in metadata, so `timed_out` does not require widening a CHECK constraint
that enumerates the terminal three.

Execution modes, profiles, adapters and limits are in [PIPELINE.md](PIPELINE.md).

### 3.3 Frontend — `frontend/`

Next.js App Router with TypeScript and Tailwind CSS. Phase 1 ships a
dark-first status shell: product identity, the current phase, and the planned
test-suite capabilities labelled as planned. It renders **no analytics and no
fabricated data**, because there is nothing real to show yet. Phase 13
replaces it with the operational dashboard.

### 3.4 Configuration

Resolution order, lowest precedence first: field defaults → `.env` at the
repository root → real process environment variables. Docker Compose and CI
therefore override anything without a file on disk.

`.env.example` documents the complete configuration surface, including
variables that later phases will consume. Only the variables Phase 1 actually
uses are modelled as `Settings` fields; declaring fields nothing reads would
be dead code, and the request shapes the Gnani and Twilio integrations need
are not yet known. `Settings` uses `extra="ignore"` so a complete `.env` does
not break startup.

### 3.5 Containers

| Service | Image / build | Notes |
|---------|---------------|-------|
| `db` | `postgres:16-alpine` | `pg_isready` health check, named volume `bhashabench-postgres-data` |
| `backend` | `backend/Dockerfile`, target `development` | Non-root user, hot reload, `curl` health check on `/health`, waits for `db` healthy |
| `frontend` | `frontend/Dockerfile`, target `development` | Non-root user, waits for `backend` healthy |

The backend Dockerfile is multi-stage (`base` → `development` / `production`):
dependencies install before application code so the slow layer is cached, and
both runtime targets drop to a non-root `appuser`. It pins **Python 3.12**
regardless of the developer's local interpreter, so the container matches CI.

Compose reads every credential from `.env` using `${VAR:?message}`, which
fails with a clear error rather than silently starting on a default password.
No credential is committed.

On Windows hosts, `node_modules` and `.next` are anonymous volumes and
`__pycache__` is a named volume, so container-built artefacts never collide
with host-built ones across the bind mount.

---

## 4. Planned architecture

### 4.1 Run lifecycle (Phase 9 target)

```
scenario ──▶ caller agent ──▶ Timbre TTS ──▶ degradation ──▶ Twilio ──▶ bot
   ▲                                                                     │
   │                                                                     ▼
evaluation ◀── judge (Evon) ◀── transcript ◀── Prisma STT ◀── bot audio ──┘
```

Each turn persists its audio, transcript, latency and degradation seed, so a
disputed score can be replayed and audited.

### 4.2 Provider isolation

Every external service sits behind a narrow protocol —
`TranscriptionProvider`, `SynthesisProvider`, `ReasoningProvider`,
`TelephonyProvider` — defined in `services/`. Three reasons: CI runs against
recorded fixtures instead of paid APIs; a provider can be swapped without
touching the orchestrator; and no code outside the adapter needs a credential.

Adapters are written in the phase that integrates them, against real provider
documentation. No endpoint path, auth scheme or payload shape is guessed
in advance.

Phase 4 made `TranscriptionProvider` real (see §3.2b). It also made the rule
above concrete in an unglamorous way: where Gnani's documentation is silent or
self-contradictory, the gap is recorded in `DOCUMENTATION_GAPS` and the
capability is declared **unsupported** rather than guessed. Three of Prisma's
four output modes are unsupported for exactly this reason — their literal wire
values are described in prose but never quoted, and `code-mix` versus
`code_mix` is not a coin worth flipping in a benchmark.

One consequence to carry into Phase 5 and beyond: an adapter whose request
shape matches the documentation is *contract-verified*, which is not the same
as *transport-verified*. A mocked transport cannot disagree with you. Each
provider phase should state which of the two it achieved.

### 4.3 Reproducibility

- `NOISE_MASTER_SEED` seeds the degradation pipeline; a run records the
  derived per-call seed.
- Synthesised audio is cached by `(text, voice, locale)`.
- Judge rubrics are versioned, so an old score stays interpretable.
- Deterministic replay mode re-runs a conversation without new API calls.

### 4.4 Safety and cost control

Phase 8 is the first phase that can spend money or dial a stranger, so its
guardrails ship in the same phase as the capability:

- `ALLOWED_BOT_NUMBERS` — an explicit allow-list. An empty value means **no
  number is dialable**, so the fail-safe state is "refuse", not "allow all".
- `MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`, `MAX_CONCURRENT_CALLS` — checked
  before dialling, not after.
- Twilio webhook signatures verified on every inbound request.

---

## 5. Structural notes and deviations

Deviations from the Phase 1 specification, and why:

1. **Repository root is `BhashaBench/`, not a nested `bhashabench/`.** The
   working directory already carried the project name; nesting would have
   produced `BhashaBench/bhashabench/`.
2. **`backend/app/api/v1/` sub-package** instead of a flat `api/`. The spec
   requires versioned routing; a version sub-package with its own aggregating
   `router.py` is how that stays clean past the second route group.
3. **`backend/app/api/deps.py`** added for the injectable `SettingsDep` — the
   seam that makes handler tests possible without global patching.
4. **`backend/requirements-dev.txt`** added, so the production image installs
   neither pytest nor Ruff.
5. **`backend/tests/conftest.py`, `test_config.py`, `test_app_metadata.py`**
   added alongside the specified `test_health.py`. The spec requires tests for
   configuration loading and application metadata; one file per concern beats
   one large file.
6. **`.dockerignore` and `.gitattributes`** added. The first keeps host
   artefacts and `.env` out of build contexts; the second pins LF endings so
   files authored on Windows work inside Linux containers.
7. **`uvicorn` without the `[standard]` extra.** Those extras compile from
   source on the newest CPython releases, which breaks a plain
   `pip install -r requirements.txt` on a developer machine. Plain Uvicorn
   serves correctly; `--reload` falls back to polling.
8. **`httpx2` rather than `httpx`** as the test transport, which is what
   Starlette 1.10+ requires for `TestClient`.

---

## 6. Technology choices

| Choice | Why |
|--------|-----|
| FastAPI | Native async for concurrent calls and WebSocket media streaming; OpenAPI for free |
| Pydantic / pydantic-settings | One validation library for both API contracts and configuration |
| PostgreSQL | Relational run/turn/evaluation data, plus `JSONB` for provider payloads |
| Next.js App Router | Server components for a fast dashboard shell; one framework for UI and routing |
| Tailwind CSS | Consistent spacing and dark-mode tokens without a bespoke design system |
| Ruff | Lint and format in one fast tool |
| pytest | Fixtures compose cleanly for provider fakes in later phases |
| Docker Compose | One command brings up API, UI and database identically on every machine |
