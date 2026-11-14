# Competition readiness report

**Great Indian AI Internship Challenge (Gnani AI) — deadline 10 November 2026,
23:59 IST.**

| | |
|---|---|
| **Date** | 2026-11-09 |
| **Branch** | `main` — no new branch, no force-push, no rewritten history |
| **Base** | `983f4d9` (Phase 8.1, approved) |
| **Live Gnani calls** | **None.** No credit consumed. All 41 live tests stayed opt-in and skipped |
| **Public deployment** | **Not performed.** Classified **C** — see §8 |
| **Verdict** | **Ready to record and submit.** Four items need you, listed in §14 |

Legend used throughout: **Verified** (command output recorded) ·
**Partially verified** · **Not verified** · **Blocked**.

---

## 1. Executive summary

The repository was already in good order at `983f4d9`. Three things were
genuinely wrong and are now fixed; one approved behavioural change was needed
to make a credible demonstration possible at all.

**What was broken and is fixed**

1. **`audio_fixture_test` could not complete through the API** — the documented
   path to an end-to-end demo. Root cause, minimal fix and tests in §5. This
   was the one behavioural change, and it was approved before implementation.
2. **The Docker backend image was crash-looping** on
   `ModuleNotFoundError: No module named 'websockets'`. A stale image, not a
   code defect — the dependency is declared. Rebuilt; no code changed.
3. **The frontend 404'd on `/app`** under Docker because its `.next` cache
   volume was stale. Fixed by renewing the anonymous volumes; no code changed.

**What was found and is reported, not fixed**

4. **Server-side rendering is broken under full Docker Compose.** The
   workspace's server components fetch the API from inside the container, where
   `localhost:8000` is the container itself, so every workspace page renders
   "The API is not reachable". The demo therefore runs the frontend on the
   host. §9.
5. **The per-run bot adapter is ignored at execution** — a third defect not in
   any previous report. §6.
6. **`offline_simulation` is narrower than documented**, not broader: it does
   reach a terminal state, but only across repeated `/start` calls. §6.
7. **A scenario's declared SNR and packet loss are not applied** — only the
   profile name is. The demo's declared 10 dB / 8% is in fact 25 dB / no packet
   loss; the competition material quoted the declared figures and has been
   corrected. §6.4.

**The demonstration** is a Tamil crop-insurance claim that runs the whole
pipeline and terminates with the outcome `no_progress` — the instrument
reporting that the bot under test got nowhere. That negative result is the
product working, and the demo narration says so.

## 2. Git commits

| Hash | Subject |
|---|---|
| `983f4d9` | base — Phase 8.1, approved, unchanged by this work |
| `527bc3a` | `fix(pipeline): let an API-started fixture run obtain its bot audio` — the one approved behavioural change |
| `73ed0e0` | `feat(demo): add a reproducible Tamil crop-insurance demonstration` |
| the commit adding this file | `docs(competition): record the readiness assessment` |

See §15 for how to verify the pushed state. No hash in this report was written
before the commit it names existed.

## 3. Application startup — **Verified**

The stack that was verified end to end, and the one the demo script uses:
PostgreSQL in Docker, backend and frontend on the host.

```
$ curl http://localhost:8000/api/v1/health
status: ok | env: development
   api          -> ok    FastAPI application is serving requests.
   configuration-> ok    Settings loaded for environment 'development'
   database     -> ok    Connected; SELECT 1 succeeded.
```

| Surface | URL | State |
|---|---|---|
| Public site | <http://localhost:3000> | **Verified** — HTTP 200 |
| Workspace | <http://localhost:3000/app> | **Verified** — HTTP 200 |
| Run history | `/app/runs` | **Verified** — HTTP 200 |
| Conversation inspector | `/app/runs/[runId]` | **Verified** — HTTP 200 |
| New test | `/app/new-test` | **Verified** — HTTP 200 |
| Scenario library | `/app/scenarios` | **Verified** — HTTP 200 |
| Provider status | `/app/providers` | **Verified** — HTTP 200 |
| API | <http://localhost:8000> | **Verified** |
| API docs | <http://localhost:8000/docs> | **Verified** |

The Docker backend was also rebuilt and verified healthy independently
(`api`, `configuration`, `database` all `ok`). The Docker **frontend** is a
different matter — §9.

## 4. Demo scenario and the recorded run — **Verified**

### The scenario

`scenarios/demo/tamil_crop_insurance.yaml` — a smallholder paddy farmer near
Thanjavur calling a crop-insurance helpline about a claim filed after
unseasonal rain. Tamil, with English for the policy number, the scheme name
and the amount. Validated through `POST /api/v1/scenarios/validate` →
`valid: true, errors: []`.

**Audio — declared versus applied.** The file *declares* rural mobile
conditions: `noise_profile: rural`, `snr_db: 10`, `packet_loss_percent: 8`.
**The current engine does not apply the declared 10 dB SNR or 8% packet
loss.** It reads only the profile name and maps `rural` to the fixed
`light_background_noise` preset, so what a run *applies* is: 8 kHz mono,
300–3400 Hz phone-band filtering, background noise at **25 dB SNR**, and **no
packet loss**. Run `479ecd51`'s degraded artefacts record exactly that
(`transformations: [to_mono, resample, bandpass, add_noise]`, `snr_db: 25.0`).
Defect §6.4.

**The spoken opening.** The deterministic caller speaks `persona.identity` and
`goal.objective` verbatim in its opening, and both were originally English
authoring notes, so the Tamil opening read *"வணக்கம், நான் Smallholder paddy
farmer near Thanjavur. Find out whether the crop-loss claim has been
assessed…"* aloud (run `479ecd51`, preserved unchanged as recorded). Both
fields are now first-person colloquial Tamil, code-mixed only where the
scenario declares it (*Samba season, crop insurance, claim, assess, amount*).
`known_facts`, `expected_outcomes`, the rule order and determinism are
unchanged, and `backend/tests/test_demo_scenario.py` pins all four. This is a
scenario-data change; the caller engine was not modified.

**Why it is in `scenarios/demo/` rather than `scenarios/`:** the six files in
`scenarios/` are a survey with one scenario per language and
`test_languages_are_distinct` enforces that. A second Tamil file there would
have failed an existing test that encodes a deliberate design decision, and
weakening a test to fit a demo is the wrong trade. The reference glob is not
recursive, so `demo/` is invisible to it and to the bundle — no bundle
regeneration was needed, and the survey is untouched.

### The run

```
suite       : created 22921233-3340-4234-94bb-8738f69658b3
scenario    : created a5e78ceb-8a68-4b69-861a-98fd444fc290  (tamil_crop_insurance, ta-IN)
run         : 1751c189-0ba7-4282-a32c-3536aba54d94  (mode audio_fixture_test)

  status                         'completed'
  outcome                        'no_progress'
  mode                           'audio_fixture_test'
  bot_adapter                    'scripted'
  stt_provider                   'fake'
  tts_provider                   'fake'
  caller_turns                   5
  bot_turns                      4
  bot_transcripts_succeeded      4
  bot_transcripts_failed         0
  goal_achieved                  False
  bot_audio_externally_received  False
  uses_language_model            False
  noise_profile                  'light_background_noise'
  degradation_seed               42
  total_audio_seconds            8.0
  audio artefacts stored         12
```

Twelve artefacts: an `original` and a `degraded` variant per caller turn, each
degraded file recording the `derived_from` reference of the original it came
from. Nine conversation turns alternating caller and bot, the caller's
utterances in Tamil script.

**`bot_audio_externally_received: False` is the line that matters.** The run
moved real audio and still refuses to claim a bot was contacted, because the
scripted adapter reports `received_from_bot=False`. That field is computed from
the replies, not from the mode label.

### Steps that succeeded

| Step | Result |
|---|---|
| Scenario validates | `valid: true` |
| Suite and scenario load (idempotent) | **Verified** |
| Run created in `audio_fixture_test` | **Verified** |
| Run executes to a terminal status | **Verified** — `completed` |
| Caller speech synthesised, degraded, stored | **Verified** — 8.00 s measured, seed 42 |
| Bot replies transcribed | **Verified** — 4 of 4, 0 failures |
| Artefacts listed with provenance | **Verified** — 12, `derived_from` present on degraded |
| Artefact audio streams | **Verified** — `HTTP 200`, 8044 bytes, `audio/wav` |
| Waveform drawn from decoded bytes | **Verified** — 12 waveforms × 160 measured bars |
| Workspace renders the run | **Verified** — see the screenshots listed in §10 |

### Steps that did **not** succeed, and why

| Step | Result |
|---|---|
| `goal_achieved` | **False.** The fake transcription provider returns a canned Hindi string (`namaste, main aapki kya madad kar sakta hoon`) to a Tamil caller, so the caller legitimately makes no progress. Honest, and a good illustration — but it is not a success story and the demo does not present it as one. |
| Recognition accuracy | **Not measured, and not measurable here.** The committed audio fixtures contain no speech, so there is no reviewed ground truth. No accuracy, WER or quality figure is produced anywhere. |
| A real voice bot | **Not tested.** `sample_bot/` is empty and no external bot endpoint exists. |
| Live Gnani Prisma/Timbre in the demo | **Not exercised.** Providers are the offline fakes; no credit consumed. |
| Waveform showing a speech envelope | **Not achieved.** Real decoded audio, but visually flat — the fake synthesiser emits a constant-amplitude tone. Phase 8 limitation 3, now confirmed in the browser. |

## 5. The approved behavioural change — **Verified**

Approved before implementation, after the alternatives were put to the owner.

**Why a change was needed at all.** No execution mode could produce a complete
end-to-end audio demonstration through the API:

| Mode | Through the API | Honest for this demo? |
|---|---|---|
| `offline_simulation` | Reaches a terminal state only over repeated `/start` calls, and moves **no audio** — no artefacts, no transcripts, no waveforms | Honest but shows almost nothing |
| `audio_fixture_test` | **Failed on turn 0** — the defect | Would have been the honest mode |
| `external_bot_test` | Works, and sets `bot_audio_externally_received: true` | **Dishonest** — that field asserts the audio came from a real bot. There is no bot |

So the only honest mode was the broken one.

**Root cause.** `get_engine_factory` called `build_adapter(name)` with no
`replies`, producing `ScriptedBotAdapter([])`, which raises on turn 0. The
existing API tests never caught it because they override the engine factory and
inject their own adapter — the one seam that was broken is the seam those tests
replace.

**The fix.** An opt-in setting, `PIPELINE_FIXTURE_AUDIO_PATH`. The route reads
that file once and gives the scripted adapter one reply per turn, sized from
`CALLER_MAX_TURNS` so a run terminates on its budget before exhausting the
replies.

| Property | Why it is that way |
|---|---|
| **Unset means byte-identical to before** | A scripted run still has no replies and still fails on turn 0. That failure is honest with no fixture configured, so it was not softened |
| **A fixture can never read as a bot** | The scripted adapter reports `received_from_bot=False`; `bot_audio_externally_received` stays `false` |
| **Only `scripted` is offered replies** | `manual` refuses them, correctly — its audio arrives later |
| **No client value reaches the path** | No request field exists for it; it is an operator environment setting |
| **A bad path fails loudly** | Missing, empty or a directory → `PipelineConfigurationError` naming the path, instead of resurfacing as the turn-0 error |

**Regression risk: low.** Default behaviour is unchanged, and the full suite
passes. **Security risk: low.** The path is operator-controlled with no
request-side input, so there is no traversal surface; no endpoint, schema,
model or migration changed.

**Nine new tests** in `backend/tests/test_pipeline_fixture_audio.py` drive the
**real** `get_engine_factory` rather than the overridden one, pinning both the
new behaviour and the unchanged default. `test_a_configured_fixture_is_replayed`
would raise `BotAdapterError` without the fix, so it can genuinely fail.

**Files changed:** `backend/app/core/config.py` (one setting),
`backend/app/pipeline/bots/registry.py` (one helper),
`backend/app/api/v1/test_runs.py` (wiring in the composition root). No
pipeline, engine, caller, schema or migration logic was touched.

## 6. Defects found, reported and **not** fixed

### 6.1 The per-run bot adapter is ignored at execution — **Verified**, new

`get_engine` yields `factory(None)`, so `/start`, `/bot-audio` and `/cancel`
build the **settings-default** adapter and disregard the `bot_adapter` recorded
when the run was created. A run created with `bot_adapter: "manual"` still
fails with a *scripted* error:

```
mode: 'audio_fixture_test'   bot_adapter: 'manual'
error: "the bot adapter failed: the scripted bot has no reply for turn 0"
```

The API accepts and stores a field it then ignores, and the **new-test form
offers the choice**, so an operator can select `manual` in the UI and get
`scripted` behaviour. Not fixed: it is a second behavioural change beyond the
one approved, and the demo does not need it.

### 6.2 `offline_simulation` — **narrower** than documented — **Verified**

Previous reports said it "never reaches a terminal status". Measured: one
`/start` leaves it `running`, but repeated calls drove it to `completed` with
outcome `bot_unintelligible` after 4 caller turns. The caller gives up because
no bot ever speaks, which offline is correct about. Still a defect — a single
`/start` should not leave a run indefinitely un-terminal — but it is not the
permanent hang that was recorded. Unresolved.

### 6.3 `audio_fixture_test` — **now fixed**, see §5

Was: fails on turn 0 through the API. Now: completes when a fixture is
configured; unchanged when it is not.

### 6.4 A scenario's declared `snr_db` and `packet_loss_percent` are not applied — **Verified**

The pipeline maps a scenario's `audio.noise_profile` name to a fixed preset
(`_SCENARIO_PROFILES` in `backend/app/pipeline/engine.py`) and ignores the
scenario's own `snr_db` and `packet_loss_percent`. `docs/PIPELINE.md` already
states that no profile applies packet loss; what was wrong was the
competition material, which quoted the declared numbers as if they were
applied.

| Scenario | Declared | Applied by the current engine |
|---|---|---|
| `tamil_crop_insurance` (demo) | `rural`, 10 dB SNR, 8% packet loss | `light_background_noise`: phone band, **25 dB SNR**, **no packet loss** |
| `telugu_order_tracking` | `worst_case`, 6 dB SNR, 18% packet loss | `heavy_background_noise`: phone band, **7 dB SNR** (not 6), **no packet loss** |

Every degraded artefact records the parameters actually used, and the run
inspector shows *Noise applied* beside *Scenario declared*, so the product
itself never overclaimed. The demo script, this report, the pitch, the
LinkedIn post and `scenarios/README.md` have been corrected to quote the
applied condition. Not fixed: honouring the declared values is a behavioural
change to degradation and was not approved.

## 7. Quality gates — **Verified**

Every figure below is command output from after the final edit.

| Gate | Command | Result |
|---|---|---|
| Collection | `pytest --collect-only -q` | **1,999 collected** (34 modules) |
| Full suite | `pytest -q` | **1,958 passed, 41 skipped, 0 failed** (168.97 s) |
| Deselected | — | **0** — the live tests are collected and skipped |
| New tests | `pytest backend/tests/test_pipeline_fixture_audio.py` | **9 passed** |
| Lint | `ruff check .` | **All checks passed!** |
| Format | `ruff format --check .` | **142 files already formatted** |
| Migrations | `alembic check` | **No new upgrade operations detected.** |
| API surface | `python scripts/api_surface.py` | **35 paths, 43 operations** (unchanged) |
| Frontend types | `npx tsc --noEmit` | **Clean**, exit 0 |
| Frontend lint | `npx eslint .` | **Clean**, exit 0 |
| Whitespace | `git diff --check` | Clean |

The README per-module table sums to **1,999**, matching collection exactly.
Ruff's scope remains the tracked Python source (142 files once the two new
files are committed), the Phase 8.1 invariant.

> **A verification caveat worth recording.** An intermediate run reported "9
> failed, 256 errors". That was self-inflicted: two `pytest` sessions were
> running concurrently and the database tests create and drop their own
> database. Re-run alone, the suite is green. **Do not run two suites at once.**

## 8. Security and deployment decision

### Classification: **C — not safe to deploy publicly without additional security work**

Running it locally or on a private network for the recording is fine, and that
is the recommendation. Publishing it to the internet is not.

Evidence, all from the repository:

| Concern | Finding |
|---|---|
| Authentication | **None anywhere.** No `HTTPBearer`, `APIKeyHeader`, `OAuth2` or auth dependency in `backend/app`. Authentication is Phase 15 |
| Authorization | None. The code states it: "a run id is an identifier, not a credential" |
| Destructive endpoints | **Unauthenticated `DELETE`** on `/api/v1/suites/{id}` (with `?cascade=true`, taking its scenarios) and `/api/v1/scenarios/{id}`, plus unauthenticated `PUT`/`PATCH`. Anyone reaching the host can destroy the library |
| Recorded audio | `GET /test-runs/{id}/artifacts/{turn}/audio` streams stored conversation audio. Gated by `PIPELINE_SERVE_ARTEFACTS` in staging and production, but **development always serves it** |
| Transcript exposure | Run and conversation turns, including transcripts, are readable by id with no credential |
| Provider spend | With live Gnani credentials configured, unauthenticated `POST /speech/generate` and `POST /transcription` spend the owner's credits. Anyone could bill the owner |
| Inbound rate limiting | **None.** The `RateLimitError` handling maps *upstream provider* 429s; it does not limit inbound requests |
| Resource exhaustion | Partially bounded: concurrency limited to 2 with a 503 beyond, and upload size caps exist. Not a substitute for auth |
| Database exposure | Compose maps PostgreSQL to a host port. On a public host that exposes the database |
| CORS | Defaults to `http://localhost:3000` — appropriately narrow |
| Secret handling | Good. `.env` is git-ignored and untouched; provider errors pass through `redact`; no secret appears in an API response |

**Decision: do not deploy.** Submit the GitHub repository plus a locally
recorded video. No rushed authentication was added to make a public URL
possible — that would be a Phase 15 feature built in an afternoon to win a
checkbox, and it would be the least trustworthy code in the repository.

## 9. Docker Compose limitations — **Verified**, reported not fixed

| Issue | Cause | Status |
|---|---|---|
| Backend container crash-looped | Stale image predating the Phase 4 `websockets` dependency | **Fixed** by rebuild; no code change |
| Frontend 404 on `/app` | Stale `.next` anonymous volume | **Fixed** by `--renew-anon-volumes`; no code change |
| Workspace shows "The API is not reachable" under full Compose | The frontend's **server components** fetch `NEXT_PUBLIC_API_BASE_URL` from inside the container, where `localhost:8000` is the container. `lib/api/client.ts` has one base URL, commented "from the browser's point of view", with no server-side override | **Not fixed** — needs a frontend change (a server-side base URL used when `typeof window === "undefined"`), which was outside the approved scope |
| Artefact audio 404 across stacks | Audio written by one backend is not in the other's storage | Avoided by using one consistent stack |

The error state itself is **correct behaviour**: the workspace says the API is
unreachable instead of inventing data, exactly as Phase 8 designed. The
configuration is wrong, not the code.

**Consequence for the demo:** run PostgreSQL in Docker and the backend and
frontend on the host. Documented in README and the demo script.

## 10. Browser QA — **Verified**

Driven in a real browser against the running application at 1440×900 and
390×844.

| Check | Result |
|---|---|
| All seven routes | HTTP 200 |
| Horizontal overflow, desktop | **None** (scrollWidth 1425/1440 landing, 1440/1440 workspace) |
| Horizontal overflow, mobile 390 px | **None** (380/390). The only elements wider than their box are `sr-only`, i.e. visually hidden |
| Console errors | **None** on the landing page, workspace, scenarios, providers or new-test |
| Audio real, not placeholder | **Verified** — `HTTP 200`, 8044 bytes, `audio/wav`; 12 waveforms of 160 bars each, drawn from decoded bytes, with no synthetic fallback |
| Honesty panels render | **Verified** — "No external bot was contacted", "The caller is a rule engine, not a language model", "Measurements, not scores" |
| Only implemented modes offered | **Verified** — three mode radios; no `telephony_test` option |
| Evon and telephony status shown | **Verified** on the providers page |
| Error state accuracy | **Verified** — with the API down the workspace says so and shows no figures |

Two console errors were observed and **both were my own configuration**, not
product defects: a CORS error when I served the frontend on port 3001 (CORS
allows 3000), and an artefact 404 when the frontend talked to a backend that
did not hold the audio. Neither occurs in the documented demo stack.

No release-blocking visual or interaction defect was found, so no frontend code
was changed.

### Screenshots — **Verified**, from the running application

`docs/competition/screenshots/` — 9 files, no mockups:

`01-landing-desktop-1440` · `02-workspace-overview-1440` ·
`03-run-inspector-1440` · `04-scenario-library-1440` ·
`05-provider-status-1440` · `06-new-test-1440` · `07-landing-mobile-390` ·
`08-run-inspector-mobile-390` · `09-run-history-1440`

## 11. Documents produced

| Document | Location |
|---|---|
| One-page pitch | `docs/COMPETITION_ONE_PAGE_PITCH.md` |
| Demo video script (2:30, timestamped) | `docs/COMPETITION_DEMO_SCRIPT.md` |
| LinkedIn post draft | `docs/COMPETITION_LINKEDIN_POST.md` |
| Submission checklist | `docs/COMPETITION_SUBMISSION_CHECKLIST.md` |
| This report | `docs/COMPETITION_READINESS_REPORT.md` |
| Demo runner | `scripts/demo.py` |
| Demo scenario | `scenarios/demo/tamil_crop_insurance.yaml` |

README gained a **Run the demo** section with prerequisites, exact commands,
URLs, health checks, shutdown, the known rough edges and a video-link
placeholder. `.env.example`, `docs/PIPELINE.md` and `scenarios/README.md`
document the new setting and the demo directory. `.playwright-mcp/` was added
to `.gitignore` so browser scratch output is never committed.

## 12. Remaining defects and limitations

**Open defects**

1. The per-run `bot_adapter` is ignored at execution (§6.1) — new, unresolved.
2. `offline_simulation` does not terminate on a single `/start` (§6.2) —
   unresolved.
3. Server-side rendering is broken under full Docker Compose (§9) —
   unresolved; the demo avoids it.
4. A scenario's declared `snr_db` and `packet_loss_percent` are not applied;
   only the profile name is (§6.4) — unresolved, by decision.

**Capability limits, by design and documented**

- No telephony. `telephony_test` exists in the vocabulary and is refused.
- No automated evaluation, accuracy figure or word error rate.
- No authentication anywhere.
- Gnani **Evon** is not integrated; the caller is a deterministic rule engine.
- No real voice bot has been tested; no phone call has been placed.
- No frontend test suite; no run auto-refresh; no scenario-detail or
  suite-management UI.
- Audio fixtures contain no speech, so no recognition accuracy is measurable.

**Not verified in this work**

- Live Gnani calls — deliberately not made; no credit consumed.
- `next build` was not re-run after the final edits (no frontend file changed).
- The untracked `.agents/` and `.claude/` directories were not audited.
- No security review beyond the deployment assessment in §8.

## 13. What I did not do

- Did not deploy anything publicly.
- Did not spend Gnani credits or make a live provider call.
- Did not modify `.env`, or print a credential into any committed file.
- Did not weaken or delete a test. `test_languages_are_distinct` constrained
  where the demo scenario could live, and the scenario moved rather than the
  test.
- Did not fix the two defects in §6.1 and §6.2, or change frontend code.
- Did not submit the challenge form, publish the LinkedIn post, or record the
  video. Those are yours, and §14 lists them.
- Did not regenerate the scenario bundle — correctly, since `demo/` is outside
  the reference glob.

## 14. What you must do before submitting

1. **Record the video** from `docs/COMPETITION_DEMO_SCRIPT.md`. Start the stack
   exactly as §1 of that script says, and run `python scripts/demo.py run`
   before recording so a completed run already exists. Keep it to 2:30.
2. **Upload it**, then put the URL in `README.md` (replacing the pending
   placeholder) and in the LinkedIn draft. Commit and push that one change.
3. **Confirm the repository is public** — open the GitHub URL in a private
   window.
4. **Provide your registered email** (and a teammate's, if applicable). I left
   both blank deliberately rather than invent an address.
5. **Review and publish the LinkedIn post.** Tag Gnani AI's official page using
   LinkedIn's own `@` suggestions — I did not write a handle, because an
   unverified mention tags a stranger.
6. **Submit the form** before 10 November 2026, 23:59 IST.

## 15. Push and synchronisation evidence

Recorded after the push, so it is evidence rather than intention.

The approved fixture fix landed as **`527bc3a`** and the demonstration as
**`73ed0e0`**.

This report is the commit after it, and **a report cannot name its own SHA** —
the same convention the earlier phase reports follow. Verify the final state
yourself with two commands:

```bash
git log --oneline -3
git rev-parse HEAD origin/main     # the two must match
git status --porcelain             # only .agents/, .claude/, skills-lock.json
```

The push record for the first commit, and the synchronisation check after both,
are reported in the session transcript alongside this file.
