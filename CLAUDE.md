# CLAUDE.md

Guidance for AI coding agents working in this repository. Read this before
making changes.

## What this project is

BhashaBench is an automated testing and benchmarking platform for
Indian-language voice bots. It is being built in **15 controlled phases**; see
`docs/DEVELOPMENT_ROADMAP.md`.

**The original 15-phase plan is in force.** Phase 0 (baseline and defect
remediation) is complete locally and awaiting the owner's review; no new
phase starts until it is approved.

| # | Phase | Status |
|---|-------|--------|
| 0 | Baseline & defect remediation | ✅ Complete locally — awaiting owner review |
| 1 | Project foundation | ✅ Complete |
| 2 | Database & scenario engine | ✅ Complete |
| 3 | Scenario library & tooling | ✅ Complete |
| 4 | Speech to text (Gnani Prisma) | ✅ Complete (batch live-verified; streaming not live-verified) |
| 5 | Text to speech (Gnani Timbre) | ✅ Complete (batch; streaming not implemented) |
| 6 | AI caller simulation — Evon | ⛔ Blocked — no published Evon API; deterministic caller delivered |
| 7 | Audio degradation engine | 🟡 Partial |
| 8 | Telephony integration | ⬜ Not started |
| 9 | Real-time conversation engine | 🟡 Partial — sequential turn loop only |
| 10 | Recording & transcription | 🟡 Partial — per-turn artefacts only |
| 11 | Evaluation & judge engine | ⬜ Not started |
| 12 | Reporting & analytics backend | 🟡 Partial — run list and per-run report only |
| 13 | Frontend dashboard | 🟡 Partial — operator workspace, no analytics |
| 14 | CI/CD & safety | ⬜ Not started |
| 15 | Production readiness & competition demo | 🟡 Partial — competition demo only |

The competition renumbered phases in flight. The roadmap's mapping table
translates; historical reports keep the numbering they were written in.
**Phase numbers in this file are the original ones** — for example,
telephony is Phase 8, the real-time engine Phase 9, evaluation Phase 11.

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
convenient. A change that does will be asked to split. Telephony
(Phase 8), real-time orchestration (Phase 9) and evaluation (Phase 11) are
explicitly out of scope until their phase. In particular, do not add a Twilio client or any
telephony bridge, and do not set `CallSession`'s `DIALING`, `NO_ANSWER` or
`BUSY` statuses: an offline simulation must not claim a telephony state.

**Do not add a Gnani Evon client, and do not invent its endpoints or
credentials.** Phase 6's feasibility gate established that no Gnani
text-generation endpoint is published and that the released model has no
hosted inference provider, so there is nothing to cite. Phase 6 therefore
ships a deterministic rule engine, named for what it is. Two things that must
stay true: `evon` is not a registered caller provider (configuring it fails
with an error explaining why), and no code claims Evon is integrated. Do not
add a stub adapter that raises — that advertises Evon as a configurable
option, which is the dishonesty the rule exists to prevent.

Phases 4 and 5 added the Gnani **Prisma** (speech-to-text) and **Timbre**
(text-to-speech) adapters. Every constant either sends is transcribed from the
vendor's published documentation into `prisma_contract.py` or
`timbre_contract.py`. **Never add a provider constant you cannot cite.** Where the vendor's documentation is silent or
self-contradictory, the honest record goes in `DOCUMENTATION_GAPS` and the
capability is declared unsupported — three of Prisma's four output modes are
unsupported for exactly this reason, because their literal wire values are
never quoted.

Phase 6 is the first thing to write to `TestRun`, `CallSession` and
`ConversationTurn`, and it reuses them exactly as Phase 2 shaped them: one
conversation is a `CallSession`, one utterance a `ConversationTurn`, and the
caller's own state lives in the existing JSONB columns under a `caller`
namespace so Phase 8's telephony metadata can share the column. **Phase 6
adds no table and no migration** — keep it that way unless a real column is
needed, and run `alembic check`.

No call is placed, so a conversation opens as `IN_PROGRESS`, never `PENDING`;
`DIALING`, `NO_ANSWER` and `BUSY` are telephony states an offline simulation
must not claim.

Phase 4 still persists no transcript of its own: deciding which turn a loose
transcript belongs to is orchestration (Phase 9). The transcription and speech
endpoints therefore work with PostgreSQL down; the caller endpoints do not.

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
speech/        the text-to-speech subsystem (Phase 5), same shape.
               Reuses transcription/{redaction,retry,audio} rather than
               copying them; promote those three to a shared package when a
               third provider family arrives.
speech/providers/
               one adapter per vendor, same rule
caller/        the caller engine (Phase 6): state machine, transcript
               analysis, decision validation, orchestration, artefacts
caller/providers/
               one caller strategy per module. Deterministic only; there is
               no Evon adapter and adding a non-functional one is forbidden
pipeline/      the end-to-end voice pipeline (Phase 7): run engine, audio
               degradation, execution modes, artefact records
pipeline/bots/ one bot adapter per module. Neither shipping adapter opens a
               socket, and the default is the one that sends audio nowhere
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

**A provider closes only a client it created.** `get_service_factory` builds a
new provider per request, so `get_transcription_service` is a `yield`
dependency that closes it in a `finally` - the same shape as `get_db`. A
client passed in via `client=` belongs to its injector and is left open. If you
ever make the provider process-wide, move the close into the lifespan and
delete the per-request one; do not do both.

**Report only what the bytes establish.** A synthesis result's
`sample_rate_hz`, `channels` and `duration_seconds` are read from the returned
audio, never copied from the request - and the requested rate is kept alongside
so a provider that ignored it is visible. For a container we cannot inspect
without a decoder (MP3, OGG) they stay `None`, and the API omits the header
rather than echoing the request back as if it were a measurement.

**A WAV with `0xFFFFFFFF` size fields is valid, not truncated.** That is the
convention for a writer that does not know the final length, and Timbre uses it
for every utterance. `app/transcription/audio.py` treats the sentinel as
"length unknown" and measures from the bytes present, while still rejecting a
*plausible* declared length with bytes missing. Do not collapse those two cases
again - the first live call was what found it, because the stdlib `wave` writer
always back-fills the true length and so no fixture ever has that header.

**Live provider tests are function-scoped and disable keep-alive.** Each drives
its own `asyncio.run`, which closes its loop; a pooled connection outliving
that loop fails the *next* test with `RuntimeError: Event loop is closed`, and
an orphaned socket reaches pytest as `PytestUnraisableExceptionWarning`, which
`filterwarnings = ["error"]` turns into a failing exit code even when the test
passed. Both have happened. Keep one provider per test.

### The caller engine

Full design in `docs/CALLER.md`. Six rules that are easy to break:

**Rule order is the design.** `app/caller/providers/deterministic.py`
evaluates rules top to bottom, first match wins, and the order encodes
priority. A refusal is handled before a question, because a bot that says "I
cannot help, what is your number?" has refused and that is the finding worth
recording. More subtly, `caller.confirmed_close` must stay **above**
`bot.asked_for_identifier`, `bot.asked_unknown`, `bot.confirmed` and
`fallback.clarify`: every rule above it targets a state `CONFIRMING` can
legally reach and every rule below targets one it cannot, so moving it down
makes a bot answering a read-back with "yes, that is correct" drive
`confirming -> confirming` and kill the conversation. That shipped broken once.

**The transition table is the authority, and it is swept.**
`test_caller_rules.py` drives every non-terminal state against every shape of
reply and asserts the resulting transition is legal. If you add a rule or a
state, that test is what tells you whether the table still agrees — do not
weaken it. `ALLOWED[INTRODUCING]` omitting `CONFIRMING` was a real defect: a
bot that answered the objective in its first reply had the read-back rejected.

**The caller never sees `expected_outcomes`.** `CallerContext` has no such
field, deliberately, so the caller cannot recite what it is marked against.
Outcome matching happens in the orchestrator's `report()`, and
`outcomes_observed` is a keyword indicator, not a score — its own API
description says so, because evaluation is Phase 11.

**Validation runs before synthesis, always.** `CallerService.validate`
rejects an empty or overlong utterance, an illegal transition, nine
instruction-leak patterns, and any identifier-shaped digit run not traceable
to a known fact. The rule engine structurally cannot fail most of these; they
exist for the model provider that replaces it, which is why they live in the
service and not in the provider. A provider cannot be trusted to police
itself. The identifier threshold is five digits, not four, so a caller can say
"I registered in 2019" — do not lower it without reading the comment.

**A transcription failure is a null turn; a bad upload is a 4xx.** Three
outcomes that look alike and must not be merged: the bot said nothing (empty
transcript, a bot defect), we could not transcribe it (`content=None` plus a
`transcription_error`, our problem, conversation continues), and the request
was malformed (re-raised, nothing persisted, so a `.txt` upload does not get
`200 OK` and a null turn indistinguishable from silence). The split lives in
`_REQUEST_DEFECTS` in the orchestrator.

**Redact provider error text.** Both the transcription and synthesis failure
paths put a string into `turn_metadata`, which is also returned on the API
surface. Pass it through `redact` — these two sites shipped unredacted once,
the same class of defect Phase 4 fixed twice.

### The pipeline

Full design in `docs/PIPELINE.md`. Six rules that are easy to break:

**The execution mode is the honesty control.** `OFFLINE_SIMULATION` moves no
audio, `AUDIO_FIXTURE_TEST` runs every stage with the bot stubbed, and only
`EXTERNAL_BOT_TEST` may be described as testing a bot. `TELEPHONY_TEST` exists
in the enum and is excluded from `IMPLEMENTED_MODES`, so a run cannot be
created in it — an enum member that cannot be used is the honest record of the
gap. Do not add it to that set until telephony genuinely exists.

**`bot_audio_externally_received` must stay computed from the replies, not from
the mode.** A single fixture reply clears it permanently, which is what makes a
mislabelled `external_bot_test` visible. Deriving it from the requested mode
would turn it into a restatement of the label it exists to check.

**The engine wraps Phase 6; it does not reimplement it.** `next_caller_turn`
decides and synthesises, `submit_bot_audio` transcribes and persists. The
engine owns the degradation, the adapter exchange and the audio validation
between them. Two conversation engines would disagree eventually.

**The original artefact always survives.** `degrade()` returns new bytes and
writes nothing, and a processed artefact records `derived_from`. A degraded file
whose source is gone is not evidence. The variant suffix is a whitelist, like
every other path component — no caller-supplied string reaches a filename.

**A seed is required for anything stochastic**, enforced in
`DegradationConfig.validate`. Noise is scaled from the signal's own RMS so the
stated SNR holds for that utterance, and the achieved ratio is asserted to
better than 0.5 dB rather than trusted. Nothing here claims simulated noise is
a field recording.

**The concurrency limiter is process-wide, and must stay that way.**
`slots_for_limit` is `lru_cache`d on the limit so every request shares one
instance; a per-request limiter counts to one and enforces nothing, which is
how `PIPELINE_MAX_CONCURRENT_RUNS` spent a whole phase unused. It refuses with
503 rather than queueing, it releases in a `finally` so cancellation and
timeouts cannot leak a slot, and `_admitted` is re-entrant because
`supply_bot_audio` calls `run_to_completion` and would otherwise 503 against
its own slot. Do not swap it for an `asyncio.Semaphore`: a waiting semaphore
binds its waiters to one event loop, and this one is shared across the loops
that `asyncio.run` creates.

**Three failures that must not be merged:** the bot said nothing (empty
transcript, a bot defect), we could not transcribe it (`content=None` plus a
`transcription_error`, our problem, the run continues), and the audio was not
decodable (the run fails `audio_validation_failed`). On the manual endpoint a
malformed *upload* is refused with a 4xx and leaves the run waiting, so the
operator can retry — a mistyped filename is not a reason to discard a
conversation.

### The frontend (Phase 13, delivered as competition Phase 8)

Two surfaces, one visual system, separate chrome. The root layout carries
the document and the fonts only; `/` supplies a marketing header and `/app`
supplies the operator rail.

```
frontend/
  app/page.tsx          the public site
  app/app/              the workspace: overview, runs, new-test,
                        scenarios, providers
  components/ui/        primitives, the status vocabulary, loading states
  components/shell/     sidebar, mobile drawer, page header, wordmark
  components/domain/    runs table, conversation, audio, stage timeline,
                        evidence, filters, the new-test form
  components/marketing/ public header/footer, pipeline diagram
  lib/api/              the ONLY place the frontend calls the API
```

Six rules that are easy to break:

**`lib/api/client.ts` is the only module that calls the API.** One `request`
function owns the timeout, the error envelope and query serialisation. There
is no mock mode and no fallback data: a failed call renders an error state,
because returning plausible data when the backend is down makes a broken
deployment look like a working one.

**`lib/api/types.ts` is transcribed, not invented.** No field appears there
that the API does not return, and a field the API returns as `null` because
a provider does not report it is typed `| null` and rendered "not reported".
A misspelled query parameter is *ignored* by FastAPI, not rejected — which is
how a search box can appear to filter while showing everything.

**The honesty fields are rendered structurally, not as copy.**
`uses_language_model`, `bot_audio_externally_received`, `measurement_note`,
`evon_status`, `telephony_status` and `settings_not_enforced` exist so a
client cannot overclaim. A missing `settings_not_enforced` means unknown, never
"everything was enforced".
`RunEvidence` derives its caveats from the run, never from the mode label —
which is what makes a mislabelled `external_bot_test` visible.

**Three failure modes stay three things.** An empty transcript is the bot
saying nothing; `text: null` plus a `transcription_error` is our failure; a
run failing `audio_validation_failed` is neither. Merging any two of them
attributes our fault to the system under test.

**The waveform is drawn from decoded audio or not at all.** No synthetic
fallback. A generated waveform is a picture of a sound that does not exist.

**`cacheComponents` is on, so `export const dynamic` is forbidden** — it
errors at build. Data access goes behind `<Suspense>` with a skeleton, which
is what keeps every route a static shell with streamed content. `min-w-0` on
grid and flex children is load-bearing: without it a panel holding a
`min-w-max` table inflates its own track and the page scrolls sideways.

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

### Counting the API surface

**Never count endpoints by walking `app.routes`.** The installed FastAPI
mounts included routers lazily as internal `_IncludedRouter` objects instead
of flattening them onto the application, so the walk yields 7 entries — the
four docs routes plus `/` and `/health` — and reads as "the v1 API is not
mounted". It is mounted.

The generated OpenAPI document is the authority, and `scripts/api_surface.py`
is the single place the documented figures come from:

```bash
python scripts/api_surface.py          # 36 paths, 44 operations
python scripts/api_surface.py --json   # machine-readable
```

It counts operations by subtracting the Path Item Object's fixed
non-operation fields (`$ref`, `summary`, `description`, `servers`,
`parameters`) rather than matching a method allow-list, and it reports any key
it cannot classify instead of silently miscounting. One WebSocket route
(`/api/v1/transcription/stream`) is deliberately absent from the schema —
OpenAPI 3.1 cannot describe a WebSocket — so it is counted separately in prose,
never folded into the 35.

If the numbers change, run the script and update `README.md` and this file
together. Do not hardcode a figure the script does not produce.

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
pytest                                  # 2073 collected; 2032 pass, 41 live ones skipped
pytest backend/tests/test_database.py   # one module
ruff check . && ruff format --check .   # from the repository root
```

- `filterwarnings = ["error"]` is set. A new deprecation warning **fails the
  suite** — fix the cause rather than widening the filter. In particular use
  Starlette's current status constant names (`HTTP_413_CONTENT_TOO_LARGE`,
  `HTTP_422_UNPROCESSABLE_CONTENT`).
- **Ruff's scope is the tracked Python source, and that is deliberate.**
  `include` is set explicitly in `pyproject.toml` **without `*.md`**, because
  Ruff's default includes Markdown and formats the Python blocks inside it —
  which made `ruff format --check .` a gate over prose that could fail with no
  Python touched. `.agents` and `.claude` are excluded as untracked local
  tooling. The invariant: Ruff's scope equals `git ls-files "*.py"` plus
  `pyproject.toml`. Check it with `ruff check . --show-files`, and do not
  re-add `*.md` or drop those excludes without re-reading this.
- **Never quote a formatted-file count you have not just measured.** The
  figure moved three times across phases 7 and 8 because the gate's scope was
  growing silently, not because code was added.
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

- **`main` only.** Work is committed directly on `main`; do not create
  feature branches. There is no `develop` branch - it was removed once
  Phases 1 and 2 were integrated, and its history is preserved in `main`.
- **Never push without the owner's explicit approval.** Commit locally,
  report, and wait; approval for one push does not extend to the next.
- **Stage explicit paths**, never `git add .` or `git add -A`. Local agent
  tooling (`.agents/`, `.claude/`, `skills-lock.json`) is excluded through
  `.git/info/exclude` and must never be committed.
- One concern per commit. Never bundle unrelated changes; split a file
  that mixes concerns rather than committing it whole.
- Conventional Commits. Explain **why** in the body, not just what.
- Never force-push or rewrite pushed history.
- Never start a phase before the owner has approved the previous one.
- Roll back with `git revert`, never with `reset` on pushed history.
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
| `docs/CALLER.md` | a caller state, rule, validation check, limit or endpoint changes |
| `docs/PIPELINE.md` | an execution mode, degradation profile, bot adapter, artefact rule or run endpoint changes |
| `docs/FRONTEND.md` | a route, design token, primitive or API-client rule changes |
| `backend/tests/fixtures/audio/README.md` | an audio fixture is added or changed |
| `scenarios/README.md` | a reference scenario is added or changed |
| `docs/DEVELOPMENT_ROADMAP.md` | a phase's scope or status changes |
| `.env.example` | any configuration variable is added or renamed |
| the path/operation counts in `README.md` and this file | an endpoint is added or removed — rerun `python scripts/api_surface.py`, never hand-count |
| the test counts in `README.md` and this file | tests are added or removed — rerun `pytest --collect-only -q`, and keep the per-module table summing to the collected total |
| `CLAUDE.md` | these instructions change |

After editing anything in `scenarios/`, regenerate
`scenarios/bundles/indian_language_reference.yaml` (the command is in
`scenarios/README.md`). A test fails if the bundle is stale.

The phase-status tables in `README.md`, `CLAUDE.md` and the roadmap must
agree — they are the first thing a reader checks to learn what actually works.
