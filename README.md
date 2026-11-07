# BhashaBench

**Test your voice AI before India tests it for you.**

An automated testing and benchmarking platform for Indian-language voice
bots — simulated callers, realistic audio degradation and automated
conversation scoring.

> ### Project status: Phases 1–3 of 15 complete; Phase 4 awaiting review
>
> **Phase 1 — Foundation.** FastAPI backend, health endpoints, Next.js status
> shell, Docker Compose stack, test and lint toolchain.
>
> **Phase 2 — Database & scenario engine.** PostgreSQL persistence via
> Alembic migrations, and the scenario engine: YAML authoring with strict
> validation, plus CRUD endpoints for test suites and scenarios.
>
> **Phase 3 — Scenario library & tooling.** Search, filtering and tags across
> suites; suite editing and guarded deletion; scenario copy and move; a
> 13-language catalogue with structured code-mixing annotations; bulk YAML
> import and deterministic export; and the `bhashabench` CLI.
>
> **Phase 4 — Speech to text.** *Implemented, awaiting owner review — not
> approved.* A provider-independent `TranscriptionProvider` interface with a
> Gnani Prisma adapter (batch and streaming) and an offline fake, audio
> validation, bounded retry and credential redaction. **The adapter is
> verified against Gnani's published contract, not against the live service:**
> no credential has been issued to this repository, so authentication and real
> requests are unverified. See [docs/PROVIDERS.md](docs/PROVIDERS.md).
>
> **No calls are placed and no scores are produced yet.** Telephony, text to
> speech, audio degradation, caller simulation and automated evaluation arrive
> in later phases — see [the roadmap](docs/DEVELOPMENT_ROADMAP.md). The
> `TestRun`, `CallSession` and `ConversationTurn` tables exist as foundational
> schema only; nothing writes to them, and Phase 4 persists no transcript.
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
- [Command-line interface](#command-line-interface)
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

Scenario definitions landed in Phase 2 and speech to text in Phase 4.
Nothing else below is implemented yet; each item names the phase that
delivers it.

| Capability | What it does | Phase |
|------------|--------------|-------|
| ~~Scenario definitions~~ | **Done (Phase 2).** Declare a persona, a language, an objective and success criteria in YAML | 2 |
| ~~Speech to text~~ | **Done (Phase 4), pending review.** Transcribe bot audio via Gnani Prisma — batch and streaming, behind a provider-independent interface | 4 |
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
   │  /api/v1/suites       │
   │  /api/v1/scenarios    │
   └───────────┬───────────┘
               │
   ┌───────────┴────────────┬──────────────────────┐
   │                        │                      │
┌──▼──────────────┐  ┌──────▼────────┐   ┌─────────▼─────────┐
│ Orchestrator    │  │ Scenario      │   │ PostgreSQL 16     │
│ (Phase 9)       │  │ engine        │   │ 5 tables, owned   │
└──┬──────────────┘  │ implemented   │   │ by Alembic        │
   │                 └───────────────┘   └───────────────────┘
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
| Data access | `backend/app/repositories/` | Every SQL statement; takes a Session, never commits |
| Persistence | `backend/app/models/` | SQLAlchemy ORM models |
| Engine | `backend/app/db/` | Declarative base, engine, session dependency |

Further reading:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design decisions
- [`docs/DATABASE.md`](docs/DATABASE.md) — schema, ER diagram, migrations
- [`docs/SCENARIO_FORMAT.md`](docs/SCENARIO_FORMAT.md) — the scenario YAML format

---

## Technology stack

| Area | Choice | Version |
|------|--------|---------|
| Backend | Python, FastAPI, Uvicorn | 3.12+, FastAPI 0.162 |
| Validation & config | Pydantic, pydantic-settings | 2.14, 2.16 |
| Persistence | SQLAlchemy (2.0-style typed ORM), Alembic, psycopg | 2.1, 1.20, 3.3 |
| Scenario format | PyYAML (`safe_load` only) | 6.0 |
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
│   │   ├── core/languages.py  the 13-language catalogue, single source
│   │   ├── api/               HTTP layer
│   │   │   ├── deps.py        injectable dependencies
│   │   │   └── v1/            versioned routes (health, suites, scenarios,
│   │   │                       languages, transcription)
│   │   ├── cli/               the `bhashabench` command-line interface
│   │   ├── db/                declarative base, engine, session dependency
│   │   ├── models/            SQLAlchemy ORM models (5 tables)
│   │   ├── repositories/      every SQL statement lives here
│   │   ├── schemas/           response models, error envelope, scenario spec
│   │   ├── services/          health, scenario loader, bundles, suite +
│   │   │                      scenario logic, transcription
│   │   ├── transcription/     speech-to-text subsystem (Phase 4): domain
│   │   │   │                  models, errors, audio, retry, redaction
│   │   │   └── providers/     Gnani Prisma + offline fake. The only place a
│   │   │                      vendor's wire format may appear.
│   │   └── utils/timing.py    UTC clock helpers
│   ├── alembic/               migrations (alembic.ini is in backend/)
│   ├── tests/                 954 tests across 19 modules
│   │   └── fixtures/audio/    generated test audio (no speech; see its README)
│   ├── requirements.txt       runtime dependencies
│   ├── requirements-dev.txt   test and lint dependencies
│   └── Dockerfile             multi-stage: development / production
├── frontend/
│   ├── app/                   App Router pages, layout, global styles
│   ├── components/            header, footer, section, status pill, cards
│   ├── lib/content.ts         typed product copy and phase status
│   ├── public/
│   └── Dockerfile             multi-stage: development / builder / production
├── benchmarks/                benchmark suite definitions      (Phase 11)
├── sample_bot/                reference bot to test against    (Phase 6)
├── scripts/                   operational scripts
├── scenarios/                 reference scenario YAML (6 languages)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CLI.md
│   ├── DATABASE.md
│   ├── DEVELOPMENT_ROADMAP.md
│   └── SCENARIO_FORMAT.md
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

### Command-line tools

```bash
pip install -e .                     # installs the `bhashabench` entry point
bhashabench --help
python -m app.cli --help             # equivalent, without installing
```

See [Command-line interface](#command-line-interface).

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

### Read by the application today

| Variable | Purpose | Default |
|----------|---------|---------|
| `APP_ENV` | `development`, `staging`, `production` or `test`. Non-development values disable OpenAPI docs and reject a placeholder `SECRET_KEY`. | `development` |
| `APP_VERSION` | Version reported by the API | `0.1.0` |
| `SECRET_KEY` | Signing key; must be overridden outside development | placeholder |
| `DATABASE_URL` | SQLAlchemy-style URL. **Its port must match `POSTGRES_HOST_PORT`** or host-side tooling, including `alembic upgrade head`, will connect to whatever else is on the old port | local Postgres |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Consumed by the Compose `db` service | — |
| `CORS_ORIGINS` | Comma-separated allowed browser origins | `http://localhost:3000` |
| `NEXT_PUBLIC_API_BASE_URL` | Backend URL used by the frontend | `http://localhost:8000` |

### Declared for later phases

| Variable | Phase |
|----------|-------|
| `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_TIMEOUT_SECONDS`, `TRANSCRIPTION_MAX_ATTEMPTS`, `TRANSCRIPTION_MAX_UPLOAD_BYTES`, `TRANSCRIPTION_LIVE_TESTS` | 4 |
| `GNANI_API_KEY`, `GNANI_API_BASE_URL`, `GNANI_STT_MODEL` | 4–6 |
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

### Migrations

Run from `backend/`, where `alembic.ini` lives.

```bash
cd backend

alembic upgrade head                 # apply pending migrations
alembic current                      # show the applied revision
alembic history --verbose            # list revisions
alembic downgrade -1                 # undo the most recent migration
alembic check                        # fail if models and migrations drifted
alembic revision --autogenerate -m "description"
alembic upgrade head --sql           # print the SQL without running it
```

Add new models to `app/models/__init__.py` first, or autogenerate will not see
them. Read every generated migration: autogenerate misses renames and cannot
know about data backfills. See [`docs/DATABASE.md`](docs/DATABASE.md).

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
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
docker compose exec db psql -U bhashabench -d bhashabench
```

---

## Testing

The backend suite has **954 tests** in nineteen modules. 939 run by
default; the 15 live provider tests are deselected unless you opt in:

| Module | Tests | Covers |
|--------|-------|--------|
| `test_health.py` | 16 | Root, liveness and versioned health endpoints; the database probe reachable and unreachable; the error envelope; a check that no secret appears in a response |
| `test_config.py` | 14 | Defaults, environment overrides, comma-separated list parsing, validation failures, production behaviour, settings caching |
| `test_app_metadata.py` | 9 | App title/summary/version, the generated OpenAPI document, the application factory |
| `test_scenario_spec.py` | 107 | YAML syntax, unsafe payloads, recursive/cyclic aliases, size and expansion limits, every validation rule, round-trip serialisation, file loading |
| `test_database.py` | 37 | Connection, the migrated schema, model creation, relationships, foreign-key delete behaviour, every constraint, transaction rollback |
| `test_api_suites_scenarios.py` | 63 | The Phase 2 endpoints, pagination, duplicates, unknown ids, malformed UUIDs, oversized bodies, error-envelope shape |
| `test_languages.py` | 89 | Catalogue invariants (unique codes and locales, endonym scripts), tag shape and membership rejection, and that the schema and the API read from this one source |
| `test_bundle.py` | 39 | Bundle parsing and building: per-entry error collection, duplicate rejection, the 500-entry cap, byte-identical round-trips, no ids or timestamps in output |
| `test_api_library.py` | 74 | Search, filters, pagination and ordering; suite `PATCH` and guarded `DELETE`; copy and move; import dry-run and atomicity; export round-trip |
| `test_cli.py` | 65 | Argument parsing, exit codes and output for every command through Typer's `CliRunner`, plus that no connection string reaches the terminal on a database outage |
| `test_reference_scenarios.py` | 40 | Every committed scenario in `scenarios/` validates and round-trips, the set covers six languages and the documented audio and code-mixing cases, and the generated bundle is not stale |
| `test_tooling.py` | 8 | That the host and container pytest configurations enforce the same things, so the second run corroborates the first instead of decorating it |
| `test_transcription_core.py` | 104 | Audio format detection from content, WAV header parsing, size/duration/channel limits, filename safety, the retry policy's arithmetic and what it refuses to retry, the provider registry |
| `test_transcription_prisma.py` | 81 | The Gnani Prisma adapter against its published contract: request shape, every documented status, response normalisation, malformed responses, language and mode mapping |
| `test_transcription_api.py` | 83 | The service layer and the real FastAPI routes - batch upload, provider capabilities, the WebSocket lifecycle, error-to-status mapping, structured logging |
| `test_transcription_security.py` | 53 | Credential redaction, no secret in a response/log/stream frame, path traversal, capped uploads, temp-file cleanup, repository hygiene |
| `test_transcription_streaming.py` | 38 | Prisma's WebSocket protocol: 1024-byte framing, event mapping, ordering, malformed frames, cancellation, bounded buffering |
| `test_audio_fixtures.py` | 19 | The committed fixtures still match their generator byte for byte, and still claim no speech and no expected transcript |
| `test_transcription_live.py` | 15 | **Opt-in, billable.** Real Gnani Prisma calls. Skipped unless `TRANSCRIPTION_LIVE_TESTS=true` *and* `GNANI_API_KEY` are both set |

```bash
pytest
```

### The database tests need PostgreSQL

`test_database.py`, `test_api_suites_scenarios.py`, `test_api_library.py` and
the database-backed half of `test_cli.py` run against a **real PostgreSQL** — not SQLite, because the schema uses JSONB, native UUIDs and
`ON DELETE RESTRICT`, none of which SQLite models faithfully.

```bash
docker compose up -d db              # start it first
pytest
```

The fixtures create a dedicated `bhashabench_test` database, migrate it with
Alembic (so the migration is exercised on every run) and wrap each test in a
transaction that is rolled back. Your own database is never touched.

If PostgreSQL is unreachable those tests are **skipped with an explicit
reason** naming the host and port tried, plus a session-end banner stating
they were skipped and not passed. They never silently pass.

Point them elsewhere with `BHASHABENCH_TEST_DATABASE_URL`.

```
================= 939 passed, 15 skipped in 30.05s ================
```

pytest is configured in `pyproject.toml` with `filterwarnings = ["error"]`,
so a new deprecation warning fails the build rather than accumulating
silently.

Frontend validation is lint plus a real production build:

```bash
cd frontend && npm run lint && npm run typecheck && npm run build
```

---

## Command-line interface

`bhashabench` is the authoring and administration tool for the scenario
library — a thin front end over the same services the API calls, so the two
cannot disagree about whether a scenario is valid.

```bash
pip install -e .                     # provides the `bhashabench` command

# Offline: no database, no running service.
bhashabench validate scenarios/appointment_booking.yaml
bhashabench validate-bundle scenarios/bundles/indian_language_reference.yaml
bhashabench languages

# Database-backed.
bhashabench suite create "Reference"
bhashabench scenario list --language ta-IN --tag payment
bhashabench import scenarios/bundles/indian_language_reference.yaml --suite "$ID" --dry-run
bhashabench export "$ID" --output bundle.yaml
```

Exit codes are distinguished so a shell script can act on them: `0` success,
`1` the operation failed (not found, conflict, refused), `2` invalid input,
`3` the database is unreachable. Every command takes `--json`.

Full reference: [`docs/CLI.md`](docs/CLI.md).

---

## API endpoints

### Meta and health

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/` | Product name, tagline, version, environment, docs path |
| `GET` | `/health` | `{"status": "ok", "version": "0.1.0"}` — cheap liveness probe |
| `GET` | `/api/v1/health` | Per-subsystem health, uptime and a UTC timestamp |
| `GET` | `/api/v1/languages` | The 13 supported languages with endonym, script and locale |

### Test suites

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/api/v1/suites` | 201 with the created suite. 409 if the name is taken |
| `GET` | `/api/v1/suites` | Paginated list, newest first (`limit`, `offset`) |
| `GET` | `/api/v1/suites/{suite_id}` | One suite with its scenario count. 404 if unknown |
| `PATCH` | `/api/v1/suites/{suite_id}` | Updates the name, the description, or both. 409 on a duplicate name |
| `DELETE` | `/api/v1/suites/{suite_id}` | 409 if the suite still holds scenarios. `?cascade=true` deletes them with it |

### Scenarios

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/api/v1/suites/{suite_id}/scenarios` | 201. Takes `{"yaml": "..."}` |
| `GET` | `/api/v1/suites/{suite_id}/scenarios` | Paginated summaries, ordered by name |
| `GET` | `/api/v1/scenarios/{scenario_id}` | One scenario with its full specification |
| `PUT` | `/api/v1/scenarios/{scenario_id}` | Replaces the definition. Takes `{"yaml": "..."}` |
| `DELETE` | `/api/v1/scenarios/{scenario_id}` | 204 |
| `POST` | `/api/v1/scenarios/validate` | Validates YAML without storing anything |
| `GET` | `/api/v1/scenarios` | Searches the whole library. `suite_id`, `language`, `name`, repeatable `tag`, `limit`, `offset` |
| `POST` | `/api/v1/scenarios/{scenario_id}/copy` | 201. Copies into another suite with a new id. Takes `{"target_suite_id": ..., "new_name": ...}` |
| `POST` | `/api/v1/scenarios/{scenario_id}/move` | Moves to another suite, keeping the id |
| `POST` | `/api/v1/transcription` | Transcribes one uploaded audio file (`multipart/form-data`). Container identified from content, not from the declared type |
| `GET` | `/api/v1/transcription/providers` | Every registered provider with its capabilities, limitations and documentation gaps - including ones missing a credential |
| `WS` | `/api/v1/transcription/stream` | Streaming transcription. Send PCM frames, receive `started` / `final_transcript` / `completed` events. Not in the OpenAPI document - OpenAPI 3.1 cannot describe a WebSocket; see [docs/PROVIDERS.md](docs/PROVIDERS.md) |
| `POST` | `/api/v1/suites/{suite_id}/scenarios/import` | Bulk import from a bundle. Takes `{"yaml": ..., "dry_run": ..., "atomic": ...}` |
| `GET` | `/api/v1/suites/{suite_id}/scenarios/export` | The suite as a deterministic, re-importable bundle |

Scenario names are unique **per suite**, so two suites may each hold an
`appointment_booking`. See
[`docs/SCENARIO_FORMAT.md`](docs/SCENARIO_FORMAT.md) for the YAML format.

`POST /api/v1/scenarios/validate` returns **200 even for invalid YAML**, with
the verdict in `valid` and field-addressed errors. A 4xx there would make
"your YAML is wrong" indistinguishable from "the validation endpoint is
broken". An oversized body is the exception and returns 413.

### Health output

`GET /api/v1/health` probes the database with `SELECT 1` and reports what it
finds. The `database` component is `ok` when reachable and `unavailable` when
not — `unavailable` rather than `degraded`, because without the database every
suite and scenario endpoint fails. The aggregate follows the worst component.

```json
{
  "status": "ok",
  "service": "BhashaBench",
  "version": "0.1.0",
  "api_version": "v1",
  "environment": "development",
  "timestamp": "2026-11-01T17:40:11.204881Z",
  "uptime_seconds": 1.412,
  "components": [
    { "name": "api", "status": "ok", "detail": "FastAPI application is serving requests." },
    { "name": "configuration", "status": "ok", "detail": "Settings loaded for environment 'development'; .env file present, DATABASE_URL configured." },
    { "name": "database", "status": "ok", "detail": "Connected; SELECT 1 succeeded." }
  ]
}
```

### Errors

Every error, including unhandled exceptions, uses one envelope:

```json
{ "error": { "type": "not_found", "message": "suite '...' does not exist", "status_code": 404 } }
```

| Status | `type` | When |
|--------|--------|------|
| 404 | `not_found` | Unknown suite or scenario id |
| 409 | `conflict` | Duplicate suite name, or duplicate scenario name in a suite |
| 413 | `payload_too_large` | YAML beyond the size limit |
| 422 | `validation_error` | Malformed request body, a non-UUID path segment, or an unsupported `?language=` filter |
| 422 | `yaml_syntax_error` | YAML that will not parse, or an unsafe tag |
| 422 | `scenario_validation_error` | Parsed, but violates the scenario schema |
| 500 | `internal_error` | Unhandled exception; details are logged, never returned |

---

## Roadmap

Fifteen phases, each ending with working code, passing tests and updated
documentation. Full detail in
[`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md).

| # | Phase | Status |
|---|-------|--------|
| 1 | Project foundation | ✅ Complete |
| 2 | Database & scenario engine | ✅ Complete |
| 3 | Scenario library & tooling | ✅ Complete |
| 4 | Speech to text (Gnani Prisma) | 🟨 Implemented, awaiting review |
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
