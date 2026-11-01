# Phase 1 — Project Foundation: Completion Report

| | |
|---|---|
| **Phase** | 1 of 15 — Project Foundation |
| **Date** | 2026-11-01 (closure pass same day) |
| **Local path** | `C:\Users\ayush\OneDrive\Desktop\BhashaBench` |
| **GitHub** | <https://github.com/YushBytes/BhashaBench> (private) |
| **Branch** | `feature/phase-01-foundation` |
| **Commits** | 9 |
| **Tracked files** | 61 |
| **Status** | **Closed.** All four images build and run, all three Compose services are healthy, and all three branches are pushed and hash-verified. Remaining items are deferred scope, not unverified claims. |

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
`README.md` were deleted.

During the closure pass, `backend/Dockerfile` and `frontend/Dockerfile` were
each amended to fix a real build/run defect (decisions 19–21, detailed in
§8.2–§8.4), and `docker-compose.yml` plus `.env.example` gained the
configurable host-port bindings.

**No pre-existing user file was modified or overwritten** — the project
directory was empty at the start, and the unrelated repository at
`C:\Users\ayush\OneDrive\Desktop` was left untouched.

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
| 19 | **`Acquire::ForceIPv4=true` for apt** | `deb.debian.org` publishes A and AAAA records; this host's Docker build network resolves the AAAA address but has no IPv6 egress, and the connection is blackholed rather than refused, so apt retries with long timeouts. The step hung >25 minutes; with the flag it completes in 31.6s. A no-op where IPv6 works. See §8.2. |
| 20 | **`PIP_DEFAULT_TIMEOUT=120`, `PIP_RETRIES=10`** | pip opened its connection to `files.pythonhosted.org` and then stalled mid-read, hitting the 15s default and reporting the misleading `No matching distribution found`. These raise patience only — they never relax version resolution, so the pins still bind exactly. See §8.3. |
| 21 | **`mkdir -p /app/.next` before `chown` in the frontend image** | Compose mounts `/app/.next` as an anonymous volume. Docker seeds such a volume from the image and creates it **root-owned** when the path is absent — and `.next` is excluded by `.dockerignore`. `next dev` running as `node` then died with `EACCES`. Creating the directory first makes the volume inherit `node` ownership. See §8.4. |

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
6. Nine commits rather than the seven suggested. Commit boundaries were
   adjusted to match the actual work: environment and quality configuration
   landed with the repository scaffold and the tests with the backend, while
   three commits were added that the original plan could not have
   anticipated — `chore(config)` for the host-port conflict found during
   Docker validation, and two `fix(docker)` commits for the network and
   volume-ownership defects found during the closure pass (decisions 19–21).

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
## 8. Docker image build results

All four images now build and run. The two failures that blocked the first
attempt were diagnosed to root cause and fixed in the Dockerfiles; neither fix
weakens the build.

### 8.1 Summary

| Image | Target | Tag | Size | Builds | Runs |
|-------|--------|-----|------|--------|------|
| Backend | `development` | `bhashabench-backend:latest` | 280 MB | ✅ | ✅ |
| Backend | `production` | `bhashabench-backend:prod` | 223 MB | ✅ | ✅ |
| Frontend | `development` | `bhashabench-frontend:latest` | 1.8 GB | ✅ | ✅ |
| Frontend | `production` | `bhashabench-frontend:prod` | 756 MB | ✅ | ✅ |

### 8.2 Root cause 1 — apt hung indefinitely

```
#25 [backend base 3/5] RUN apt-get update && apt-get install ... curl
#25 3.766 Get:4 http://deb.debian.org/debian trixie/main amd64 Packages [9678 kB]
   ... no further output for >25 minutes ...
```

Probed from inside the build network:

```
-- address families for deb.debian.org:80 --
   IPv4: ['199.232.114.132']
   IPv6: ['2a04:4e42:5c::644']
-- TCP connect over IPv4 --   OK 199.232.114.132 in 0.01s
-- TCP connect over IPv6 --   FAIL: OSError: [Errno 101] Network is unreachable
```

`deb.debian.org` publishes both A and AAAA records. This host's Docker build
network resolves the AAAA address but has no IPv6 egress, and the connection
is blackholed rather than refused, so apt retries with long timeouts.

**Fix:** `Acquire::ForceIPv4=true` on both apt invocations. The identical
step, including installing curl, then completed in **31.6s**. It is a no-op on
networks where IPv6 works.

**Classification:** host/Docker network configuration, surfaced by a Dockerfile
that did not pin the address family. Not a Dockerfile logic error, and not a
Docker Hub problem.

### 8.3 Root cause 2 — pip reported a misleading resolution failure

```
#27 21.33 ERROR: Could not find a version that satisfies the requirement
          fastapi~=0.162.0 (from versions: none)
#27 21.34 ERROR: No matching distribution found for fastapi~=0.162.0
```

`from versions: none` suggests a resolution problem. `pip install -vvv`
showed the actual cause:

```
#7 2.056 Starting new HTTPS connection (1): pypi.org:443
#7 3.456   Starting new HTTPS connection (1): files.pythonhosted.org:443
#7 23.36 ERROR: Exception:
#7 23.36   File ".../urllib3/response.py", line 438, in _error_catcher
#7 23.36   File "/usr/local/lib/python3.12/ssl.py", line 1116, in read
#7 23.36 TimeoutError: The read operation timed out
```

pip established the connection and then the sustained read stalled, exceeding
its 15-second default. Small requests succeeded throughout (a 285 KB index
fetch returned HTTP 200 in 0.7s), so this was throughput instability on larger
transfers, not unreachability.

**Fix:** `PIP_DEFAULT_TIMEOUT=120` and `PIP_RETRIES=10`. The same install then
completed in **~220s**, resolving to exactly the pinned versions:

```
Successfully installed fastapi-0.162.0 pydantic-2.14.2 pydantic-settings-2.16.2
  starlette-1.10.0 uvicorn-0.54.0 annotated-doc-0.0.5 annotated-types-0.8.0
  anyio-4.16.0 click-8.5.0 h11-0.16.0 idna-3.20 opentelemetry-api-1.45.2
  pydantic-core-2.50.2 python-dotenv-1.2.4 typing-extensions-4.16.0
  typing-inspection-0.4.4
```

These settings raise patience only. They do not relax version resolution, so
`requirements.txt` still binds exactly as written.

**Classification:** network throughput, mitigated in the Dockerfile. Not a
dependency-specification error.

### 8.4 Root cause 3 — frontend crash-looped under Compose

The frontend image built and ran standalone, but the Compose service restarted
repeatedly:

```
✓ Ready in 897ms
Error: EACCES: permission denied, mkdir '/app/.next/dev'
  errno: -13, code: 'EACCES', syscall: 'mkdir', path: '/app/.next/dev'
```

Compose mounts `/app/.next` as an anonymous volume so a container-built cache
never mixes with one built on the Windows host. Docker seeds such a volume
from the image's content at that path, and creates it **root-owned** when the
path is absent in the image. `.next` is excluded by `.dockerignore` and is
never produced in the development target, so it was absent — and `next dev`
running as the non-root `node` user could not write into it. `node_modules`
escaped this only incidentally: it does exist in the image, so its volume
inherited the ownership set by the existing `chown`.

**Fix:** `RUN mkdir -p /app/.next && chown -R node:node /app`, so the volume is
seeded from a `node`-owned directory. No change to the volume layout or to
Compose.

**Classification:** Dockerfile defect, interacting with Docker's
anonymous-volume seeding. Found only because the full stack was started, not
merely built.

### 8.5 Runtime verification per image

Backend **production** (`bhashabench-backend:prod`):

| Check | Result |
|-------|--------|
| `GET /` | `200`, correct identity payload |
| `GET /health` | `{"status":"ok","version":"0.1.0"}` |
| `GET /api/v1/health` | `200`, aggregate `degraded` (as designed) |
| Runs as | `appuser` (non-root) |
| `import pytest` | `ModuleNotFoundError` — dev tooling correctly absent |

Backend **development** (`bhashabench-backend:latest`):

| Check | Result |
|-------|--------|
| `GET /health` | `{"status":"ok","version":"0.1.0"}` |
| Runs as | `appuser` (non-root) |
| pytest / ruff present | `9.2.0` / `0.17.3` |
| **Full suite inside the image** | **35 passed in 0.35s** |
| Ruff inside the image, project config supplied | `All checks passed!`, 21 files formatted |

Frontend **production** (`bhashabench-frontend:prod`):

| Check | Result |
|-------|--------|
| HTTP status | `200` |
| `<title>` | `BhashaBench — Test your voice AI before India tests it for you.` |
| Content assertions | `BhashaBench`, `Phase 1 of 15`, `Planned · Phase 7`, `Fifteen phases` all present |
| Runs as | `node` (non-root) |
| `NODE_ENV` | `production` |

### 8.6 Full Compose stack

```
$ docker compose up -d
 Container bhashabench-db        Healthy
 Container bhashabench-backend   Started
 Container bhashabench-backend   Healthy
 Container bhashabench-frontend  Started

$ docker compose ps
bhashabench-backend  | Up 7 minutes (healthy)
bhashabench-db       | Up 2 hours (healthy)
bhashabench-frontend | Up 19 seconds
```

Health-gated ordering works as configured: the backend waits for the database
to report healthy, and the frontend waits for the backend. Verified through the
published host ports:

| Endpoint | Result |
|----------|--------|
| `http://localhost:8000/` | `200`, identity payload |
| `http://localhost:8000/health` | `{"status":"ok","version":"0.1.0"}` |
| `http://localhost:8000/api/v1/health` | `degraded` — `api: ok`, `configuration: ok`, `database: degraded` |
| `http://localhost:3000/` | `200`, correct `<title>` and page content |

Frontend log after the fix, with no `EACCES`:

```
▲ Next.js 16.4.3 (Turbopack)
- Network:  http://0.0.0.0:3000
✓ Ready in 783ms
 GET / 200 in 717ms (next.js: 351ms, application-code: 366ms)
```

### 8.7 Compose configuration

```
$ docker compose config --quiet
(exit 0)
```

Interpolation resolves correctly, including `DATABASE_URL` composed from the
Postgres credentials against the in-network host `db`, and the three
configurable host-port bindings.

---

## 9. PostgreSQL verification

| Check | Result |
|-------|--------|
| Container health check (`pg_isready`) | `healthy` after ~9s |
| Server version | `PostgreSQL 16.15 on x86_64-pc-linux-musl` |
| Credentials from `.env` accepted | ✅ |
| Write/read round-trip (`create table`, `insert`, `select`) | ✅ `1 => phase-1 docker validation` |
| Named volume | `bhashabench-postgres-data` created and retained |
| Still healthy at end of closure pass | ✅ `Up 2 hours (healthy)` |
| Smoke table removed afterwards | ✅ database left empty |

Host port is `5434` on this machine, set via `POSTGRES_HOST_PORT`, because
`5432` is held by an unrelated project.

**Unrelated containers were not stopped, restarted or deleted.** Confirmed at
the end of the pass:

```
novaflow-pytest-mongo | Up 7 hours
whistledrop-db        | Up 7 hours (healthy)
whistledrop-db-test   | Up 7 hours (healthy)
```

Only `bhashabench-frontend` was deliberately removed and recreated
(`docker compose rm -sfv frontend`), to discard the root-owned anonymous
volume described in §8.4. The `bhashabench-postgres-data` volume was never
removed.

---

## 10. Final verification suite

Run against the final committed state:

| Check | Command | Result |
|-------|---------|--------|
| Backend tests | `pytest` | **35 passed in 0.38s** |
| Backend tests, in container | `pytest` inside dev image | **35 passed in 0.35s** |
| Ruff lint | `ruff check .` | `All checks passed!` |
| Ruff format | `ruff format --check .` | `26 files already formatted` |
| Frontend lint | `npm run lint` | clean, no findings |
| Frontend types | `npm run typecheck` | clean, no errors |
| Frontend build | `npm run build` | `✓ Compiled successfully`, 4/4 static pages |
| Compose config | `docker compose config --quiet` | exit 0 |

### Live endpoint re-verification

| Request | Status | Response |
|---------|--------|----------|
| `GET /` | `200` | name, tagline, version `0.1.0`, environment, `docs_url` |
| `GET /health` | `200` | `{"status":"ok","version":"0.1.0"}` |
| `GET /api/v1/health` | `200` | `degraded`; 3 components; UTC timestamp; uptime |
| `GET /does-not-exist` | `404` | `{"error":{"type":"not_found",...}}` |
| `POST /health` | `405` | `{"error":{"type":"http_error",...}}` |
| `GET /docs` | `200` | Swagger UI |
| `GET /openapi.json` | `200` | paths exactly `['/', '/api/v1/health', '/health']` |

With a local `.env` present, the `configuration` component correctly reports
`.env file present` rather than `absent` — the config-source detection works in
both states.

---

## 11. Git commits

Branch `feature/phase-01-foundation`, oldest first:

| # | Hash | Commit | Changes |
|---|------|--------|---------|
| 1 | `bb5d017` | `chore(repo): initialise monorepo structure` | 8 files, +253 |
| 2 | `32945c3` | `feat(backend): establish FastAPI application` | 24 files, +984 |
| 3 | `8c8f1c6` | `feat(frontend): initialise Next.js dashboard` | 21 files, +7621 |
| 4 | `c926ec2` | `chore(docker): configure development infrastructure` | 3 files, +205 |
| 5 | `f5ced2c` | `docs(project): add architecture and development roadmap` | 4 files, +1249 |
| 6 | `0aa8a25` | `chore(config): make Compose host ports configurable` | 2 files, +16 −4 |
| 7 | `9128b60` | `docs(project): add Phase 1 completion report` | 1 file, +629 |
| 8 | `e3648ed` | `fix(docker): make the backend image build on networks with broken IPv6` | 1 file, +20 −3 |
| 9 | `a319011` | `fix(docker): give the frontend container ownership of its .next volume` | 1 file, +9 −1 |

The commit that records this updated report is necessarily the tenth, and
cannot contain its own hash. Run `git log --oneline` for the authoritative
current list.

Full hashes:

```
bb5d017ef940771c7ba61154274055aea45d4596
32945c328cece9f3cf28424d16333d37d3da66c5
8c8f1c6bd9e6b49f58bba6483158972708b31694
c926ec27c43cc35163ca9259d664f3cdd732f90c
f5ced2c3ff4da3ddc5786a2ca1e0fabad950f98e
0aa8a25f227f9d8c677d29ca1c58617c805882ef
9128b60e655e9a7b8bafaebaff5d8ac44ab7f0b3
e3648ed3a7269955c8e852d253a62bc1db6f2019
a31901178968c7bffd68776f866f15a06cc65744
```

### Commit authorship was corrected

The first seven commits were originally authored with
`maprojects3829@gmail.com`. GitHub attributes commits **by email**, and that
address is registered to a different account (`madhurgrover-cs`), so every
commit displayed as authored by that user even though `user.name` read
`YushBytes` and the repository belongs to `YushBytes`.

Identity was corrected to the account's noreply address:

```
user.name  = YushBytes
user.email = 234807623+YushBytes@users.noreply.github.com
```

All commits were then rewritten with `git filter-branch --env-filter`,
changing author **and** committer email. This rewrote history on already-pushed
branches and therefore required a force push, which the project owner
explicitly authorised for this one correction.

Proof the rewrite changed metadata only:

| Branch | Tree before | Tree after | Identical |
|--------|-------------|------------|-----------|
| `main` / `develop` | `c69daf30d800…` | `c69daf30d800…` | ✅ |
| `feature/phase-01-foundation` | `e126266da82f…` | `e126266da82f…` | ✅ |

`git diff` between the old and new tips is empty; commit count, messages and
timestamps are unchanged. The `refs/original/*` backups and a stale
`refs/stash` ref were then dropped and garbage-collected, leaving **0**
occurrences of the old address in reachable history.

GitHub now reports `author=YushBytes` for all nine commits.

---

## 12. GitHub repository

| | |
|---|---|
| **URL** | <https://github.com/YushBytes/BhashaBench> |
| **Visibility** | **Private** |
| **Owner** | `YushBytes` |
| **Default branch** | `main` |
| **Created** | This closure pass — it did not previously exist (`gh repo view` returned `Could not resolve to a Repository`) |
| **Remote** | `origin` → `https://github.com/YushBytes/BhashaBench.git` |

No pre-existing repository was overwritten.

### Remote branch verification

Local hashes compared against `git ls-remote` (authoritative, not the cached
remote-tracking refs):

| Branch | Local | Remote | Match |
|--------|-------|--------|-------|
| `main` | `f5ced2c3ff4d` | `f5ced2c3ff4d` | ✅ |
| `develop` | `f5ced2c3ff4d` | `f5ced2c3ff4d` | ✅ |
| `feature/phase-01-foundation` | `a31901178968` | `a31901178968` | ✅ |

All three report `ahead 0, behind 0`; no branch has diverged.

The force push used `--force-with-lease` with an explicit expected value per
branch, so a remote that had moved underneath would have aborted the push
rather than being clobbered. The first attempt did in fact reject with
`stale info` — `filter-branch` had rewritten the remote-tracking refs — and
was resolved by re-fetching to restore a true baseline before pushing, not by
escalating to a bare `--force`.

Nothing has been merged into `main`; `main` and `develop` sit at `f5ced2c`
while the two Docker fixes remain on the feature branch for review.

---

## 13. Security audit

| Check | Result |
|-------|--------|
| `.env` tracked in any commit, on any branch, ever | **Never** |
| `.env` ignored by git | ✅ `.gitignore:4` |
| Any `.env*` tracked besides `.env.example` | None |
| Private key material (`*.pem`, `*.key`, `*.p12`, `*.pfx`) | None |
| Build artefacts (`node_modules/`, `.next/`, `.venv/`, `__pycache__/`) tracked | None |
| Credential-shaped assignments across all commits | Only `SECRET_KEY=replace-with-a-generated-secret` and `POSTGRES_PASSWORD=change-me` in `.env.example` — both placeholders |
| Provider credentials in `.env.example` | All empty (`GNANI_API_KEY`, `TWILIO_*`) |
| `.env` present in the pushed remote tree | **Absent** (verified via `git ls-tree -r origin/feature/phase-01-foundation`) |
| Untracked-and-unignored files (what `git add -A` would stage) | **0** |
| Secrets in API responses | Test asserts neither `SECRET_KEY` nor `DATABASE_URL` appears in the root payload |
| Health endpoint leakage | `describe_environment()` returns only `present`/`absent`, `configured`/`default` — never a value |

`.gitignore` coverage was verified behaviourally with `git check-ignore`
rather than by reading the file:

```
IGNORED  .env                                   <- .gitignore:4
IGNORED  .venv/pyvenv.cfg                       <- .gitignore:40
IGNORED  frontend/node_modules/.package-lock.json <- frontend/.gitignore:4
IGNORED  frontend/.next/BUILD_ID                <- frontend/.gitignore:17
IGNORED  backend/app/__pycache__/x.pyc          <- .gitignore:18
IGNORED  storage/audio/a.wav                    <- .gitignore:76
IGNORED  secrets/k.pem                           <- .gitignore:13
IGNORED  app.log                                 <- .gitignore:81
```

`.env.example` declares all 18 specification-required variables, plus the
Postgres and host-port settings, with no real value anywhere.

One note: a local `.env` containing generated development secrets exists on
disk at the project root. It is git-ignored and was never committed or pushed.

### Repository hygiene

| Check | Result |
|-------|--------|
| Project repo root | `C:/Users/ayush/OneDrive/Desktop/BhashaBench` ✅ |
| Git directory | `…/BhashaBench/.git` ✅ |
| Working tree | Clean |
| Tracked files | 61 |
| `Desktop\.git` deleted | **No** — left untouched as instructed |
| Does the Desktop repo track this project? | **No** — its index holds 0 files, it has 0 commits and 0 remotes; it is entirely inert |
| Personal files outside the project touched | **None** |

---

## 14. Known limitations

1. **The database is not connected.** `DATABASE_URL` is validated and
   reported, but no engine or session exists, which is why `/api/v1/health`
   returns `degraded`. Phase 2.
2. **Frontend data is static.** `lib/content.ts` holds typed constants, since
   the endpoints that would serve it arrive in Phase 12.
3. **No CI pipeline.** `.github/workflows/` holds only `.gitkeep`; CI is
   Phase 14. The two Docker fixes in this pass are exactly the kind of
   environment-specific breakage CI would have caught earlier.
4. **No authentication, rate limiting or structured logging.** Phase 15.
5. **Provider credentials are declared but inert.** No Gnani or Twilio
   endpoint, auth scheme or payload shape is assumed anywhere, by design.
6. **In-container pytest does not use the project's pytest settings.**
   `pyproject.toml` lives at the repository root and is not copied into the
   backend image, and its `testpaths`/`pythonpath` are root-relative. Tests do
   run correctly in the container (35 passed, imports resolve via
   `PYTHONPATH=/app`), but via pytest's defaults rather than the project's
   `addopts` and `filterwarnings = ["error"]`. Copying the file in naively
   makes things worse — it triggers `PytestConfigWarning: No files were found
   in testpaths`, which `filterwarnings` escalates to a failure. Resolving
   this properly means reconciling the path layout, which is not Phase 1 work.
7. **The IPv6 condition is mitigated, not repaired.** `Acquire::ForceIPv4`
   works around this host's missing IPv6 egress inside the Docker build
   network. The underlying Docker/host networking is unchanged; fixing it is a
   system-settings change outside this repository's scope.
8. **Frontend development image is large** (1.8 GB). It carries the full
   dependency tree and build cache by design. The production image is 756 MB;
   neither has been size-optimised, which is Phase 15 work.
9. **No visual screenshot of the dashboard.** Three Chrome browsers are
   connected to this machine and selecting one requires interactive input, so
   the UI was verified by asserting on served HTML and the compiled CSS
   (§7) rather than by image.
10. **The project lives inside a OneDrive-synced folder.** This made dependency
    installation slow and OneDrive may try to sync `node_modules` and `.venv`.
    Moving the project outside OneDrive, or excluding those directories from
    sync, would help.
11. **An inert git repository remains at `C:\Users\ayush\OneDrive\Desktop`.**
    Zero commits, zero indexed files, zero remotes — it looks like an
    accidental `git init`. Left in place as instructed. Removing it is
    optional: `Remove-Item -Recurse -Force "$HOME\OneDrive\Desktop\.git"`.

---

## 15. Remaining work

### Phase 1 — optional follow-ups

- [ ] Open the `feature/phase-01-foundation` → `develop` pull request:
      ```
      gh pr create --base develop --head feature/phase-01-foundation \
        --title "feat: Phase 1 - project foundation"
      ```
- [ ] Decide whether to merge the two Docker fixes down to `develop`/`main`.
- [ ] Optionally remove the inert `Desktop\.git`.

### Phase 2 — Data Model & Persistence (awaiting approval, not started)

- SQLAlchemy models: `Scenario`, `TestRun`, `Call`, `Turn`, `Evaluation`,
  `BenchmarkResult`.
- Alembic migrations with the initial revision checked in.
- Async engine and session dependency.
- Replace the `database` health placeholder with a real `SELECT 1` probe.
- Repository tests against a throwaway PostgreSQL container.

Full detail for phases 2–15: `docs/DEVELOPMENT_ROADMAP.md`.

---

## 16. Completion criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Repository structure established | ✅ All specified paths present and verified |
| 2 | Backend starts successfully | ✅ On host and in both images |
| 3 | Frontend starts successfully | ✅ On host and in both images |
| 4 | Docker configuration valid | ✅ `docker compose config --quiet` exits 0 |
| 5 | PostgreSQL starts through Compose | ✅ Healthy, queried, write/read round-trip |
| 6 | Backend tests pass | ✅ 35 passed on host; 35 passed inside the dev image |
| 7 | Frontend lint and build succeed | ✅ ESLint, `tsc --noEmit`, `next build` all clean |
| 8 | Ruff checks pass | ✅ `check` and `format --check` clean |
| 9 | Documentation complete | ✅ README, ARCHITECTURE, ROADMAP, CONTRIBUTING, this report |
| 10 | Git commits created | ✅ 9 Conventional Commits |
| 11 | GitHub push verified | ✅ Private repo created; 3 branches pushed; hashes verified via `ls-remote` |
| 12 | Backend dev + prod images build and run | ✅ 280 MB / 223 MB, both serve, both non-root |
| 13 | Frontend dev + prod images build and run | ✅ 1.8 GB / 756 MB, both serve, both non-root |

**Phase 1 is closed.** Every criterion is met by direct verification, not
inference. No claim in this report rests on a build that did not complete or a
push that was not confirmed.

**Phase 2 has not been started** and awaits explicit approval.
