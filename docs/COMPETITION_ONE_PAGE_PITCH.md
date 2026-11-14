# BhashaBench

**Test whether Indian-language voice AI actually understands people in
real-world conditions.**

Great Indian AI Internship Challenge — Gnani AI
· <https://github.com/YushBytes/BhashaBench>

---

## The problem

A voice bot that performs flawlessly in a quiet demo frequently fails on a real
Indian phone call. The call arrives over a lossy mobile network with traffic, a
ceiling fan or a market in the background. The caller speaks Tamil with an
accent the model was not tuned for, switches to English for the account number
and the amount, and interrupts the bot halfway through its prompt.

Teams discover these failures the way their customers do: in production.
Manual testing does not scale to ten languages times twenty scenarios. Studio
audio hides the packet loss and codec artefacts that break recognition in the
field. Code-mixing — Hinglish, Tanglish and their regional equivalents — is how
people actually speak and rarely how bots are evaluated. And "it sounded fine"
is not a metric.

## The solution

BhashaBench turns a voice-bot conversation into a **structured, reproducible,
inspectable test**. A scenario declares a persona, a language, an objective, the
facts the caller may quote and the acoustic conditions to simulate. The platform
synthesises the caller's speech, degrades it the way a real network does,
carries it to the bot under test, transcribes the reply, decides what the caller
says next, and stores every turn with its audio and timings.

The result is evidence an engineer can read: what was said, in what order, under
what conditions, with what measured durations — and, explicitly, what was *not*
established.

## Implemented and verified

| Component | State |
|---|---|
| Scenario engine — YAML authoring, strict validation, 13-language catalogue, code-mixing annotations, bundles, CLI | Implemented |
| **Gnani Prisma** (speech to text) behind a provider-independent interface | Implemented; live-verified 2026-11-07 (auth, real batch request, response parsing) |
| **Gnani Timbre** (text to speech) — 13 voices, 10 languages, 8 kHz telephony audio | Implemented; live-verified 2026-11-07 (auth, request shape, decodable 8 kHz mono audio) |
| Deterministic caller engine — 9-state machine, 11 ordered rules, decision validation | Implemented |
| Audio degradation — band-limiting, noise at a measured SNR, clipping, packet loss, reproducible from a fixed seed | Implemented; achieved SNR asserted to better than 0.5 dB. Runs apply fixed named presets: a scenario's declared SNR and packet loss are not applied, and no preset applies packet loss |
| Pipeline orchestration — execution modes, artefact store, process-wide concurrency limit | Implemented |
| Operator workspace and public site | Implemented |

**2,073 automated tests; 2,032 pass, 41 are opt-in billable live-provider tests
and are skipped.** 36 API paths, 44 operations. Zero lint, type or migration
drift.

## Demo use case: Tamil crop-insurance claim

`scenarios/demo/tamil_crop_insurance.yaml` — a smallholder paddy farmer near
Thanjavur calls a crop-insurance helpline about a claim filed after unseasonal
rain. Tamil with English for the policy number, the scheme name and the amount.
The recorded run applied **light background noise at 25 dB SNR on the
300–3400 Hz phone band, with no packet loss**: the scenario declares rural
conditions at 10 dB SNR with 8% packet loss, and at the time the engine
applied only the profile's fixed preset. Since Phase 0 a new run applies the
declared 10 dB and 8% loss. Each degraded artefact records the parameters
actually used.

The recorded run completed five caller turns and four bot turns, transcribed
four replies, stored **12 audio artefacts** (original and degraded for each
turn, each degraded file naming the original it came from), and recorded the
outcome **`no_progress`** — the instrument detecting that the bot under test
got nowhere. That negative result is the product working.

## Architecture

```
scenario (YAML) → deterministic caller → Gnani Timbre (TTS)
    → degradation (seeded: band-limit, noise at measured SNR, clipping, loss)
    → bot adapter → Gnani Prisma (STT) → caller decides the next turn
    → PostgreSQL + on-disk audio artefacts → operator workspace
```

Every vendor's wire format is confined to one adapter module; nothing above the
provider boundary has heard of a vendor field name. That is what lets a second
engine be benchmarked later without touching anything else.

## What makes it different

- **Reproducible by construction.** Degradation is seeded; the same seed and
  profile produce byte-identical audio. An artefact nobody can reproduce is not
  evidence.
- **Indian-language first.** Thirteen languages with endonym, script and locale;
  code-mixing is a declared, first-class test axis, not an afterthought.
- **Measurements, not scores.** The platform reports counts, durations and
  state transitions. It computes no accuracy figure, because none is computable
  without a reviewed reference transcript.
- **Engineered not to overclaim.** An execution mode records whether audio
  reached a real bot, derived from the replies rather than from the label — so
  a run mislabelled as an external bot test is visible as one.

## Limitations, stated plainly

- **Live-tested:** Prisma and Timbre authentication, request and response paths.
- **Simulated:** the bot. The demonstration run stubs it with fixture audio and
  uses the offline fake speech providers, so the transcript shown is scripted
  stub output. **No recognition accuracy, word error rate or quality score is
  measured or claimed anywhere.**
- **Not implemented:** telephony (`telephony_test` exists in the vocabulary and
  is refused), automated evaluation and scoring, authentication.
- **Not integrated:** Gnani **Evon**. No text-generation endpoint is published
  and the released model has no hosted inference provider, so the caller is a
  deterministic rule engine, named for what it is. `evon` is not a registered
  provider and is refused by name.
- **No real voice bot has been tested through the pipeline**, and no telephone
  call has ever been placed.
- **Two known defects remain open** and are documented in the repository:
  `offline_simulation` does not reach a terminal status in a single call, and
  the bot adapter chosen per run is ignored at execution in favour of the
  configured default.

Simulated conditions are simulated. This repository contains no field
recordings and makes no claim that it does.
