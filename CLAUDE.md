# CLAUDE.md

Guidance for AI coding agents working in this repository. Read this before
making changes.

## What this project is

BhashaBench is an automated testing and benchmarking platform for
Indian-language voice bots. It is being built in **15 controlled phases**; see
`docs/DEVELOPMENT_ROADMAP.md`.

**Phases 1 and 2 are complete.** Phase 3 has not started.

| Phase | Status |
|-------|--------|
| 1 — Project foundation | ✅ Complete |
| 2 — Database & scenario engine | ✅ Complete |
| 3–15 | ⬜ Not started |

## The two rules that matter most

1. **Never claim something works when it does not.** If a subsystem is not
   implemented, report it as `degraded`/`unavailable`/`planned` **with a
   reason** — never as healthy, and never with fabricated data. The frontend
   renders no sample analytics for exactly this reason.
2. **Never commit a secret.** `.env` is git-ignored. Credentials belong in a
   local `.env` or in GitHub Environments — never in a tracked file, never in
   `.env.example`, never in a log line or an API response.

## Phase discipline

Do not implement functionality belonging to a future phase, even if it seems
convenient. A pull request that does will be asked to split. Phase 3+ work —
telephony, speech-to-text, text-to-speech, audio degradation, caller
simulation, evaluation — is explicitly out of scope until its phase.

The `TestRun`, `CallSession` and `ConversationTurn` tables exist as
**foundational schema only**. Nothing executes a run, places a call or
transcribes anything.

## Architecture rules

### Layering (backend)

```
api/          HTTP only: routing, status codes, request/response shaping
services/     business rules; raise domain errors, never HTTPException
repositories/ every SQL statement; take an explicit Session, never commit
models/       SQLAlchemy ORM
schemas/      Pydantic request/response and the scenario specification
db/           engine, session, declarative base
```

- Route handlers stay thin. No `select()` in a route, no HTTP concepts in a
  service.
- Repository functions **never commit**. The service owns the transaction
  boundary.
- Services raise `NotFoundError` / `ConflictError` from
  `app/services/errors.py`. The exception handlers in `app/main.py` are the
  single place that maps a domain failure to an HTTP status.

### Database

- **Alembic owns the schema.** The application must never call
  `Base.metadata.create_all()`. Every change is a migration.
- Add new models to `app/models/__init__.py`, or Alembic autogenerate will
  silently miss them.
- Run `alembic check` after changing a model — it fails when models and
  migrations have drifted.
- UUID primary keys, `timestamptz` timestamps, explicit `ondelete` on every
  foreign key.
- `Enum(...)` needs `create_constraint=True`. SQLAlchemy defaults it to
  `False`, which leaves the column an unvalidated VARCHAR enforced only in
  Python.

### Sessions are synchronous

Handlers that touch the database are `def`, not `async def`, so FastAPI runs
them in a worker thread. Do not introduce an async engine without changing
this decision deliberately — see `app/db/session.py` for the reasoning.

### YAML

Parse with `yaml.safe_load` only. `yaml.load` can construct arbitrary Python
objects and turns a scenario file into remote code execution. Size, node-count
and depth limits in `app/services/scenario_loader.py` exist to stop
anchor/alias expansion bombs; do not remove them.

`safe_load` still builds *cyclic* objects from a recursive alias, so
`_measure` tracks object identity along its active recursion path and raises
`ScenarioRecursionError`. Two things to preserve if you touch it: the set is an
**active path**, not a seen-ever set (a seen-ever set would wrongly reject the
second reference to a shared anchor), and ids are discarded in a `finally` so a
deeper exception cannot leave a stale entry behind. Do not rely on
`MAX_YAML_DEPTH` to catch cycles — that only worked because it happened to be
below Python's recursion limit.

## Testing

```bash
pytest                                  # whole suite (246 tests)
pytest backend/tests/test_database.py   # one module
ruff check . && ruff format --check .   # from the repository root
```

- `filterwarnings = ["error"]` is set. A new deprecation warning **fails the
  suite** — fix the cause rather than widening the filter. In particular use
  Starlette's current status constant names (`HTTP_413_CONTENT_TOO_LARGE`,
  `HTTP_422_UNPROCESSABLE_CONTENT`).
- Database tests need PostgreSQL (`docker compose up -d db`). They create and
  drop their own `bhashabench_test` database and are never allowed to skip
  silently.
- Never write `assert True`. Every behavioural change needs a test that can
  actually fail.
- Do not import the `TestSuite` or `TestRun` ORM classes under their real
  names into a test module — pytest tries to collect any module-level
  `Test*` class. Alias them (`TestSuite as SuiteModel`).

## Local environment notes

- `DATABASE_URL`'s port **must match `POSTGRES_HOST_PORT`**. They can
  disagree, and host-side tooling — including `alembic upgrade head` — will
  then connect to whatever else is on the old port.
- `alembic.ini` lives in `backend/`, not the repository root, so it is present
  inside the Docker image. Run Alembic from `backend/`.
- The repository sits inside a OneDrive-synced folder on the primary
  development machine, which makes `pip install` and `npm install` slow.
- `uvicorn` is installed without the `[standard]` extra deliberately; those
  extras compile from source on new CPython releases.

## Git

- Branch from `develop`, named `feature/phase-NN-short-description`.
- Conventional Commits. Explain **why** in the body, not just what.
- Never force-push or rewrite pushed history.
- Never merge into `main` without being asked.
- Review `git diff --cached` before committing: no secrets, no build
  artefacts.

## Documentation to keep in sync

| File | When |
|------|------|
| `README.md` | setup, commands, endpoints, environment variables change |
| `docs/ARCHITECTURE.md` | a structural decision is made or revised |
| `docs/DATABASE.md` | the schema changes |
| `docs/SCENARIO_FORMAT.md` | the scenario specification changes |
| `docs/DEVELOPMENT_ROADMAP.md` | a phase's scope or status changes |
| `.env.example` | any configuration variable is added or renamed |
| `CLAUDE.md` | these instructions change |

The phase-status tables in `README.md`, `CLAUDE.md` and the roadmap must
agree — they are the first thing a reader checks to learn what actually works.
