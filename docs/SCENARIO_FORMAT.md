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

### Supported languages

`hi-IN`, `ta-IN`, `te-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `bn-IN`, `gu-IN`,
`pa-IN`, `or-IN`, `as-IN`, `ur-IN`, `en-IN`.

A well-formed but unsupported tag such as `fr-FR` is rejected, and the error
lists the supported tags — so an author learns the options rather than
discovering mid-run that nothing can speak their choice.

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
| Nesting depth | 20 | Bounds recursive structures |

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

## Round-tripping

`normalized_yaml` is itself valid input, and re-validating it produces an
identical specification — a property the test suite asserts. Serialisation
preserves the declared field order rather than alphabetising, and does not
escape non-ASCII text, so Indian-language content stays readable.
