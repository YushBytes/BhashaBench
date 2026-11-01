# Phase 1 — Project Foundation: Completion Report

| | |
|---|---|
| **Phase** | 1 of 15 — Project Foundation |
| **Date** | 2026-11-01 |
| **Repository** | `C:\Users\ayush\OneDrive\Desktop\BhashaBench` |
| **Branch** | `feature/phase-01-foundation` |
| **Commits** | 6 |
| **Tracked files** | 60 |
| **Status** | Complete, with two environment-caused verification gaps recorded in [Known limitations](#known-limitations) |

---

## 1. Summary of implementation

Phase 1 establishes a monorepo that runs, lints, tests and builds, so later
phases add features rather than plumbing. Delivered:

- **Backend** — A modular FastAPI application with three working endpoints,
  environment-based configuration with validation, a uniform JSON error
  envelope, OpenAPI documentation and full type annotations. 35 tests pass.
- **Frontend** — A Next.js 16 App Router application (TypeScript, Tailwind
  CSS v4, ESLint) presenting a dark-committed status shell: product identity,
  the real phase position, the planned test-suite capabilities labelled by
  phase, and the endpoints that actually respond. Lint, typecheck and
  production build all pass.
- **Infrastructure** — Multi-stage Dockerfiles for both services and a
  Compose stack with PostgreSQL 16, health checks, dependency ordering and a
  persistent volume. No credential is committed.
- **Quality tooling** — Ruff (lint + format) and pytest configured in
  `pyproject.toml`, with `filterwarnings = ["error"]` so new deprecations
  fail the build.
- **Documentation** — README, architecture document, 15-phase roadmap and
  contributing guide, each stating up front that only Phase 1 exists.

The organising principle throughout was **not to overstate what works.**
`GET /api/v1/health` deliberately returns an aggregate of `degraded`, because
its `database` component honestly reports that no connection is attempted in
this phase. The frontend renders no analytics, charts or sample results.

---

## 2. Files created

### Repository root

| File | Purpose |
|------|---------|
| `.gitignore` | Excludes secrets, Python/Node artefacts, runtime audio, editor files |
| `.gitattributes` | Pins LF for files consumed by Linux containers |
| `.dockerignore` | Keeps `.env`, virtualenvs, `node_modules` and caches out of build contexts |
| `.env.example` | Full configuration surface, documented, with no real values |
| `pyproject.toml` | Ruff and pytest configuration |
| `docker-compose.yml` | backend + frontend + PostgreSQL development stack |
| `README.md` | Overview, problem statement, setup, commands, testing, roadmap |
| `CONTRIBUTING.md` | Branches, commit conventions, code standards, PR process |
| `PHASE_COMPLETION_REPORT.md` | This report |

### Backend — 18 files

| File | Purpose |
|------|---------|
| `backend/app/__init__.py` | Package marker and `__version__` |
| `backend/app/main.py` | App factory, exception handlers, lifespan, root and liveness routes |
| `backend/app/core/__init__.py` | Cross-cutting concerns package |
| `backend/app/core/config.py` | `Settings` via pydantic-settings, `AppEnv`, validators, `get_settings()` |
| `backend/app/api/__init__.py` | HTTP layer package |
| `backend/app/api/deps.py` | Injectable `SettingsDep` |
| `backend/app/api/v1/__init__.py` | v1 API package |
| `backend/app/api/v1/health.py` | `GET /api/v1/health` |
| `backend/app/api/v1/router.py` | Aggregating v1 router |
| `backend/app/models/__init__.py` | Database models — intentionally empty until Phase 2 |
| `backend/app/schemas/__init__.py` | Schemas package |
| `backend/app/schemas/common.py` | `ServiceIdentity`, `HealthResponse`, `ApiHealthResponse`, `ComponentHealth`, `ErrorResponse`, `ErrorDetail` |
| `backend/app/services/__init__.py` | Service layer package |
| `backend/app/services/health.py` | Health aggregation and uptime |
| `backend/app/utils/__init__.py` | Helpers package |
| `backend/app/utils/timing.py` | `utc_now()`, `monotonic_seconds()` |
| `backend/requirements.txt` | Runtime dependencies |
| `backend/requirements-dev.txt` | Test and lint dependencies |
| `backend/Dockerfile` | Multi-stage: `base` → `development` / `production` |

### Backend tests — 4 files, 35 tests

| File | Tests | Covers |
|------|-------|--------|
| `backend/tests/__init__.py` | — | Package marker |
| `backend/tests/conftest.py` | — | `settings`, `test_app`, `client` fixtures |
| `backend/tests/test_health.py` | 12 | Root, liveness and API health endpoints; error envelope; secret-leak check |
| `backend/tests/test_config.py` | 14 | Defaults, env overrides, validation, production behaviour, caching |
| `backend/tests/test_app_metadata.py` | 9 | App metadata, OpenAPI document, application factory |

### Frontend — 12 authored files

| File | Purpose |
|------|---------|
| `frontend/app/layout.tsx` | Root layout, metadata, fonts, header/footer composition |
| `frontend/app/page.tsx` | Landing page: hero, capabilities, endpoint table, roadmap |
| `frontend/app/globals.css` | Design tokens, Tailwind `@theme` mapping, focus ring, reduced motion |
| `frontend/components/site-header.tsx` | Sticky navigation with waveform wordmark |
| `frontend/components/site-footer.tsx` | Footer with phase and version |
| `frontend/components/section.tsx` | Reusable titled section |
| `frontend/components/status-pill.tsx` | `live` / `partial` / `planned` chip |
| `frontend/components/capability-card.tsx` | Planned capability, labelled with its phase |
| `frontend/components/roadmap-list.tsx` | All 15 phases with honest status |
| `frontend/lib/content.ts` | Typed product copy, phases, capabilities, endpoints |
| `frontend/Dockerfile` | Multi-stage: `base` → `development` / `builder` / `production` |
| `frontend/.dockerignore` | Frontend build-context exclusions |

Generated by `create-next-app` and retained: `package.json` (edited),
`package-lock.json`, `tsconfig.json`, `next.config.ts`, `eslint.config.mjs`,
`.gitignore`, `AGENTS.md`, `app/favicon.ico`.

### Documentation and placeholders

`docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_ROADMAP.md`, and `.gitkeep` files in
`scenarios/`, `benchmarks/`, `sample_bot/`, `scripts/`, `.github/workflows/`
and `frontend/public/`.

### Files modified

`frontend/app/layout.tsx`, `frontend/app/page.tsx`,
`frontend/app/globals.css` and `frontend/package.json` were replaced or edited
after scaffolding. The default `create-next-app` SVG assets and boilerplate
`README.md` were deleted. **No pre-existing user file was modified or
overwritten** — the project directory was empty at the start.

---

## 3. Architecture decisions

| # | Decision | Reasoning |
|---|----------|-----------|
| 1 | **Dedicated git repository inside the project directory** | The working directory was inside a stray repository rooted at `C:\Users\ayush\OneDrive\Desktop`, which had no commits and ~100 untracked personal files (resumes, PDFs, coursework). Committing from there risked publishing personal documents. A repository scoped to the project is isolated and safe. See [Known limitations](#known-limitations). |
| 2 | **Application factory `create_app(settings)`** | Lets tests build an app against arbitrary settings without mutating globals. The module-level `app` is what Uvicorn imports. |
| 3 | **Versioned router package `api/v1/`** | The phase requires versioned routing. A version sub-package with its own aggregating `router.py` means adding an endpoint touches no application setup, and a future `v2` is purely additive. |
| 4 | **Settings injected as a dependency** | Handlers receive `Settings` through `SettingsDep` rather than importing a global, so tests override it with `dependency_overrides`. `get_settings()` is `lru_cache`d so `.env` parses once. |
| 5 | **Uniform error envelope** | Three handlers (`HTTPException`, `RequestValidationError`, bare `Exception`) emit one `{"error": {...}}` shape, so clients parse one structure. Unexpected exceptions are logged server-side and never leak internals. |
| 6 | **Health reports `degraded`, not `ok`** | The `database` component states it is not probed, and the aggregate follows the worst component. A green tick the system cannot justify is worse than no tick. Phase 2 replaces the branch with a real `SELECT 1`. |
| 7 | **No credentials in health output** | `describe_environment()` returns only `present`/`absent` and `configured`/`default`, never a value. A test asserts no secret appears in a response body. |
| 8 | **Settings model only what Phase 1 reads** | `.env.example` documents the full surface including future variables, but only the variables actually consumed are `Settings` fields. A field nothing reads is dead code, and the request shapes the Gnani and Twilio integrations need are not yet known. `extra="ignore"` keeps a complete `.env` from breaking startup. |
| 9 | **Fail fast on misconfiguration** | Settings resolve during the lifespan startup hook, so a bad `APP_ENV` or a placeholder `SECRET_KEY` in staging/production stops the boot rather than surfacing on first request. OpenAPI docs are disabled when `APP_ENV=production`. |
| 10 | **Frontend content as typed constants** | The endpoints that would serve roadmap and capability data do not exist until Phase 12. Writing a client for them would be a fake integration, so `lib/content.ts` holds typed constants and Phase 13 replaces it. |
| 11 | **Committed dark theme, not system-following** | A developer tool that sits beside a terminal; one palette keeps the `live`/`partial`/`planned` status colours unambiguous. |
| 12 | **Multi-stage Dockerfiles, non-root users** | Dependencies install before application code so the slow layer caches across code-only changes; the production target carries no pytest or Ruff; both runtime targets drop to a non-root user. |
| 13 | **Python 3.12 pinned in the container** | The local interpreter is 3.14.6, but the project targets 3.12 (`requires-python`, Ruff `target-version`). Pinning the image keeps the container matched to CI. |
| 14 | **`uvicorn` without the `[standard]` extra** | Those extras (`httptools`, `uvloop`, `watchfiles`) ship no wheels for the newest CPython and fall back to compiling from source, which hung a plain `pip install` on this machine for over five minutes. Plain Uvicorn serves correctly; `--reload` degrades to polling. Documented in `requirements.txt`. |
| 15 | **`httpx2` rather than `httpx` for tests** | Starlette 1.10 raises `StarletteDeprecationWarning` when `TestClient` is used with the older `httpx`, which `filterwarnings = ["error"]` turns into a failure. |
| 16 | **`NoDecode` on `cors_origins`** | pydantic-settings JSON-decodes list-typed fields before validators run, so a comma-separated environment value raised `SettingsError`. `Annotated[list[str], NoDecode]` defers parsing to the field validator. |
| 17 | **Configurable Compose host ports** | Port 5432 was already bound on this machine by another project's PostgreSQL container, which makes `docker compose up` fail with an opaque port-conflict error. `POSTGRES_HOST_PORT`, `BACKEND_HOST_PORT` and `FRONTEND_HOST_PORT` default to the conventional ports; in-container ports are unchanged. |
| 18 | **`.gitattributes` pinning LF** | Files authored on Windows must stay parsable and executable inside Linux containers. |

### Deviations from the phase specification

1. Repository root is `BhashaBench/` rather than a nested `bhashabench/` — the
   working directory already carried the project name.
2. `backend/app/api/v1/` sub-package and `backend/app/api/deps.py` added
   (decisions 3 and 4).
3. `backend/requirements-dev.txt` added, so the production image installs no
   test tooling.
4. `backend/tests/conftest.py`, `test_config.py` and `test_app_metadata.py`
   added alongside the specified `test_health.py` — the phase requires tests
   for configuration loading and application metadata, and one file per
   concern is clearer than one large file.
5. `.dockerignore` and `.gitattributes` added (decision 18).
6. One extra commit (`chore(config)`) beyond the seven suggested, for the
   port-conflict fix discovered during Docker validation.

All deviations are documented in `docs/ARCHITECTURE.md` §5.

---

## 4. Dependencies installed

### Backend runtime — `backend/requirements.txt`

| Package | Constraint | Resolved |
|---------|-----------|----------|
| `fastapi` | `~=0.162.0` | 0.162.0 |
| `uvicorn` | `~=0.54.0` | 0.54.0 |
| `pydantic` | `~=2.14.0` | 2.14.2 |
| `pydantic-settings` | `~=2.16.0` | 2.16.2 |

Transitive: `starlette` 1.10.0, `pydantic-core` 2.50.2, `annotated-types`,
`annotated-doc`, `typing-extensions`, `typing-inspection`, `python-dotenv`,
`click`, `h11`, `anyio`, `idna`, `opentelemetry-api`, `colorama`.

### Backend development — `backend/requirements-dev.txt`

| Package | Constraint | Resolved |
|---------|-----------|----------|
| `pytest` | `~=9.2.0` | 9.2.0 |
| `httpx2` | `~=2.16.0` | 2.16.0 |
| `ruff` | `~=0.17.0` | 0.17.3 |

Transitive: `httpcore2` 2.16.0, `truststore`, `pluggy`, `iniconfig`,
`packaging`, `pygments`, `certifi`.

### Frontend — `frontend/package.json`

| Package | Version |
|---------|---------|
| `next` | 16.4.3 |
| `react` / `react-dom` | 19.3.0 |
| `typescript` | ^5 |
| `tailwindcss` / `@tailwindcss/turbopack` | ^4 |
| `eslint` | ^9 |
| `eslint-config-next` | 16.4.3 |
| `@types/node` / `@types/react` / `@types/react-dom` | ^20 / ^19 / ^19 |

287 packages installed. No dependency was added beyond the scaffold.

### Container base images

`python:3.12-slim`, `node:22-alpine`, `postgres:16-alpine`.

---

## 5. Commands used

```bash
# Inspection
git rev-parse --show-toplevel && git status --short && git branch -a && git remote -v
python --version && node --version && docker compose version && gh auth status

# Repository
git init -b main
git config user.name "YushBytes" && git config user.email "maprojects3829@gmail.com"

# Backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install --only-binary :all: \
  fastapi uvicorn pydantic pydantic-settings pytest httpx2 ruff
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8011

# Frontend
npx create-next-app@latest frontend --ts --tailwind --eslint --app \
  --no-src-dir --import-alias "@/*" --use-npm --yes
npm run typecheck && npm run lint && npm run build
npx next start --port 3011

# Docker
docker compose config --quiet
docker compose up -d db
docker compose exec -T db psql -U bhashabench -d bhashabench -tAc "select version();"
docker compose build backend frontend

# Verification
curl -fsS http://127.0.0.1:8011/ | http://127.0.0.1:8011/health | /api/v1/health
git log --all --name-only --pretty=format: | grep -E "^\.env$"
git grep -nIE "(SECRET_KEY|API_KEY|AUTH_TOKEN|PASSWORD)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9_-]{16,}" $(git rev-list --all)
```

---

## 6. Backend test results

`pytest` — **35 passed**, run from the repository root.

```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\ayush\OneDrive\Desktop\BhashaBench
configfile: pyproject.toml
testpaths: backend/tests
collected 35 items

backend\tests\test_app_metadata.py .........                             [ 25%]
backend\tests\test_config.py ..............                              [ 65%]
backend\tests\test_health.py ............                                [100%]

============================= 35 passed in 0.40s ==============================
```

### Ruff

```
$ ruff check .
All checks passed!

$ ruff format --check .
25 files already formatted
```

Two findings were raised on the first run and fixed properly rather than
suppressed: `SIM102` (a nested conditional in the secret-key validator,
collapsed) and `UP037` (a quoted forward reference in `schemas/common.py`,
removed by declaring `ErrorDetail` before `ErrorResponse`).

### Live endpoint verification

Uvicorn on port 8011, real HTTP requests:

| Request | Result |
|---------|--------|
| `GET /` | `200` — `{"name":"BhashaBench","tagline":"Test your voice AI before India tests it for you.","version":"0.1.0","environment":"development","docs_url":"/docs"}` |
| `GET /health` | `200` — `{"status":"ok","version":"0.1.0"}` |
| `GET /api/v1/health` | `200` — `status: degraded`, three components, UTC timestamp, uptime `0.829s` |
| `GET /nope` | `404` — `{"error":{"type":"not_found","message":"Not Found","status_code":404}}` |
| `GET /docs` | `200` — Swagger UI served |

---

## 7. Frontend build results

```
$ npm run typecheck
> tsc --noEmit
(no output — clean)

$ npm run lint
> eslint .
(no output — clean)

$ npm run build
▲ Next.js 16.4.3 (Turbopack)
✓ Compiled successfully in 5.7s
  Finished TypeScript in 4.1s
✓ Generating static pages using 5 workers (4/4) in 1606ms

Route (app)
┌ ○ /
└ ○ /_not-found
○  (Static)  prerendered as static content
```

### Rendered-output verification

The production build was served with `next start` on port 3011 and the HTML
asserted against, rather than being assumed from a successful compile:

| Check | Result |
|-------|--------|
| HTTP status | `200` |
| `<title>` | `BhashaBench — Test your voice AI before India tests it for you.` |
| Product name and tagline present | ✅ |
| `Phase 1 of 15` present | ✅ |
| `Planned · Phase 7` capability label present | ✅ |
| `/api/v1/health` endpoint row present | ✅ |
| All 15 roadmap phases rendered | ✅ |
| `Create Next App` boilerplate remaining | 0 occurrences |

The compiled stylesheet was fetched and the custom Tailwind tokens confirmed
present, so the design is verified as applied rather than merely compiled:
`.bg-surface-base`, `.bg-surface-raised`, `.text-text-primary`,
`.text-text-secondary`, `.border-border-subtle`, `.bg-accent`,
`.text-status-live`, `.text-status-partial`, `.font-mono` — all found in the
18 KB emitted CSS.

---

## 8. Docker validation results

### Compose configuration — ✅ valid

```
$ docker compose config --quiet
(exit 0)
```

Variable interpolation resolves correctly, including `DATABASE_URL` composed
from the Postgres credentials against the in-network host `db`, and the three
configurable host-port bindings.

### PostgreSQL — ✅ verified end to end

```
$ docker compose up -d db
 Volume bhashabench-postgres-data  Created
 Network bhashabench_default       Created
 Container bhashabench-db          Started

$ docker compose ps
bhashabench-db | running | Up 16 seconds (healthy) | 0.0.0.0:5434->5432/tcp
```

| Check | Result |
|-------|--------|
| Container health check (`pg_isready`) | `healthy` after 3 polls (~9s) |
| Server version | `PostgreSQL 16.15 on x86_64-pc-linux-musl` |
| Credentials from `.env` accepted | ✅ |
| Write/read round-trip (`create table`, `insert`, `select`) | ✅ `1 => phase-1 docker validation` |
| Named volume created | `bhashabench-postgres-data` |
| Smoke table dropped afterwards | ✅ database left empty |

### Backend runtime on Python 3.12 — ✅ verified in a container

The local interpreter is 3.14.6, but the project targets 3.12, so the pinned
requirements and the full suite were cross-validated inside
`python:3.12-slim` with the repository mounted:

```
$ docker run --rm -v "...\BhashaBench:/src" -w /src python:3.12-slim bash -c     "pip install -r backend/requirements.txt -r backend/requirements-dev.txt      && ruff check . && ruff format --check . && pytest -q"

Python 3.12.14
--- installed ---
fastapi           0.162.0
httpx2            2.16.0
pydantic          2.14.2
pydantic-settings 2.16.2
pytest            9.2.0
ruff              0.17.3
starlette         1.10.0
uvicorn           0.54.0
--- ruff check ---
All checks passed!
--- ruff format ---
26 files already formatted
--- pytest ---
...................................                                      [100%]
35 passed in 2.06s
[exited with code 0]
```

Every pinned constraint resolved to exactly the intended version, and lint,
format and all 35 tests pass on 3.12 as well as on 3.14. This confirms the
backend's containerised runtime environment independently of the image build
below.

### Backend and frontend images — ⚠️ not completed

The image builds did not finish. The cause is external to the repository:
Docker Hub layer downloads on this machine stalled at roughly 10 KB/s.

```
#13 [backend base 1/5] FROM docker.io/library/python:3.12-slim@sha256:aa943ce4...
#13 sha256:6fc242d2... 4.19MB / 29.86MB 421.5s
#13 retrying in 1s
```

A `python:3.12-slim` image is already present locally, but BuildKit resolved
the tag to a newer upstream digest and attempted to fetch it. The frontend
image progressed further (`node:22-alpine` pulled, `npm ci` running) before
the run was stopped.

Nothing in `docker-compose.yml`, `backend/Dockerfile` or `frontend/Dockerfile`
was implicated: no Dockerfile instruction failed, and no build error was
emitted. **The images themselves remain unverified, and this is listed as a
limitation below.** What *is* verified is every ingredient they assemble: the
Compose configuration, the PostgreSQL service, the backend's Python 3.12
dependency set and test suite (above), and both services running on the host
(sections 6 and 7).

---

## 9. Git commits

Branch `feature/phase-01-foundation`, oldest first:

| # | Hash | Commit | Changes |
|---|------|--------|---------|
| 1 | `9129768` | `chore(repo): initialise monorepo structure` | 8 files, +253 |
| 2 | `0c9b707` | `feat(backend): establish FastAPI application` | 24 files, +984 |
| 3 | `8864c80` | `feat(frontend): initialise Next.js dashboard` | 21 files, +7621 |
| 4 | `08c659d` | `chore(docker): configure development infrastructure` | 3 files, +205 |
| 5 | `449b84b` | `docs(project): add architecture and development roadmap` | 4 files, +1249 |
| 6 | `1d4fefe` | `chore(config): make Compose host ports configurable` | 2 files, +16 −4 |

Full hashes:

```
9129768c75efdf8319ac249ebfc378879429bcc6
0c9b707018bd640f95592a6cdd827adc56c04c67
8864c80ba19a1d49c2e2764696018ec393d94800
08c659dee84d04486d84b6f7440e5fa7f781aaae
449b84b4aff78f1bf3ed6f7bde08e1bad0a6e4cf
1d4fefeaa2706c1808838d2aee563f0749f79bc7
```

### Branches

| Branch | Tip | Notes |
|--------|-----|-------|
| `main` | `449b84b` | Foundation through documentation |
| `develop` | `449b84b` | Integration branch |
| `feature/phase-01-foundation` | `1d4fefe` | Phase 1 work, current checkout |

Nothing was merged into `main`, and no branch was force-updated.

### Secret audit

| Check | Result |
|-------|--------|
| `.env` tracked in any commit, on any branch | Never tracked |
| `.env` ignored by git | Confirmed via `git check-ignore` → `.gitignore:4` |
| Credential-shaped assignments across all commits | Only `SECRET_KEY=replace-with-a-generated-secret` and `POSTGRES_PASSWORD=change-me` in `.env.example` — both placeholders |
| Provider credentials in `.env.example` | All empty |
| `node_modules/`, `.next/`, `.venv/` staged | 0 paths |

---

## 10. GitHub push status

**Not pushed — no remote is configured.**

```
$ git remote -v
(no output)
```

Per the phase instructions, local commits were completed and no remote was
created. The GitHub CLI is authenticated on this machine as **`YushBytes`**
with `repo` and `workflow` scopes, so either route below will work.

### Option A — create the repository with the GitHub CLI

```bash
cd "C:\Users\ayush\OneDrive\Desktop\BhashaBench"

# Private (recommended until you have reviewed the contents):
gh repo create BhashaBench --private --source=. --remote=origin

# Then push all three branches and set upstreams:
git push -u origin main
git push -u origin develop
git push -u origin feature/phase-01-foundation
```

### Option B — connect an existing empty repository

```bash
cd "C:\Users\ayush\OneDrive\Desktop\BhashaBench"
git remote add origin https://github.com/YushBytes/BhashaBench.git
git push -u origin main
git push -u origin develop
git push -u origin feature/phase-01-foundation
```

### Then open the Phase 1 pull request

```bash
gh pr create --base develop --head feature/phase-01-foundation \
  --title "feat: Phase 1 — project foundation" \
  --body "Monorepo scaffold, FastAPI backend with health endpoints, Next.js status shell, Docker Compose stack, Ruff + pytest, and documentation. 35 backend tests pass; frontend lint, typecheck and build pass."
```

Before pushing, confirm `.env` is absent from the index:

```bash
git ls-files | Select-String "^\.env$"     # PowerShell — expect no output
```

---

## 11. Known limitations

1. **Backend and frontend Docker images were never built.** The builds
   stalled on Docker Hub layer downloads at roughly 10 KB/s (§8). No
   Dockerfile instruction failed, but the images were not produced, so "the
   backend and frontend start successfully *as containers*" is not something
   this report can claim. The backend's Python 3.12 runtime, its pinned
   dependencies and all 35 tests *were* validated inside
   `python:3.12-slim` (§8), and both services were verified running on the
   host (§§6–7). Re-run `docker compose up -d --build` on a faster
   connection to close the remaining gap.
2. **An unrelated git repository exists at `C:\Users\ayush\OneDrive\Desktop`.**
   It has no commits, no remote, and ~100 untracked personal files. It looks
   like an accidental `git init`. The project repository is nested inside it,
   which git tolerates but which can confuse tooling run from the Desktop
   folder. Consider removing it: `Remove-Item -Recurse -Force "$HOME\OneDrive\Desktop\.git"`
   — your call, and nothing in this project depends on it.
3. **The project lives inside a OneDrive-synced folder.** This made dependency
   installation unusually slow (the first `pip install` exceeded five minutes)
   and OneDrive may try to sync `node_modules` and `.venv`. Moving the project
   outside OneDrive, or excluding those directories from sync, would help.
4. **The database is not connected.** `DATABASE_URL` is validated and
   reported, but no engine or session exists, which is why
   `/api/v1/health` returns `degraded`. Phase 2.
5. **Frontend data is static.** `lib/content.ts` holds typed constants, since
   the endpoints that would serve it arrive in Phase 12.
6. **No CI pipeline.** `.github/workflows/` holds only `.gitkeep`; CI is
   Phase 14.
7. **No authentication, rate limiting or structured logging.** Phase 15.
8. **Provider credentials are declared but inert.** No Gnani or Twilio
   endpoint, auth scheme or payload shape is assumed anywhere, by design.
9. **No visual screenshot of the dashboard.** Three Chrome browsers are
    connected to this machine and selecting one requires interactive input,
    so the UI was verified by asserting on served HTML and the compiled CSS
    (§7) rather than by image.

---

## 12. Remaining work

### To fully close Phase 1

- [ ] Complete `docker compose up --build` on a usable connection and confirm
      all three containers reach `healthy`.
- [ ] Create the GitHub remote and push all three branches (§10).
- [ ] Open the `feature/phase-01-foundation` → `develop` pull request.
- [ ] Optionally remove the stray Desktop git repository.

### Phase 2 — Data Model & Persistence (awaiting approval)

- SQLAlchemy models: `Scenario`, `TestRun`, `Call`, `Turn`, `Evaluation`,
  `BenchmarkResult`.
- Alembic migrations with the initial revision checked in.
- Async engine and session dependency.
- Replace the `database` health placeholder with a real `SELECT 1` probe.
- Repository tests against a throwaway PostgreSQL container.

Full detail for phases 2–15: `docs/DEVELOPMENT_ROADMAP.md`.

---

## 13. Completion criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Repository structure established | ✅ All specified paths present and verified |
| 2 | Backend starts successfully | ✅ Uvicorn served all endpoints over HTTP |
| 3 | Frontend starts successfully | ✅ `next start` served the built app, content asserted |
| 4 | Docker configuration valid | ✅ `docker compose config --quiet` exits 0 |
| 5 | PostgreSQL starts through Compose | ✅ Healthy, queried, write/read round-trip |
| 6 | Backend tests pass | ✅ 35 passed |
| 7 | Frontend lint and build succeed | ✅ ESLint, `tsc --noEmit` and `next build` clean |
| 8 | Ruff checks pass | ✅ `check` and `format --check` clean |
| 9 | Documentation complete | ✅ README, ARCHITECTURE, ROADMAP, CONTRIBUTING |
| 10 | Git commits created | ✅ 6 commits on three branches |
| 11 | GitHub push verified, if a remote exists | ➖ No remote configured; commands provided (§10) |
| — | Backend Python 3.12 runtime, deps and tests in a container | ✅ 35 passed, Ruff clean, on `python:3.12-slim` (§8) |
| — | Backend/frontend images build in Docker | ⚠️ Not verified — registry download stall (§8, limitation 1) |

**Phase 1 is complete and stopping here.** Phase 2 has not been started and
awaits explicit approval.
