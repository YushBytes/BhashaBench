# BhashaBench

**Test your voice AI before India tests it for you.**

An automated testing and benchmarking platform for Indian-language voice
bots — simulated callers, realistic audio degradation and automated
conversation scoring.

> ### Project status: Phases 1–5 of 15 complete; 6 blocked; 7, 9, 10, 12, 13 and 15 partial
>
> The original 15-phase plan is in force again. The summaries below were
> written as each piece of work closed, in the competition numbering; the
> [roadmap](docs/DEVELOPMENT_ROADMAP.md) maps them to the original phases.
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
> `evon` is not a registered provider and is refused by name.
>
> **A Sarvam language-model caller is implemented and tested offline only**
> (`sarvam-105b` and `sarvam-105b-conversations`), with the rule engine as its
> fallback. **No request has been sent to Sarvam and none can be:** live
> testing is not authorised, and live calls are disabled by a constant in the
> code rather than by a setting. The approved ₹100 is a ceiling for later live
> tests, not a budget in use. `uses_language_model` is derived from what
> actually produced each turn, so it is `false` on every run so far.
> **Not evaluated:**
> conversation quality, and behaviour against a real voice bot — nothing here
> has had a conversation with one. Design and limits in
> [docs/CALLER.md](docs/CALLER.md).
>
> **Phase 7, with parts of 9 and 10 — End-to-end voice pipeline.** A scenario becomes a multi-turn
> conversation with real audio: the Phase 6 caller decides what to say, Timbre
> synthesises it, a reproducible degradation engine makes it sound like a phone
> call, a bot adapter carries it, and Prisma transcribes the reply. Eleven
> operations across ten paths under `/api/v1/test-runs`, five noise profiles,
> both the original and the degraded audio preserved for every turn, and a
> process-wide limit on how many runs execute at once - beyond it
> `POST /start` answers 503 rather than queueing.
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
> **Phase 9 (partial) — Concurrency enforcement.** The process-wide
> `PIPELINE_MAX_CONCURRENT_RUNS` limit is actually read and enforced; it
> refuses with 503 rather than queueing, and releases its slot in a `finally`
> so a cancellation or timeout cannot leak one.
>
> **Phase 13 (partial) — Operator workspace & public site.** A public site at `/` that
> explains what the instrument measures, and an operator workspace at `/app`
> that drives it: run history with filters, a conversation inspector, audio
> playback with waveforms drawn from the decoded bytes, the scenario library
> and provider status. Two backend endpoints were added because the workspace
> could not be built honestly without them — run listing and stored artefact
> audio.
>
> The frontend renders **no sample analytics and has no mock mode**: a failed
> API call renders an error state, because plausible data returned while the
> backend is down makes a broken deployment look like a working one. The
> honesty fields (`uses_language_model`, `bot_audio_externally_received`,
> `measurement_note`, `evon_status`, `telephony_status`) are rendered
> structurally rather than as copy.
>
> **Not tested:** no live voice bot and no telephony went through the
> workspace. **Known gaps, unresolved:** `audio_fixture_test` cannot complete
> through the API, and `offline_simulation` does not reach a terminal status —
> both are documented in
> [docs/PHASE_08_IMPLEMENTATION_REPORT.md](docs/PHASE_08_IMPLEMENTATION_REPORT.md).
> There is no frontend test suite, no run auto-refresh and no authentication.
> Design in [docs/FRONTEND.md](docs/FRONTEND.md).
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

- [Run the demo](#run-the-demo)
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

## Run the demo

A reproducible end-to-end demonstration: a Tamil crop-insurance call executed
through the whole pipeline, inspectable in the operator workspace.

**Competition submission** — [one-page pitch](docs/COMPETITION_ONE_PAGE_PITCH.md)
· [recording script](docs/COMPETITION_DEMO_SCRIPT.md)
· [readiness report](docs/COMPETITION_READINESS_REPORT.md)
· demo video: **_pending upload_**

### Prerequisites

Python 3.12+, Node 20+, Docker (for PostgreSQL only), and a `.env` copied from
[`.env.example`](.env.example).

### Start the stack

Three terminals. This is the configuration that was verified end to end.

```bash
# 1. PostgreSQL only
docker compose up -d db

# 2. Backend. PIPELINE_FIXTURE_AUDIO_PATH is what lets a fixture run complete;
#    without it a scripted run has no replies and fails on turn 0, by design.
#    PowerShell: $env:PIPELINE_FIXTURE_AUDIO_PATH="backend/tests/fixtures/audio/tone_8k_mono.wav"
PIPELINE_FIXTURE_AUDIO_PATH=backend/tests/fixtures/audio/tone_8k_mono.wav   python -m uvicorn app.main:app --app-dir backend --port 8000

# 3. Frontend - keep it on port 3000, which is what CORS_ORIGINS allows, and
#    bind it to loopback so other devices on the network cannot reach it
cd frontend && npm run dev -- --hostname 127.0.0.1 --port 3000
```

| Surface | URL |
|---|---|
| Public site | <http://localhost:3000> |
| Operator workspace | <http://localhost:3000/app> |
| API | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| Health | <http://localhost:8000/api/v1/health> |

Check it is up before going further — all three components should read `ok`:

```bash
curl http://localhost:8000/api/v1/health
```

### Load the scenario and execute a run

```bash
python scripts/demo.py setup   # load the demo scenario (idempotent)
python scripts/demo.py run     # execute one run and print its evidence
```

`run` prints the workspace URL for the run it just executed. Open it to see the
transcript, the stage timings, both audio variants per turn and the waveforms.

The script creates a suite and a scenario if they are absent and reuses them
otherwise. **It deletes nothing and calls no paid API** — the demonstration uses
the offline `fake` speech and transcription providers, so no Gnani request is
made and no credit is consumed.

### What the demo does and does not establish

**Does:** a scenario becomes a multi-turn Tamil conversation; the caller's
speech is synthesised, degraded from a fixed seed, carried to a bot adapter and
transcribed; every turn is persisted with both audio variants; and the run
terminates with a recorded outcome.

**Does not:** test a real voice bot. The bot is stubbed with fixture audio and
the providers are the offline fakes, so **the bot transcript on screen is
scripted stub output and the waveform is flat because the fake synthesiser
emits a constant tone.** No accuracy, word error rate or quality score is
computed anywhere. `bot_audio_externally_received` is `false` on this run, which
is the platform refusing to claim otherwise.

### Shut down

```bash
# Ctrl+C the backend and the frontend, then:
docker compose stop db      # keeps the data
# docker compose down       # also removes the containers; the named volume survives
```

### Known rough edges

- **Do not run the whole stack with `docker compose up`** for the demo. The
  frontend's server components fetch the API from inside the container, where
  `localhost:8000` is the container itself, so the workspace renders "The API is
  not reachable". Run the frontend on the host instead.
- If the frontend 404s on `/app` after pulling changes, its build cache volume
  is stale: `docker compose up -d --force-recreate --renew-anon-volumes frontend`.
- Audio playback needs the frontend on port 3000, or the browser fetch is
  blocked by CORS.
- A bare `npm run dev` listens on every network interface, so the demo is
  reachable from other devices on the same network. `--hostname 127.0.0.1`
  keeps it on this machine. `package.json` and the frontend Dockerfile are
  deliberately unchanged: inside the container the server must listen on
  `0.0.0.0` for Compose's port mapping to work.

### Screenshots

Captured from the running application, in
[`docs/competition/screenshots/`](docs/competition/screenshots/): the public
site, the workspace overview, run history, the conversation inspector, the
scenario library, provider status and the new-test workflow, at 1440 px and
390 px.

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

Struck-through rows are delivered; every other row is not implemented yet and
names the original phase that delivers it.

| Capability | What it does | Phase |
|------------|--------------|-------|
| ~~Scenario definitions~~ | **Done (Phase 2).** Declare a persona, a language, an objective and success criteria in YAML | 2 |
| ~~Speech to text~~ | **Done (Phase 4).** Transcribe bot audio via Gnani Prisma — batch and streaming, behind a provider-independent interface | 4 |
| ~~Text to speech~~ | **Done (Phase 5).** Synthesise caller speech via Gnani Timbre - 13 voices, 10 languages, telephony-rate audio | 5 |
| ~~Simulated callers~~ | **Done (Phase 6).** A caller that pursues a goal rather than replaying a script - deterministic and rule-based. Gnani Evon is **not** integrated: no documented API access exists | 6 |
| ~~Audio degradation~~ | **Delivered (Phase 7).** Band-limiting, background noise at a measured SNR, gain, clipping, G.711 codecs, packet loss, jitter, dropouts, truncation and silence - declarable per scenario, overridable per run, measured per artefact and reproducible from a seed. Simulated conditions, not field recordings | 7 |
| ~~Operator workspace~~ | **Delivered (Phase 13, partial).** A public site at `/` and a workspace at `/app`: run history, a conversation inspector with audio playback and waveforms drawn from the stored bytes, scenario library and provider status | 13 |
| Live telephony | Outbound calls with Twilio bidirectional media streaming | 8 |
| Real-time conversation | External voice bots over a streaming audio protocol, barge-in and silence handling. (A text protocol and HTTP adapter exist: see `docs/BOT_PROTOCOL.md`) | 9 |
| Recording | Full-conversation recording, retention and deletion | 10 |
| ~~Automated scoring~~ | **Delivered (Phase 11).** A reproducible pass / fail / undetermined verdict with per-criterion reasons, WER and CER against reviewed references with Indic-aware normalisation, latency and phrase checks - every metric defined in one registry, no composite score. The LLM judge interface exists but is offline-only: no model has judged anything | 11 |
| Reporting | Aggregate queries, run comparison and regression detection | 12 |
| CI regression testing | Every pull request runs the suite and fails on quality regression | 14 |

---

## Architecture overview

```
   ┌───────────────────────┐
   │  Next.js frontend     │   implemented: public site + workspace
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
   ├── Caller engine — rule-based     (Phase 6; Sarvam LLM offline only; no Evon)
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
- [`docs/FRONTEND.md`](docs/FRONTEND.md) — the public site and the operator
  workspace: routes, design tokens, the API client and the honesty rules
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
│   │   │   ├── providers/     deterministic rule engine, and the model-backed
│   │   │   │                  strategy. No Evon adapter - see docs/CALLER.md
│   │   │   └── llm/           vendor-neutral LLM contract, live gate, budget;
│   │   │                      clients/ holds the Sarvam adapter (offline only)
│   │   ├── pipeline/          end-to-end voice pipeline (Phase 7): run engine,
│   │   │   │                  audio degradation, execution modes
│   │   │   └── bots/          bot adapters. Only `http` opens a socket,
│   │   │                      for text; the default sends nothing anywhere
│   │   └── utils/timing.py    UTC clock helpers
│   ├── alembic/               migrations (alembic.ini is in backend/)
│   ├── reference_bot/         reference text bot (docs/BOT_PROTOCOL.md)
│   ├── tests/                 3029 tests across 69 modules
│   │   └── fixtures/audio/    generated test audio (no speech; see its README)
│   ├── requirements.txt       runtime dependencies
│   ├── requirements-dev.txt   test and lint dependencies
│   └── Dockerfile             multi-stage: development / production
├── frontend/                  public site and operator workspace (Phase 8)
│   ├── app/page.tsx           the public site
│   ├── app/app/               the workspace: overview, runs, new-test,
│   │                          scenarios, providers
│   ├── components/ui/         primitives, status vocabulary, loading states
│   ├── components/shell/      sidebar, mobile drawer, page header
│   ├── components/domain/     runs table, conversation inspector, audio
│   │                          player, stage timeline, evidence notices
│   ├── components/marketing/  public header/footer, pipeline diagram
│   ├── lib/api/               the ONLY place the frontend calls the API
│   ├── lib/content.ts         public-site copy and phase status
│   ├── public/
│   └── Dockerfile             multi-stage: development / builder / production
├── benchmarks/                benchmark suite definitions      (Phase 11)
├── scripts/                   operational scripts
│   └── api_surface.py         counts API paths/operations from the OpenAPI schema
├── scenarios/                 reference scenario YAML (6 languages)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── CALLER.md
│   ├── CLI.md
│   ├── DATABASE.md
│   ├── DEVELOPMENT_ROADMAP.md
│   ├── FRONTEND.md
│   ├── PIPELINE.md
│   ├── PROVIDERS.md
│   └── SCENARIO_FORMAT.md
├── .github/workflows/ci.yml   CI foundation (Phase 0); Phase 14 extends it
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

The public site is then on <http://localhost:3000> and the operator
workspace on <http://localhost:3000/app>.

The workspace calls the API **from the browser** to stream audio, so the
origin it is served from must appear in the backend's `CORS_ORIGINS`.
Serving the frontend on any port other than 3000 means adding that origin,
or audio playback fails as an opaque console error rather than a useful
status code.

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
| `BACKEND_URL` | Where the frontend's server reaches the backend: the `/api/v1` proxy target and server-component fetches. Compiled into the rewrites at `next build` | `http://localhost:8000` (`http://backend:8000` in Compose) |
| `NEXT_PUBLIC_API_BASE_URL` | Host-reachable backend URL for the public site's API-docs link | `http://localhost:8000` |
| `CALLER_PROVIDER` | Caller strategy. `deterministic` (a rule engine) or `sarvam` (a Sarvam model with the rule engine as fallback; offline-tested only, and unable to make a live call while live calls are unauthorised). `evon` is refused by name | `deterministic` |
| `SARVAM_API_KEY` | Sarvam key, sent as `api-subscription-key`. Not needed, and not used, while live calls are off | _empty_ |
| `SARVAM_API_BASE_URL` | Sarvam REST base URL; must be https | `https://api.sarvam.ai` |
| `CALLER_LLM_MODEL` | `sarvam-105b` or `sarvam-105b-conversations`. Required for `CALLER_PROVIDER=sarvam`; there is no default model | _empty_ |
| `CALLER_LLM_LIVE_CALLS_ENABLED` | Operator switch for live language-model calls. Necessary and **not sufficient**: `LIVE_CALLS_AUTHORISED` in `app/caller/llm/budget.py` is a constant, is `False`, and no setting changes it | `false` |
| `CALLER_LLM_LIVE_BUDGET_INR` | Total rupees live calls may commit across all runs and restarts. Values above 100 are rejected | `0` |
| `CALLER_LLM_BUDGET_LEDGER_PATH` | The spending ledger; `storage/` is git-ignored | `storage/llm-budget/ledger.json` |
| `CALLER_LLM_MAX_COST_PER_RUN_INR` | Most one conversation may commit, worst case | `5` |
| `CALLER_LLM_COST_MARGIN` | Fraction added to the vendor's GST-exclusive prices. A project allowance, not a vendor figure | `0.18` |
| `CALLER_LLM_MAX_OUTPUT_TOKENS` / `CALLER_LLM_MAX_PROMPT_TOKENS` | Per-turn token limits; the prompt is measured as an upper bound, not a tokenizer count | `300` / `8000` |
| `CALLER_LLM_MAX_ATTEMPTS` | Total requests for one turn, counting every kind of failure, before the rule engine takes it | `2` |
| `CALLER_LLM_REQUEST_TIMEOUT_SECONDS` | Ceiling on one language-model request | `30.0` |
| `CALLER_LLM_TEMPERATURE` | Always sent explicitly; the vendor's documented default is contradictory | `0.5` |
| `CALLER_LLM_SEED` | Optional seed. Best-effort by the vendor's description; recorded as sent, never as honoured | _unset_ |
| `CALLER_LLM_REASONING_EFFORT` | `low`/`medium`/`high`/`max` for `sarvam-105b`; empty disables reasoning. Must be empty for the conversations model | _empty_ |
| `CALLER_MAX_TURNS` | Ceiling on conversation turns, on top of the scenario's own `goal.max_turns`. The lower wins | `20` |
| `CALLER_MAX_CLARIFICATIONS` | How often the caller presses for a usable answer before closing as no progress | `2` |
| `CALLER_MAX_MESSAGE_CHARS` | Longest caller utterance accepted from a provider | `600` |
| `CALLER_TURN_TIMEOUT_SECONDS` | Ceiling on one full turn, synthesis and transcription included | `90.0` |
| `CALLER_AUDIO_STORAGE_DIR` | Conversation audio directory; `storage/` is git-ignored | `storage/caller-audio` |
| `CALLER_SYNTHESISE_AUDIO` | Synthesise caller audio per turn. Off deliberately — with `SPEECH_PROVIDER=timbre` every turn is a billable call. The pipeline forces it on for runs that move audio | `false` |
| `PIPELINE_BOT_ADAPTER` | Default bot adapter. `scripted` and `manual` send nothing anywhere, which is why one is the default; `http` must be chosen per run | `scripted` |
| `BOT_HTTP_BASE_URL` | Base URL of a bot speaking `bhashabench-text-bot/1` (`docs/BOT_PROTOCOL.md`) | empty |
| `BOT_HTTP_TOKEN` | Bearer token for that bot. Never commit a value | empty |
| `BOT_HTTP_ALLOWED_HOSTS` | Comma-separated hosts the `http` adapter may contact, exactly or `*.suffix`. Empty refuses every host | empty |
| `BOT_HTTP_ALLOW_LOOPBACK` | Permit a loopback bot (the local reference bot). Refused when `APP_ENV` is staging or production | `false` |
| `BOT_HTTP_ALLOW_PRIVATE` | Permit a bot on a private network range | `false` |
| `BOT_HTTP_TIMEOUT_SECONDS` | Ceiling on one request to the bot | `10` |
| `BOT_HTTP_MAX_ATTEMPTS` | Requests per turn, counting retries | `2` |
| `PIPELINE_FIXTURE_AUDIO_PATH` | WAV the `scripted` adapter replays as every bot reply. Unset, a scripted audio run fails on turn 0 | _unset_ |
| `PIPELINE_FIXTURE_BOT_TEXT_PATH` | Bot replies as text, one per line, for `offline_simulation` with the `scripted` adapter. Unset, such a run fails on its first bot turn | _unset_ |
| `METRICS_TOKEN` | Bearer token for `GET /metrics` (Prometheus text); empty turns the endpoint off | empty |
| `LOG_FORMAT` | `text`, or `json` for one object per line with the request id | `text` |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` / `RATE_LIMIT_LOGINS_PER_MINUTE` | Per-client limits on `/api/` and on login (also per email); 429 with `Retry-After`; 0 disables | `600` / `10` |
| `TRUST_FORWARDED_FOR` | Key rate limits by `X-Forwarded-For`; only behind a proxy that overwrites it | `false` |
| `BOT_WS_URL` | ws:// or wss:// URL of a bot speaking `bhashabench-voice-bot/1` for the `ws_voice` adapter (token and host allowlist shared with `http`) | empty |
| `PIPELINE_RECOVERY_INTERVAL_SECONDS` | How often the server closes runs left in flight with nothing executing them; 0 disables | `300` |
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
| `JUDGE_RETRIES`, `PASS_THRESHOLD` | not adopted in Phase 11: the judge's attempt limit is a call argument capped at 3, and the verdict is a conjunction of criteria, so there is no threshold to set |

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

Both Ruff commands are run **from the repository root**, and their scope is
the project's tracked Python source — currently 140 files. The scope is set in
`pyproject.toml` and is therefore identical locally and in CI; there is no
second, differently-scoped invocation anywhere.

Two exclusions are deliberate and worth knowing about:

- **Markdown is not in scope.** Ruff's default `include` carries `*.md` and so
  formats the Python code blocks inside documentation. That made
  `ruff format --check .` a gate over prose — the eleven files in `docs/`
  counted as eleven "Python" files, and editing a code sample could fail the
  check with no Python touched. `include` is set explicitly without `*.md`.
- **`.agents/` and `.claude/` are excluded.** They are untracked local agent
  tooling inside the working tree, and contributed 79 files to the count,
  making the figure a property of one machine rather than of the repository.

The invariant to check if you change this: Ruff's file scope should equal
`git ls-files "*.py"` plus `pyproject.toml`, which Ruff lints for schema
validity.

```bash
ruff check . --show-files   # the exact set Ruff considers
git ls-files "*.py"         # what it should be, plus pyproject.toml
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

The backend suite **collects 3029 tests** across sixty-nine modules.
**2988 run by default and pass**; the 41 live provider tests are *collected
and skipped* unless you opt in. They are skipped, not deselected — which is
why the collected total (3029) exceeds the number that run (2988):

| Module | Tests | Covers |
|--------|-------|--------|
| `test_health.py` | 16 | Root, liveness and versioned health endpoints; the database probe reachable and unreachable; the error envelope; a check that no secret appears in a response |
| `test_config.py` | 18 | Defaults, environment overrides, comma-separated list parsing, validation failures, production behaviour (including refusing the placeholder database password and a localhost-only CORS list), settings caching |
| `test_app_metadata.py` | 9 | App title/summary/version, the generated OpenAPI document, the application factory |
| `test_evaluation_api.py` | 13 | The evaluation endpoints through the real routes and PostgreSQL: the metric catalogue, the stateless error-rate scorer and its validation, evaluating, listing and re-evaluating a real run after a reference, appended corrections with history, caller turns refused, and 404s |
| `test_evaluation_evaluator.py` | 25 | The run evaluator: every verdict path on synthetic evidence (pass, bot failures, our faults undetermined, unfinished, phrases), pooled error rates, excluded failed transcriptions, nearest-rank latency, fingerprint reproducibility, and real text-bot runs evaluated from what they stored, re-evaluated, and re-scored after a reference is added |
| `test_evaluation_judge.py` | 17 | The LLM judge contract with the scripted client: strict parsing that rejects invented citations, unscored or duplicate criteria and uncited scores; bounded retries; non-retryable failures stop; the live gate recorded as no request sent; and the information boundary |
| `test_evaluation_metrics.py` | 25 | WER and CER on synthetic ground truth - perfect, partial, substitution, deletion, insertion, empty reference - a random cross-check against Levenshtein, code-mixed case, Indic numerals, dandas, nukta equivalence, ZWJ/ZWNJ, script mismatch and number words scored as errors, grapheme clusters, and that every metric documents itself |
| `test_evaluation_store.py` | 6 | The evaluation and reference tables against PostgreSQL: append-only history with the newest winning, the empty-text and verdict constraints, and cascades from turns and runs |
| `test_analytics.py` | 33 | Phase 12 reporting: the Wilson interval and Fisher's exact test against published values, CSV formula-injection neutralisation, and against PostgreSQL the pass rate over decided runs only, a re-evaluated run counted once, grouping, mixed evaluator versions flagged, pooled WER, regressions refused on small samples, day trends, CSV export, and run comparison and JSON/CSV export of real text-bot runs |
| `test_observability.py` | 16 | Phase 15 observability: `/metrics` off without a token, refusing a missing or wrong token, counting responses by method and status class, and rendering valid Prometheus text with the run gauge; a request id on every response and error, a safe caller id echoed and an unsafe one (too long, spaces, header injection, markup) replaced, log records carrying the current id, JSON log lines with the standard fields and structured extras, credentials redacted in message and extras, logging setup never removing another handler, and the format setting accepting only `text` or `json`
| `test_benchmark_gate.py` | 6 | The CI regression gate: every reference scenario run as a `text_bot_test` against the scripted reference bot and evaluated, compared with `benchmarks/baseline.json` so a worse verdict fails the build; the baseline matching `scenarios/` and containing passes worth guarding; a deliberately broken (refusing) bot tripping the gate on every baseline pass; and the comparison rules for worse, better, missing, new and unknown verdicts
| `test_hardening.py` | 14 | Phase 14 part 2 hardening: the sliding-window limiter (limit, window, independent keys, 0 disables), 429 with `Retry-After` on the API, liveness never limited, login limited per email across addresses and checked before the right password is verified, `X-Forwarded-For` ignored unless trusted, and the security headers on responses and errors, HSTS only when deployed, no API CSP on the docs, `no-store` on auth
| `test_streaming_voice.py` | 17 | Phase 9 streaming voice: framing and levels, latency from caller end to first voiced frame, end-of-turn silence, silence timeout, the deadline and barge-in on a simulated clock; then the `ws_voice` adapter against the reference bot over a real socket in real time - a prompt answer with measured latency, one socket across turns, end-pointing without a signal, a barge-in making the caller yield, a silent bot timing out with no audio, an endless bot cut off at the deadline, a wrong token and an off-allowlist host refused, no token in errors - and a whole `external_bot_test` run recording per-turn streaming evidence and a silent bot turn, with fixture mode refusing an external voice bot
| `test_background_runs.py` | 8 | Phase 9 background execution: a run started with `background=true` answers 202 and completes after its request, a crash closes the run as `failed`/`abandoned` by the background worker with a redacted reason, a finished run and a run with no free slot are refused before the 202 with nothing started, the recovery sweep closing runs whose worker died while leaving recent and protected runs alone, a zero interval starting no loop, and the app never sweeping with the global settings
| `test_telephony_calls.py` | 16 | Phase 8 telephony with the mock provider against PostgreSQL and the real webhook: a placed call stored masked and labelled mocked with the caller namespace untouched, placing alone setting no status, an off-list number refused before the provider is contacted, concurrent, per-run and per-day limits, signed events driving each of four outcomes through the call and its conversation (`DIALING` first, `BUSY`/`NO_ANSWER` only from events), unsigned, wrong-secret and tampered events changing nothing, duplicates and stale events recorded but not applied, unknown providers and calls 404, the webhook absent with telephony off, oversized events refused, calls deleted with their run, and an invalid allowlist failing at startup
| `test_telephony_core.py` | 44 | Phase 8 telephony core, offline: E.164 normalisation and refusal, masking, every guardrail refusing before dialling and never naming the full number, an empty allowlist allowing nothing, webhook signatures refusing edits, missing headers, bad timestamps, replays and an unconfigured secret, every provider status mapped and calls only moving forward, `telephony_test` still unimplemented, the mock labelled mocked with four scripted outcomes and strict event parsing, and the registry refusing the mock in production and any provider that does not exist
| `test_signed_links.py` | 18 | Phase 10 signed audio links: the HMAC primitive verifying a fresh link and refusing any edit to variant, expiry, user or signature, another path, expiry, a rotated secret, an over-long lifetime and malformed values; and through the API, a link opening one turn's audio or the recording with no session, refusing to be pointed at another turn or tampered with, revoked when its minter leaves the workspace, unmintable by an outsider or for audio that does not exist, and capped at fifteen minutes
| `test_retention.py` | 14 | Phase 10 deletion and retention: deleting a finished run through the API removes its row, conversation, turns, evaluations and every audio file including the recording while the suite and scenario survive; a run in flight is 409; a member is 403 and an outsider 404; the protected historical runs are never deleted; and `runs purge` through the real CLI lists without changing anything by default, deletes only expired finished runs with `--apply`, falls back to `RETENTION_DAYS`, refuses to run without a period, accepts whole days only, and never lists the protected runs
| `test_recording.py` | 8 | Phase 10 full-conversation recordings: turns concatenated in order with correct offsets across sample rates and channel counts, the degraded caller variant chosen as what was on the line, undecodable or missing turns excluded with a reason rather than filled with silence, no audio when nothing decodes; and through the API, a finished audio run storing a recording whose segments link to its turn artefacts and whose WAV duration matches the manifest, `not_applicable` for a run with no audio, 404 before a run finishes, and the recording removed with its conversation's artefacts
| `test_storage.py` | 31 | Phase 10 blob storage: key validation (absolute, `..`, empty segments, backslash, NUL, length), the local adapter's round trip, overwrite, idempotent delete, prefix deletion that touches nothing else, atomic writes that leave neither a partial object nor a temporary file, a symlink out of the root refused (skipped on Windows, which needs elevation to create one; runs in CI), the registry and settings refusing a backend that does not exist, and the artefact store writing, reading and deleting a conversation through it
| `test_access_control.py` | 26 | Phase 14 authorisation swept across the generated OpenAPI document: every operation outside the public allowlist 401 without a credential; on real suites, scenarios, runs, conversations and evaluations, every resource route 404 to an outsider (identical to a missing id), a viewer's reads matching the owner's and every write 403, members unable to delete; listings, aggregates and CSV export empty for an outsider and a foreign `suite_id` filter 404; runs and conversations unable to borrow another tenant's scenario; project inference for new suites; per-project suite names; project deletion refused while non-empty; the WebSocket handshake refused with 1008 without a credential or from a foreign origin; and the migration moving pre-tenancy suites into a member-less `legacy` workspace and rolling back without losing them
| `test_workspaces_api.py` | 26 | Phase 14 workspaces, members and projects through the real routes: authentication on every route, the creator owning a new workspace and its `Default` project, only the caller's workspaces listed, a foreign workspace or project 404 rather than 403, the full add-member matrix by role, admins unable to touch owners or other admins or promote to admin, the last owner kept, leaving, project creation by role, unique names, and rename/describe
| `test_auth_api.py` | 41 | Phase 14 authentication through the real routes and PostgreSQL: bearer and cookie login (HttpOnly, SameSite=Strict, no token in the body, Secure when deployed), every login failure the same 401, lockout refusing even the right password, hash upgrade on login, digest-only storage, logout, absolute/idle/revoked expiry, deactivation, throttled activity writes, cross-origin cookie writes refused, password change revoking other sessions, sign-up off by default, no password echoed in a 422 or written to a log, and the `users create` CLI with its exit codes and no password argument
| `test_auth_primitives.py` | 41 | Phase 14 identity primitives: scrypt hashing round-trip, salting, an independent recomputation against `hashlib.scrypt`, malformed and oversized input verifying false, rehash detection and the length-based password policy; token shape and uniqueness; the role matrix monotone by rank and assignment never above the actor; and against PostgreSQL the lower-case unique email, digest-only session tokens, the role CHECK, slug format, per-workspace project names, cascades from a user and RESTRICT from a workspace |
| `test_outbound.py` | 36 | The outbound-request guard: scheme and userinfo rules, the host allowlist and its wildcards, metadata/link-local/private/loopback address rules including IPv4-mapped IPv6 and decimal literals, and plain http only to loopback |
| `test_reference_bot.py` | 28 | The reference text bot over a real localhost socket: the full session lifecycle, bearer authentication, the error envelope, idempotent retries, correlation echo, session capacity and expiry, and reply-script validation |
| `test_scenario_spec.py` | 107 | YAML syntax, unsafe payloads, recursive/cyclic aliases, size and expansion limits, every validation rule, round-trip serialisation, file loading |
| `test_database.py` | 37 | Connection, the migrated schema, model creation, relationships, foreign-key delete behaviour, every constraint, transaction rollback |
| `test_api_suites_scenarios.py` | 63 | The Phase 2 endpoints, pagination, duplicates, unknown ids, malformed UUIDs, oversized bodies, error-envelope shape |
| `test_languages.py` | 89 | Catalogue invariants (unique codes and locales, endonym scripts), tag shape and membership rejection, and that the schema and the API read from this one source |
| `test_bundle.py` | 39 | Bundle parsing and building: per-entry error collection, duplicate rejection, the 500-entry cap, byte-identical round-trips, no ids or timestamps in output |
| `test_api_library.py` | 74 | Search, filters, pagination and ordering; suite `PATCH` and guarded `DELETE`; copy and move; import dry-run and atomicity; export round-trip |
| `test_database_gate.py` | 16 | `BHASHABENCH_REQUIRE_DATABASE`: an unreachable test database skips by default and fails when required - including a real pytest subprocess against a closed port |
| `test_pipeline_recovery.py` | 20 | `bhashabench runs recover-stale` through the real Typer app: eligibility, the dry-run default, the timeout floor, `--apply` closing a stuck run as status `failed`, outcome `abandoned`, without deleting turns, events or artefacts, and the two protected historical runs staying excluded and unchanged with or without `--apply` |
| `test_cli.py` | 65 | Argument parsing, exit codes and output for every command through Typer's `CliRunner`, plus that no connection string reaches the terminal on a database outage |
| `test_reference_scenarios.py` | 40 | Every committed scenario in `scenarios/` validates and round-trips, the set covers six languages and the documented audio and code-mixing cases, and the generated bundle is not stale |
| `test_demo_scenario.py` | 7 | The recorded demo's scenario file: it validates, its facts and marking criteria are unchanged, and its spoken Tamil opening passes caller validation, is deterministic and contains no English beyond the declared code-mixed terms |
| `test_tooling.py` | 10 | That the host and container pytest configurations enforce the same things, so the second run corroborates the first instead of decorating it, and that no provider credential exported in the shell reaches an offline test |
| `test_transcription_core.py` | 112 | Audio format detection from content, WAV header parsing, size/duration/channel limits, filename safety, the retry policy's arithmetic and what it refuses to retry, the provider registry |
| `test_transcription_prisma.py` | 81 | The Gnani Prisma adapter against its published contract: request shape, every documented status, response normalisation, malformed responses, language and mode mapping |
| `test_transcription_api.py` | 93 | The service layer and the real FastAPI routes - batch upload, provider capabilities, the WebSocket lifecycle, error-to-status mapping, structured logging |
| `test_transcription_security.py` | 57 | Credential redaction (including BhashaBench `bbs_` session tokens anywhere in a message), no secret in a response/log/stream frame, path traversal, capped uploads, temp-file cleanup, repository hygiene |
| `test_transcription_streaming.py` | 38 | Prisma's WebSocket protocol: 1024-byte framing, event mapping, ordering, malformed frames, cancellation, bounded buffering |
| `test_audio_fixtures.py` | 19 | The committed fixtures still match their generator byte for byte, and still claim no speech and no expected transcript |
| `test_transcription_live.py` | 15 | **Opt-in, billable.** Real Gnani Prisma calls. Skipped unless `TRANSCRIPTION_LIVE_TESTS=true` *and* `GNANI_API_KEY` are both set |
| `test_speech_timbre.py` | 132 | The Gnani Timbre adapter against its published contract: JSON body, every documented status and both error shapes, binary-response handling, the streaming WAV header, serialisation, client ownership |
| `test_speech_core.py` | 121 | The Timbre contract constants, voice catalogue, domain models, registry and service rules - including that a tag the model ignores is refused rather than spoken aloud |
| `test_speech_api.py` | 77 | The real FastAPI speech routes: binary response and its media types, `X-Speech-*` headers, error mapping, provider capabilities, cleanup on every exit path, security |
| `test_caller_core.py` | 73 | The caller state machine, the transcript analyser (Indic digits, code-switched keywords), the decision schema and the provider registry |
| `test_caller_rules.py` | 155 | Every rule of the deterministic caller; that five different bot replies produce five different turns; a legality sweep of every state against every shape of reply |
| `test_caller_service.py` | 34 | Decision validation, instruction-leak and invented-identifier rejection, synthesis, credential redaction in an error |
| `test_caller_orchestrator.py` | 39 | Multi-turn conversations against real PostgreSQL: success, every failure reason, determinism, persistence, transcription failure, audio artefacts |
| `test_caller_api.py` | 44 | The caller routes through `TestClient`: creation, turns, text and audio submission, termination, limits, prompt injection, OpenAPI |
| `test_pipeline_degradation.py` | 87 | The DSP: resampling, channel conversion, bandpass, noise at a measured SNR, clipping, packet loss, every profile, reproducibility from a seed |
| `test_pipeline_bots.py` | 43 | The bot adapter protocol, both adapters and the registry - including that neither contacts anything and the default sends audio nowhere - and the offline text-reply fixture loader |
| `test_pipeline_http_bot.py` | 31 | The HTTP text bot adapter over real localhost sockets: a whole conversation with the reference bot, wrong credentials, concurrent sessions, bounded and idempotent retries, malformed and oversized replies, timeouts, redirects not followed, path-segment escaping, unreachable and disallowed hosts, SSRF and rebinding refusals, and that the token reaches no log or error |
| `test_pipeline_text_bot.py` | 12 | `text_bot_test` end to end against real PostgreSQL and the reference bot on a real socket: a goal-achieving conversation, per-turn provenance, unreachable and credential-refused bots, a bot that hangs up early, mode/adapter mismatches refused, and the same run through the real API with no engine override |
| `test_pipeline_engine.py` | 72 | Multi-turn audio runs against real PostgreSQL: the full workflow, every failure path, cancellation, the manual flow, reproducibility, declared scenario audio measured from the stored bytes (achieved SNR, realised packet loss, operator precedence), and settings declared but not enforced |
| `test_pipeline_api.py` | 111 | The test-run operations, plus the run's recorded bot adapter honoured on every route and offline simulation reaching a terminal state (text fixture, manual `/bot-text`): creation, execution, artefacts, reports, bot-audio submission, cancellation, path-traversal rejection, the 503 at the concurrency limit, OpenAPI, plus the Phase 8 run listing (filters, pagination window, ILIKE wildcard escape, caller-only exclusion) and artefact audio (range handling, traversal through the turn index, served to an authorised viewer in every environment and refused without a credential) |
| `test_pipeline_fixture_audio.py` | 9 | The fixture audio an API-started scripted run replays: the file read and repeated per turn, a missing/empty/directory path refused, the real engine factory wiring it to the scripted adapter, the reply still marked as not received from a bot, and the unset setting leaving the turn-0 failure intact |
| `test_pipeline_concurrency.py` | 41 | The admission limiter: the configured maximum is never exceeded, capacity frees up for the next run, and exceptions, cancellation and timeouts all release it |
| `test_pipeline_conditions.py` | 33 | Jitter, dropouts, truncation, silence padding and measured gain, each alone and combined: achieved values measured from the bytes, shortfalls noted, seeded reproducibility, range validation, fixed order, and the original never modified |
| `test_pipeline_declared_conditions.py` | 20 | Channel conditions declared by a scenario or overridden per run, applied in real audio runs against PostgreSQL: per-field operator precedence and recorded sources, achieved values on each artefact, truncation, a disabled stage reported as not enforced, end-to-end reproducibility, and bounds |
| `test_speech_live.py` | 26 | **Opt-in, billable.** Real Gnani Timbre calls. Skipped unless `SPEECH_LIVE_TESTS=true` *and* `GNANI_API_KEY` are both set |
| `test_caller_llm_contract.py` | 84 | The provider-independent LLM caller contract, offline: the prompt is built from the caller context alone (no expected outcomes, rubric or accounting), the states offered to a model are a subset of the transition table, a reply is parsed strictly and then meets the same validation gate as the rule engine, and cost arithmetic never treats an unknown price or unknown usage as zero |
| `test_caller_llm_provider.py` | 53 | The model-backed caller strategy driven by a scripted client, with no network: a generated turn and its evidence, bounded retry across every kind of failure, deterministic fallback with the reason recorded and never reported as model-generated, per-turn token and per-run cost limits judged on the worst case, unknown usage charged not zeroed, and the scripted client being unselectable by configuration |
| `test_caller_llm_conversation.py` | 21 | Whole model-backed conversations against PostgreSQL with a scripted client: per-turn generation evidence is persisted, uses_language_model is derived from the turns that were actually generated (false before any turn and for an all-fallback conversation, sticky after one generated turn), the per-run cost limit holds across turns, the scenario's expected outcomes appear in no request, turn record or log line, and the run list and the caller API carry the derived value |
| `test_caller_llm_budget.py` | 38 | The live-spending controls, offline: live language-model calls are unauthorised in code and no configuration value opens the gate, the 100-rupee ceiling can be lowered and never raised, a request's worst case is reserved in a durable ledger before it is sent and settled to reported usage afterwards, an unknown cost stays charged, and an unreadable or locked ledger refuses rather than reading as zero |
| `test_caller_llm_sarvam.py` | 139 | The Sarvam client for both `sarvam-105b` and `sarvam-105b-conversations`, against a mock transport with **no request to Sarvam**: as shipped nothing is sent whatever the configuration and the caller falls back with `live_calls_disabled`; with the gate opened inside the test only, the documented request shape (key header, explicit model, temperature and output limit, reasoning disabled on one model and never mentioned to the other, seed, structured output), response and usage parsing without invented values, every documented status mapped to one normalised error, quota never retried as throttling, no credential in errors, logs, settings dumps or the ledger, cost from reported usage or the worst case, and the budget refusing before a request is sent; plus the settings and registry rules |

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
================ 2988 passed, 41 skipped ================
```

pytest is configured in `pyproject.toml` with `filterwarnings = ["error"]`,
so a new deprecation warning fails the build rather than accumulating
silently.

### Continuous integration

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push to
`main` and every pull request against it, in three independent jobs:

| Job | Checks |
|---|---|
| `backend` | Python 3.12, a PostgreSQL 16 service, `ruff check`, `ruff format --check`, `alembic upgrade head`, `alembic check`, then `pytest` with `BHASHABENCH_REQUIRE_DATABASE=1` |
| `frontend` | Node 22, `npm ci`, `npm run typecheck`, `npm run lint`, `npm run build` |
| `compose` | `docker compose config --quiet` against the placeholders in `.env.example` |

`BHASHABENCH_REQUIRE_DATABASE=1` turns an unreachable test database into a
failure instead of a skip, so a broken database service cannot pass CI with
the database tests quietly skipped. CI reads no secrets, and the live Gnani
suites stay off.

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
bhashabench runs recover-stale --older-than 24h          # dry run; --apply closes as failed/abandoned
```

Exit codes are distinguished so a shell script can act on them: `0` success,
`1` the operation failed (not found, conflict, refused), `2` invalid input,
`3` the database is unreachable. Every command takes `--json`.

Full reference: [`docs/CLI.md`](docs/CLI.md).

---

## API endpoints

The API exposes **62 paths and 79 HTTP operations**, plus one WebSocket route
that OpenAPI 3.1 cannot describe (`/api/v1/transcription/stream`), for 63
documented paths in total.

Those figures come from the generated OpenAPI document, never from a hand
count and never from walking `app.routes` — the installed FastAPI mounts
included routers lazily, so that walk sees only the routes declared directly
on `app` and wrongly reads as "the v1 API is not mounted". Recompute them with:

```bash
python scripts/api_surface.py          # paths, operations and the full table
python scripts/api_surface.py --json   # same, machine-readable
```

### Meta and health

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/` | Product name, tagline, version, environment, docs path |
| `GET` | `/health` | `{"status": "ok", "version": "0.1.0"}` — cheap liveness probe |
| `GET` | `/api/v1/health` | Per-subsystem health, uptime and a UTC timestamp |
| `GET` | `/api/v1/languages` | The 13 supported languages with endonym, script and locale |

### Authentication

See [docs/AUTH.md](docs/AUTH.md).

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/api/v1/auth/signup` | 201 with the new user and their own workspace. 403 unless `AUTH_ALLOW_SIGNUP=true` |
| `POST` | `/api/v1/auth/login` | Signs in. `session_type=cookie` (default) sets an HttpOnly, SameSite=Strict cookie and returns no token; `bearer` returns the token once. Every failure is the same 401 |
| `POST` | `/api/v1/auth/logout` | 204; revokes the session and clears the cookie |
| `GET` | `/api/v1/auth/me` | The signed-in user, their workspaces and roles, and the session's expiry |
| `POST` | `/api/v1/auth/password` | Changes the password and revokes every other session |

### Workspaces, members and projects

A workspace the caller is not a member of answers 404. Roles and rules: [docs/AUTH.md](docs/AUTH.md).

| Method | Path | Returns |
|--------|------|---------|
| `GET` / `POST` | `/api/v1/workspaces` | The caller's workspaces with their role / create one (caller becomes owner; a `Default` project is created) |
| `GET` | `/api/v1/workspaces/{id}` | One workspace |
| `GET` / `POST` | `/api/v1/workspaces/{id}/members` | Members and roles / add an existing account by email (admin or owner) |
| `PATCH` / `DELETE` | `/api/v1/workspaces/{id}/members/{user_id}` | Change a role / remove a member or leave. The last owner is kept (409) |
| `GET` / `POST` | `/api/v1/workspaces/{id}/projects` | Projects / create one (admin or owner) |
| `GET` / `PATCH` / `DELETE` | `/api/v1/projects/{id}` | One project / rename or describe it / delete it while empty (admin or owner) |

### Telephony (mocked provider only)

No route places a call: no run mode can use one. See [docs/TELEPHONY.md](docs/TELEPHONY.md).

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/api/v1/telephony/events/{provider}` | A signed call-status event from the configured provider (no session; the signature is the credential). 401 unsigned or tampered, 404 unknown provider or call, `applied: false` for duplicates and stale events |
| `GET` | `/api/v1/test-runs/{id}/telephony/calls` | A run's calls with provider, `mocked`, masked number, status and every event as received |

### Test suites

Every route below needs a session; a suite in a workspace you are not in is
404. Roles and the full enforcement table: [docs/AUTH.md](docs/AUTH.md).

| Method | Path | Returns |
|--------|------|---------|
| `POST` | `/api/v1/suites` | 201 with the created suite in `project_id` (inferred only when you can edit exactly one project). 409 if the name is taken in that project |
| `GET` | `/api/v1/suites` | Paginated list of the suites you can see, newest first (`limit`, `offset`, `project_id`) |
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
| `GET` | `/api/v1/test-runs` | Paginated run history, newest first. Filters on `suite_id`, `status`, `mode`, `language`, `outcome` and `scenario`. Only runs the pipeline created are listed; a caller-only conversation records no pipeline metadata and stays addressable through `/api/v1/caller` |
| `POST` | `/api/v1/test-runs/{id}/start` | Runs turns until terminal, or until the run needs audio from outside. A run left `running` with `awaiting_bot_audio_for_turn` is waiting, not failed |
| `POST` | `/api/v1/test-runs/{id}/bot-audio` | Supplies the bot's reply as audio; it is validated, transcribed and the run continues |
| `POST` | `/api/v1/test-runs/{id}/bot-text` | Supplies the bot's reply as text for an offline run with the manual adapter; the run continues |
| `POST` | `/api/v1/test-runs/{id}/cancel` | Stops a run. Outcome `cancelled`, never `failed` - an operator's decision is not a finding about the bot |
| `GET` | `/api/v1/test-runs/{id}` | State, counters and outcome |
| `GET` | `/api/v1/test-runs/{id}/turns` | Every utterance of the run's conversation |
| `GET` | `/api/v1/test-runs/{id}/artifacts` | Audio references and measured metadata. A degraded artefact names the original it came from |
| `GET` | `/api/v1/test-runs/{id}/artifacts/{turn_index}/audio` | The stored audio for one turn (`?variant=original\|processed`), with single-range `bytes=` support so a player can seek. Needs the viewer role in the run's workspace, or a signed link from `POST .../audio-links` |
| `POST` | `/api/v1/test-runs/{id}/audio-links` | A signed link, valid at most 15 minutes, that opens one turn's audio (or the recording) without a session. Bound to that file and to its minter, whose access is re-checked on every use. See [docs/STORAGE.md](docs/STORAGE.md) |
| `DELETE` | `/api/v1/test-runs/{id}` | Deletes a finished run, its evidence and every stored audio file (admin or owner). 409 while in flight or for a protected historical run. Not reversible |
| `GET` | `/api/v1/test-runs/{id}/recording` | The full-conversation recording's manifest: status, duration, and each segment linked to its turn artefact. Assembled after the run, no silence inserted. See [docs/STORAGE.md](docs/STORAGE.md) |
| `GET` | `/api/v1/test-runs/{id}/recording/audio` | The recording itself, 16-bit mono WAV, with `Range` support. Same access rules as turn audio |
| `GET` | `/api/v1/test-runs/{id}/report` | Full evidence: state, artefacts, caller state transitions and every stage with its measured duration. Measurements, not scores |
| `GET` | `/api/v1/test-runs/bot-adapters/available` | Bot adapters with their capabilities and whether each is configured, plus the execution modes a run may use |
| `POST` | `/api/v1/test-runs/{id}/evaluations` | Evaluates the run from its stored evidence and appends the result: a `pass` / `fail` / `undetermined` verdict with per-criterion reasons, and every metric with its working. See [docs/EVALUATION.md](docs/EVALUATION.md) |
| `GET` | `/api/v1/test-runs/{id}/evaluations` | Every evaluation of the run, newest first |
| `POST` | `/api/v1/test-runs/{id}/turns/{turn_index}/reference` | Records a reviewed reference transcript for a bot turn - the ground truth WER and CER need. Append-only; 409 for a caller turn |
| `GET` | `/api/v1/test-runs/{id}/turns/{turn_index}/reference` | A bot turn's references, oldest first; the last is used |
| `GET` | `/api/v1/evaluation/metrics` | Every metric's definition, formula, evidence, direction, missing-data rule and limitations. `composite_score` is always null |
| `POST` | `/api/v1/evaluation/error-rate` | WER and CER of a hypothesis against a reference, with the full breakdown. Stores nothing |
| `GET` | `/api/v1/analytics/summary` | Verdict counts and pass rate (pass / (pass + fail), Wilson 95% interval), pooled WER and per-run latency distribution, optionally `group_by` language, scenario, adapter, mode, outcome or suite. See [docs/REPORTING.md](docs/REPORTING.md) |
| `GET` | `/api/v1/analytics/compare` | Two evaluated runs side by side with per-metric deltas and comparability warnings. 409 if either is unevaluated; makes no statistical claim |
| `GET` | `/api/v1/analytics/regressions` | Pass-rate regression between `baseline_*` and `candidate_*` groups by Fisher's exact test; `insufficient_evidence` below five decided runs a side |
| `GET` | `/api/v1/analytics/trend` | Verdict counts and pass rate per day or week |
| `GET` | `/api/v1/analytics/runs.csv` | Runs with their latest verdict and key metrics as CSV, cells neutralised against formula injection |
| `GET` | `/api/v1/test-runs/{id}/export` | One run's metadata, turns, references and latest evaluation as JSON (default) or per-turn CSV |
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
| 0 | Baseline & defect remediation | ✅ Complete |
| 1 | Project foundation | ✅ Complete |
| 2 | Database & scenario engine | ✅ Complete |
| 3 | Scenario library & tooling | ✅ Complete |
| 4 | Speech to text (Gnani Prisma) | ✅ Complete (batch live-verified; streaming not live-verified) |
| 5 | Text to speech (Gnani Timbre) | ✅ Complete (batch; streaming not implemented) |
| 6 | AI caller simulation — Evon | 🟡 Partial — rule engine delivered; Sarvam LLM caller implemented and tested offline, live calls not authorised or verified; Evon blocked |
| 7 | Audio degradation engine | ✅ Complete (synthetic noise; no recorded noise beds) |
| 8 | Telephony integration | 🟡 Partial — provider abstraction, guardrails, signed webhooks and a mocked provider; no real call placed or authorised |
| 9 | Real-time conversation engine | ✅ Complete (streaming turn-taking and recovery verified against the reference bot; STT/TTS still per utterance; energy VAD) |
| 10 | Recording & transcription | ✅ Complete (local filesystem storage; recordings assembled from turn audio, not captured live) |
| 11 | Evaluation & judge engine | ✅ Complete (deterministic; LLM judge offline-only, not validated against human labels) |
| 12 | Reporting & analytics backend | ✅ Complete (comparison, regression, aggregates, export; signed artefact URLs moved to Phase 10; no PDF) |
| 13 | Frontend dashboard | ✅ Complete (analytics, comparison, workspace, authoring and live run views on the real API; lib/ unit-tested, components not) |
| 14 | CI/CD & safety | ✅ Complete (auth, tenancy, rate limits, headers, dependency and secret scanning, regression gate; no nightly run) |
| 15 | Production readiness & competition demo | 🟡 Partial — production images, compose, startup refusals, backup/restore (rehearsed locally) and a priced plan; not deployed, no week unattended |

> This is the **original** 15-phase numbering, restored after the competition.
> The competition renumbered phases in flight; the roadmap's mapping table
> translates between the two. This table is the same one in
> [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md) and
> [`CLAUDE.md`](CLAUDE.md) — all three must agree.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch naming, commit message
conventions, testing expectations and the main-only commit workflow.

## License

MIT.
