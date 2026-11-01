# Phase 2 — Database & Scenario Engine: Completion Report

| | |
|---|---|
| **Phase** | 2 of 15 — Database & Scenario Engine |
| **Date** | 2026-11-02 (correction and final verification pass) |
| **Repository** | <https://github.com/YushBytes/BhashaBench> (private) |
| **Branch** | `feature/phase-02-database-scenarios` |
| **Base** | `develop` @ `e69930c` |
| **Commits on this branch** | **9** — 7 implementation/documentation + 2 from the correction pass. 10 Phase 1 commits preserved beneath them. |
| **Tracked files** | 93 (was 61 after Phase 1) |
| **Tests** | **246 passing**, 0 failed, 0 skipped (was 35 after Phase 1) |
| **Status** | **READY FOR OWNER REVIEW.** Not approved — approval is the owner's decision. |

> **Commit-count correction.** An earlier revision of this report stated
> "5 + 1 report = 6" commits. That was wrong: it omitted both documentation
> commits. The branch carried **7** commits before this correction pass, and
> **9** after it. The authoritative list is in §9, and `git log --oneline` is
> the final word.

> Phase 1's report is preserved in git history at `e69930c`. This document
> replaces it to describe the current phase.

---

## 1. Implemented features

### Database layer

- Five SQLAlchemy 2.0-style typed declarative models with UUID primary keys,
  timezone-aware timestamps, explicit `ondelete` on every foreign key, and
  CHECK-constrained status columns.
- A lazily-created, cached engine with `pool_pre_ping`, and a request-scoped
  session dependency that rolls back and closes in a `finally`.
- Alembic migrations owning the schema. The application never calls
  `create_all()`.
- The Phase 1 database health placeholder replaced with a real `SELECT 1`
  probe.

### Scenario engine

- `ScenarioSpec`: a strict Pydantic schema for the scenario YAML format —
  `extra="forbid"` throughout, every number range-checked, frozen models.
- A YAML loader using `yaml.safe_load` only, with size, node-count and nesting
  limits, and validation errors carrying dotted field paths.
- Serialisation back to canonical YAML that itself re-validates.
- Persistence of the validated specification as a JSONB document.

### REST API

Nine endpoints under the existing `/api/v1` prefix, with the Phase 1 error
envelope extended to cover the new failure modes.

### Layering

A repository layer holding every SQL statement, and a service layer holding
the rules and owning transaction boundaries. Route handlers are thin.

### Not implemented, by design

No telephony, audio processing, transcription, speech synthesis, caller
simulation, evaluation or test execution. `TestRun`, `CallSession` and
`ConversationTurn` are foundational schema; nothing writes to them.

---

## 1a. Correction pass — recursive YAML aliases

Completed after the implementation above, in response to an independent
review. Reported separately from the Phase 2 implementation work because it
was verified separately.

### What was actually wrong

`yaml.safe_load` is safe from code execution but still builds a genuinely
cyclic object graph from a recursive alias:

```yaml
name: recursive-test
language: hi-IN
persona: &persona
  identity: *persona
```

This was confirmed empirically before any code was changed —
`document["persona"]["identity"] is document["persona"]` evaluates to `True`.

**The predicted `RecursionError` did not actually occur.** `_measure`
increments depth at every level, so a cycle tripped `MAX_YAML_DEPTH` (20) and
returned a controlled `ScenarioTooLargeError`. The review's underlying concern
was nonetheless valid, for two measured reasons:

1. **The error misdiagnosed the fault.** It reported *"YAML nesting exceeds
   the maximum depth of 20"*, which sends an author looking for deep nesting
   that does not exist.
5. **The protection was incidental, not designed.** It held only because
   `MAX_YAML_DEPTH` happened to be smaller than Python's recursion limit.
   Raising `MAX_YAML_DEPTH` to 5000 and re-running the same input produced a
   bare `RecursionError` — verified before the fix was written:

   ```
   MAX_YAML_DEPTH=20      -> ScenarioRecursionError (controlled)   [after fix]
   MAX_YAML_DEPTH=5000    -> RecursionError (uncontrolled)         [before fix]
   ```

### The fix

`_measure` now carries an `active` set holding the `id()` of every container on
its current recursion path, and raises when it re-enters one.

| Requirement | How it is met |
|---|---|
| Detect cycles by object identity | `id(node)` for every `dict`/`list`/`tuple` |
| Active recursion-path set, not seen-ever | Ids are discarded once a subtree completes, so sibling references to a shared anchor are not rejected |
| Controlled, documented error | `ScenarioRecursionError`, subclassing `ScenarioSyntaxError` |
| Preserve the 256 KiB input cap | Unchanged |
| Preserve the 10,000 node cap | Unchanged |
| Preserve the depth limit of 20 | Unchanged |
| No unbounded recursion | Depth limit and cycle check both bound the walk |
| No unhandled `RecursionError` at the API | Cycle check, plus a defensive `RecursionError` → `ScenarioRecursionError` conversion in `parse_yaml` |
| Normal non-cyclic anchors still work | Three tests: shared anchor, 50-way sibling fan-out, diamond DAG |
| Useful, consistent error messages | Names the self-reference; maps to the existing 422 `yaml_syntax_error` |

Ids are discarded in a `finally` block, so an exception raised deeper in the
walk cannot leave a stale id behind and make a later sibling reference look
like a cycle.

`ScenarioRecursionError` subclasses `ScenarioSyntaxError` deliberately: the
existing exception handler already maps that class to HTTP 422
`yaml_syntax_error`, so **the public API contract is unchanged** while callers
and tests can still catch the specific type.

### Scope of the change

Two files for the fix, one for an audit finding. No model, migration, schema,
route or public function signature was touched.

```
backend/app/services/scenario_loader.py | 109 +++++++++++++++---
backend/tests/test_scenario_spec.py     | 171 +++++++++++++++++++++++
.gitignore                              |  20 ++++
```

---

## 2. Database schema and relationships

```mermaid
erDiagram
    TEST_SUITES ||--o{ SCENARIOS : "contains"
    TEST_SUITES ||--o{ TEST_RUNS : "is executed by"
    TEST_RUNS ||--o{ CALL_SESSIONS : "places"
    SCENARIOS ||--o{ CALL_SESSIONS : "is exercised by"
    CALL_SESSIONS ||--o{ CONVERSATION_TURNS : "records"
```

| Table | Purpose | Written to in Phase 2? |
|-------|---------|------------------------|
| `test_suites` | Named collection of scenarios | ✅ Yes |
| `scenarios` | One test case; validated spec as JSONB | ✅ Yes |
| `test_runs` | One execution of a suite | ❌ Foundational only |
| `call_sessions` | One telephony call in a run | ❌ Foundational only |
| `conversation_turns` | One utterance in a call | ❌ Foundational only |

### Delete behaviour

| Foreign key | Behaviour | Why |
|---|---|---|
| `scenarios.suite_id` → `test_suites` | `CASCADE` | A suite's scenarios belong to it |
| `test_runs.suite_id` → `test_suites` | `CASCADE` | Same |
| `call_sessions.test_run_id` → `test_runs` | `CASCADE` | Same |
| `conversation_turns.call_session_id` → `call_sessions` | `CASCADE` | Same |
| `call_sessions.scenario_id` → `scenarios` | **`RESTRICT`** | A scenario exercised by a recorded call must not vanish and leave that result uninterpretable |

### Constraints

| Constraint | Table | Enforces |
|---|---|---|
| `uq_test_suites_name` | `test_suites` | Suite names are globally unique |
| `uq_scenarios_suite_id_name` | `scenarios` | Scenario names unique **per suite**, not globally |
| `uq_conversation_turns_call_session_id_turn_index` | `conversation_turns` | One turn per index per call |
| `ck_test_runs_run_status` | `test_runs` | Status is one of the five valid values |
| `ck_call_sessions_call_status` | `call_sessions` | Status is one of the seven valid values |
| `ck_conversation_turns_speaker` | `conversation_turns` | Speaker is `caller` or `bot` |
| `ck_test_runs_finished_at_matches_status` | `test_runs` | A terminal run has a finish time; a non-terminal one does not |
| `ck_test_runs_finished_after_started` | `test_runs` | Time runs forwards |
| `ck_call_sessions_ended_after_started` | `call_sessions` | Time runs forwards |
| `ck_call_sessions_duration_non_negative` | `call_sessions` | Duration ≥ 0 |
| `ck_conversation_turns_turn_index_non_negative` | `conversation_turns` | Index ≥ 0 |

### Key schema decisions

| # | Decision | Reasoning |
|---|----------|-----------|
| 1 | **Scenario spec as one JSONB column, not five tables** | It is always read and written whole, never queried field-by-field, and will keep gaining fields. Normalising would mean five more tables and a migration per new option, for no query benefit. It is not unvalidated: every write passes `ScenarioSpec`. |
| 2 | **`name`/`description`/`language` projected into real columns** | These are what the API filters, sorts and enforces uniqueness on — none of which JSONB does efficiently. Written in one place (`_spec_to_columns`) so they cannot drift from the spec. |
| 3 | **`spec_version` stored on every row** | A future schema change can identify and migrate old documents rather than guess at their shape. |
| 4 | **Constraint naming convention on `MetaData`** | Without it PostgreSQL invents names and Alembic cannot reliably drop them in a downgrade — the usual cause of one-way migrations. |
| 5 | **Enums as CHECK-constrained VARCHAR, not PostgreSQL `ENUM`** | A Postgres enum cannot have a value removed and needs DDL to add one. See §10 limitation 1 for the defect this initially hid. |
| 6 | **Synchronous sessions** | Phase 1 established the `psycopg` sync URL, Alembic runs synchronously, and FastAPI runs a `def` handler in a worker thread — so a sync session does not block the event loop. An async engine would add a second concurrency model, a greenlet dependency and async-aware migrations for no present benefit. |
| 7 | **`lazy="raise_on_sql"` on unbounded relationships** | An accidental N+1 fails loudly in development rather than quietly degrading production. |
| 8 | **`passive_deletes=True`** | Lets the database's `ON DELETE CASCADE` do the work instead of SQLAlchemy loading every child row first. |
| 9 | **`alembic.ini` in `backend/`, not the repo root** | The backend image copies only `backend/`, so the file must live there to be present in the container. |
| 10 | **Alembic reads the URL from settings, not `alembic.ini`** | A password never enters a committed file, and migrations always target what the application itself would connect to. |
| 11 | **Domain errors, not `HTTPException`, in services** | Service code stays usable outside a request, and the HTTP mapping lives in exactly one place. |
| 12 | **Write endpoints accept YAML, not a JSON mirror** | One authoring format means two schemas cannot drift, and the API validates exactly what a user would put in a file. |
| 13 | **`/scenarios/validate` returns 200 for invalid YAML** | The request to validate succeeded; `valid` carries the verdict. A 4xx would make "your YAML is wrong" indistinguishable from "the endpoint is broken". |
| 14 | **Duplicate checked before insert *and* `IntegrityError` caught** | The check and the insert are not atomic; the database constraint is what actually guarantees uniqueness. |
| 15 | **Health probe injected, not imported** | Imported directly it always used the process-wide engine from global settings, so a test overriding `Settings` still reported on the developer's own database — healthy for the wrong reason. |
| 16 | **`scenario_count` from SQL `COUNT`** | Measuring `len(suite.scenarios)` meant loading every scenario row to produce one number, and the collection could be stale. |

Full reasoning: [`docs/DATABASE.md`](docs/DATABASE.md).

---

## 3. Migration details

| | |
|---|---|
| **Revision** | `3e3312d5327a` |
| **File** | `backend/alembic/versions/20261101_1725_3e3312d5327a_create_suite_scenario_and_execution_tables.py` |
| **Down revision** | none (initial) |
| **Tables created** | 5 |
| **Indexes created** | 9 |

### Verification

```
$ cd backend

$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 3e3312d5327a, Create the suite, scenario and execution tables.

$ alembic downgrade base
INFO  [alembic.runtime.migration] Running downgrade 3e3312d5327a -> , Create the suite, scenario and execution tables.
   tables after downgrade: ['alembic_version']

$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 3e3312d5327a, Create the suite, scenario and execution tables.
   tables: ['alembic_version', 'call_sessions', 'conversation_turns', 'scenarios', 'test_runs', 'test_suites']

$ alembic check
No new upgrade operations detected.
```

| Check | Result |
|-------|--------|
| `upgrade head` against the Compose database | ✅ |
| `downgrade base` — fully reversible | ✅ Only `alembic_version` remains |
| Re-`upgrade head` after downgrade | ✅ |
| `alembic check` — no model/migration drift | ✅ |
| Migration run **inside the container** | ✅ `3e3312d5327a (head)` |
| Existing database volume deleted or reset | ❌ **No.** `bhashabench-postgres-data` untouched throughout |
| Destructive shortcuts (`stamp`, manual DDL) used | ❌ No. The one time the DB was stamped at a deleted revision, the migration was restored from git and downgraded properly |

A `post_write_hooks` entry runs `ruff format` and `ruff check --fix` on every
generated migration, so a migration cannot be the one file that fails CI.

---

## 4. Scenario YAML schema and example

```yaml
name: appointment_booking
description: Test whether a voice bot can book a doctor appointment.
language: hi-IN

persona:
  identity: Working professional
  speaking_style: polite
  traits:
    - impatient
    - prefers short responses

goal:
  objective: Book an appointment for tomorrow.
  max_turns: 15

known_facts:
  patient_name: Rahul
  preferred_time: "10 AM"

expected_outcomes:
  - Confirm appointment date
  - Confirm appointment time
  - Confirm patient name

audio:
  noise_profile: clean
  snr_db: 30
```

A fully commented reference file covering every field is at
`scenarios/appointment_booking.yaml`, and it is loaded and validated as part
of the Docker verification in §8.

### Schema summary

| Section | Required | Notable validation |
|---------|----------|--------------------|
| `name` | yes | `^[a-z0-9][a-z0-9_-]*$`, max 200, unique per suite |
| `language` | yes | Well-formed BCP 47 **and** in the 13-language supported set |
| `persona` | yes | `identity` required; `speaking_style` enum; ≤10 traits, no duplicates |
| `goal` | yes | `objective` required; `max_turns` 1–100 (default 20) |
| `known_facts` | no | ≤50 entries; **string values only, not coerced** |
| `expected_outcomes` | yes | 1–20 entries, no duplicates |
| `audio` | no | `snr_db` 0–40, `packet_loss_percent` 0–30, `noise_profile` enum |
| `constraints` | no | `max_silence_seconds` 0–60, phrase lists ≤20 |

### Security

| Measure | Value |
|---------|-------|
| Parser | `yaml.safe_load` **only** — never `yaml.load` |
| Max input size | 256 KiB, checked before parsing |
| Max node count | 10,000, checked **after** parsing (catches anchor/alias bombs that stay under the byte cap) |
| Max nesting depth | 20 |
| Unknown fields | Rejected (`extra="forbid"`) |

A test asserts that a `!!python/object/apply:pathlib.Path.touch` payload is
refused **and** that the file it targets does not exist afterwards.

Full reference: [`docs/SCENARIO_FORMAT.md`](docs/SCENARIO_FORMAT.md).

---

## 5. API endpoints

| Method | Path | Success | Error cases |
|--------|------|---------|-------------|
| `POST` | `/api/v1/suites` | 201 | 409 duplicate name, 422 invalid body |
| `GET` | `/api/v1/suites` | 200 paginated | 422 bad pagination |
| `GET` | `/api/v1/suites/{suite_id}` | 200 + `scenario_count` | 404, 422 bad UUID |
| `POST` | `/api/v1/suites/{suite_id}/scenarios` | 201 | 404 suite, 409 duplicate, 413 oversized, 422 invalid YAML/schema |
| `GET` | `/api/v1/suites/{suite_id}/scenarios` | 200 paginated summaries | 404 suite |
| `GET` | `/api/v1/scenarios/{scenario_id}` | 200 + full spec | 404, 422 bad UUID |
| `PUT` | `/api/v1/scenarios/{scenario_id}` | 200 | 404, 409 name clash, 422 invalid |
| `DELETE` | `/api/v1/scenarios/{scenario_id}` | 204 | 404, 409 if referenced by call history |
| `POST` | `/api/v1/scenarios/validate` | 200 with verdict | 413 oversized |

Pagination: `limit` (1–100, default 20) and `offset` (≥0), with `total` in
every page response. Capped so a client cannot request a whole table at once.

### Error envelope

Unchanged in shape from Phase 1 — `{"error": {type, message, status_code}}` —
extended with new types:

| Status | `type` |
|--------|--------|
| 404 | `not_found` |
| 409 | `conflict` |
| 413 | `payload_too_large` |
| 422 | `validation_error`, `yaml_syntax_error`, `scenario_validation_error` |
| 500 | `internal_error` (details logged, never returned) |

**Authentication and authorization are not implemented.** None existed in the
project before this phase, and a partial scheme would be worse than none. All
endpoints are unauthenticated. This is deferred to Phase 15 and recorded in
§10.

---

## 6. Test results

```
$ pytest
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\ayush\OneDrive\Desktop\BhashaBench
configfile: pyproject.toml
testpaths: backend/tests
collected 246 items
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 87%]
..............................                                           [100%]
246 passed in 11.70s
```

Focused run of the new tests first, as required:

```
$ pytest backend/tests/test_scenario_spec.py -k "Recursive or NonCyclic" -v
12 passed, 95 deselected in 0.16s
```

**0 failed, 0 skipped, 0 xfailed** - the database was available, so nothing
was skipped. 234 -> 246 is the 12 new regression tests; no existing test was
removed, weakened or renamed to accommodate the fix.

| Module | Tests | Covers |
|--------|-------|--------|
| `test_health.py` | 16 | Root, liveness, versioned health; the probe reachable **and** unreachable; the endpoint still answering 200 with the database down; the error envelope |
| `test_config.py` | 14 | Defaults, env overrides, list parsing, validation failures, production behaviour, caching |
| `test_app_metadata.py` | 9 | App metadata, the exact OpenAPI path set, the application factory |
| `test_scenario_spec.py` | 107 | Valid/minimal YAML, syntax errors, empty and non-mapping documents, invalid UTF-8, unsafe payloads, **recursive/cyclic aliases (12 new)**, size/node/depth limits, every validation rule, duplicates, round-tripping, file loading |
| `test_database.py` | 37 | Connection, migrated schema shape, model creation, relationships, FK delete behaviour, every constraint, transaction rollback and savepoints |
| `test_api_suites_scenarios.py` | 63 | All nine endpoints, pagination stability, duplicates per suite, unknown ids, malformed UUIDs, oversized bodies, envelope consistency, no internal leakage |
| **Total** | **246** | |

### Test isolation

Database tests run against a **real PostgreSQL**, not SQLite: the schema uses
JSONB, native UUIDs and `ON DELETE RESTRICT`, none of which SQLite models
faithfully.

The fixtures create a dedicated `bhashabench_test` database, migrate it with
Alembic — exercising the migration on every run — and wrap each test in a
transaction that is rolled back. The developer's own database is never
touched, and the test database is dropped at session end.

### Environmental limitation handling

Database tests are **never silently skipped**. With PostgreSQL unreachable:

```
$ BHASHABENCH_TEST_DATABASE_URL=postgresql+psycopg://nobody:nothing@127.0.0.1:59999/absent pytest
SKIPPED [1] backend\tests\test_database.py:550: PostgreSQL unreachable at
127.0.0.1:59999 (OperationalError). Database-backed tests were SKIPPED, not
passed. Start it with: docker compose up -d db

137 passed, 97 skipped in 5.63s
```

Plus a session-end banner. The 137 pure-logic tests still run. A 3-second
connect timeout keeps this path fast — it was 132s before the timeout was
added.

---

## 7. Lint and formatting results

```
$ ruff check .
All checks passed!

$ ruff format --check .
54 files already formatted
```

**No type checker is configured** in this repository - there is no mypy,
pyright or pyre configuration in `pyproject.toml`, `requirements-dev.txt` or
any standalone config file. Ruff's `ANN` rules enforce that annotations are
*present*; nothing checks that they are *correct*. Static type checking is
therefore reported as **not run, because not configured** - not as passing.

The existing Phase 1 Ruff configuration is unchanged — same rule selection
(including `ANN` type-annotation enforcement), same 100-character line length.
No rule was disabled or file excluded to make Phase 2 pass.

Findings fixed properly rather than suppressed during this phase: `I001`
import ordering, `SIM300`, `RUF043` (regex `match=` patterns made raw),
`UP046` (`Generic[T]` → PEP 695 `class Page[T]`), `E501`, and `RUF100`.

`filterwarnings = ["error"]` remains in force. This caught two deprecated
Starlette status constants (`HTTP_413_REQUEST_ENTITY_TOO_LARGE`,
`HTTP_422_UNPROCESSABLE_ENTITY`) at import time; both were replaced with their
current names rather than filtered.

---

## 8. Docker verification

### Image build

```
$ docker compose build backend
Successfully installed ... alembic-1.20.1 psycopg-3.3.6 psycopg-binary-3.3.6
  pydantic-2.14.2 pyyaml-6.0.3 sqlalchemy-2.1.6 ...
#18 naming to docker.io/library/bhashabench-backend:latest done
BUILD_EXIT=0
```

Every pinned constraint resolved to the intended version.

### Stack startup

```
$ docker compose up -d
 Container bhashabench-db       Healthy
 Container bhashabench-backend  Started
 Container bhashabench-backend  Healthy

bhashabench-backend | Up 6 seconds (healthy)
bhashabench-db      | Up 4 hours (healthy)
bhashabench-frontend| Up 2 hours
```

### Migrations in the container

```
$ docker compose exec backend alembic upgrade head
$ docker compose exec backend alembic current
3e3312d5327a (head)
```

### Tests in the container

```
$ docker compose exec backend python -m pytest tests
234 passed in 8.13s
```

*(That figure is from the original Phase 2 verification, before the 12
recursive-alias regression tests existed. The correction pass re-ran the
same command and got 246 — see below.)*

All 234 pass inside the container against the containerised PostgreSQL —
including every database and API test.

### Live API verification through Docker

| Check | Result |
|-------|--------|
| `GET /api/v1/health` | `ok`; `database: ok — Connected; SELECT 1 succeeded.` |
| `POST /api/v1/suites` | 201, UUID returned |
| `POST .../scenarios` from the reference YAML file | 201; `appointment_booking`, `hi-IN`, `spec_version 1`, `snr 18.0` |
| Quoted numeric fact survives storage | ✅ `phone_last_four: '0042'` — leading zero intact |
| `GET /api/v1/suites/{id}` | `scenario_count: 1` |
| `GET .../scenarios` | `total: 1` |
| Duplicate scenario | **409** |
| Unsafe `!!python/object/apply` YAML | `valid: false`, `yaml_syntax` |
| Invalid schema | `valid: false`, field paths `language` and `audio.snr_db` |
| `DELETE /api/v1/scenarios/{id}` | **204**, then **404** |

Smoke-test data was removed afterwards; the development database is back to
`suites=0 scenarios=0`.

### Correction-pass Docker verification

The backend image was rebuilt with the corrected loader and the container
recreated (`BUILD_EXIT=0`), then re-verified:

| Check | Result |
|-------|--------|
| Backend container health | `healthy` |
| `alembic current` in container | `3e3312d5327a (head)` |
| `GET /api/v1/health` | aggregate `ok`; `database: ok` |
| Full suite in container | **246 passed in 10.21s** |
| Focused recursive tests in container | **12 passed** |
| Valid scenario `POST` (reference file) | **201** |
| Valid scenario `GET` | **200**, `snr=18.0` |
| Invalid YAML `POST` | **422** `yaml_syntax_error`, with line and column |
| **Recursive alias `POST`** | **422** `yaml_syntax_error`, message names the self-reference |
| **Recursive alias to `/scenarios/validate`** | **200**, `valid: false`, error on `<document>` |
| **Nested recursive alias (list)** | **200**, `valid: false` |
| `RecursionError` or traceback in backend logs | **0 matches** |

No 500 was produced by any malformed input, and no stack trace reached a
client.

### Unrelated containers

`whistledrop-db`, `whistledrop-db-test` and `novaflow-pytest-mongo` were not
stopped, restarted or deleted at any point. The
`bhashabench-postgres-data` volume was never removed.

---

## 9. GitHub branch and commit details

| | |
|---|---|
| **Repository** | <https://github.com/YushBytes/BhashaBench> (private) |
| **Branch** | `feature/phase-02-database-scenarios` |
| **Branched from** | `develop` @ `e69930c` |

### Phase 2 commits, oldest first

| # | Hash | Commit | Changes |
|---|------|--------|---------|
| 1 | `dcfd34c` | `feat(db): add SQLAlchemy models, Alembic migrations and session management` | 17 files, +1208 −12 |
| 2 | `bcff109` | `feat(scenarios): add the YAML scenario specification and safe loader` | 2 files, +508 |
| 3 | `432d19a` | `feat(api): add suite and scenario CRUD endpoints` | 13 files, +938 −7 |
| 4 | `1e75cd5` | `test(phase-02): cover database, scenario validation and API endpoints` | 19 files, +2273 −48 |
| 5 | `b927baf` | `docs(phase-02): document the database schema and scenario format` | 6 files, +934 −91 |
| 6 | `07cd46c` | `docs(phase-02): add Phase 2 completion report` | 2 files, +629 |
| 7 | `e8b6e92` | `docs(phase-02): record verified remote branch hashes` | 1 file, +31 −4 |
| 8 | `2b5770d` | `fix(scenarios): reject recursive YAML aliases safely` | 2 files, +264 −16 |
| 9 | `08d04c3` | `chore(repo): ignore database dumps and backups` | 1 file, +20 |

Full hashes:

```
dcfd34c573638059372a874ebdeaedab3b1e11e2
bcff109edfb3e90276dbf4d5d318079f160210e8
432d19a353a0a19db8bce1cf78dd0f1ee4477b04
1e75cd515c61654493475f212d7a5de06797032d
b927baf00cd3e487ce3c46e38d52faf5243c33a8
07cd46c955be060a7ea597935bbbce1a6a76c6d9
e8b6e9274facbb6c229beb9871fb6531da0d73a5
2b5770de3b8b31f62de101757cb59e179a96af8c
08d04c3a5483c72faf4cfcc6886d0b76297f1da1
```

Commits 1–7 are the Phase 2 implementation and its documentation.
Commits 8 and 9 are this correction pass. The commit recording this
revision of the report cannot contain its own hash; `git log --oneline`
is authoritative.

### A note on `develop`

`develop` sat at `f5ced2c`, five commits **behind** the approved Phase 1 work,
so it was not a valid base. It was **fast-forwarded** to `e69930c` (no merge
commit, no history rewrite) and pushed before branching. All 10 Phase 1
commits are preserved and reachable.

### Branch state

| Branch | Tip | Notes |
|--------|-----|-------|
| `main` | `f5ced2c` | Untouched. Nothing merged into it. |
| `develop` | `e69930c` | Fast-forwarded to approved Phase 1 |
| `feature/phase-01-foundation` | `e69930c` | Preserved, not deleted |
| `feature/phase-02-database-scenarios` | see §9 verification | This phase |

No force push, no history rewrite, no branch deleted.

### Remote verification

Compared with `git ls-remote` — the authoritative remote state, not the
cached remote-tracking refs:

| Branch | Local | Remote | Match |
|--------|-------|--------|-------|
| `main` | `f5ced2c3ff4d` | `f5ced2c3ff4d` | ✅ |
| `develop` | `e69930c30c8a` | `e69930c30c8a` | ✅ |
| `feature/phase-01-foundation` | `e69930c30c8a` | `e69930c30c8a` | ✅ |
| `feature/phase-02-database-scenarios` | `07cd46c955be` | `07cd46c955be` | ✅ |

Both active branches report `ahead 0, behind 0`. The push that created the
Phase 2 branch was a plain `git push -u` — the remote branch did not exist
beforehand, so no force was involved and nothing was overwritten.

GitHub attributes all six Phase 2 commits to `YushBytes`. The remote tree
contains no `.env`.

History preservation on this branch:

```
total commits reachable: 16
Phase 1 tip e69930c is an ancestor: YES
```

That is 10 Phase 1 commits + 6 Phase 2 commits. Nothing was rewritten,
force-pushed or deleted.

> The commit that adds this verification block is the seventh on the branch
> and is therefore not in the hash above. Re-run
> `git ls-remote origin refs/heads/feature/phase-02-database-scenarios`
> against `git rev-parse feature/phase-02-database-scenarios` to confirm the
> current tip; the two matched at every push during this phase.

---

## 10. Known limitations

1. **The recursive-alias guard previously depended on the depth limit.**
   Fixed in commit `2b5770d` and covered by 12 regression tests, but worth
   recording as a *class* of problem. Two of this phase's defects - this one
   and the enum constraints below - were protections that appeared to work
   for an incidental reason. `MAX_YAML_DEPTH` must never be raised above
   Python's recursion limit without re-reading the cycle check.
2. **`_measure` is still recursive.** It is bounded by both the depth limit
   and the cycle check, and a defensive `RecursionError` handler converts any
   escape into a controlled error - but an iterative walk would remove the
   stack dependency altogether. Not changed here because it is a larger
   rewrite than the defect warranted.
3. **Cycle detection runs on the parsed document, not during parsing.**
   `safe_load` therefore still *builds* the cyclic object before it is
   rejected. The 256 KiB input cap bounds how large that object can be, so
   this is a bounded cost rather than an exposure, but a custom loader could
   refuse the alias at construction time.
4. **The enum CHECK constraints were initially missing.** SQLAlchemy's
   `Enum(create_constraint=...)` defaults to **`False`**, so the first version
   of the status columns were plain `VARCHAR`s whose allowed values were
   enforced only in Python — a write bypassing the ORM could have stored
   anything. A test that inserted an invalid status with raw SQL caught it.
   All three enums now set `create_constraint=True` and the initial migration
   was regenerated to include the constraints. *This is fixed*, but it is
   recorded because commit `dcfd34c`'s message claims the constraints were
   present from the start, and the correction landed in commit `1e75cd5`.
5. **No authentication or authorization.** Every endpoint is unauthenticated.
   None existed before this phase and inventing a partial scheme would be
   worse than none. Deferred to Phase 15.
6. **No suite update or delete endpoint.** Only create, list and get. Phase 3
   adds the rest, and a `DELETE /suites/{id}` needs a decision about what
   happens to run history first.
7. **`PUT` replaces, it does not patch.** There is no `PATCH`. A scenario is
   one coherent document, and partially updating a nested spec would make it
   easy to leave a scenario in a state its author never reviewed.
8. **Offset pagination.** Fine at current scale, but a row inserted between
   two page requests can shift results. Cursor pagination is the eventual fix.
9. **`updated_at` is ORM-driven.** `onupdate` fires on ORM-issued UPDATEs; a
   bulk `UPDATE` bypassing the ORM would not touch it. No such statement
   exists today. A database trigger would be the robust fix.
10. **Scenario `spec` is not queryable field-by-field.** Deliberate (§2
   decision 1), but filtering scenarios by, say, `audio.noise_profile` would
   need a GIN index or a new projected column.
11. **The `database` health probe is not cached.** Every `/api/v1/health` call
   opens a connection and runs `SELECT 1`. Cheap, but a high-frequency poller
   would add measurable load. `/health` is unaffected — it does not touch the
   database.
12. **In-container pytest needs explicit flags.** `pyproject.toml` is at the
   repository root and not copied into the image, and its `testpaths` are
   root-relative. Tests run correctly in the container but via pytest's
   defaults unless flags are passed (as §8 does). Carried over from Phase 1.
13. **`DATABASE_URL` and `POSTGRES_HOST_PORT` can still disagree.** Now
   documented prominently in `.env.example`, `README.md` and `CLAUDE.md`, and
   the local `.env` was corrected — it pointed at port 5432, which on this
   machine is an unrelated project's PostgreSQL, so `alembic upgrade head`
   would have migrated the wrong database. A startup assertion would be
   better than documentation.
14. **No CI pipeline.** `.github/workflows/` still holds only `.gitkeep`.
   Phase 14. The 246 tests are run manually.
15. **One reference scenario, not a library.** `scenarios/` holds a single
   fully-commented file. The multi-language library is Phase 3.
16. **`ANN401` and `B008` remain ignored** in the Ruff configuration,
   unchanged from Phase 1.
17. **The project sits in a OneDrive-synced folder**, which makes dependency
   installation slow. Unchanged from Phase 1.

---

## 11. Deferred work

### Phase 3 — Scenario Library & Tooling (next, not started)

The scenario format, its validation and its CRUD endpoints were delivered in
this phase, because the schema and the authoring format are two halves of one
decision — storing documents whose shape was not yet defined would have been
the wrong order. Phase 3 is rescoped accordingly:

- Reference scenarios across all 13 supported languages.
- Bulk import/export between a directory of YAML files and a suite.
- A scenario-validation CLI in `scripts/` for use in CI before storage.
- Suite update and delete; scenario copy/move between suites.
- Code-mixing annotation, ahead of Phase 11.

### Later phases

Speech-to-text (4), text-to-speech (5), caller simulation (6), audio
degradation (7), telephony (8), orchestration (9), evaluation (10),
benchmarking (11), reporting (12), dashboard (13), CI (14), hardening and auth
(15). See [`docs/DEVELOPMENT_ROADMAP.md`](docs/DEVELOPMENT_ROADMAP.md).

---

## 12. Completion requirements

| Requirement | Status |
|-------------|--------|
| Database models implemented | ✅ 5 models, typed, UUID keys, `timestamptz`, constrained |
| Alembic migrations work | ✅ upgrade, downgrade, re-upgrade, `alembic check` clean |
| Scenario YAML parsing and validation work | ✅ `safe_load`, strict schema, field-path errors |
| Database persistence works | ✅ Verified through the API in Docker |
| Required REST endpoints work | ✅ All nine, verified live |
| Automated tests pass | ✅ **246 passed** on host and in the container; 0 failed, 0 skipped |
| Ruff and formatting checks pass | ✅ `All checks passed!`, 54 files formatted |
| Docker backend build and runtime verified | ✅ Image builds; migrations and tests run inside it |
| Phase 1 functionality intact | ✅ All Phase 1 endpoints work; 3 Phase 1 tests updated to match deliberate Phase 2 changes, none weakened |
| Documentation updated | ✅ README, ARCHITECTURE, ROADMAP, new DATABASE.md, SCENARIO_FORMAT.md, CLAUDE.md |
| Git commits created and pushed | ✅ 9 on the branch; see §9 |
| Local and remote hashes verified | ✅ See §9 and the terminal summary |
| Recursive-alias defect corrected | ✅ Commit `2b5770d`, 12 regression tests, verified via the live API |
| Static type checking | ➖ Not run — no type checker is configured in this repository |

---

## 13. Phase 2 readiness

### READY FOR OWNER REVIEW

Every completion requirement is met and verified by direct execution, not
inference. The recursive-alias defect raised in review is corrected, covered
by regression tests, and verified through the live API in Docker.

**This is not a claim of approval.** Phase 2 is prepared for the owner's
review; approval and integration are the owner's decision.

What a reviewer may want to look at first:

| Area | Where |
|------|-------|
| The correction itself | `backend/app/services/scenario_loader.py`, `_measure` |
| Why it was needed | §1a of this report |
| Regression coverage | `backend/tests/test_scenario_spec.py`, `TestRecursiveAliases` and `TestNonCyclicAliases` |
| Schema decisions | §2 and `docs/DATABASE.md` |
| Honest limitations | §10 — 17 items, including two "incidental protection" defects |

---

## 14. Recommended next action

> **Completed.** The owner approved Phase 2, and this integration has since
> been carried out: `main` was fast-forwarded through Phase 1 (`e69930c`)
> and Phase 2 (`3aa5f19`), verified, pushed, and the `develop`,
> `feature/phase-01-foundation` and `feature/phase-02-database-scenarios`
> branches were deleted locally and remotely after ancestry checks. `main`
> is now the only branch. The steps below are retained as the record of
> what was planned and done.

After owner approval:

1. **Integrate the approved history into `main`.** `main` is still at
   `f5ced2c`, which predates Phase 1's closure. Both `develop` (`e69930c`,
   Phase 1) and `feature/phase-02-database-scenarios` need to reach it.
   `develop` fast-forwards from `main` cleanly; Phase 2 then fast-forwards
   from `develop`, since it was branched from `e69930c` and nothing has landed
   on `develop` since.
2. **Verify the integrated branch** before relying on it: `pytest`,
   `ruff check .`, `ruff format --check .`, `alembic check`, and a
   `docker compose up -d` smoke test against `main`.
3. **Only then remove unnecessary branches**, and only after confirming each
   one's work is reachable from `main` (`git merge-base --is-ancestor`).

None of that has been done here. No branch was merged, deleted or
force-pushed during this pass.

---

## 15. Phase 3 has not started

**Confirmed.** No telephony, audio processing, audio degradation, voice
synthesis, transcription, AI caller agent or evaluation logic exists in this
repository.

`TestRun`, `CallSession` and `ConversationTurn` are schema only — created by
the migration, covered by tests, and written to by nothing. No endpoint
creates a row in any of them.

No branch was merged, deleted, rebased or force-pushed during this pass, and
no database or Docker volume was reset. Awaiting the owner's review.
