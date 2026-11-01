# BhashaBench

**Test your voice AI before India tests it for you.**

An automated testing and benchmarking platform for Indian-language voice
bots — simulated callers, realistic audio degradation and automated
conversation scoring.

> ### Project status: Phase 1 of 15 — Foundation complete
>
> This repository currently contains the **project foundation only**: a
> running FastAPI backend with health endpoints, a Next.js status shell, a
> Docker Compose stack and the test/lint toolchain.
>
> **No calls are placed, no speech is processed and no scores are produced
> yet.** Speech services, telephony, the degradation pipeline and evaluation
> arrive in later phases — see [the roadmap](docs/DEVELOPMENT_ROADMAP.md).
> Nothing in this README should be read as a claim that an unimplemented
> feature works.

---

## Table of contents

- [The problem](#the-problem)
- [What BhashaBench will do](#what-bhashabench-will-do)
- [Architecture overview](#architecture-overview)
- [Technology stack](#technology-stack)
- [Repository layout](#repository-layout)
- [Quick start with Docker](#quick-start-with-docker)
- [Local installation without Docker](#local-installation-without-docker)
- [Environment configuration](#environment-configuration)
- [Development commands](#development-commands)
- [Testing](#testing)
- [API endpoints](#api-endpoints)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## The problem

A voice bot that performs flawlessly in a quiet demo frequently fails on a
real Indian phone call. The call arrives over a lossy mobile network with
traffic, a ceiling fan or a market in the background. The caller speaks Tamil
with an accent the model was not tuned for, switches to English mid-sentence,
and interrupts the bot halfway through its prompt.

Teams discover these failures the way their customers do: in production. The
reasons are structural, not careless.

- **Manual testing does not scale.** Validating ten languages against twenty
  scenarios by hand is hundreds of calls per release, so it is done once and
  never repeated.
- **Clean test audio hides real failures.** Studio-quality recordings do not
  exercise the packet loss, codec artefacts and background noise that break
  speech recognition in the field.
- **Code-mixing is untested.** Hinglish and its regional equivalents are how
  people actually speak, and rarely how bots are evaluated.
- **"It sounded fine" is not a metric.** Without scored, reproducible runs
  there is no way to prove a release did not regress.

BhashaBench exists to make voice-bot quality **measurable, repeatable and
automated**: call the bot, speak to it with a simulated caller, degrade the
audio the way a real network does, and score the conversation against
explicit criteria.

---

## What BhashaBench will do

None of the following is implemented yet. Each item names the phase that
delivers it.

| Capability | What it does | Phase |
|------------|--------------|-------|
| Scenario definitions | Declare a persona, a language, an objective and success criteria in YAML | 3 |
| Speech to text | Transcribe bot audio via Gnani Prisma, with code-mixing support | 4 |
| Text to speech | Synthesise caller speech via Gnani Timbre, matched to the persona | 5 |
| Simulated callers | An AI caller that pursues a goal rather than replaying a script, driven by Gnani Evon | 6 |
| Audio degradation | Background noise, packet loss, jitter and telephony codecs, applied from a fixed seed | 7 |
| Live telephony | Outbound calls with Twilio bidirectional media streaming and barge-in handling | 8 |
| Orchestration | Run a full conversation end to end and persist every turn | 9 |
| Automated scoring | Per-criterion pass/fail with reasoning, plus latency, word error rate and task completion | 10 |
| Multilingual benchmarks | Comparable suites across ten Indian languages plus code-mixed speech | 11 |
| Reporting | Aggregate queries, run comparison and regression detection | 12 |
| Dashboard | Run history, transcript playback and score breakdowns | 13 |
| CI regression testing | Every pull request runs the suite and fails on quality regression | 14 |

---

## Architecture overview

```
   ┌───────────────────────┐
   │  Next.js dashboard    │   implemented: status shell only
   └───────────┬───────────┘
               │ JSON over HTTP
   ┌───────────▼───────────┐
   │  FastAPI backend      │   implemented
   │  /  /health           │
   │  /api/v1/health       │
   └───────────┬───────────┘
               │
   ┌───────────┴────────────┬──────────────────────┐
   │                        │                      │
┌──▼──────────────┐  ┌──────▼────────┐   ┌─────────▼─────────┐
│ Orchestrator    │  │ Scenario      │   │ PostgreSQL        │
│ (Phase 9)       │  │ registry (P3) │   │ service runs;     │
└──┬──────────────┘  └───────────────┘   │ no schema yet     │
   │                                     └───────────────────┘
   ├── Caller agent — Gnani Evon      (Phase 6)
   ├── Speech to text — Gnani Prisma  (Phase 4)
   ├── Text to speech — Gnani Timbre  (Phase 5)
   ├── Audio degradation             (Phase 7)
   └── Telephony — Twilio            (Phase 8) ──▶ bot under test
```

The backend is layered so that logic stays testable without HTTP and each
future provider has an obvious home:

| Layer | Package | Responsibility |
|-------|---------|----------------|
| HTTP | `backend/app/api/` | Routing and status codes; no business logic |
| Contracts | `backend/app/schemas/` | Pydantic request/response models |
| Logic | `backend/app/services/` | Behaviour, testable without a client |
| Config | `backend/app/core/` | Settings and validation |
| Persistence | `backend/app/models/` | Empty until Phase 2 |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design decisions
behind this, including why the `database` health component reports
`degraded` rather than `ok`.

---

## Technology stack

| Area | Choice | Version |
|------|--------|---------|
| Backend | Python, FastAPI, Uvicorn | 3.12+, FastAPI 0.162 |
| Validation & config | Pydantic, pydantic-settings | 2.14, 2.16 |
| Backend tooling | pytest, Ruff | 9.2, 0.17 |
| Frontend | Next.js (App Router), React, TypeScript | 16.4, 19.3, 5.x |
| Styling | Tailwind CSS | 4.x |
| Frontend tooling | ESLint (`eslint-config-next`) | 9.x |
| Database | PostgreSQL | 16 |
| Containers | Docker Compose | v2+ |

---

## Repository layout

```
BhashaBench/
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI app factory, error handlers, lifespan
│   │   ├── core/config.py     pydantic-settings configuration
│   │   ├── api/               HTTP layer
│   │   │   ├── deps.py        injectable dependencies
│   │   │   └── v1/            versioned routes (health.py, router.py)
│   │   ├── models/            database models (empty until Phase 2)
│   │   ├── schemas/common.py  response models and error envelope
│   │   ├── services/health.py health aggregation
│   │   └── utils/timing.py    UTC clock helpers
│   ├── tests/                 35 tests across 3 modules
│   ├── requirements.txt       runtime dependencies
│   ├── requirements-dev.txt   test and lint dependencies
│   └── Dockerfile             multi-stage: development / production
├── frontend/
│   ├── app/                   App Router pages, layout, global styles
│   ├── components/            header, footer, section, status pill, cards
│   ├── lib/content.ts         typed product copy and phase status
│   ├── public/
│   └── Dockerfile             multi-stage: development / builder / production
├── scenarios/                 test scenario definitions        (Phase 3)
├── benchmarks/                benchmark suite definitions      (Phase 11)
├── sample_bot/                reference bot to test against    (Phase 6)
├── scripts/                   operational scripts
├── docs/
│   ├── ARCHITECTURE.md
│   └── DEVELOPMENT_ROADMAP.md
├── .github/workflows/         CI pipelines                     (Phase 14)
├── docker-compose.yml
├── .env.example
├── pyproject.toml             Ruff and pytest configuration
├── CONTRIBUTING.md
└── PHASE_COMPLETION_REPORT.md
```

---

## Quick start with Docker

Requires Docker Desktop with Compose v2.

```bash
git clone https://github.com/YushBytes/BhashaBench.git
cd BhashaBench

# 1. Create your environment file.
cp .env.example .env                  # PowerShell: Copy-Item .env.example .env

# 2. Set a real SECRET_KEY and POSTGRES_PASSWORD in .env.
#    Generate a secret with:
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. Start everything.
docker compose up --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| API docs (ReDoc) | http://localhost:8000/redoc |
| PostgreSQL | `localhost:5432` |

Compose refuses to start if `POSTGRES_DB`, `POSTGRES_USER` or
`POSTGRES_PASSWORD` is missing from `.env`, rather than falling back to a
default password.

```bash
docker compose ps                    # status, including health
docker compose logs -f backend       # follow backend logs
docker compose down                  # stop, keep the database volume
docker compose down -v               # stop and delete the database volume
```

The database volume `bhashabench-postgres-data` persists across `down`/`up`.
Note that PostgreSQL only applies `POSTGRES_PASSWORD` when the volume is first
initialised; changing it later also requires `docker compose down -v`.

---

## Local installation without Docker

### Backend

Python 3.12 or newer.

```bash
# From the repository root.
python -m venv .venv

# Activate:
.venv\Scripts\Activate.ps1           # Windows PowerShell
source .venv/bin/activate            # macOS / Linux

pip install -r backend/requirements.txt -r backend/requirements-dev.txt

uvicorn app.main:app --reload --app-dir backend
```

The API is then on <http://localhost:8000>, with docs at `/docs`.

> `uvicorn` is installed **without** the `[standard]` extra. Those extras
> compile from source on the newest CPython releases, which breaks a plain
> `pip install` on many machines. Plain Uvicorn serves correctly; `--reload`
> falls back to polling-based file watching.

### Frontend

Node.js 20 or newer.

```bash
cd frontend
npm install
npm run dev
```

The dashboard is then on <http://localhost:3000>.

### Database only

To run just PostgreSQL while developing the backend on the host:

```bash
docker compose up -d db
```

---

## Environment configuration

Copy `.env.example` to `.env` and edit it. **`.env` is git-ignored and must
never be committed.**

`.env.example` documents the full configuration surface, including variables
that later phases will consume. Only the variables below are read by code
today; the rest are declared so the surface is stable, and are inert until
their phase lands.

### Read by Phase 1

| Variable | Purpose | Default |
|----------|---------|---------|
| `APP_ENV` | `development`, `staging`, `production` or `test`. Non-development values disable OpenAPI docs and reject a placeholder `SECRET_KEY`. | `development` |
| `APP_VERSION` | Version reported by the API | `0.1.0` |
| `SECRET_KEY` | Signing key; must be overridden outside development | placeholder |
| `DATABASE_URL` | SQLAlchemy-style URL; validated and reported, not yet connected | local Postgres |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Consumed by the Compose `db` service | — |
| `CORS_ORIGINS` | Comma-separated allowed browser origins | `http://localhost:3000` |
| `NEXT_PUBLIC_API_BASE_URL` | Backend URL used by the frontend | `http://localhost:8000` |

### Declared for later phases

| Variable | Phase |
|----------|-------|
| `GNANI_API_KEY`, `GNANI_API_BASE_URL` | 4–6 |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | 8 |
| `PUBLIC_BASE_URL` | 8 |
| `ALLOWED_BOT_NUMBERS`, `MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`, `MAX_CONCURRENT_CALLS` | 8 |
| `AUDIO_STORAGE_PATH`, `NOISE_MASTER_SEED` | 7 |
| `JUDGE_RETRIES`, `PASS_THRESHOLD` | 10 |

No endpoint paths, authentication schemes or request parameters for
third-party providers are assumed anywhere in this repository. Those are
written in the phase that integrates each provider, against its real
documentation.

---

## Development commands

Run from the repository root with the virtual environment active.

### Backend

```bash
pytest                               # run all tests
pytest -v                            # verbose
pytest backend/tests/test_health.py  # one module
pytest -k config                     # match by name

ruff check .                         # lint
ruff check --fix .                   # lint and autofix
ruff format .                        # format
ruff format --check .                # verify formatting without writing

uvicorn app.main:app --reload --app-dir backend
```

### Frontend

```bash
cd frontend
npm run dev                          # dev server with hot reload
npm run build                        # production build
npm run start                        # serve the production build
npm run lint                         # ESLint
npm run typecheck                    # tsc --noEmit
```

### Docker

```bash
docker compose config --quiet        # validate docker-compose.yml
docker compose up -d --build         # rebuild and start detached
docker compose exec backend pytest   # run tests inside the container
docker compose exec db psql -U bhashabench -d bhashabench
```

---

## Testing

The backend suite has **35 tests** in three modules:

| Module | Covers |
|--------|--------|
| `test_health.py` | Root, liveness and versioned health endpoints; the error envelope; a check that no secret appears in a response |
| `test_config.py` | Defaults, environment overrides, comma-separated list parsing, validation failures, production behaviour, settings caching |
| `test_app_metadata.py` | App title/summary/version, the generated OpenAPI document, and the application factory |

```bash
pytest
```

```
======================= 35 passed in 0.40s =======================
```

pytest is configured in `pyproject.toml` with `filterwarnings = ["error"]`,
so a new deprecation warning fails the build rather than accumulating
silently.

Frontend validation is lint plus a real production build:

```bash
cd frontend && npm run lint && npm run typecheck && npm run build
```

---

## API endpoints

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/` | Product name, tagline, version, environment, docs path |
| `GET` | `/health` | `{"status": "ok", "version": "0.1.0"}` |
| `GET` | `/api/v1/health` | Per-subsystem health, uptime and a UTC timestamp |

`GET /api/v1/health` reports the aggregate as **`degraded`**, not `ok`. That
is deliberate: the `database` component is honestly reported as not probed,
because Phase 1 opens no connection, and the aggregate follows the worst
component.

```json
{
  "status": "degraded",
  "service": "BhashaBench",
  "version": "0.1.0",
  "api_version": "v1",
  "environment": "development",
  "timestamp": "2026-11-01T14:33:13.855805Z",
  "uptime_seconds": 0.829,
  "components": [
    { "name": "api", "status": "ok", "detail": "FastAPI application is serving requests." },
    { "name": "configuration", "status": "ok", "detail": "Settings loaded for environment 'development'; .env file absent, DATABASE_URL default." },
    { "name": "database", "status": "degraded", "detail": "Not probed. A connection URL is configured but the persistence layer is not implemented in this phase." }
  ]
}
```

Every error, including unhandled exceptions, uses one envelope:

```json
{ "error": { "type": "not_found", "message": "Not Found", "status_code": 404 } }
```

---

## Roadmap

Fifteen phases, each ending with working code, passing tests and updated
documentation. Full detail in
[`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md).

| # | Phase | Status |
|---|-------|--------|
| 1 | Project foundation | ✅ Complete |
| 2 | Data model & persistence | ⬜ Not started |
| 3 | Scenario definition format | ⬜ Not started |
| 4 | Speech to text (Gnani Prisma) | ⬜ Not started |
| 5 | Text to speech (Gnani Timbre) | ⬜ Not started |
| 6 | AI caller simulation (Gnani Evon) | ⬜ Not started |
| 7 | Audio degradation pipeline | ⬜ Not started |
| 8 | Twilio telephony & media streaming | ⬜ Not started |
| 9 | Conversation orchestration engine | ⬜ Not started |
| 10 | Automated evaluation & scoring | ⬜ Not started |
| 11 | Multilingual benchmarking | ⬜ Not started |
| 12 | Results API & reporting | ⬜ Not started |
| 13 | React dashboard | ⬜ Not started |
| 14 | CI regression testing | ⬜ Not started |
| 15 | Hardening, observability & release | ⬜ Not started |

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch naming, commit message
conventions, testing expectations and the pull request process.

## License

MIT.
