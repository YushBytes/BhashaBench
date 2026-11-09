# Reference scenarios

Six scenarios, one per language, chosen so that each one fails for a different
reason when a bot is weak. They are the worked examples for
[`docs/SCENARIO_FORMAT.md`](../docs/SCENARIO_FORMAT.md) and the fixtures used
when demonstrating the library commands.

| File | Language | What it stresses |
|------|----------|------------------|
| `appointment_booking.yaml` | `hi-IN` Hindi | Every field the schema accepts, documented inline. Hinglish mixing on numbers and medical terms. |
| `tamil_electricity_bill.yaml` | `ta-IN` Tamil | Heavy Tanglish — account numbers and amounts in English, over market noise. The mixed tokens are the ones that decide whether the payment is right. |
| `bengali_balance_enquiry.yaml` | `bn-IN` Bengali | An elderly caller who pauses mid-sentence on a noisy line. Long silences that are not end-of-turn. |
| `marathi_delivery_reschedule.yaml` | `mr-IN` Marathi | A frustrated repeat caller who falls back to Hindi and English — mixing triggered by frustration, exactly when recognition can least afford it. |
| `telugu_order_tracking.yaml` | `te-IN` Telugu | The worst channel this bench simulates: 6 dB SNR, 18% packet loss. Everything else is deliberately simple so a failure points at the audio. |
| `english_insurance_claim.yaml` | `en-IN` Indian English | The control: `code_mixing.expected: false` asserts the caller stays monolingual, so a regression that starts mixing gets caught. |

`bundles/indian_language_reference.yaml` holds all six as one importable
bundle, built with the same serialiser the export endpoint uses. Importing it
and exporting the suite reproduces the file byte for byte; a test asserts that
against a real database.

## `demo/` — not part of the reference set

`demo/tamil_crop_insurance.yaml` is the scenario used for the recorded
demonstration: a crop-insurance claim under a government scheme, Tamil with
English for the policy number and the amount, on a rural mobile line at 10 dB
SNR with 8% packet loss.

It is deliberately **not** in this directory's top level. The six files above
are a survey with one scenario per language, and `test_languages_are_distinct`
enforces that — a second Tamil file here would fail it. The reference glob
(`scenarios/*.yaml`) is not recursive, so `demo/` is invisible to it and to the
bundle. The demo scenario is a first-class scenario in every other respect:
the same schema, the same validator, the same import path, and it validates
against the live API.

Adding a file to `demo/` therefore does **not** require regenerating the
bundle. Adding one to the top level does.

---

## Using them

```bash
# Check every file. No database needed.
for f in scenarios/*.yaml; do bhashabench validate "$f" || exit 1; done

# Load all six into a new suite.
SUITE=$(bhashabench suite create "Reference" --json | jq -r .id)
bhashabench import scenarios/bundles/indian_language_reference.yaml \
  --suite "$SUITE" --dry-run
bhashabench import scenarios/bundles/indian_language_reference.yaml --suite "$SUITE"

# Then explore.
bhashabench scenario list --suite "$SUITE"
bhashabench scenario list --tag logistics
bhashabench scenario list --language ta-IN
```

See [`docs/CLI.md`](../docs/CLI.md) for the full command reference.

---

## Regenerating the bundle

After editing any scenario here, rebuild the bundle so the two do not drift:

```bash
cd backend
python -c "
import pathlib
from app.services.bundle import build_bundle
from app.services.scenario_loader import spec_from_file

paths = sorted(pathlib.Path('../scenarios').glob('*.yaml'))
text = build_bundle(
    [spec_from_file(p) for p in paths],
    suite_name='Indian language reference suite',
    suite_description=(
        'Six reference scenarios, one per language, covering code-mixing, '
        'audio stress and a monolingual control.'
    ),
)
pathlib.Path('../scenarios/bundles/indian_language_reference.yaml').write_text(
    text, encoding='utf-8', newline='\n'
)
"
```

Export is deterministic, so running this without having changed a scenario
leaves the file byte-identical — the diff is empty when nothing moved.

---

## Scope

These describe test cases. Nothing here places a call, synthesises speech or
produces a score: telephony, speech services, audio degradation, caller
simulation and evaluation arrive in later phases. The `audio` and
`constraints` blocks are validated and stored today, and applied then.
