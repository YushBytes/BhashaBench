# Scenario YAML Format

A scenario is one test case: who calls, what they want, in which language, and
what the bot must achieve. Scenarios are authored as YAML and validated
strictly before they are stored.

The authoritative schema is `backend/app/schemas/scenario_spec.py`. A working
reference file lives at `scenarios/appointment_booking.yaml`.

---

## A complete example

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

A minimal valid scenario is much shorter — everything optional has a default:

```yaml
name: minimal
language: en-IN
persona:
  identity: Caller
goal:
  objective: Ask a question.
expected_outcomes:
  - Bot answers
```

---

## Field reference

### Top level

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `name` | string | **yes** | — | Lowercase letters, digits, `_`, `-`. Must start alphanumeric. Max 200. Unique within its suite. |
| `description` | string | no | `null` | Max 2000 characters. |
| `language` | string | **yes** | — | BCP 47 tag from the supported set below. |
| `persona` | mapping | **yes** | — | See below. |
| `goal` | mapping | **yes** | — | See below. |
| `known_facts` | mapping | no | `{}` | Max 50 entries. String values only. |
| `expected_outcomes` | list | **yes** | — | 1–20 entries, no duplicates. |
| `audio` | mapping | no | all defaults | See below. |
| `constraints` | mapping | no | omitted | See below. |
| `tags` | list | no | `[]` | Max 20 labels for filtering. See below. |
| `code_mixing` | mapping | no | omitted | How the caller mixes languages. See below. |

### `persona`

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `identity` | string | **yes** | — | Who the caller is. Max 500. |
| `speaking_style` | enum | no | `neutral` | `polite`, `neutral`, `brusque`, `confused`, `hurried`, `elderly`. |
| `traits` | list | no | `[]` | Max 10, no duplicates (case-insensitive). |

### `goal`

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `objective` | string | **yes** | — | Max 2000. |
| `max_turns` | integer | no | `20` | 1–100. Hard cap on conversation turns. |

### `audio`

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `noise_profile` | enum | no | `clean` | `clean`, `urban`, `rural`, `market`, `indoor_fan`, `worst_case`. |
| `snr_db` | number | no | `30.0` | 0–40 dB. Higher is cleaner. |
| `packet_loss_percent` | number | no | `0.0` | 0–30 percent. |

### `constraints`

Omitted entirely by default.

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `max_silence_seconds` | number | no | `5.0` | Above 0, up to 60. |
| `allow_interruptions` | boolean | no | `true` | Whether the caller may talk over the bot. |
| `required_phrases` | list | no | `[]` | Max 20. |
| `forbidden_phrases` | list | no | `[]` | Max 20. |

### `tags`

Free-form labels, used by the library endpoints to filter a large scenario
collection: `?tags=healthcare,smoke`.

```yaml
tags:
  - healthcare
  - smoke
  - regression
```

Each tag matches `^[A-Za-z0-9][A-Za-z0-9_-]*$` and is **normalised to
lowercase, de-duplicated and sorted** on the way in. `Healthcare`,
`healthcare` and `HEALTHCARE` are therefore the same tag, and two scenarios
labelled the same way serialise identically — a tag vocabulary that splits on
capitalisation is worse than no vocabulary at all. Filtering is a containment
match on the stored JSONB, so a scenario must carry *every* requested tag.

### `code_mixing`

Indian callers switch language inside a single sentence. Hinglish, Tanglish
and their regional equivalents are ordinary speech, not an edge case — a bot
tested only on monolingual input can pass a benchmark and still fail a real
call. This block records that expectation explicitly so it can be performed by
a caller agent and scored by an evaluator in later phases.

```yaml
language: hi-IN

code_mixing:
  primary: hi-IN
  secondary:
    - en-IN
  expected: true
  secondary_ratio: 0.3
  switch_triggers:
    - numbers
    - technical_terms
  sample_utterances:
    - "Mujhe kal ka appointment chahiye at 10 AM"
    - "Doctor available hai evening slot mein?"
```

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `primary` | string | no | the scenario's `language` | If given it must equal `language`. Two sources of truth for the dominant language would eventually disagree. |
| `secondary` | list | **yes** | — | 1–3 supported tags, most prominent first, no duplicates. A mixing block with nothing to mix is meaningless, so an empty list is rejected. |
| `expected` | boolean | no | `true` | Set `false` to assert the caller stays **monolingual** — how a regression in regional-language handling gets caught. |
| `switch_triggers` | list | no | `[]` | Max 6 of: `numbers`, `technical_terms`, `proper_nouns`, `frustration`, `clarification`, `throughout`. Empty means unconstrained. |
| `secondary_ratio` | number | no | `null` | 0–0.9. Rough share of words in the secondary languages. Capped below 1.0 because past that point the primary language is mislabelled, not mixed. |
| `sample_utterances` | list | no | `[]` | Max 10. Illustrative for authors, not assertions. |

Rules enforced on this block:

- A language cannot be mixed into itself — `primary` may not appear in
  `secondary`, and `secondary` may not repeat a tag.
- `secondary_ratio` requires `expected: true`. Declaring a ratio while
  asserting no mixing is a contradiction, and silently honouring one half of
  it would make the scenario behave unlike what its author wrote.
- Every tag is checked against the catalogue, so `code_mixing` cannot
  reference a language the platform does not support.

Nothing here detects language from audio; that belongs to the speech phases.
This is the authored intent.

### Supported languages

Thirteen languages, ordered by number of speakers. The catalogue in
`backend/app/core/languages.py` is the single source of truth: the schema, the
search filters, the CLI and `GET /api/v1/languages` all read from it, so a
language cannot be supported in one place and unknown in another.

| Code | Name | Endonym | Script | Locale |
|------|------|---------|--------|--------|
| `hi-IN` | Hindi | हिन्दी | Deva | `hi_IN` |
| `bn-IN` | Bengali | বাংলা | Beng | `bn_IN` |
| `mr-IN` | Marathi | मराठी | Deva | `mr_IN` |
| `te-IN` | Telugu | తెలుగు | Telu | `te_IN` |
| `ta-IN` | Tamil | தமிழ் | Taml | `ta_IN` |
| `gu-IN` | Gujarati | ગુજરાતી | Gujr | `gu_IN` |
| `ur-IN` | Urdu | اردو | Arab | `ur_IN` |
| `kn-IN` | Kannada | ಕನ್ನಡ | Knda | `kn_IN` |
| `or-IN` | Odia | ଓଡ଼ିଆ | Orya | `or_IN` |
| `ml-IN` | Malayalam | മലയാളം | Mlym | `ml_IN` |
| `pa-IN` | Punjabi | ਪੰਜਾਬੀ | Guru | `pa_IN` |
| `as-IN` | Assamese | অসমীয়া | Beng | `as_IN` |
| `en-IN` | Indian English | Indian English | Latn | `en_IN` |

`script` is the ISO 15924 code, which tells a renderer or a TTS voice which
writing system to expect — note that Bengali and Assamese share `Beng` while
Hindi and Marathi share `Deva`, so script alone never identifies a language.
`locale` is the POSIX form, for the components that want it in that shape.

The catalogue is readable at runtime, so a client does not have to hardcode
the list:

```bash
curl -s http://localhost:8000/api/v1/languages
```

```json
{
  "total": 13,
  "languages": [
    {"code": "hi-IN", "name": "Hindi", "endonym": "हिन्दी", "script": "Deva", "locale": "hi_IN"}
  ]
}
```

A malformed tag and an unsupported one fail differently on purpose. `Hindi` or
`hi_IN` is rejected for *shape* (the expected form is `xx` or `xx-XX`), while a
well-formed but unsupported tag such as `fr-FR` is rejected with the full list
of supported tags — so an author learns the options rather than discovering
mid-run that nothing can speak their choice.

---

## Validation rules worth knowing

**Unknown fields are errors.** Every model sets `extra="forbid"`. A typo like
`persoan:` fails loudly instead of being silently ignored, which would
otherwise make a scenario behave unlike what its author wrote. The error names
both the unexpected key and the missing one.

**Quote values that look like numbers.** `known_facts` values must be strings
and are *not* coerced. YAML's implicit typing would read `account: 0123` as
the integer `123` and lose the leading zero — and these values get spoken
aloud. Write `account: "0123"`.

**At least one expected outcome is required.** A scenario with nothing to
check can neither pass nor fail.

**Duplicates are rejected** in `expected_outcomes` and `persona.traits`
(case-insensitive). A repeated outcome would be scored twice and skew the
result.

**`.nan` and `.inf` are rejected.** YAML accepts those literals; the numeric
range checks refuse them.

**Whitespace is stripped** from every string field.

---

## Security and resource limits

Scenario YAML is parsed **only** with `yaml.safe_load`. `yaml.load` with the
default loader constructs arbitrary Python objects from tags such as
`!!python/object/apply:os.system`, which would turn a scenario file into
remote code execution. Payloads of that shape are rejected as syntax errors,
and a test asserts that such a payload does not take effect.

| Limit | Value | Why |
|-------|-------|-----|
| Input size | 256 KiB | A real scenario is a few kilobytes |
| Node count | 10,000 | Anchors and aliases let a few hundred bytes expand into gigabytes — the "billion laughs" pattern stays under any byte cap, so expansion is measured *after* parsing |
| Nesting depth | 20 | Bounds deeply nested structures |
| Cyclic aliases | Rejected | See below |

### Recursive aliases are rejected

`safe_load` is safe from code execution but will still build a genuinely
*cyclic* object graph from a recursive alias:

```yaml
name: recursive-test
language: hi-IN
persona: &persona
  identity: *persona      # refers to the structure that contains it
```

That produces a mapping whose own value is itself, which naive traversal walks
forever. The loader detects it by tracking object identity along its active
traversal path and rejects it:

```
422  yaml_syntax_error
scenario YAML contains a recursive alias: an anchor refers to a structure
that contains itself. Remove the self-reference - a scenario must be a
finite document.
```

**Non-cyclic anchors keep working.** Referencing one anchor from several
places is normal and accepted — only a structure that contains *itself* is
refused:

```yaml
persona:
  identity: Caller
  traits: &shared
    - impatient
expected_outcomes: *shared    # fine: shared, not cyclic
```

Files are stat-checked before being read, so an oversized file is rejected
without being pulled into memory.

---

## Validating a scenario

### Over HTTP

`POST /api/v1/scenarios/validate` takes YAML and returns a verdict. Nothing is
stored, and no suite is needed.

```bash
curl -s -X POST http://localhost:8000/api/v1/scenarios/validate \
  -H 'Content-Type: application/json' \
  -d '{"yaml": "name: minimal\nlanguage: en-IN\npersona:\n  identity: Caller\ngoal:\n  objective: Ask a question.\nexpected_outcomes:\n  - Bot answers\n"}'
```

Valid input returns the normalised specification, both as JSON and as
canonical YAML with defaults materialised:

```json
{
  "valid": true,
  "errors": [],
  "normalized": { "name": "minimal", "goal": { "max_turns": 20 }, "...": "..." },
  "normalized_yaml": "name: minimal\nlanguage: en-IN\n..."
}
```

Invalid input returns **HTTP 200** with `valid: false` and field-addressed
errors. The status is 200 because the request to validate succeeded; a 4xx
would make "your YAML is wrong" indistinguishable from "the validation
endpoint is broken".

```json
{
  "valid": false,
  "errors": [
    {
      "field": "audio.snr_db",
      "message": "Input should be less than or equal to 40",
      "type": "less_than_equal"
    }
  ],
  "normalized": null,
  "normalized_yaml": null
}
```

Field paths are dotted and include list indices — `persona.traits.0`,
`audio.snr_db` — matching how an author reads their own file. A YAML syntax
error is reported against `<document>` with the line and column.

The one failure that is *not* a 200 is an oversized body, which returns 413:
that is a property of the request rather than of the scenario.

### On the command line

`validate` needs no database and no running service, which is the point — an
author checking a file should not have to start PostgreSQL, and CI should be
able to reject a malformed scenario before any service exists.

```bash
bhashabench validate scenarios/appointment_booking.yaml
# valid: appointment_booking (hi-IN Hindi)

bhashabench validate scenarios/appointment_booking.yaml --show-normalized
bhashabench validate - < scenarios/appointment_booking.yaml   # from stdin
bhashabench validate broken.yaml --json                       # machine-readable
```

Exit codes are meaningful: `0` valid, `2` rejected. See [CLI.md](CLI.md).

### In Python

```python
from pathlib import Path
from app.services.scenario_loader import spec_from_file, spec_from_yaml, spec_to_yaml

spec = spec_from_file(Path("scenarios/appointment_booking.yaml"))
spec = spec_from_yaml(yaml_text)
text = spec_to_yaml(spec)  # canonical YAML, declared field order
```

Raises `ScenarioSyntaxError`, `ScenarioValidationError` (carrying
`.errors` with field paths) or `ScenarioTooLargeError`.

---

## Storing a scenario

```bash
# Create a suite
curl -s -X POST http://localhost:8000/api/v1/suites \
  -H 'Content-Type: application/json' \
  -d '{"name": "Hindi appointment flows"}'

# Add a scenario to it
curl -s -X POST "http://localhost:8000/api/v1/suites/$SUITE_ID/scenarios" \
  -H 'Content-Type: application/json' \
  -d "$(python -c 'import json,sys; print(json.dumps({"yaml": open("scenarios/appointment_booking.yaml").read()}))')"
```

The stored row keeps the whole normalised specification in `scenarios.spec`,
with `name`, `description` and `language` projected into their own columns for
filtering and uniqueness. `spec_version` records the schema revision that
produced it.

Scenario names are unique **per suite**, so two suites may each contain an
`appointment_booking`. A duplicate within one suite returns 409.

---

## Bundles: bulk import and export

A bundle is one YAML document holding a suite's metadata and many scenarios.
It is what moves a scenario library between environments, into version control
and through review.

```yaml
format: bhashabench.scenario-bundle/v1
suite:
  name: Hindi appointment flows
  description: Reference suite
scenarios:
  - name: appointment_booking
    language: hi-IN
    persona:
      identity: Working professional
    goal:
      objective: Book an appointment for tomorrow.
    expected_outcomes:
      - Confirm appointment date
```

| Field | Required | Notes |
|-------|----------|-------|
| `format` | **yes** | Must be exactly `bhashabench.scenario-bundle/v1`. Checked first, so a scenario file handed to the bundle parser gets "this is not a bundle" rather than a list of missing-field errors. |
| `suite.name` | **yes** | Descriptive only on import — the target suite is addressed by URL, never by this name, so a bundle cannot be made to write into a suite the caller did not name. |
| `suite.description` | no | Carried through on export. |
| `scenarios` | **yes** | 1–500 entries, each a scenario document in the format above. |

Each entry is validated with the ordinary scenario schema, so a bundle can
never introduce a scenario that a single-scenario POST would reject. Entry
errors are **collected, not short-circuited**: one request tells an author
about every bad entry, addressed by index and name, rather than making them
fix fifty entries one round trip at a time.

### Importing

```bash
# Dry run first: validates, reports collisions, writes nothing
curl -s -X POST "http://localhost:8000/api/v1/suites/$SUITE_ID/scenarios/import"   -H 'Content-Type: application/json'   -d "$(python -c 'import json;print(json.dumps({"yaml":open("bundle.yaml").read(),"dry_run":True}))')"
```

```json
{
  "total": 3, "valid": 2, "imported": 0, "failed": 1,
  "duplicates": ["appointment_booking"],
  "entry_errors": [
    {"index": 2, "name": "bad_entry", "errors": [{"field": "language", "message": "...", "type": "value_error"}]}
  ],
  "dry_run": true, "committed": false
}
```

Two flags govern behaviour:

- **`dry_run`** (default `false`) — validate and report, write nothing.
- **`atomic`** (default `true`) — all or nothing. One failed or colliding
  entry abandons the whole import, so a partially-applied library never has to
  be unpicked by hand. Set `false` to import the valid entries and have the
  rest reported.

`committed` is reported separately from `imported` so that "nothing to do" is
distinguishable from "nothing was done". Existing scenarios are **never
overwritten**: a name already present in the target suite is reported as a
duplicate and skipped. Updating is an explicit `PUT`.

### Exporting

```bash
curl -s "http://localhost:8000/api/v1/suites/$SUITE_ID/scenarios/export"
bhashabench export "$SUITE_ID" --output bundle.yaml
```

Export is **deterministic and round-trippable**. Scenarios come out ordered by
name, defaults are materialised, and no database identifier or timestamp is
included — so exporting the same suite twice produces byte-identical output,
and a bundle committed to git produces a reviewable diff rather than noise.
Re-importing an exported bundle into an empty suite reproduces the original
scenarios exactly; the test suite asserts both properties.

Because ids are omitted, a bundle describes scenarios rather than rows. That
is what makes it safe to move between environments.

---

## Round-tripping

`normalized_yaml` is itself valid input, and re-validating it produces an
identical specification — a property the test suite asserts. Serialisation
preserves the declared field order rather than alphabetising, and does not
escape non-ASCII text, so Indian-language content stays readable.
