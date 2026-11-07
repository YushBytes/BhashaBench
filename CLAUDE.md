# CLAUDE.md

Guidance for AI coding agents working in this repository. Read this before
making changes.

## What this project is

BhashaBench is an automated testing and benchmarking platform for
Indian-language voice bots. It is being built in **15 controlled phases**; see
`docs/DEVELOPMENT_ROADMAP.md`.

**Phases 1, 2 and 3 are complete.** Phase 4 is implemented and awaiting
owner review — not approved. Phase 5 has not started.

| Phase | Status |
|-------|--------|
| 1 — Project foundation | ✅ Complete |
| 2 — Database & scenario engine | ✅ Complete |
| 3 — Scenario library & tooling | ✅ Complete |
| 4 — Speech to text (Gnani Prisma) | 🟨 Implemented, awaiting review |
| 5–15 | ⬜ Not started |

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
convenient. A pull request that does will be asked to split. Phase 5+ work —
text-to-speech, caller simulation, audio degradation, telephony,
orchestration, evaluation — is explicitly out of scope until its phase. In
particular, do not add Gnani Timbre or Evon clients, and do not invent their
endpoints or credentials.

Phase 4 added the Gnani **Prisma** speech-to-text adapter. Every constant it
sends is transcribed from the vendor's published documentation into
`app/transcription/providers/prisma_contract.py`. **Never add a provider
constant you cannot cite.** Where the vendor's documentation is silent or
self-contradictory, the honest record goes in `DOCUMENTATION_GAPS` and the
capability is declared unsupported — three of Prisma's four output modes are
unsupported for exactly this reason, because their literal wire values are
never quoted.

The `TestRun`, `CallSession` and `ConversationTurn` tables exist as
**foundational schema only**. Nothing executes a run or places a call, and
Phase 4 persists no transcript: deciding which turn a transcript belongs to is
orchestration (Phase 9), and a table written by nothing would be schema
guesswork. The transcription endpoints therefore work with PostgreSQL down.

## Architecture rules

### Layering (backend)

```
api/           HTTP only: routing, status codes, request/response shaping
services/      business rules; raise domain errors, never HTTPException
repositories/  every SQL statement; take an explicit Session, never commit
models/        SQLAlchemy ORM
schemas/       Pydantic request/response and the scenario specification
db/            engine, session, declarative base
transcription/ the speech-to-text subsystem (Phase 4):
               models, errors, audio, retry, redaction, registry, base
transcription/providers/
               one adapter per vendor - the ONLY place a vendor's wire
               format may appear
```

- Route handlers stay thin. No `select()` in a route, no HTTP concepts in a
  service.
- Repository functions **never commit**. The service owns the transaction
  boundary.
- Services raise `NotFoundError` / `ConflictError` from
  `app/services/errors.py`. The exception handlers in `app/main.py` are the
  single place that maps a domain failure to an HTTP status.

### The language catalogue

`app/core/languages.py` is the **single source of truth** for supported
languages. The scenario schema, the search filters, the CLI and
`GET /api/v1/languages` all read from it. Do not hardcode a language list
anywhere else, and do not add a language without its endonym, ISO 15924 script
and POSIX locale.

`validate_tag` checks shape before membership, so `hi_IN` fails as malformed
while `fr-FR` fails as unsupported with the full supported list. Those are
different mistakes and deserve different messages.

A third mistake arrived with Phase 4: a tag that *is* in the catalogue and
that the selected provider cannot transcribe. Prisma covers ten of the
thirteen, so Urdu, Odia and Assamese are authorable and not transcribable.
`app.transcription.errors.UnsupportedLanguageError` is deliberately a
different class from the catalogue's, and the message says *by the provider* -
conflating them sends a developer looking for a typo that is not there. Never
substitute a neighbouring language.

### The provider boundary

Nothing above `app/transcription/providers/` may import a vendor module or
mention a vendor field name. The service layer has never heard of
`audio_file` or `detected_language_code`. That boundary is what lets Phase 11
benchmark a second engine without touching the evaluation code.

Adding a provider means writing an adapter, declaring a
`ProviderCapabilities`, and adding one entry to `_FACTORIES` in
`registry.py`. There is no plugin discovery on purpose: "which engine produced
this score?" must be answerable by reading the source.

**Optional means optional.** `confidence`, `segments` and word timings stay
`None` unless the provider genuinely returns them. Prisma's documented schema
has none of the three. Defaulting `confidence` to `1.0` would read as "the
model was certain" rather than "the provider does not report this", and every
metric built on it would be fiction. The same applies to streaming: Prisma
emits no interim results, so its adapter never emits `PartialTranscript` and
declares `supports_partial_results = False`.

**Streaming is never retried automatically.** The audio has already been
consumed from a one-shot iterator by the time a failure is known, so a retry
would transcribe a tail and present it as the whole utterance. The retry
decision belongs to whoever still holds the audio.

**The fake provider is refused when `APP_ENV=production`.** It returns
scripted transcripts; publishing those as measurements is precisely what rule
one forbids.

### Front ends share services, not messages

The API and the CLI both call `services/`. A domain error that suggests a
remedy must not name one front end's mechanism: `delete_suite` takes a
`cascade_remedy` phrase so the HTTP refusal says `cascade=true` and the CLI
says `--cascade`. Telling a shell user to pass `cascade=true` sends them
looking for a flag that does not exist.

The CLI translates domain errors in `DomainErrorGroup.invoke`, inside the
Typer app — not in `main()`. Doing it in `main()` meant only the console script
got messages and exit codes; every other entry point got a bare `1`.

`app/cli/__init__.py` exports only `app`. Binding the entry function as `main`
there would shadow the `app.cli.main` submodule, so `app.cli.main` would
resolve to a function and patching the module by path would fail.

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
pytest                                  # whole suite (954 tests, 15 live ones deselected)
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
- A class-scoped fixture must not be written as an instance method; pytest 9
  deprecates it, and `filterwarnings = ["error"]` turns that into an error.
  Use a module-level fixture.
- CLI tests drive the real Typer app through `CliRunner`, with
  `app.cli.main.session_scope` rebound to the test's rolled-back transaction.
  Do not test CLI behaviour by calling the command functions directly — that
  skips the argument parsing and the exit codes, which is most of what a CLI
  is.

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

- `main` is the single authoritative branch and holds all approved work.
  Start new work from the latest `main`, on a temporary branch named
  `feature/phase-NN-short-description`. Delete it after integration.
  There is no `develop` branch - it was removed once Phases 1 and 2 were
  integrated into `main`.
- Conventional Commits. Explain **why** in the body, not just what.
- Never force-push or rewrite pushed history.
- Never merge into `main` without being asked, and never integrate a phase
  before the owner has approved it.
- Review `git diff --cached` before committing: no secrets, no build
  artefacts.

## Documentation to keep in sync

| File | When |
|------|------|
| `README.md` | setup, commands, endpoints, environment variables change |
| `docs/ARCHITECTURE.md` | a structural decision is made or revised |
| `docs/DATABASE.md` | the schema changes |
| `docs/SCENARIO_FORMAT.md` | the scenario specification or bundle format changes |
| `docs/CLI.md` | a command, flag, exit code or output format changes |
| `docs/PROVIDERS.md` | a provider contract, capability, limitation or verification status changes |
| `backend/tests/fixtures/audio/README.md` | an audio fixture is added or changed |
| `scenarios/README.md` | a reference scenario is added or changed |
| `docs/DEVELOPMENT_ROADMAP.md` | a phase's scope or status changes |
| `.env.example` | any configuration variable is added or renamed |
| `CLAUDE.md` | these instructions change |

After editing anything in `scenarios/`, regenerate
`scenarios/bundles/indian_language_reference.yaml` (the command is in
`scenarios/README.md`). A test fails if the bundle is stale.

The phase-status tables in `README.md`, `CLAUDE.md` and the roadmap must
agree — they are the first thing a reader checks to learn what actually works.
