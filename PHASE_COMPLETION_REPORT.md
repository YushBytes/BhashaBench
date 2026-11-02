# Phase 3 — Scenario Library & Tooling: Completion Report

| | |
|---|---|
| **Phase** | 3 of 15 — Scenario Library & Tooling |
| **Date** | 2026-11-03 |
| **Repository** | <https://github.com/YushBytes/BhashaBench> (**public**, by the owner's explicit decision) |
| **Branch** | `main` — the single authoritative branch |
| **Base** | `main` @ `50405cf` (last pre-Phase-3 commit) |
| **Commits in this phase** | **11** |
| **HEAD** | `c1725e7` |
| **Tracked files** | 117 (was 93 after Phase 2) |
| **Tests** | **561 passing**, 0 failed, 0 skipped — on the host *and* in the container (was 246 after Phase 2) |
| **API paths** | 14 (was 8) |
| **Migrations** | 2 (`3e3312d5327a`, `4997650a09c8`) |
| **Status** | **READY FOR OWNER REVIEW.** Not approved — approval is the owner's decision. |

> Phase 2's report is preserved in git history. This document replaces it to
> describe the current phase.

> **Phase 4 has not started.** No Gnani Prisma, Timbre or Evon client exists,
> no telephony, no audio processing, no scoring. Nothing in this report should
> be read as a claim that an unimplemented feature works.

---

## Contents

- [A. What was delivered](#a-what-was-delivered)
- [B. The language catalogue](#b-the-language-catalogue)
- [C. Code-mixing annotations](#c-code-mixing-annotations)
- [D. Tags and library search](#d-tags-and-library-search)
- [E. Suite editing and guarded deletion](#e-suite-editing-and-guarded-deletion)
- [F. Copy and move](#f-copy-and-move)
- [G. Bundles: import and export](#g-bundles-import-and-export)
- [H. The `bhashabench` CLI](#h-the-bhashabench-cli)
- [I. Reference scenarios](#i-reference-scenarios)
- [J. Migration and index](#j-migration-and-index)
- [K. Defects found and fixed during this phase](#k-defects-found-and-fixed-during-this-phase)
- [L. Verification results](#l-verification-results)
- [M. Acceptance checklist](#m-acceptance-checklist)
- [N. Commits](#n-commits)
- [O. Known limitations](#o-known-limitations)
- [P. Deferred work](#p-deferred-work)
- [Q. Security review](#q-security-review)
- [R. Recommended next action](#r-recommended-next-action)

---

## A. What was delivered

Phase 2 produced the scenario *format*, its validation and per-suite CRUD.
Phase 3 is everything around that: making a collection of scenarios
navigable, editable, portable, and usable without an HTTP client.

| Feature | Shape |
|---------|-------|
| Library search | `GET /api/v1/scenarios` across every suite, filtered by suite, language, name substring and repeatable tags |
| Language catalogue | 13 Indian languages in one module; `GET /api/v1/languages` |
| Code-mixing annotations | Optional structured `code_mixing` block; scenario spec v2 |
| Tags | Normalised labels on a scenario, filterable via a JSONB GIN index |
| Suite editing | `PATCH /api/v1/suites/{id}` distinguishing omitted from cleared |
| Guarded deletion | `DELETE /api/v1/suites/{id}`, refusing a non-empty suite without `?cascade=true` |
| Copy / move | `POST .../copy` (new id), `POST .../move` (same id) |
| Bundle import | `POST .../scenarios/import` with dry-run and atomicity |
| Bundle export | `GET .../scenarios/export`, deterministic and round-trippable |
| CLI | `bhashabench` — 14 commands, 4 distinguished exit codes, `--json` throughout |
| Reference scenarios | Six languages in `scenarios/`, plus a generated bundle |

**Not in this phase, deliberately:** no provider integrations, no telephony,
no audio processing, no caller simulation, no scoring. The `TestRun`,
`CallSession` and `ConversationTurn` tables remain foundational schema that
nothing writes to.

---

## B. The language catalogue

`backend/app/core/languages.py` is the single source of truth. The scenario
schema, the search filters, the CLI and `GET /api/v1/languages` all read the
same tuple, so a language cannot be supported in one place and unknown in
another.

Thirteen languages, ordered by number of speakers, each carrying its endonym,
ISO 15924 script and POSIX locale:

`hi-IN`, `bn-IN`, `mr-IN`, `te-IN`, `ta-IN`, `gu-IN`, `ur-IN`, `kn-IN`,
`or-IN`, `ml-IN`, `pa-IN`, `as-IN`, `en-IN`

```json
{"code": "hi-IN", "name": "Hindi", "endonym": "हिन्दी", "script": "Deva", "locale": "hi_IN"}
```

Two design points worth stating:

- **Shape is checked before membership.** `hi_IN` and `Hindi` are rejected as
  malformed (the expected form is `xx` or `xx-XX`); `fr-FR` is rejected as
  unsupported, with the full list of supported tags. Those are different
  mistakes and an author learns something different from each.
- **`script` is not an identifier.** Bengali and Assamese share `Beng`; Hindi
  and Marathi share `Deva`. It tells a renderer or a TTS voice what writing
  system to expect, nothing more.

`UnsupportedLanguageError` subclasses `ValueError`, so inside a document it
surfaces as an ordinary Pydantic validation error. The one path that consults
the catalogue directly — the `?language=` search filter — needed an explicit
exception handler; see §K.

---

## C. Code-mixing annotations

Indian callers switch language inside a single sentence. Hinglish, Tanglish
and their regional equivalents are ordinary speech, not an edge case — a bot
tested only on monolingual input can pass a benchmark and still fail a real
call. Phase 3 records that expectation explicitly, so a Phase 6 caller agent
can perform it and a Phase 10 evaluator can score it.

```yaml
code_mixing:
  primary: hi-IN            # defaults to the scenario's language
  secondary: [en-IN]        # 1-3 tags, most prominent first
  expected: true            # false asserts a monolingual caller
  secondary_ratio: 0.3      # 0-0.9
  switch_triggers: [numbers, technical_terms]
  sample_utterances:
    - Mujhe kal ka appointment chahiye at 10 AM
```

Rules enforced:

- `primary`, if given, must equal the scenario's `language` — two sources of
  truth for the dominant language would eventually disagree.
- A language cannot be mixed into itself: `primary` may not appear in
  `secondary`, and `secondary` may not repeat a tag.
- `secondary` must name at least one language. A mixing block with nothing to
  mix is meaningless.
- `secondary_ratio` requires `expected: true`. A declared ratio alongside an
  assertion of no mixing is a contradiction, and honouring half of it would
  make the scenario behave unlike what its author wrote.
- `secondary_ratio` is capped at 0.9: past that the primary language is
  mislabelled rather than mixed.
- Every tag is checked against the catalogue.

**Backward compatibility.** `tags` and `code_mixing` are both optional with
defaults, so every Phase 2 document still validates unchanged.
`SPEC_VERSION` moved 1 → 2 and a v1 row keeps its recorded version until it is
next written. **No data migration was required.**

Six named switch triggers rather than free text — `numbers`,
`technical_terms`, `proper_nouns`, `frustration`, `clarification`,
`throughout` — so a later caller agent can act on them.

---

## D. Tags and library search

```
GET /api/v1/scenarios?language=ta-IN&tag=payment&tag=utilities&name=bill&limit=50
```

Filters combine with **AND**: `language` exact, `name` a case-insensitive
substring, `tag` repeatable and requiring *every* named tag.

- Ordered by `name` then `id`, so paging stays stable even when two suites
  hold a scenario with the same name.
- `ilike` patterns are escaped (`escape="\\"`), so a `%` or `_` in a search
  term is a literal, not a wildcard.
- One statement builder (`_search_statement`) is shared by the page query and
  the count query — they cannot drift and report a total that disagrees with
  the rows.
- An unknown `suite_id` is a 404, not an empty page. An unsupported
  `language` is a 422 carrying the supported list. "No results" and "you asked
  for something that does not exist" are different answers.

Tags are normalised at validation: lowercased, de-duplicated and sorted.
`Healthcare` and `healthcare` are the same tag, which keeps a tag vocabulary
from splitting on capitalisation, and two scenarios tagged the same way
serialise identically — which is what makes export deterministic.

---

## E. Suite editing and guarded deletion

`PATCH /api/v1/suites/{suite_id}` reads `payload.model_fields_set` to tell an
**omitted** field from one explicitly set to `null`: omitting `description`
keeps it, sending `null` clears it. A PATCH that cannot express "clear this"
forces a client into a PUT it does not want.

`DELETE /api/v1/suites/{suite_id}` **refuses a non-empty suite** with 409 and
reports how many scenarios it holds. `scenarios.suite_id` is
`ON DELETE CASCADE`, so a bare delete would silently remove every scenario in
the suite — the wrong default for an unrecoverable operation. `?cascade=true`
is the explicit opt-in, and the response reports how many went with it.

A scenario referenced by recorded call history cannot be deleted at all
(`call_sessions.scenario_id` is `ON DELETE RESTRICT`); that surfaces as a 409,
not a 500.

---

## F. Copy and move

| | id | Name requirement |
|---|---|---|
| `copy` | **new** UUID | `new_name` required when copying within the same suite |
| `move` | **preserved** | `new_name` optional, for a destination that already uses the name |

Copy re-validates the specification through `ScenarioSpec.model_validate`
rather than trusting the stored document, so a copy can never be the vehicle
by which an invalid spec enters a second suite. Move preserving the id means
references to a moved scenario stay valid — which matters once call history
points at scenarios. Move to the suite a scenario is already in is a no-op,
not an error.

---

## G. Bundles: import and export

Format identifier: `bhashabench.scenario-bundle/v1`. One YAML document holding
a suite's metadata and up to 500 scenarios.

```yaml
format: bhashabench.scenario-bundle/v1
suite:
  name: Indian language reference suite
scenarios:
  - name: appointment_booking
    language: hi-IN
    ...
```

- `format` is checked **first**, so a scenario file handed to the bundle
  parser is told "this is not a bundle" rather than given a list of
  missing-field errors.
- `suite.name` is descriptive only. The target suite is addressed by URL, so a
  bundle cannot be made to write into a suite the caller did not name.
- Entry errors are **collected, not short-circuited**: one request reports
  every bad entry by index and name, instead of making an author fix fifty
  entries one round trip at a time.
- Every entry goes through the ordinary scenario schema, so a bundle cannot
  introduce a scenario that a single-scenario POST would reject.

**Import** takes two flags:

| Flag | Default | Effect |
|------|---------|--------|
| `dry_run` | `false` | Validate, report collisions, write nothing |
| `atomic` | `true` | One failure or duplicate abandons the whole batch |

`committed` is reported separately from `imported`, so "nothing to do" is
distinguishable from "nothing was done". Existing scenarios are **never
overwritten** — a name already in the target suite is reported as a duplicate
and skipped. Updating stays an explicit `PUT`.

**Export** is deterministic: scenarios ordered by name, defaults materialised,
mappings key-sorted, and no database identifier or timestamp included.
Exporting the same suite twice is byte-identical, so a bundle committed to git
produces a reviewable diff rather than noise. Because ids are omitted, a
bundle describes scenarios rather than rows, which is what makes it safe to
move between environments.

**The round trip is byte-exact in both directions, verified against a real
database:** importing `scenarios/bundles/indian_language_reference.yaml` into
an empty suite and exporting it reproduces that file exactly. That property
was broken when first measured; see §K.

---

## H. The `bhashabench` CLI

`backend/app/cli/`. A thin front end over the same services the API calls — it
owns no validation, no SQL and no business rules. Duplicating any of those
would let the CLI and the API disagree about whether a scenario is valid,
which is the one thing a test-authoring tool must never do.

**Offline** (no PostgreSQL needed): `validate`, `validate-bundle`,
`languages`. The common case is an author checking a file, and CI should be
able to reject a malformed scenario before any service exists.

**Database-backed:** `import`, `export`, `suite list|show|create|update|delete`,
`scenario list|show|copy|move`. These resolve configuration through the same
`app.core.config` settings and open a session through `app.db.session`, so
there is no second connection story and no credential handling in the CLI.

Exit codes, because a CLI's real consumer is a shell script:

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Understood but could not be completed — not found, conflict, refused |
| `2` | Input rejected — bad YAML, failed validation, bad arguments |
| `3` | The database could not be reached |

A script should retry a `3` and never retry a `2`. Errors go to stderr and
data to stdout, so `--json` output stays parsable even when a command fails.

Three behaviours worth calling out:

- **No credential ever reaches the terminal.** A connection failure reports
  the exception class and what to do about it; the driver's own message is
  deliberately not echoed, because it can contain the URL and therefore the
  password. A test asserts no connection string or password appears in output.
- **Files are stat-checked before being read**, so a directory, a dangling
  symlink or an oversized file gives a clear message rather than an opaque
  `OSError`, and a file over 256 KiB is refused without being read into
  memory. No path restriction is applied, deliberately: this is a local tool
  run by the person who owns the shell. The API is the opposite case — input
  there is untrusted, so it never accepts a path and takes the document in the
  request body.
- **Non-ASCII output does not crash.** The catalogue prints endonyms in
  Devanagari, Tamil, Bengali and Arabic script; on a Windows console the
  default code page cannot encode them. `configure_streams()` reconfigures to
  UTF-8 with `errors="replace"` — a `?` is a cosmetic problem, a traceback is
  not.

Full reference: [`docs/CLI.md`](docs/CLI.md).

---

## I. Reference scenarios

Six scenarios in `scenarios/`, one per language, each chosen to fail for a
different reason so the set reads as a survey rather than six copies of one
test.

| File | Language | Stresses |
|------|----------|----------|
| `appointment_booking.yaml` | `hi-IN` | Every field the schema accepts, documented inline; Hinglish on numbers and medical terms |
| `tamil_electricity_bill.yaml` | `ta-IN` | Heavy Tanglish over market noise — the English-mixed tokens are the ones that decide whether a payment is right |
| `bengali_balance_enquiry.yaml` | `bn-IN` | Elderly caller who pauses mid-sentence; 8-second silence allowance |
| `marathi_delivery_reschedule.yaml` | `mr-IN` | Mixing triggered by frustration on a second attempt |
| `telugu_order_tracking.yaml` | `te-IN` | 6 dB SNR, 18% packet loss; everything else simple so a failure points at the channel |
| `english_insurance_claim.yaml` | `en-IN` | The control — `expected: false` asserts a monolingual caller |

`scenarios/bundles/indian_language_reference.yaml` holds all six, built with
the same serialiser the export endpoint uses.
[`scenarios/README.md`](scenarios/README.md) explains each one and how to
regenerate the bundle.

40 tests keep these honest: each file validates and round-trips, the filename
matches the scenario name, every file is tagged, the set covers six distinct
languages and the documented audio and code-mixing cases, native-script text
survives serialisation unescaped, and the bundle is checked for drift against
the files it came from. A schema change that invalidates an example now fails
the build instead of quietly leaving the documentation wrong.

---

## J. Migration and index

One migration: **`4997650a09c8`** — *Index the scenario specification for tag
filtering.*

```sql
CREATE INDEX ix_scenarios_spec_gin ON scenarios USING gin (spec);
```

Tag filtering is a JSONB containment test (`spec @> '{"tags": [...]}'`).
B-tree indexes cannot answer containment, so without GIN every tag query is a
sequential scan that deserialises each document.

Verified by `EXPLAIN`:

```
Bitmap Heap Scan on scenarios
  Recheck Cond: (spec @> '{"tags": ["healthcare"]}'::jsonb)
  ->  Bitmap Index Scan on ix_scenarios_spec_gin
        Index Cond: (spec @> '{"tags": ["healthcare"]}'::jsonb)
```

The index covers the whole `spec` column rather than a `jsonb_path_ops`
expression index on `tags` alone: later phases will filter on other parts of
the document, and a general index serves those without another migration. The
cost is a larger index and slightly slower writes — acceptable for a table
written once per authored scenario and read on every library query.

Reversibility verified this session: `alembic downgrade -1` removed the index
(confirmed absent in `pg_indexes`), `alembic upgrade head` restored it with
the same definition, and `alembic check` reports no drift.

**No destructive migration shortcut was used. No volume was reset. No existing
migration was modified.**

---

## K. Defects found and fixed during this phase

Six, all found by exercising the thing rather than reading it. Each is its own
commit with its own test.

### K.1 An unsupported `?language=` filter returned 500

The search endpoint consults the catalogue directly, so an unknown tag raised
`UnsupportedLanguageError` — a `ValueError` — outside Pydantic's validation
path. The catch-all handler turned it into a 500, telling the caller that a
bad query string was a server fault. Now mapped to the same 422
`validation_error` envelope as every other rejected input. (`5cc1947`)

### K.2 CLI domain errors produced an exit code with no message

Error translation lived in `main()`, *outside* `app()`, so it applied only to
the console script. Any other entry — `python -m app.cli`, or a test harness
driving the Click object — got exit code 1 and **no output at all** for a
missing suite or a name clash. Moved into `DomainErrorGroup.invoke` on the
top-level Typer group, which wraps subcommands too, so every entry point
reports identically. (`5522c5e`)

This one is worth dwelling on: the exit codes the documentation promised were
only ever produced on one of three code paths, and the test that would have
caught it could not be written, because —

### K.3 `app.cli.main` resolved to a function, not the module

`app/cli/__init__.py` re-exported the entry function as `main`, which shadowed
the `app.cli.main` submodule on the package. `monkeypatch.setattr(
"app.cli.main.session_scope", ...)` failed with
`AttributeError: 'function' object has no attribute 'session_scope'`. The
package now exports only `app`, and the console script points at
`app.cli.main:main`. (`5522c5e`)

### K.4 The CLI told users to pass a flag that does not exist

The non-empty-suite refusal said "repeat the request with `cascade=true`" —
the HTTP query parameter — to a shell user whose only option is `--cascade`.
The service now takes the remedy wording from its caller
(`SuiteNotEmptyError` carries the suite name and count as fields), so the API
names `cascade=true` and the CLI names `--cascade`. A test on each side
asserts it does not print the other's. (`ef11c3a`)

Two smaller items in the same commit: `validate` printed every field error
twice (the exception embeds the first five in its message for consumers that
have only a message to show, and the CLI then listed them all again), and it
summarised `code_mixing.expected: false` as `hi-IN + en-IN` — stating the
opposite of what that scenario asserts.

### K.5 Export was not byte-identical to the file it was imported from

The finding that mattered most. Importing the reference bundle and exporting
the suite produced a document that was valid and semantically equal but
**different**: the `known_facts` keys came back reordered.
`scenarios.spec` is `jsonb`, which stores keys sorted by length then bytewise
rather than preserving insertion order — so a scenario read from the database
serialised differently from the same scenario read from a file.

The diff was pure noise, and it broke the property that makes a bundle
reviewable in git. The unit tests could not see it, because they never crossed
`jsonb`: an export compared only against another export agreed perfectly.

`known_facts` is looked up by name, so its order carries no meaning. Sorting
it at validation — as `tags` already was — makes the canonical serialisation
depend on the scenario alone. Two tests now cross the database: the reference
bundle round-trips byte for byte, and a scenario authored with its facts
deliberately out of order comes back sorted, so a test that compares an export
only against itself cannot pass while the defect stands. (`2258143`)

### K.6 The in-container test run enforced nothing

The suite is run twice — on the host from the repository root, and in Docker
from `backend/`. Only the first had any pytest configuration:
`pyproject.toml` is not inside `./backend`, which is all docker-compose
mounted. In the container, pytest found **no config file at all**:
`filterwarnings = ["error"]` was inactive, `--strict-markers` and
`--strict-config` were off, and collection was unconstrained enough to try to
collect `app/models/test_run.py` as a test module.

A second run that enforces less than the first is worse than no second run,
because it reads as corroboration. `backend/pytest.ini` now carries that
configuration for runs rooted at `backend/`; the root `pyproject.toml` stays
the authority for host runs, and `tests/test_tooling.py` asserts the two agree
on every setting except the two path settings, which are relative to different
roots. docker-compose also mounts `./scenarios` and `./pyproject.toml`
read-only so the reference-scenario tests and the comparison can run there.
(`c1725e7`)

---

## L. Verification results

Every command below was run in this session. Output is quoted, not
paraphrased.

### L.1 Tests — host

```
$ pytest
rootdir: C:\Users\ayush\OneDrive\Desktop\BhashaBench
configfile: pyproject.toml
561 passed in 18.81s
```

| Module | Tests | New? |
|--------|-------|------|
| `test_health.py` | 16 | |
| `test_config.py` | 14 | |
| `test_app_metadata.py` | 9 | modified |
| `test_scenario_spec.py` | 107 | |
| `test_database.py` | 37 | |
| `test_api_suites_scenarios.py` | 63 | modified |
| `test_languages.py` | **89** | **new** |
| `test_bundle.py` | **39** | **new** |
| `test_api_library.py` | **74** | **new** |
| `test_cli.py` | **65** | **new** |
| `test_reference_scenarios.py` | **40** | **new** |
| `test_tooling.py` | **8** | **new** |
| **Total** | **561** | **315 new** |

Baseline was **246**. All 246 still pass; none was removed, skipped, weakened
or rewritten to accommodate new behaviour. The two modified modules changed
only to track deliberate changes: `test_app_metadata.py` asserts the exact
set of 14 OpenAPI paths, and both now read `SPEC_VERSION` from the schema
rather than hardcoding `1`.

### L.2 Tests — in the container

```
$ docker compose exec backend pytest
rootdir: /app
configfile: pytest.ini
561 passed in 19.61s
```

Same count, same configuration strictness, including the reference-scenario
tests and the configuration comparison.

### L.3 Lint and formatting

```
$ ruff check .
All checks passed!

$ ruff format --check .
70 files already formatted
```

Ruff 0.17.3. No rule was disabled and no `noqa` was added during this phase.

### L.4 Migrations

```
$ alembic current
4997650a09c8 (head)

$ alembic check
No new upgrade operations detected.

$ alembic history
3e3312d5327a -> 4997650a09c8 (head), Index the scenario specification for tag filtering.
<base> -> 3e3312d5327a, Create the suite, scenario and execution tables.

$ alembic downgrade -1   # then: ix_scenarios_spec_gin present: False
$ alembic upgrade head   # then: CREATE INDEX ix_scenarios_spec_gin ON public.scenarios USING gin (spec)
```

### L.5 Docker

All four images build:

```
bhashabench-backend:latest    366MB
bhashabench-backend:prod      321MB
bhashabench-frontend:latest  1.80GB
bhashabench-frontend:prod     756MB
```

The containerised stack serves the API:

```
$ curl -s localhost:8000/api/v1/health
health: ok ['ok', 'ok', 'ok']
$ curl -s localhost:8000/api/v1/languages      → 13
$ curl -s localhost:8000/openapi.json          → 200, 14 paths
```

The CLI runs inside the container against the Compose database — validate,
suite create, import 6 scenarios, export, cascade delete — leaving it at
`0 suite(s)`, `0 scenario(s)`.

Both production images were also started and checked, then stopped:

```
backend:prod    /health → {"status":"ok","version":"0.1.0"}
                /api/v1/health → ok, environment production, all components ok
                /docs → 404   (documentation is disabled in production)
frontend:prod   / → 200, renders "BhashaBench"
```

> **Build note.** The first three attempts at `docker compose build backend`
> failed with pip read timeouts against `files.pythonhosted.org`, and once
> with a registry timeout resolving the Dockerfile frontend. A direct
> `pip download` inside a clean `python:3.12-slim` container succeeded, so the
> cause was transient network degradation on this host, not the Dockerfile or
> `requirements.txt`. A retry built cleanly. `typer 0.27.3` is confirmed
> present in the image.

### L.6 API smoke test

Run against a local instance on the migrated development database, then
against the containerised stack. Every new endpoint exercised; the development
database was left at `0 suite(s)`, `0 scenario(s)`.

| Check | Result |
|-------|--------|
| `GET /languages` | 13, `hi-IN` first, script `Deva` |
| `POST /suites/{id}/scenarios/import` dry run | `imported 0, failed 0, dry_run true, committed false` |
| …then for real | `imported 6, failed 0, committed true` |
| `GET /scenarios?language=ta-IN` | 1 — `tamil_electricity_bill` |
| `GET /scenarios?tag=logistics&tag=worst-case` | 1 — `telugu_order_tracking` (AND, not OR) |
| `GET /scenarios?language=fr-FR` | **422** `validation_error` |
| `DELETE /suites/{id}` non-empty | **409**, message names `cascade=true` and not `--cascade` |
| `GET .../export` twice | byte-identical |
| `GET .../export` vs the imported file | **byte-identical** |
| `POST .../copy` | new id, target suite |
| `POST .../move` | id preserved, target suite |
| `PATCH /suites/{id}` `{"description": null}` | description cleared |

### L.7 Unrelated containers and volumes

`whistledrop-db`, `whistledrop-db-test` and `novaflow-pytest-mongo` were
running at the start of this session and are still running, untouched. No
volume was removed. `bhashabench-postgres-data` was never reset — the two
migration downgrades in §L.4 were schema-only and immediately re-applied.

---

## M. Acceptance checklist

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Scenario library listing with search, filter and pagination | **PASS** — §D |
| 2 | Suite update and safe delete | **PASS** — §E |
| 3 | Scenario copy and move between suites | **PASS** — §F |
| 4 | Centralised catalogue of 13 Indian languages | **PASS** — §B |
| 5 | Structured code-mixing annotations | **PASS** — §C |
| 6 | Bulk YAML import with dry-run and atomicity | **PASS** — §G |
| 7 | Bulk export, deterministic and round-trippable | **PASS** — §G, verified byte-exact through PostgreSQL |
| 8 | A CLI reusing the existing services | **PASS** — §H |
| 9 | Versioned REST endpoints | **PASS** — all under `/api/v1`, 14 paths |
| 10 | Migrations only where needed | **PASS** — one index migration; no data migration, §J |
| 11 | Backward compatibility with Phase 2 documents | **PASS** — both new fields optional; 246 baseline tests still green |
| 12 | Safe YAML only; limits preserved | **PASS** — `safe_load` only; size, node-count, depth and cycle guards unchanged and still tested |
| 13 | Path traversal and arbitrary-write protection | **PASS** — §H, §Q |
| 14 | No secrets in logs, output or the repository | **PASS** — §Q |
| 15 | Extensive tests; nothing weakened to pass | **PASS** — 246 → 561, §L.1 |
| 16 | Documentation updated | **PASS** — §N |
| 17 | Committed to `main` and pushed | **PASS** — §N |
| 18 | No Phase 4 work | **PASS** — no provider client, no telephony, no audio, no scoring |

---

## N. Commits

Eleven commits on `main`, base `50405cf`, oldest first:

| SHA | Message |
|-----|---------|
| `5fbc59d` | `feat(languages): centralise the Indian language catalogue and add code-mixing` |
| `2ed9335` | `feat(scenarios): add library search, suite update/delete and copy/move` |
| `86c301b` | `feat(cli): add the bhashabench command-line interface` |
| `5cc1947` | `fix(api): return 422 for an unsupported ?language= filter` |
| `5522c5e` | `fix(cli): translate domain errors inside the app, and unshadow the module` |
| `623e14d` | `test(phase-03): expand scenario tooling coverage` |
| `ef11c3a` | `fix(cli): report refusals and validation failures in the user's own terms` |
| `af0dfec` | `feat(scenarios): add reference scenarios for six Indian languages` |
| `4111573` | `docs(phase-03): document the library, the bundle format and the CLI` |
| `2258143` | `fix(scenarios): sort known_facts so the canonical form ignores provenance` |
| `c1725e7` | `fix(ci): give the in-container test run the same configuration as the host` |

49 files changed, 7151 insertions, 131 deletions. 24 files added, 25 modified,
none deleted.

**Documentation updated:** `README.md`, `CLAUDE.md`, `docs/CLI.md` (new),
`docs/SCENARIO_FORMAT.md`, `docs/DATABASE.md`, `docs/ARCHITECTURE.md`,
`docs/DEVELOPMENT_ROADMAP.md`, `scenarios/README.md` (new). The phase-status
tables in the README, `CLAUDE.md` and the roadmap agree.

**No history was rewritten. No force-push. No branch was created or deleted.
`main` remains the single authoritative branch.**

---

## O. Known limitations

1. **Code-mixing is an authored expectation, not a measurement.** Nothing
   detects language from audio. `code_mixing` records what a caller *should*
   do; performing it is Phase 6 and scoring it is Phase 10.
2. **`audio` and `constraints` are validated and stored, not applied.** Audio
   degradation is Phase 7; conversation constraints are Phase 9.
3. **Export has no pagination or streaming.** A bundle is built in memory and
   capped at 500 scenarios. Adequate for authored suites; a library of tens of
   thousands would need a streaming export.
4. **Import has no update mode.** A name already present is reported as a
   duplicate and skipped, never overwritten. Updating in bulk is not possible
   in one call; `PUT` per scenario is the route.
5. **The GIN index covers the whole `spec` document.** Deliberate, for the
   reasons in §J, but it is larger and slower to write than a targeted
   expression index would be.
6. **The CLI has no `scenario create` or `scenario delete`.** Authoring is
   file-first: write YAML, `validate`, then `import`. Single-scenario creation
   and deletion remain API operations.
7. **The frontend does not use any of this.** The dashboard is still the
   Phase 1 shell; it renders no library UI. Phase 13.
8. **The console script requires `pip install -e .`.** The Docker image does
   not install the package, so in-container use is `python -m app.cli`.
   Documented in `docs/CLI.md`.
9. **`spec_version` is recorded but nothing migrates on it.** A v1 row keeps
   its version until it is next written. There is no backfill, because none
   was needed — both new fields are optional.

---

## P. Deferred work

Not defects; explicitly out of Phase 3 scope.

- Scenario versioning and history (editing a scenario overwrites it).
- Tag management endpoints — listing the tag vocabulary in use, renaming a tag
  across a library.
- Suite-level copy/clone, and import that creates the suite it names.
- Export filtered by a search query rather than by suite.
- Full-text search on `objective` and `expected_outcomes`.
- Soft delete / trash for suites and scenarios.
- Scenario templates or generation.
- Shell completion for the CLI (`add_completion=False` today).
- Multi-tenancy. Suite names are globally unique; an owner concept would make
  that a composite constraint.

---

## Q. Security review

| Area | Status |
|------|--------|
| YAML parsing | `yaml.safe_load` only. The Phase 2 limits — 256 KiB, 10,000 nodes, depth 20, cyclic-alias rejection by active-path object identity — are unchanged and still tested, including that an unsafe `!!python/object/apply` payload does not take effect. Bundles are parsed by the same loader. |
| Path handling | CLI paths are resolved and stat-checked before reading; a directory, a dangling symlink or an oversized file is refused with a clear message. `--output` writes only into an existing directory. The API never accepts a path at all — the document arrives in the request body. |
| Shell execution | None. No `subprocess`, no `os.system`, no shell interpolation anywhere in the CLI or services. |
| SQL | Every statement is a parameterised SQLAlchemy construct in `repositories/`. `ilike` patterns are escaped so user input cannot inject a wildcard. No string-built SQL. |
| Credentials in output | The CLI never echoes a driver message; a database outage reports the exception class and remedy only. A test asserts no connection string or password appears in CLI output, and an existing test asserts the same for API responses. |
| Stack traces | Unhandled exceptions return the `internal_error` envelope; details are logged, never returned. |
| Secrets in the repository | A pattern scan over all 46 content-bearing files changed in this phase found one match, reviewed and cleared: a self-describing test literal in a pre-existing test (`secret_key="a-real-looking-secret"`) used to construct production `Settings`. No credential, token, key or private key was committed. `.env` remains untracked; only `.env.example` is tracked. |
| Repository visibility | Unchanged — **public**, per the owner's explicit decision. No GitHub setting was modified. |
| Invented integrations | None. No Gnani endpoint, credential or client was added. No sample value resembling a real credential was created. |

**No real secret was found at any point in this phase.**

---

## R. Recommended next action

1. **Review this report and the 11 commits.** `git log --oneline 50405cf..HEAD`
   and `git diff 50405cf..HEAD` are the authoritative record.
2. **Pay particular attention to §K.5 and §K.6.** Both were cases where the
   tests agreed with themselves and were wrong about reality — an export
   compared only against another export, and a second test run that enforced
   nothing. Both are now covered by tests that cross the boundary they were
   blind to.
3. **If approved**, Phase 4 (Gnani Prisma — speech to text) may begin. The
   scenario library is now complete enough to drive it: a run will need to
   look up a scenario, read its language from the catalogue, and record
   transcripts against `call_sessions` and `conversation_turns`.
4. **If not approved**, the specific criterion in §M to revisit, so the gap can
   be closed before Phase 4.

**Phase 3 is complete and awaiting your review. Phase 4 has not started and
will not start without your explicit approval.**
