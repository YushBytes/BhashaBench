# BhashaBench

**Test your voice AI before India tests it for you.**

An automated testing and benchmarking platform for Indian-language voice
bots — simulated callers, realistic audio degradation and automated
conversation scoring.

> ### Project status: Phases 1–5 of 15 complete
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
> **Phase 4 — Speech to text.** A provider-independent
> `TranscriptionProvider` interface with a
> Gnani Prisma adapter (batch and streaming) and an offline fake, audio
> validation, bounded retry and credential redaction.
>
> **Live-verified against Gnani on 2026-11-07:** authentication, a real batch
> request, and response parsing. **Not verified:** real streaming, and
> streaming provider behaviour. **Recognition accuracy is not independently
> benchmarked** — the test fixtures are synthesised tones with no ground
> truth, so no accuracy claim is made anywhere. Per-capability table in
> [docs/PROVIDERS.md](docs/PROVIDERS.md).
>
> **Phase 5 — Text to speech.** A provider-independent `SynthesisProvider`
> interface with a Gnani Timbre adapter (13 voices, 10 languages,
> telephony-rate audio) and an offline fake. `POST /api/v1/speech/generate`
> returns binary audio.
>
> **Live-verified against Gnani on 2026-11-07:** authentication, that the
> shared key carries the TTS scope, the request shape, the full adapter path,
> and that the audio is decodable (8 kHz mono 16-bit, 4.400 s). **Not
> evaluated:** pronunciation and prosody — nobody has listened to it, and no
> automated test can judge it.
>
> **Phase 6 — Caller engine.** A provider-independent `CallerProvider`
> interface with a **deterministic, rule-based** caller: an explicit nine-state
> machine, eleven ordered rules over signals extracted from the bot's
> transcript, decision validation, conversation persistence on the Phase 2
> schema, and seven endpoints under `/api/v1/caller`. A whole multi-turn
> conversation runs offline against a scripted bot.
>
> **Phase 6 uses deterministic, rule-based caller orchestration. Official
> Gnani Evon integration is deferred until documented access and credentials
> are available.** **Evon integration is NOT implemented or verified in this
> phase** — no Gnani text-generation endpoint is published and the released
> model has no hosted inference provider, so there is nothing to adapt.
> `evon` is not a registered provider and is refused by name; every caller
> response carries `uses_language_model: false`. **Not evaluated:**
> conversation quality, and behaviour against a real voice bot — nothing here
> has had a conversation with one. Design and limits in
> [docs/CALLER.md](docs/CALLER.md).
>
> **Phase 7 — End-to-end voice pipeline.** A scenario becomes a multi-turn
> conversation with real audio: the Phase 6 caller decides what to say, Timbre
> synthesises it, a reproducible degradation engine makes it sound like a phone
> call, a bot adapter carries it, and Prisma transcribes the reply. Nine
> endpoints under `/api/v1/test-runs`, five noise profiles, both the original
> and the degraded audio preserved for every turn, and a process-wide limit on
> how many runs execute at once - beyond it `POST /start` answers 503 rather
> than queueing.
>
> Every run records an **execution mode**, and that is the honesty control:
> `offline_simulation` moves no audio, `audio_fixture_test` runs every stage
> with the bot's replies read from fixtures, and only `external_bot_test` may
> be described as testing a bot. `telephony_test` exists in the vocabulary and
> **cannot be used** - a run in that mode is refused, because no telephony
> exists.
>
> **Not tested:** no live Gnani call was made through the pipeline, and **no
> real voice bot has been tested** - no external bot endpoint was available.
> **Not measured:** recognition accuracy under degradation. The audio fixtures
> contain no speech with reviewed ground truth, so no accuracy claim is
> possible. Simulated noise is shaped white noise at a stated signal-to-noise
> ratio, **not** a field recording. Design and limits in
> [docs/PIPELINE.md](docs/PIPELINE.md).
>
> **No calls are placed and no scores are produced yet.** Telephony and
> automated evaluation arrive in later phases — see
> [the roadmap](docs/DEVELOPMENT_ROADMAP.md). Phases 6 and 7 write to the
> `TestRun`, `CallSession` and `ConversationTurn` tables, and only for
> conversations they ran themselves against a scripted or supplied bot reply;
> Phase 4 still persists no transcript of its own.
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

Phases 1 to 7 are delivered. Nothing else below is implemented yet; each item
names the phase that delivers it.

| Capability | What it does | Phase |
|------------|--------------|-------|
| ~~Scenario definitions~~ | **Done (Phase 2).** Declare a persona, a language, an objective and success criteria in YAML | 2 |
| ~~Speech to text~~ | **Done (Phase 4).** Transcribe bot audio via Gnani Prisma — batch and streaming, behind a provider-independent interface | 4 |
| ~~Text to speech~~ | **Done (Phase 5).** Synthesise caller speech via Gnani Timbre - 13 voices, 10 languages, telephony-rate audio | 5 |
| ~~Simulated callers~~ | **Done (Phase 6).** A caller that pursues a goal rather than replaying a script - deterministic and rule-based. Gnani Evon is **not** integrated: no documented API access exists | 6 |
| ~~Audio degradation~~ | **Done (Phase 7).** Band-limiting, background noise at a measured SNR, clipping, level and packet loss, reproducible from a fixed seed. Simulated conditions, not field recordings | 7 |
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
   ├── Caller engine — rule-based     (Phase 6; Evon not integrated)
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
- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) — provider contracts and what is
  actually verified
- [`docs/CALLER.md`](docs/CALLER.md) — the caller engine: states, rules, limits
- [`docs/PIPELINE.md`](docs/PIPELINE.md) — the voice pipeline: execution modes,
  degradation, bot adapters

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
│   │   ├── speech/            text-to-speech subsystem (Phase 5), same shape
│   │   │   └── providers/     Gnani Timbre + offline fake
│   │   ├── caller/            caller engine (Phase 6): state machine, rules,
│   │   │   │                  transcript analysis, validation, orchestration
│   │   │   └── providers/     deterministic rule engine. No Evon adapter -
│   │   │                      see docs/CALLER.md for why
│   │   ├── pipeline/          end-to-end voice pipeline (Phase 7): run engine,
│   │   │   │                  audio degradation, execution modes
│   │   │   └── bots/          bot adapters. Neither opens a socket; the
│   │   │                      default sends audio nowhere
│   │   └── utils/timing.py    UTC clock helpers
│   ├── alembic/               migrations (alembic.ini is in backend/)
│   ├── tests/                 1957 tests across 33 modules
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
├── sample_bot/                reference bot to test against    (empty)
├── scripts/                   operational scripts
├── scenarios/                 reference scenario YAML (6 languages)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CALLER.md
│   ├── CLI.md
│   ├── DATABASE.md
│   ├── DEVELOPMENT_ROADMAP.md
│   ├── PIPELINE.md
│   ├── PROVIDERS.md
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
| `CALLER_PROVIDER` | Caller strategy. `deterministic` is the only value; `evon` is refused by name | `deterministic` |
| `CALLER_MAX_TURNS` | Ceiling on conversation turns, on top of the scenario's own `goal.max_turns`. The lower wins | `20` |
| `CALLER_MAX_CLARIFICATIONS` | How often the caller presses for a usable answer before closing as no progress | `2` |
| `CALLER_MAX_MESSAGE_CHARS` | Longest caller utterance accepted from a provider | `600` |
| `CALLER_TURN_TIMEOUT_SECONDS` | Ceiling on one full turn, synthesis and transcription included | `90.0` |
| `CALLER_AUDIO_STORAGE_DIR` | Conversation audio directory; `storage/` is git-ignored | `storage/caller-audio` |
| `CALLER_SYNTHESISE_AUDIO` | Synthesise caller audio per turn. Off deliberately — with `SPEECH_PROVIDER=timbre` every turn is a billable call. The pipeline forces it on for runs that move audio | `false` |
| `PIPELINE_BOT_ADAPTER` | Default bot adapter. Both options send audio nowhere, which is why one is the default | `scripted` |
| `PIPELINE_RUN_TIMEOUT_SECONDS` | Wall-clock ceiling on one run | `600.0` |
| `PIPELINE_MAX_CONCURRENT_RUNS` | Bounds provider spend and memory. Enforced per process: `POST /start` answers 503 beyond it rather than queueing | `2` |
| `PIPELINE_NOISE_SEED` | Default degradation seed, fixed so a run is reproducible | `42` |
| `PIPELINE_NOISE_PROFILE` | Profile for runs that name none; a scenario's own wins | `clean` |

### Declared for later phases

| Variable | Phase |
|----------|-------|
| `TRANSCRIPTION_PROVIDER`, `TRANSCRIPTION_TIMEOUT_SECONDS`, `TRANSCRIPTION_MAX_ATTEMPTS`, `TRANSCRIPTION_MAX_UPLOAD_BYTES`, `TRANSCRIPTION_LIVE_TESTS` | 4 |
| `GNANI_API_KEY`, `GNANI_API_BASE_URL` | 4–5 |
| `GNANI_STT_MODEL` | 4 |
| `SPEECH_PROVIDER`, `SPEECH_TIMEOUT_SECONDS`, `SPEECH_MAX_ATTEMPTS`, `SPEECH_MAX_TEXT_CHARS`, `SPEECH_LIVE_TESTS`, `GNANI_TTS_MODEL`, `GNANI_TTS_VOICE` | 5 |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | 8 |
| `PUBLIC_BASE_URL` | 8 |
| `ALLOWED_BOT_NUMBERS`, `MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`, `MAX_CONCURRENT_CALLS` | 8 |
| `AUDIO_STORAGE_PATH`, `NOISE_MASTER_SEED` | superseded by `CALLER_AUDIO_STORAGE_DIR` and `PIPELINE_NOISE_SEED` in Phase 7 |
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

The backend suite has **1957 tests** in thirty-three modules. 1916 run by
default; the 41 live provider tests are deselected unless you opt in:

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
| `test_transcription_core.py` | 111 | Audio format detection from content, WAV header parsing, size/duration/channel limits, filename safety, the retry policy's arithmetic and what it refuses to retry, the provider registry |
| `test_transcription_prisma.py` | 81 | The Gnani Prisma adapter against its published contract: request shape, every documented status, response normalisation, malformed responses, language and mode mapping |
| `test_transcription_api.py` | 93 | The service layer and the real FastAPI routes - batch upload, provider capabilities, the WebSocket lifecycle, error-to-status mapping, structured logging |
| `test_transcription_security.py` | 53 | Credential redaction, no secret in a response/log/stream frame, path traversal, capped uploads, temp-file cleanup, repository hygiene |
| `test_transcription_streaming.py` | 38 | Prisma's WebSocket protocol: 1024-byte framing, event mapping, ordering, malformed frames, cancellation, bounded buffering |
| `test_audio_fixtures.py` | 19 | The committed fixtures still match their generator byte for byte, and still claim no speech and no expected transcript |
| `test_transcription_live.py` | 15 | **Opt-in, billable.** Real Gnani Prisma calls. Skipped unless `TRANSCRIPTION_LIVE_TESTS=true` *and* `GNANI_API_KEY` are both set |
| `test_speech_timbre.py` | 132 | The Gnani Timbre adapter against its published contract: JSON body, every documented status and both error shapes, binary-response handling, the streaming WAV header, serialisation, client ownership |
| `test_speech_core.py` | 121 | The Timbre contract constants, voice catalogue, domain models, registry and service rules - including that a tag the model ignores is refused rather than spoken aloud |
| `test_speech_api.py` | 77 | The real FastAPI speech routes: binary response and its media types, `X-Speech-*` headers, error mapping, provider capabilities, cleanup on every exit path, security |
| `test_caller_core.py` | 71 | The caller state machine, the transcript analyser (Indic digits, code-switched keywords), the decision schema and the provider registry |
| `test_caller_rules.py` | 155 | Every rule of the deterministic caller; that five different bot replies produce five different turns; a legality sweep of every state against every shape of reply |
| `test_caller_service.py` | 34 | Decision validation, instruction-leak and invented-identifier rejection, synthesis, credential redaction in an error |
| `test_caller_orchestrator.py` | 39 | Multi-turn conversations against real PostgreSQL: success, every failure reason, determinism, persistence, transcription failure, audio artefacts |
| `test_caller_api.py` | 43 | The caller routes through `TestClient`: creation, turns, text and audio submission, termination, limits, prompt injection, OpenAPI |
| `test_pipeline_degradation.py` | 87 | The DSP: resampling, channel conversion, bandpass, noise at a measured SNR, clipping, packet loss, every profile, reproducibility from a seed |
| `test_pipeline_bots.py` | 35 | The bot adapter protocol, both adapters and the registry - including that neither contacts anything and the default sends audio nowhere |
| `test_pipeline_engine.py` | 61 | Multi-turn audio runs against real PostgreSQL: the full workflow, every failure path, cancellation, the manual flow, reproducibility |
| `test_pipeline_api.py` | 64 | The nine test-run routes: creation, execution, artefacts, reports, bot-audio submission, cancellation, path-traversal rejection, the 503 at the concurrency limit, OpenAPI |
| `test_pipeline_concurrency.py` | 41 | The admission limiter: the configured maximum is never exceeded, capacity frees up for the next run, and exceptions, cancellation and timeouts all release it |
| `test_speech_live.py` | 26 | **Opt-in, billable.** Real Gnani Timbre calls. Skipped unless `SPEECH_LIVE_TESTS=true` *and* `GNANI_API_KEY` are both set |

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
================ 1916 passed, 41 skipped in 78.70s ================
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
| `POST` | `/api/v1/speech/generate` | Synthesises text to speech and returns the **binary audio** with its media type. Metadata travels in `X-Speech-*` headers; a measurement header is present only when it could be verified from the audio |
| `GET` | `/api/v1/speech/providers` | Every synthesis provider with its voices, languages, audio formats, speed range and documentation gaps |
| `POST` | `/api/v1/caller/conversations` | 201. Opens a caller conversation for one scenario. Takes `{"suite_id": ..., "scenario_id": ...}` |
| `POST` | `/api/v1/caller/conversations/{id}/turns` | Produces and persists the caller's next utterance |
| `POST` | `/api/v1/caller/conversations/{id}/bot-text` | Records the bot's reply as text, skipping transcription |
| `POST` | `/api/v1/caller/conversations/{id}/bot-audio` | Transcribes the bot's reply and records it. A failure is a turn with `content: null`, never an empty transcript |
| `GET` | `/api/v1/caller/conversations/{id}` | State, outcome, turn counters and the rules that fired |
| `GET` | `/api/v1/caller/conversations/{id}/turns` | Every turn of the conversation, in order |
| `POST` | `/api/v1/caller/conversations/{id}/terminate` | Ends a conversation; outcome `aborted`, which is not a bot defect |
| `GET` | `/api/v1/caller/providers` | Caller providers with their capabilities and limits, plus an `evon_status` field stating that Gnani Evon is not implemented |
| `POST` | `/api/v1/test-runs` | 201. Creates a test run for one scenario and records its execution mode. Executes nothing |
| `POST` | `/api/v1/test-runs/{id}/start` | Runs turns until terminal, or until the run needs audio from outside. A run left `running` with `awaiting_bot_audio_for_turn` is waiting, not failed |
| `POST` | `/api/v1/test-runs/{id}/bot-audio` | Supplies the bot's reply as audio; it is validated, transcribed and the run continues |
| `POST` | `/api/v1/test-runs/{id}/cancel` | Stops a run. Outcome `cancelled`, never `failed` - an operator's decision is not a finding about the bot |
| `GET` | `/api/v1/test-runs/{id}` | State, counters and outcome |
| `GET` | `/api/v1/test-runs/{id}/turns` | Every utterance of the run's conversation |
| `GET` | `/api/v1/test-runs/{id}/artifacts` | Audio references and measured metadata. A degraded artefact names the original it came from |
| `GET` | `/api/v1/test-runs/{id}/report` | Full evidence: state, artefacts, caller state transitions and every stage with its measured duration. Measurements, not scores |
| `GET` | `/api/v1/test-runs/bot-adapters/available` | Bot adapters with their capabilities, plus the execution modes a run may use |
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
| 4 | Speech to text (Gnani Prisma) | ✅ Complete |
| 5 | Text to speech (Gnani Timbre) | ✅ Complete |
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
