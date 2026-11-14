# The end-to-end voice testing pipeline

How a scenario becomes a multi-turn conversation with real audio: what runs,
what is simulated, and which of the two any given run actually did.

---

## Execution modes — read this first

The mode is the honesty control for the whole phase. Every run records one,
every report repeats it, and nothing infers it.

| Mode | Audio | The bot's side comes from | What a result establishes |
|------|-------|---------------------------|---------------------------|
| `offline_simulation` | none | text replies: the scripted adapter reads `PIPELINE_FIXTURE_BOT_TEXT_PATH`; the manual adapter waits for `POST /bot-text` | The caller's logic. **Nothing about audio.** |
| `audio_fixture_test` | real, end to end | pre-recorded or generated audio files | Synthesis, degradation, storage and transcription work together. **Nothing about any particular voice bot.** |
| `external_bot_test` | real, end to end | audio an operator obtained from the bot under test | The only mode that may be described as testing a bot |
| `telephony_test` | — | — | **Not implemented.** Creating a run in this mode is refused |

Two mechanisms keep the labels honest rather than aspirational:

- **`telephony_test` cannot be used.** The enum member exists so the
  vocabulary is complete and the gap is visible where someone would look for
  it, but `IMPLEMENTED_MODES` excludes it and `RunConfig.validate` refuses it.
- **`bot_audio_externally_received`** is true only when *every* reply in a run
  came from outside this process. A fixture reply clears it permanently, so a
  run labelled `external_bot_test` whose replies were fixtures reports `false`
  and can be seen to be mislabelled.

### What has and has not been verified

No live Gnani call was made for Phase 7. The pipeline was exercised end to end
with the offline speech and transcription fakes, which produce genuine 16-bit
WAV, so every stage between the two providers ran for real.

| | |
|---|---|
| Multi-turn audio workflow, offline | ✅ Verified — 288 offline tests |
| Degradation, reproducibility, SNR accuracy | ✅ Verified — measured, see below |
| Artefact storage, original preservation | ✅ Verified |
| Timbre / Prisma through the existing services | ✅ Verified with the offline fakes |
| Timbre / Prisma live in a pipeline run | ❌ Not tested — no live call was authorised or made |
| A real voice bot conversation | ❌ Not tested — no external bot endpoint was available |
| Telephony | ⬜ Not implemented |
| Recognition accuracy under degradation | ❌ Not measured — the fixtures contain no speech and no reviewed ground truth |
| Concurrency limit enforced | ✅ Verified — competition Phase 7.1 (original Phase 9); the limit holds under forced overlap, and exceptions, cancellation and timeouts all release capacity |

---

## The turn lifecycle

Phase 7 **wraps** Phase 6 rather than replacing it. The caller, its state
machine and the transcription semantics are all the Phase 6 implementation; the
pipeline adds the audio legs around them.

```
  orchestrator.next_caller_turn()   Phase 6: decide, synthesise, persist
            │
            ▼
  read the original artefact back   Phase 7
            │
            ▼
  degrade it                        Phase 7  ──▶ stored as a second artefact
            │                                     the original is untouched
            ▼
  adapter.send_turn(...)            Phase 7: hand it to the bot
            │
            ▼
  validate the reply's audio        Phase 7  ──▶ invalid audio is never
            │                                     stored as a successful turn
            ▼
  orchestrator.submit_bot_audio()   Phase 6: Prisma, then persist
            │
            └──▶ the caller reacts to the transcript, and the loop repeats
```

Reading the caller's audio back off disk rather than having Phase 6 hand the
bytes over is a deliberate small cost: it keeps `next_caller_turn`'s signature
and Phase 6's tests untouched, and the read is a local file.

**Every stage leaves an event**, including the ones that failed, with its
measured duration. A run that broke at transcription and one that broke at
synthesis look different in the report, which is the only way either is
diagnosable.

### Four bounds on a run

One bound is never enough:

1. The caller's own `budget.exhausted` rule, which closes the conversation
   gracefully with `TURN_BUDGET_EXHAUSTED`.
2. The engine's loop, capped at the recorded turn budget.
3. A wall-clock timeout over the whole run (`PIPELINE_RUN_TIMEOUT_SECONDS`),
   because a run that hangs holds a database session.
4. Across runs rather than within one: the concurrency limit below.

A narrower `max_turns` is written into the caller's own metadata, so Phase 6's
budget rule respects it and the caller closes itself rather than being cut off
mid-conversation with no outcome.

---

## Status and outcome

Two separate things, because "failed" is not a finding.

**Status** — how far the run got: `created`, `initializing`, `running`,
`completed`, `failed`, `cancelled`, `timed_out`.

The `test_runs.status` column keeps Phase 2's coarser five-value lifecycle; the
precise status lives in `run_metadata`. `to_run_status` is the single place the
mapping lives, and `timed_out` maps to the column's `failed` — a timeout *is* a
failure at that level of detail, and widening the enum would mean editing the
`finished_at_matches_status` CHECK constraint that enumerates the terminal
three.

**Outcome** — why it ended:

| Outcome | Means | About the bot? |
|---------|-------|----------------|
| `goal_achieved` | The caller got what it came for | yes |
| `bot_refused` | The bot declined or had no record | yes |
| `bot_unintelligible` | Nothing transcribable came back | yes |
| `no_progress` | The bot never said anything usable | yes |
| `turn_budget_exhausted` | Ran out of turns | yes |
| `provider_error` | **Our** synthesis or transcription broke | **no** |
| `audio_validation_failed` | Audio did not survive inspection | **no** |
| `external_bot_unavailable` | The bot could not be reached | **no** |
| `cancelled` | An operator stopped it | **no** |
| `abandoned` | Left in flight with nothing executing it; closed by `bhashabench runs recover-stale --apply` | **no** |

`provider_error`, `audio_validation_failed`, `external_bot_unavailable` and
`abandoned` are collected in `OUR_FAULT_OUTCOMES`; `cancelled` is likewise not
about the bot. Aggregating them into a
bot's score would blame it for our outage, so Phase 11 should exclude them from
any quality metric; the set exists now so that decision sits where the outcomes
are defined.

An unfinished run reports `outcome: null`. It does not report a failure,
because a run that has not happened has no result.

---

## Audio degradation

A real Indian phone call is not a studio recording, and a bench that only ever
feeds a bot clean 16 kHz speech measures something nobody experiences.

### Every transformation is an approximation, not a measurement

**These are simulated conditions.** `heavy_background_noise` is shaped white
noise at a stated signal-to-noise ratio over a band-limited channel. It is
**not** a recording of a market in Coimbatore, this repository contains no
field recordings, and nothing here claims otherwise. The profiles are named for
severity because severity is what they control.

### Why there is no numpy

The repository has no numeric or audio dependency — no numpy, scipy, soundfile
or pydub — and `audioop`, which would have supplied `ratecv`, `tomono` and
`lin2lin`, was removed from the standard library in Python 3.13. The choice was
to add a scientific stack or to write the hundred or so lines of integer
arithmetic these transformations actually need.

One utterance is a few seconds of 8 kHz mono — tens of thousands of samples —
so pure Python is comfortably fast enough (~30 ms for two seconds of audio
through the heaviest profile). A dependency carried for that would be
overengineering. If a later phase needs spectral work — a real reverb, a
measured room impulse — that is the point to reconsider; it is not needed to
make speech sound like a phone call.

Only **16-bit PCM WAV** is accepted. Both Timbre and the offline fake produce
it, and guessing at other widths without a decoder is how a bench starts
reporting on audio it did not understand.

### The transformations

Applied in a fixed order, which mirrors a real path — a codec band-limits
before the line adds noise, and loss happens last because it happens on the
wire:

| # | Transformation | Notes |
|---|----------------|-------|
| 1 | `to_mono` | Averages interleaved channels |
| 2 | `resample` | Linear interpolation. Mono only — stereo is refused rather than mangled |
| 3 | `bandpass` | One-pole high-pass and low-pass in cascade: a gentle 6 dB/octave roll-off, which is the honest shape for a telephone channel. A band edge above Nyquist is clamped **and reported** |
| 4 | `add_noise` | Scaled from the signal's own RMS, so the stated ratio holds for *this* utterance |
| 5 | `reduce_amplitude` | Quiet speech |
| 6 | `clip` | Hard clip at a fraction of full scale; the count clipped is recorded |
| 7 | `packet_loss` | Whole 20 ms packets, filled with silence — scattered samples would sound like crackle, not like a gap |

### Profiles

| Profile | Rate | Band | SNR |
|---------|------|------|-----|
| `clean` | unchanged | — | — |
| `telephony_bandwidth` | 8 kHz mono | 300–3400 Hz | — |
| `light_background_noise` | 8 kHz mono | 300–3400 Hz | 25 dB |
| `moderate_background_noise` | 8 kHz mono | 300–3400 Hz | 15 dB |
| `heavy_background_noise` | 8 kHz mono | 300–3400 Hz | 7 dB |

The three noise profiles sit on the telephony channel, because noise on a
wideband studio recording is not the condition being simulated. **No named
profile applies packet loss** on its own — a profile name never implies a
lossy network. Packet loss comes from a scenario's declaration (below).

The ratios are accurate to better than 0.5 dB, asserted across seven targets by
isolating the noise (noisy signal minus clean signal) and measuring the real
achieved ratio rather than restating the parameter.

### Scenario environments map onto profiles

A scenario names an acoustic *environment*; the engine applies a *severity*.
`app/schemas/scenario_spec.py` defined these six names in Phase 2 with the note
"Phase 7 implements these":

| Scenario declares | Engine applies |
|-------------------|----------------|
| `clean` | `clean` |
| `rural` | `light_background_noise` |
| `indoor_fan` | `light_background_noise` |
| `urban` | `moderate_background_noise` |
| `market` | `heavy_background_noise` |
| `worst_case` | `heavy_background_noise` |

Several environments share a severity, which loses information — so a run
records **both** the declared environment and the profile applied, and the
report shows both rather than implying the environment was recreated.

### Settings declared but not enforced

A scenario can declare more than the platform acts on. Every run records
`settings_not_enforced` at creation — each entry a `setting`, its `declared`
value and the `reason` — and the API and inspector show it:

| Setting | Listed when | Why |
|---|---|---|
| `constraints.allow_interruptions` | always | turns strictly alternate; no barge-in (Phase 9) |
| `constraints.max_silence_seconds` | always | no silence detection or re-prompt timer (Phase 9) |
| `constraints.required_phrases`, `forbidden_phrases` | non-empty | nothing checks the bot's replies (Phase 11) |
| `code_mixing` | `expected: true`, deterministic caller | the caller speaks monolingual phrase tables |
| `persona.speaking_style`, `persona.traits` | deterministic caller | the phrase tables do not vary by them |
| `audio` | `offline_simulation` | no audio moves |

`null` on a run created before the record means unknown — never "everything
was enforced".

### A scenario's declared SNR and packet loss are applied

The environment name chooses the **channel** (the profile's rate and band).
The scenario's own `snr_db` and `packet_loss_percent` set the **noise and
loss** on it. Precedence:

1. **An operator's explicit profile** for the run wins, applied as its
   reviewed preset (no packet loss). `degradation_requested.source` is
   `operator`.
2. Otherwise **the scenario's declaration**: its `snr_db` on the mapped
   channel and its `packet_loss_percent`. `source` is `scenario`.
3. A scenario whose environment is `clean` asks for no noise, so its
   `snr_db` does not apply; a declared packet loss still does.

Requested and achieved are both recorded. The run's
`degradation_requested` holds `source`, `snr_db` and `packet_loss_percent`;
every degraded artefact holds `requested_from`, the requested `snr_db` and
`packet_loss_percent`, the **measured** `snr_db_achieved` (from the noise
actually added) and `packet_loss_realised_percent` with the packet counts.
Tests re-derive both from the stored bytes rather than trusting the fields.

Until Phase 0 the declared values were read by nothing: a scenario declaring
10 dB and 8% loss ran at its preset (25 dB, no loss). Runs created before the
change carry no `degradation_requested` and keep their preset exactly, so
their recorded evidence is unchanged.

A scenario's declared environment wins unless the request names a profile
explicitly: the scenario's audio section is part of the test's definition, and
silently running it clean would report a result for a condition never applied.

### Reproducibility

A degraded artefact is only evidence if the same input, profile and seed
produce the same bytes.

- A seed is **required** for anything stochastic. `DegradationConfig.validate`
  refuses noise or packet loss without one.
- The seed is recorded on the artefact, and the default
  (`PIPELINE_NOISE_SEED`) is fixed so a run is reproducible even when nobody
  asked for one.
- Byte-identical output across runs is asserted for every profile.

### What is recorded

Every processed artefact carries the transformation list, every parameter, the
seed, both formats, both sample rates, both channel counts, both durations, the
peak amplitude and the clipped-sample count. The realised packet-loss rate is
recorded beside the requested one, because with few packets the two differ a
lot and reporting only the request would overstate what the audio suffered.

---

## Concurrency

At most `PIPELINE_MAX_CONCURRENT_RUNS` runs execute at once. Beyond that,
`POST /start` answers **503 immediately** - it does not queue.

**Why refuse rather than wait.** A request parked behind an unbounded line has
no bound on its own latency, and a client cannot tell a slow run from a stuck
one. A refusal is a fact the client can act on. The run is untouched by it -
not started, not failed, nothing persisted - so retrying is safe rather than a
second attempt at a half-run.

**Why a counting guard and not `asyncio.Semaphore`.** A semaphore that waits
holds pending waiters, and a waiter belongs to the event loop that created it;
a process-wide semaphore would eventually be awaited from a different loop than
a waiter was parked on, which raises intermittently under exactly the
concurrency it exists to control. This limiter never waits, so it holds no
waiter and has no loop affinity. It is a non-blocking counting semaphore; it is
simply not that class. The counter is mutated under a lock held for the
check-and-increment only and never across an `await`, so a synchronous caller
from FastAPI's worker threads cannot race it.

**Scope is the process, and that is the point.** `slots_for_limit` is
`lru_cache`d on the limit, mirroring `get_settings`. A limiter built per request
would count to one and enforce nothing - which is precisely how
`PIPELINE_MAX_CONCURRENT_RUNS` spent Phase 7 as a documented number with no
consumer.

**Release is unconditional.** The slot is held by an `async with`, so normal
completion, an exception, `asyncio.CancelledError` and a timeout all unwind
through the same `finally`. A failing run cannot cost the process a slot
permanently.

**Admission is re-entrant per engine.** `supply_bot_audio` holds a slot and
then calls `run_to_completion`, which would otherwise be refused by the slot
its own caller is holding - a self-inflicted 503 under no load. One engine
instance serves one request and therefore one run, so it holds at most one
slot.

Capacity is observable for tests via `RunSlots.in_use`, `.available` and
`.peak_in_use`; the last is what makes "the limit was never exceeded" assertable
*during* a run rather than only after everything has been released.

## Artefacts

Audio stays on disk under `CALLER_AUDio_STORAGE_DIR`; only a reference reaches
the database and the API.

**The original always survives.** `degrade()` returns new bytes and writes
nothing, so the input cannot be overwritten structurally rather than by
convention. One turn holds two files:

```
<conversation-uuid>/0000-caller-original.wav
<conversation-uuid>/0000-caller-degraded.wav   derived_from: the line above
<conversation-uuid>/0001-bot.wav
```

A degraded artefact names the original it came from, so the pair can be
compared after the fact. A processed artefact without its source is not
evidence.

**Path safety.** Every component of a reference is generated or validated: a
UUID, a non-negative turn index, a speaker enum, a whitelisted variant and a
whitelisted suffix. No caller-supplied string reaches a path — an uploaded
filename of `../../../../etc/passwd.wav` is simply not used — and the resolved
path is checked to be inside the storage root before anything is written.

References are **relative**. An absolute filesystem path would disclose the
server layout and be useless to a client after a redeploy.

**Artefacts are served, carefully.** Phase 7 listed artefacts and refused to
stream them, on the grounds that who may hear a recorded conversation is an
authorisation decision with no identity to make it against. That reasoning
still holds. What changed in competition Phase 8 is that the conversation inspector cannot
work without playback, and withholding the route never created an
authorisation model — it only put the recording out of reach of the one
operator entitled to it.

`GET /test-runs/{id}/artifacts/{turn_index}/audio` streams one stored file
under three constraints:

- **No client string reaches the filesystem.** The artefact is addressed by
  run, turn index and variant — a UUID, a non-negative integer and a
  two-value enum. The stored reference is looked up in the run's own record,
  and the store refuses anything resolving outside its root besides. There is
  no request field a path could travel in.
- **The route is off where it would be reachable.** Staging and production
  refuse with 403 unless `PIPELINE_SERVE_ARTEFACTS=true`, because this payload
  is a recording rather than a status field. Development serves it: the
  operator is the only listener.
- **It claims no authorisation.** A run id is an identifier, not a credential,
  and this route is exactly as open as every other one. Real access control
  arrives with authentication in Phase 15. A 403 here says *this environment
  declines*, never *no such artefact* — the latter would be a lie about what
  is on disk.

The route resolves through the engine's own artefact store rather than
building a second one from settings: whoever constructed the engine may have
pointed it elsewhere, and a reader that guessed would report a present
recording as missing.

Generated audio is never committed; `storage/` is git-ignored.

---

## Bot adapters

How the pipeline obtains the bot's side. Two ship, and **neither opens a
socket**.

| Adapter | Does | `contacts_external_system` |
|---------|------|---------------------------|
| `scripted` | Replays fixture audio, one payload per turn. Deterministic | `false` |
| `manual` | Stores the caller's audio and waits for an operator to post the reply | `false` |

`scripted` is the default, and that is a safety decision: §7 requires the
default configuration not to send audio to arbitrary external destinations, so
the default is the adapter that sends audio nowhere at all.

### Where the scripted adapter gets its fixture

The tests construct `ScriptedBotAdapter` with their own payloads. A run started
through the **API** had no such seam, so the route built the adapter with no
replies and every `audio_fixture_test` failed on turn 0 with "the scripted bot
has no reply for turn 0". The mode was usable only from the tests - which is
also why the test suite never caught it: those tests replace the very seam that
was broken.

`PIPELINE_FIXTURE_AUDIO_PATH` is how an operator supplies that fixture. The
route reads the file once and hands the scripted adapter one reply per turn,
sized from `CALLER_MAX_TURNS`, so a run terminates on its turn budget before it
can exhaust the replies and exhaustion stays a loud error.

Four properties worth keeping:

- **Unset means unchanged.** With no path configured a scripted run still has
  no replies and still fails on turn 0. That failure is honest when no fixture
  exists, so it was not softened into a silent stop.
- **A fixture can never read as a bot.** The scripted adapter reports
  `received_from_bot=False`, so `bot_audio_externally_received` is `false` on
  such a run. This is the honesty control, and it is why the fixture is given
  to *this* adapter and not to `manual`, whose replies are asserted to come
  from a real bot.
- **Only the scripted adapter is offered replies.** `manual` refuses them, and
  correctly: its audio arrives later.
- **No client value reaches the path.** There is no request field for it; it is
  an environment setting an operator controls. A misconfigured path fails with
  a message naming it, rather than resurfacing as the turn-0 error.

**No third-party bot API is invented here.** A real integration is an adapter
written against a real bot's published interface and added to `_FACTORIES` in
`app/pipeline/bots/registry.py`. There is no plugin discovery, for the same
reason the speech subsystems have none: "which bot produced this
conversation?" must be answerable by reading the source.

### Offline replies — how `offline_simulation` terminates

Offline mode moves no audio, so the adapter's `send_turn` is never called.
The engine supplies the bot's side as text instead:

- **scripted** — replies come from `PIPELINE_FIXTURE_BOT_TEXT_PATH`, one per
  line, used in order and repeated, so a single `/start` drives the run to
  its terminal state. Unset, the run **fails** on its first bot turn with an
  error naming the setting. The replies are a fixture, not a bot.
- **manual** — after each caller turn the run pauses with
  `awaiting_bot_text_for_turn` set (healthy, not failed) until an operator
  posts what the bot said to `POST /bot-text`; the run then continues to its
  next pause or its end.

Until Phase 0 the offline bot leg recorded nothing and reported "waiting"
with no way to answer, so each `/start` added one caller turn and the run
stayed `running` indefinitely.

### The manual flow — how a real bot gets tested

This is the honest maximum available until a bot publishes an API or telephony
exists:

1. Create a run with `mode: external_bot_test` and `bot_adapter: manual`.
2. `POST /start`. The pipeline synthesises the caller's turn, degrades it,
   stores it, and pauses. The run stays `running` with
   `awaiting_bot_audio_for_turn` set — **waiting is healthy, not failed**.
3. Play that artefact to the bot under test, however the bot is reachable, and
   record the answer.
4. `POST /bot-audio` with the file. It is validated, transcribed, and the run
   continues to the next pause or to the end.

So the audio exchange is genuinely with the bot under test, while the transport
is a person rather than a protocol this project guessed at.

**The adapter a run records is the adapter that runs it.** Every route after
creation builds its engine from the `bot_adapter` stored on the run, not from
`PIPELINE_BOT_ADAPTER`. `/start` and `/bot-audio`, which call the adapter,
refuse a recorded name that is no longer registered with a 422 naming it;
reads and `/cancel` never call the adapter and stay available. (Until
Phase 0 every route after creation used the settings default, so a `manual`
run was executed by the scripted adapter and failed with its error.)

Audio supplied this way is recorded as externally obtained, because posting it
asserts that it came from the bot. **The pipeline cannot verify that claim and
does not pretend to** — the report names the adapter so a reader can weigh it.

A malformed upload is refused with a 4xx and **leaves the run waiting**, so the
operator can post the right file. A bad filename is their mistake, not a reason
to discard a conversation.

---

## Prisma and Timbre

Both are used through the services Phases 4 and 5 built. There is no second
adapter, no second client and no new vendor constant.

**Timbre** synthesises the caller's turn, inside Phase 6's `CallerService`. The
pipeline forces synthesis on regardless of `CALLER_SYNTHESISE_AUDIO`: a run
that moves audio has nothing to send without it, and that setting exists to
stop Phase 6's *text* conversations billing a provider per turn.

**Prisma** transcribes the bot's reply, through
`ConversationOrchestrator.submit_bot_audio`. That is also why there is no
transcription code in the engine: Phase 6 already stores the artefact, calls
the provider, and records a null-content turn with a `transcription_error` when
the provider fails.

Three failures that look alike and must not be merged:

| Event | Record | Run continues? |
|-------|--------|----------------|
| The bot said nothing | empty transcript — a bot defect | yes |
| We could not transcribe it | `content: null` plus `transcription_error` — our problem | yes |
| The audio was not decodable | the run fails `audio_validation_failed` | no |

A pipeline that collapsed the first two would blame the bot for its own
deafness.

Error text from a provider is redacted before it reaches `run_metadata`,
`turn_metadata` or an API response. Provider messages have carried an
`Authorization` header before now.

### Live tests

Default tests are offline and make **no** provider calls. The opt-in live tests
from Phases 4 and 5 are unchanged and still require their environment
variables. Nothing in Phase 7 consumes credit during an ordinary run of the
suite.

---

## Evidence, not scores

§11's rule, and the field descriptions on the API say so too.

**Measured or counted:** caller turns, bot turns, transcription successes and
failures, each artefact's duration, configured and observed sample rates,
channel counts, the degradation profile and its parameters, the seed, caller
state transitions, which rules fired, goal completion, the failure reason, the
provider error category, and each stage's duration.

**Not computed, and not claimed:** accuracy, word error rate, semantic
correctness, or conversation quality. None is possible without a reviewed
reference transcript — the test fixtures contain tones and generated audio, not
speech with known ground truth — and evaluation is a later phase. A successful
transcription means the pipeline worked, not that the bot answered well.

`RunReportResponse.measurement_note` states this on the wire, so a consumer
cannot mistake these counts for a quality metric.

---

## API

All endpoints are under `/api/v1/test-runs`. There is **no authentication**,
because Phases 1–6 ship none and it lands in Phase 15. Do not expose this
service publicly before then: these endpoints write files to disk and, with a
provider configured, spend money.

| Endpoint | Does |
|----------|------|
| `POST /test-runs` | Creates a run (201). Executes nothing |
| `POST /test-runs/{id}/start` | Runs turns until terminal, or until it needs external audio |
| `POST /test-runs/{id}/bot-audio` | Supplies the bot's reply and continues the run |
| `POST /test-runs/{id}/bot-text` | Supplies the bot's reply as text for an offline run with the manual adapter, and continues it. An empty string records the bot saying nothing |
| `POST /test-runs/{id}/cancel` | Stops it; outcome `cancelled`, never `failed` |
| `GET /test-runs/{id}` | State, counters and outcome |
| `GET /test-runs/{id}/turns` | Every utterance, in order |
| `GET /test-runs` | A filtered, paginated page of runs, newest first |
| `GET /test-runs/{id}/artifacts` | References and measured metadata |
| `GET /test-runs/{id}/artifacts/{turn}/audio` | The stored bytes of one artefact. Supports `Range` |
| `GET /test-runs/{id}/report` | Full evidence: state, artefacts, transitions, every stage |
| `GET /test-runs/bot-adapters/available` | Adapters, their capabilities, and the usable modes |

### Listing runs

`GET /test-runs` pages the run history the dashboard shows. Filters:
`suite_id`, `status`, `mode`, `language`, `outcome` and `scenario` (a
case-insensitive substring; `%` and `_` are escaped, so a wildcard narrows to
nothing rather than matching every row). `limit` is capped at 100.

Two things it deliberately does **not** do:

- **It lists only runs the pipeline created.** A `TestRun` is also the parent
  of a Phase 6 caller conversation, and those record no pipeline metadata —
  listing them would produce rows whose detail view is empty. They stay
  addressable through the caller API.
- **`duration_seconds` is null until a run has both a start and a finish.** An
  elapsed-so-far figure in a duration column reads as a duration and is not
  one.

Turn counts come from one grouped query over the page rather than a query per
row, and they are counted rather than defaulted: a run with no turns reports
zero because zero were found, not because the field was missing.

### A fixture run, end to end

```bash
B=http://localhost:8000/api/v1/test-runs

RUN=$(curl -s -X POST $B -H 'content-type: application/json' -d '{
  "suite_id": "<uuid>",
  "scenario_id": "<uuid>",
  "mode": "audio_fixture_test",
  "noise_profile": "moderate_background_noise",
  "seed": 42
}' | python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')

curl -s -X POST $B/$RUN/start   | python -m json.tool
curl -s     $B/$RUN/artifacts   | python -m json.tool
curl -s     $B/$RUN/report      | python -m json.tool
```

### Status codes

| Code | When |
|------|------|
| 403 | This environment does not stream stored audio (see `PIPELINE_SERVE_ARTEFACTS`) |
| 404 | No such run or scenario, or no artefact for that turn and variant |
| 409 | The run has already finished, or is not ready for this request |
| 503 | Every concurrent-run slot is in use. The run is untouched; retry it |
| 413 | Bot audio over 10 MiB |
| 415 | Bot audio in a container that cannot be decoded |
| 422 | Invalid request, an unimplemented mode, an unknown adapter, or an unsupported scenario language |
| 502 / 504 | The bot adapter was unavailable or timed out |

---

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `PIPELINE_BOT_ADAPTER` | `scripted` | Default adapter. Both options send audio nowhere |
| `PIPELINE_FIXTURE_BOT_TEXT_PATH` | _unset_ | UTF-8 file of bot replies, one per line, that the `scripted` adapter uses in `offline_simulation`, in order and repeated. Unset, an offline scripted run fails on its first bot turn with an error naming the setting |
| `PIPELINE_FIXTURE_AUDIO_PATH` | _unset_ | WAV the `scripted` adapter replays per turn. Unset keeps the turn-0 failure; set, it is what lets `audio_fixture_test` complete. The reply is still not claimed as bot audio |
| `PIPELINE_SERVE_ARTEFACTS` | `false` | Lets a *deployed* environment stream stored audio. Development always does |
| `PIPELINE_RUN_TIMEOUT_SECONDS` | `600.0` | Wall-clock ceiling on one run |
| `PIPELINE_MAX_CONCURRENT_RUNS` | `2` | Bounds provider spend and memory. Enforced: `POST /start` answers 503 beyond it |
| `PIPELINE_NOISE_SEED` | `42` | Fixed so a run is reproducible by default |
| `PIPELINE_NOISE_PROFILE` | `clean` | For runs that name none; a scenario's own profile wins |

The pipeline also reads the Phase 6 caller settings and the Phase 4/5 provider
settings. With `TRANSCRIPTION_PROVIDER=fake` and `SPEECH_PROVIDER=fake` the
whole pipeline runs with no credential at all, which is how the tests run.

---

## Persistence

**No new tables and no migration.** `alembic check` reports no drift, and the
schema is still the five tables Phase 2 created.

| Concept | Row |
|---------|-----|
| A pipeline run | `TestRun` |
| Its conversation | `CallSession` |
| One utterance | `ConversationTurn` |

`TestRun.run_metadata`'s own docstring says it is for "execution context
captured at run time: tool versions, resolved audio profile, seed" — which is
exactly what a pipeline run records. It writes there under a `pipeline`
namespace, beside Phase 6's `caller` namespace in `call_metadata`, so a later
phase recording its own run context cannot collide.

The trade-off accepted is that run state is not queryable with a typed column.
When a field earns an index it should be promoted to one.

Two traps the repositories exist to avoid, both documented in Phase 6 and both
still live: SQLAlchemy does not track mutation *inside* a JSONB value, so an
in-place edit is silently dropped at flush; and the relationships are
`lazy="raise_on_sql"`, so a related row must be loaded deliberately. The second
one bit this phase — reaching `conversation.scenario` on a freshly created row
worked until something committed, which made it a bug that only appeared behind
the HTTP layer.

---

## Testing

```bash
pytest backend/tests/test_pipeline_degradation.py  # the DSP, profiles, SNR
pytest backend/tests/test_pipeline_bots.py         # adapters and the registry
pytest backend/tests/test_pipeline_engine.py       # multi-turn runs, failures
pytest backend/tests/test_pipeline_api.py          # the HTTP surface
pytest backend/tests/test_pipeline_concurrency.py  # the admission limiter
```

288 tests, all offline. The engine and API modules need PostgreSQL
(`docker compose up -d db`) and never skip silently.

The offline speech fake produces genuine 16-bit mono WAV, which is what makes
the whole pipeline exercisable with real bytes through real DSP: only the two
providers and the bot are stubs.

---

## Known limitations

- **No live provider call has been made through the pipeline.** Phases 4 and 5
  were verified live against Gnani; a pipeline run has not been.
- **No real voice bot has been tested.** No external bot endpoint was
  available. The `manual` adapter is the path for when one is.
- **No telephony.** `telephony_test` is refused.
- **No accuracy measurement.** The fixtures contain no speech with reviewed
  ground truth, so no recognition claim is possible — under degradation or
  otherwise.
- **16-bit PCM WAV only** for degradation. MP3 and OGG bot replies can be
  transcribed but not degraded or measured.
- **One conversation per run.** `conversation_of` names this assumption; a
  later phase fanning a run over many scenarios turns it into a list.
- **Resampling is linear interpolation** and relies on the bandpass that the
  telephony profiles apply first to limit aliasing. A profile that downsampled
  without filtering would alias, which is why the presets always pair them.
- **Concurrency is enforced per process, not per deployment.** The limiter
  lives in the application process, so two uvicorn workers each admit
  `PIPELINE_MAX_CONCURRENT_RUNS` runs. Set the value per worker, or put a
  shared limiter behind it, if the real bound is a provider quota.

## Future telephony

Phase 8 adds real calls. The seams are already in place: `ExecutionMode`
carries a `TELEPHONY_TEST` member that nothing can use yet, `BotAdapter` is the
interface a telephony bridge implements, `BotReply.session_id` exists for a
call identifier, and `CallSession` already has `provider_call_id`,
`DIALING`, `NO_ANSWER` and `BUSY` statuses that this phase deliberately never
sets — an offline simulation must not claim a telephony state.

What Phase 8 has to add: a media-streaming bridge, the `ALLOWED_BOT_NUMBERS`
allow-list enforcement, barge-in handling, and the per-run cost caps
(`MAX_CALLS_PER_RUN`, `MAX_MINUTES_PER_DAY`, `MAX_CONCURRENT_CALLS`) that
`.env.example` already declares.
