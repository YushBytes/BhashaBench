# Command-Line Interface

`bhashabench` is the authoring and administration tool for the scenario
library. It is a thin front end over the same services the HTTP API calls — it
owns no validation, no SQL and no business rules of its own. Duplicating any
of those would mean the CLI and the API could disagree about whether a
scenario is valid, which is the one thing a test-authoring tool must never do.

Implementation: `backend/app/cli/`.

---

## Installing

```bash
pip install -e .            # from the repository root, with the venv active
bhashabench --help
```

Without installing:

```bash
cd backend
python -m app.cli --help
```

Both routes run the same code and produce the same exit codes.

---

## Two classes of command

**Offline** — `validate`, `validate-bundle`, `languages`. These touch only the
parser and the language catalogue, so they work with **no PostgreSQL running**.
That matters because the common case is an author checking a file, and because
CI should be able to reject a malformed scenario before any service exists.

**Database-backed** — everything under `suite` and `scenario`, plus `import`
and `export`. These resolve configuration through the same
`app.core.config` settings as the API and open a session through
`app.db.session`, so there is no second connection story and no credential
handling in the CLI at all.

```bash
docker compose up -d db     # needed only for the second group
```

---

## Exit codes

A CLI's real consumer is a shell script, so failures are distinguished rather
than collapsed into `1`:

| Code | Meaning | Examples |
|------|---------|----------|
| `0` | Success | |
| `1` | The operation was understood but could not be completed | Suite not found, name already taken, deletion refused |
| `2` | The input was rejected | Unparseable YAML, failed validation, bad UUID, out-of-range `--limit` |
| `3` | The database could not be reached | PostgreSQL down, wrong `DATABASE_URL` |

The distinction is the point: a script should retry a `3` and never retry a
`2`. A `0` from `validate` in CI means the file is good; a `2` means fix the
file.

```bash
if ! bhashabench validate "$f"; then
  echo "rejected: $f" >&2
  exit 1
fi
```

Errors go to **stderr**, data to **stdout**, so `--json` output stays
machine-parsable even when a command fails.

---

## `--json`

Every command accepts `--json`. Human output is for reading; JSON is for
piping.

```bash
bhashabench scenario list --language hi-IN --json | jq -r '.scenarios[].name'
bhashabench validate bad.yaml --json | jq '.errors[] | "\(.field): \(.message)"'
```

---

## Offline commands

### `validate`

```
$ bhashabench validate scenarios/appointment_booking.yaml
valid: appointment_booking
  language: hi-IN (Hindi)
  outcomes: 4
  tags:     appointment, healthcare, reference
  mixing:   hi-IN + en-IN
```

```bash
bhashabench validate scenarios/appointment_booking.yaml --show-normalized
bhashabench validate - < scenarios/appointment_booking.yaml
```

| Option | Effect |
|--------|--------|
| `--show-normalized` | Print the canonical YAML, with defaults materialised, on success |
| `--json` | `{"valid": true, "scenario": {...}}`, or `{"valid": false, "errors": [{"field": ..., "message": ...}]}` |

A rejected file exits `2` and names the field:

```
$ bhashabench validate broken.yaml
error: scenario definition failed validation
  language: Value error, 'fr-FR' is not a supported language; supported tags are ['hi-IN', ...]
$ echo $?
2
```

`-` as the filename reads stdin, so a scenario can be validated straight out
of a generator or a git show.

### `validate-bundle`

```
$ bhashabench validate-bundle bundle.yaml
bundle: 2 entries
  valid:   1
  invalid: 1
  suite:   Doc check

  entry 1 (doc_bad):
    language: Value error, 'fr-FR' is not a supported language; supported tags are [...]
```

Reports **every** invalid entry rather than stopping at the first, addressed by
index and name — one run gives the whole list of problems instead of making an
author fix twelve entries one round trip at a time.

### `languages`

```bash
$ bhashabench languages
13 supported languages:
  hi-IN   Hindi            हिन्दी
  bn-IN   Bengali          বাংলা
  ...

$ bhashabench languages --json | jq -r '.languages[].code'
```

Endonyms are printed in their own script. On a Windows console the default
code page cannot encode them, so the CLI reconfigures its streams to UTF-8
with replacement rather than crashing on a language list.

---

## Suites

```bash
bhashabench suite create "Hindi appointment flows" --description "Reference suite"
bhashabench suite list --limit 50
bhashabench suite show "$SUITE_ID"
bhashabench suite update "$SUITE_ID" --name "Hindi appointments"
bhashabench suite update "$SUITE_ID" --clear-description
bhashabench suite delete "$SUITE_ID"
bhashabench suite delete "$SUITE_ID" --cascade
```

`suite update` distinguishes *omitted* from *cleared*: leaving `--description`
off keeps the current description, while `--clear-description` removes it.
Passing both is a contradiction and exits `2`. Passing neither `--name` nor
`--description` nor `--clear-description` also exits `2` — a no-op update that
reports success would be worse than an error.

`suite delete` **refuses a non-empty suite** unless `--cascade` is given. The
foreign key cascades at the database level, so without this guard a single
mistyped delete would silently remove every scenario in the suite.

```
$ bhashabench suite delete "$SUITE_ID"
error: suite 'Hindi appointment flows' still contains 12 scenario(s). Delete them
first, or pass --cascade to delete the suite and its scenarios together.
```

The same refusal over HTTP names `cascade=true` instead. The service carries
the count and the suite name as fields and lets each front end word the
remedy, because telling a shell user to pass `cascade=true` would send them
looking for a flag that does not exist.

---

## Scenarios

```bash
bhashabench scenario list
bhashabench scenario list --language hi-IN
bhashabench scenario list --name appointment
bhashabench scenario list --tag healthcare --tag smoke
bhashabench scenario list --suite "$SUITE_ID" --limit 100

bhashabench scenario show "$SCENARIO_ID"
bhashabench scenario show "$SCENARIO_ID" --yaml > scenario.yaml

bhashabench scenario copy "$SCENARIO_ID" --to-suite "$OTHER_SUITE"
bhashabench scenario copy "$SCENARIO_ID" --to-suite "$SAME_SUITE" --new-name appointment_v2
bhashabench scenario move "$SCENARIO_ID" --to-suite "$OTHER_SUITE"
```

Filters combine with AND. `--language` matches exactly, `--name` is a
case-insensitive substring, and `--tag` is repeatable to require several tags
at once. An unsupported `--language` exits `2` with the supported list rather
than returning an empty page — "no results" and "you asked for a language that
does not exist" are different answers.

`copy` creates a new scenario with a **new id**; `move` **preserves the id**, so
references to a moved scenario stay valid. Copying inside one suite requires
`--new-name`, since the original already holds the name. Both refuse to
overwrite an existing name and exit `1`.

`scenario show --yaml` emits canonical YAML that is itself valid input, which
makes "pull it down, edit it, validate it, push it back" a working loop.

---

## Import and export

```bash
# Always dry-run first.
bhashabench import bundle.yaml --suite "$SUITE_ID" --dry-run

# Then for real. Atomic by default.
bhashabench import bundle.yaml --suite "$SUITE_ID"

# Import what is valid and report the rest.
bhashabench import bundle.yaml --suite "$SUITE_ID" --non-atomic

bhashabench export "$SUITE_ID" --output bundle.yaml
bhashabench export "$SUITE_ID" | tee bundle.yaml
```

```
$ bhashabench import bundle.yaml --suite "$SUITE_ID" --dry-run
dry run: 2 entries
  valid:      1
  imported:   0
  failed:     1
  committed:  False

  entry 1 (doc_bad):
    language: Value error, 'fr-FR' is not a supported language; supported tags are [...]
$ echo $?
2
```

`committed` is reported separately from `imported` so "nothing to do" is
distinguishable from "nothing was done". A dry run that found problems, and an
atomic import that was abandoned, both exit `2` — from a script's point of
view the batch did not go in, even though the command ran.

`--dry-run` validates, reports collisions and writes nothing. Without
`--non-atomic` an import is all-or-nothing: one failed or duplicate entry
abandons the whole batch, so a half-applied library never has to be unpicked
by hand. Existing scenarios are never overwritten — a name already in the
target suite is reported as a duplicate and skipped.

Export is deterministic: scenarios ordered by name, defaults materialised, no
ids and no timestamps. Exporting the same suite twice gives byte-identical
output, so a bundle committed to git produces a reviewable diff rather than
noise, and a round trip through export → import reproduces the scenarios
exactly.

The bundle format is documented in
[SCENARIO_FORMAT.md](SCENARIO_FORMAT.md#bundles-bulk-import-and-export).

---

## Worked example: a Tamil-English suite from scratch

```bash
docker compose up -d db
cd backend && alembic upgrade head && cd ..

# 1. Check the files before touching the database.
for f in scenarios/*.yaml; do bhashabench validate "$f" || exit 1; done

# 2. Create the suite and capture its id.
SUITE=$(bhashabench suite create "Tamil utility flows" --json | jq -r .id)

# 3. Build a bundle from the reference scenarios and dry-run it.
bhashabench validate-bundle bundle.yaml
bhashabench import bundle.yaml --suite "$SUITE" --dry-run

# 4. Import, then confirm.
bhashabench import bundle.yaml --suite "$SUITE"
bhashabench scenario list --suite "$SUITE" --language ta-IN

# 5. Export for review.
bhashabench export "$SUITE" --output exported.yaml
diff <(bhashabench export "$SUITE") exported.yaml && echo "deterministic"
```

---

## Files and safety

`validate`, `validate-bundle` and `import` read a path you name. The path is
resolved and stat-checked first, so a directory, a dangling symlink or an
oversized file produces a clear message rather than an opaque `OSError`, and a
file above the 256 KiB limit is refused **without being read into memory**.

No path restriction is applied, deliberately: this is a local tool run by the
person who owns the shell, and refusing to read a file they explicitly named
would be wrong. The API is the opposite case — input there *is* untrusted, so
it never accepts a path at all and takes the document in the request body.

`--output` writes only where the parent directory already exists. Creating
directories on the strength of a typo is not helpful.

A database outage reports the error class and what to do about it. The
driver's own message is deliberately not echoed, because it can contain the
connection URL and therefore the password:

```
$ bhashabench suite list
error: cannot reach the database (OperationalError). Check DATABASE_URL, or start it with: docker compose up -d db
```

A test asserts that no connection string or password appears in CLI output.
