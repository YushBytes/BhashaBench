# BhashaBench — Architecture

> **Status.** Phase 1 of 15 is complete. This document describes the *planned*
> architecture. Only the components marked **Implemented** exist today;
> everything else is design intent, recorded so that each phase has a target
> to build against. Nothing here should be read as a claim that an
> unimplemented component is operational.

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
                    ┌──────────────────────────┐
                    │  Next.js dashboard       │  ◀── Implemented (shell only)
                    │  (App Router, TS, TW)    │
                    └────────────┬─────────────┘
                                 │ HTTPS / JSON
                    ┌────────────▼─────────────┐
                    │  FastAPI backend         │  ◀── Implemented
                    │  /  /health  /api/v1/*   │
                    └────────────┬─────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌────────▼────────┐   ┌──────────▼──────────┐   ┌────────▼─────────┐
│  Orchestrator   │   │  Scenario registry  │   │  PostgreSQL      │
│  (Phase 9)      │   │  (Phase 3)          │   │  (service up,    │
└────────┬────────┘   └─────────────────────┘   │   no schema yet) │
         │                                      └──────────────────┘
         │
         ├──────────────┬──────────────┬──────────────┬──────────────┐
         │              │              │              │              │
┌────────▼─────┐ ┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐ ┌────▼──────┐
│ Caller agent │ │ Prisma STT  │ │ Timbre TTS │ │ Degradation│ │  Twilio   │
│ (Evon, Ph 6) │ │ (Phase 4)   │ │ (Phase 5)  │ │ (Phase 7)  │ │ (Phase 8) │
└──────────────┘ └─────────────┘ └────────────┘ └────────────┘ └─────┬─────┘
                                                                     │
                                                          ┌──────────▼────────┐
                                                          │ Bot under test    │
                                                          │ (customer / local │
                                                          │  sample_bot)      │
                                                          └───────────────────┘
```

---

## 3. Implemented today (Phase 1)

### 3.1 Backend — `backend/app/`

A four-layer FastAPI application. The layering exists so that logic is
testable without HTTP and so provider integrations in phases 4–8 have an
obvious home.

| Layer | Package | Responsibility |
|-------|---------|----------------|
| HTTP | `api/` | Routing, status codes, dependency injection. No logic. |
| Contracts | `schemas/` | Pydantic request/response models; the API's public shape. |
| Logic | `services/` | Behaviour, callable and testable without a client. |
| Config | `core/` | Settings, validation, cross-cutting concerns. |
| Persistence | `models/` | Empty — no tables until Phase 2. |
| Helpers | `utils/` | Small, dependency-free utilities. |

**Endpoints.**

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/` | Product name, tagline, version, environment, docs path |
| `GET` | `/health` | `{status, version}` — cheap liveness probe |
| `GET` | `/api/v1/health` | Per-subsystem health, uptime, UTC timestamp |

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
- **Honest health reporting.** `services/health.py` reports the `database`
  component as `degraded` with the reason *"not probed — persistence layer not
  implemented in this phase"*, and the aggregate status follows the worst
  component. A green tick the system cannot justify is worse than no tick.
  Phase 2 replaces that branch with a real probe.
- **No credentials in health output.** `describe_environment()` returns only
  whether a source is `present`/`absent` and `configured`/`default` — never a
  value. A test asserts the root payload contains neither `SECRET_KEY` nor
  `DATABASE_URL`.
- **Fail fast on misconfiguration.** Settings are resolved during the lifespan
  startup hook, so a bad `APP_ENV` or a placeholder `SECRET_KEY` in
  staging/production stops the boot rather than surfacing on first request.
  OpenAPI docs are disabled when `APP_ENV=production`.

### 3.2 Frontend — `frontend/`

Next.js App Router with TypeScript and Tailwind CSS. Phase 1 ships a
dark-first status shell: product identity, the current phase, and the planned
test-suite capabilities labelled as planned. It renders **no analytics and no
fabricated data**, because there is nothing real to show yet. Phase 13
replaces it with the operational dashboard.

### 3.3 Configuration

Resolution order, lowest precedence first: field defaults → `.env` at the
repository root → real process environment variables. Docker Compose and CI
therefore override anything without a file on disk.

`.env.example` documents the complete configuration surface, including
variables that later phases will consume. Only the variables Phase 1 actually
uses are modelled as `Settings` fields; declaring fields nothing reads would
be dead code, and the request shapes the Gnani and Twilio integrations need
are not yet known. `Settings` uses `extra="ignore"` so a complete `.env` does
not break startup.

### 3.4 Containers

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
