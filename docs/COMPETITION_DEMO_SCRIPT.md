# Demo recording script — 2 minutes 30 seconds

For the Great Indian AI Internship Challenge submission. Every claim in the
narration below is one the application can actually show on screen.

> **Read §1 and §2 before recording.** The stack has to be started in a
> specific way, and one visual (the waveform) needs an honest sentence attached
> to it or the demo overclaims.

---

## 1. The stack to record against

**Use the all-local stack.** It is the configuration that was verified
end to end:

| Piece | How | URL |
|---|---|---|
| PostgreSQL | `docker compose up -d db` | localhost:5434 |
| Backend | local `uvicorn`, with the fixture audio set | <http://localhost:8000> |
| Frontend | local `next dev` | <http://localhost:3000> |

```bash
# 1. database only
docker compose up -d db

# 2. backend - the fixture path is what makes a fixture run complete
#    (PowerShell: $env:PIPELINE_FIXTURE_AUDIO_PATH="backend/tests/fixtures/audio/tone_8k_mono.wav")
PIPELINE_FIXTURE_AUDIO_PATH=backend/tests/fixtures/audio/tone_8k_mono.wav \
  python -m uvicorn app.main:app --app-dir backend --port 8000

# 3. frontend, in a second terminal - bound to loopback so other devices on
#    the network cannot reach the demo
cd frontend && npm run dev -- --hostname 127.0.0.1 --port 3000

# 4. load the demo scenario and execute one run
python scripts/demo.py run
```

**Do not record against `docker compose up` for the whole stack.** Two
verified reasons: the frontend's server components fetch from inside the
container, where `localhost:8000` is the container itself, so the workspace
renders "The API is not reachable"; and artefact audio written by one backend
is not visible to the other. Both are recorded as defects in
`docs/COMPETITION_READINESS_REPORT.md`.

**Bind the frontend to `127.0.0.1`.** A bare `npm run dev` listens on every
interface, so the demo is reachable from other devices on the same network.
The `--hostname 127.0.0.1` flag keeps it on this machine; `package.json` and the
Docker image are deliberately unchanged, because the container must listen on
`0.0.0.0` for its port mapping to work.

**Keep the frontend on port 3000.** `CORS_ORIGINS` allows `http://localhost:3000`
only, and audio playback is a browser fetch — on any other port it fails with a
CORS error.

Run `python scripts/demo.py run` **before** recording so a completed run
already exists. Note the run id it prints; the script also prints the exact
workspace URL to open.

## 2. The things not to overclaim

**The waveform is real but flat.** It is drawn from decoded audio bytes — 160
bars per artefact, measured, with no synthetic fallback. It looks flat because
the configured text-to-speech is the offline fake, which emits a
constant-amplitude tone. Say so. The line is in the 1:20 segment below.

**Narrate the noise the inspector shows for the run on screen.** The scenario
declares `rural` with 10 dB SNR and 8% packet loss, and which of two
conditions a run applied depends on when it was created:

- **Runs created since Phase 0** apply the declaration: the 300–3400 Hz
  phone band, background noise at **10 dB SNR** and **8% packet loss**. The
  inspector's *Noise applied* reads `10 dB SNR · 8% packet loss`.
- **Runs created before Phase 0** — including the recorded runs `479ecd51`
  and `c6fa33c3` — applied the `light_background_noise` preset: **25 dB SNR,
  no packet loss**. Their inspector reads *Light background noise*.

Every degraded artefact records the requested and the measured values, so
the figure you say must be the one that run's inspector shows. A fresh
`python scripts/demo.py run` creates a post-Phase-0 run.

Likewise the bot transcript on screen reads `namaste, main aapki kya madad kar
sakta hoon` — scripted stub output from the fake transcription provider, not
recognition of the audio. The script says this out loud at 1:45.

---

## 3. The script

### 0:00–0:20 — Problem and introduction (20 s)

**Screen:** <http://localhost:3000> — the public site, top of page.

**Narration:**

> "A voice bot that works perfectly in a quiet demo often fails on a real
> Indian phone call. The caller speaks Tamil but says the policy number in
> English. There's a market in the background and the mobile network is
> dropping packets. Teams find these failures the way their customers do — in
> production. BhashaBench is an instrument for finding them first."

**Evidence on screen:** the headline and the problem section.

**If it fails:** if the page does not load, the frontend is not up. `cd
frontend && npm run dev -- --hostname 127.0.0.1 --port 3000`, wait for
"Ready", reload.

---

### 0:20–0:45 — Overview of the platform (25 s)

**Screen:** scroll the public site to the pipeline diagram, then click
**"Open the workspace"** (or go to <http://localhost:3000/app>).

**Narration:**

> "It works by turning a conversation into a reproducible test. A scenario
> declares who is calling, in what language, what they want, and what the line
> sounds like. The platform speaks, degrades the audio the way a network does,
> transcribes the reply and decides what to say next — and stores every turn.
> This is the operator workspace, reading the live API."

**Evidence on screen:** the overview's **System health** panel showing `api`,
`configuration` and `database` all *Healthy*, and **Recent runs** with a real
count. Point at the line "Nothing on this page is an estimate."

**If it fails:** if the overview shows "The API is not reachable", the backend
is not running on port 8000, or you are recording against the Docker frontend.
See §1.

---

### 0:45–1:20 — Scenario and configuration (35 s)

**Screen:** **Scenarios** in the left rail → point out the language column →
then **New test**.

**Narration:**

> "Thirteen Indian languages, each with its own script and endonym. This is the
> demo scenario: a paddy farmer near Thanjavur calling a crop-insurance
> helpline about a claim after unseasonal rain. He speaks Tamil, but the policy
> number and the amount come out in English — which is exactly where
> recognition breaks. Each caller turn is degraded the way a phone line
> degrades it: cut to the 300 to 3400 hertz phone band, with background noise
> at ten decibels signal-to-noise and eight per cent of packets dropped.
> *(Recording against a pre-Phase-0 run instead? Say "twenty-five decibels"
> and drop the packet-loss clause — see §2.)* On the New test page those
> conditions are selectable, and so is the execution mode. Note what is *not* offered —
> telephony, because no telephony exists yet."

**Clicks:** Scenarios → scroll to `tamil_crop_insurance` (ta-IN, தமிழ்) → New
test → open the scenario dropdown → show the noise profile dropdown → show the
three mode radios.

**Evidence on screen:** the scenario list with native scripts; the three
implemented modes (**Fixture test**, **External bot**, **Offline simulation**)
and no telephony option.

**If it fails:** if the scenario is missing, run `python scripts/demo.py setup`.

---

### 1:20–2:05 — The actual demonstration (45 s)

**Screen:** the completed run's inspector — the URL `scripts/demo.py run`
printed, e.g. `http://localhost:3000/app/runs/<run-id>`.

**Narration:**

> "Here is a run that executed. Five caller turns, four bot turns, four replies
> transcribed, eight seconds of audio measured, twelve audio artefacts stored —
> the original and the degraded version of every turn, and each degraded file
> records which original it came from, so the evidence is reproducible from a
> fixed seed.
>
> The conversation is in Tamil script, turn by turn. Every turn keeps its audio,
> and I can play either version.
>
> Two honest notes. This waveform is drawn from the decoded bytes, not a
> picture — but it is flat because the text-to-speech here is the offline test
> double, which emits a constant tone rather than speech. And the outcome is
> 'no progress': the instrument is telling me the bot under test got nowhere.
> That negative result is the product working."

**Clicks:** scroll through **Configuration** → **What was counted** → the
conversation turns → press play on one artefact → scroll to the stage timeline.

**Evidence on screen:**
- `Completed` and `No progress` badges
- the caveat panels: **"No external bot was contacted"**, **"The caller is a
  rule engine, not a language model"**, **"Measurements, not scores"**
- Configuration showing `fake` / `fake` / `scripted`, seed 42, and
  *Noise applied* (`10 dB SNR · 8% packet loss` on a post-Phase-0 run) beside
  *Scenario declared: Rural*
- Counted: caller turns 5, bot turns 4, transcribed 4, audio 8.00 s
- Tamil-script caller utterances

**If it fails:** if the run shows `failed` with "the scripted bot has no reply
for turn 0", `PIPELINE_FIXTURE_AUDIO_PATH` was not set when the backend
started. Restart the backend per §1 and run `python scripts/demo.py run` again.
If audio playback shows "could not be reached", the frontend is not on port
3000 — see §1.

---

### 2:05–2:20 — Architecture (15 s)

**Screen:** **Providers** page.

**Narration:**

> "Underneath: Gnani Timbre for speech, Gnani Prisma for recognition, both
> behind a provider-independent interface so a second engine can be benchmarked
> without touching the evaluation code. A deterministic rule engine drives the
> caller. And the platform states its own limits — Evon is not integrated,
> because no text-generation endpoint is published; telephony is not built. It
> says so on this page rather than in a footnote."

**Evidence on screen:** the Prisma and Timbre capability tables, including
their documented gaps; the `evon_status` and `telephony_status` text.

---

### 2:20–2:30 — Closing (10 s)

**Screen:** back to the run inspector, or the public site.

**Narration:**

> "Two thousand and six automated tests, and every number on screen
> was measured rather than estimated. BhashaBench makes Indian-language voice
> quality something you can test on purpose instead of discovering in
> production."

---

## 4. Recording checklist

- [ ] `docker compose up -d db` — database up
- [ ] Backend started **with** `PIPELINE_FIXTURE_AUDIO_PATH`
- [ ] Frontend on **port 3000**, bound to `127.0.0.1`
- [ ] `python scripts/demo.py run` completed; run id noted
- [ ] Browser at 1440×900 or wider, zoom 100%
- [ ] Close unrelated tabs; hide bookmarks and any personal information
- [ ] Nothing showing a credential — never open `.env` on camera
- [ ] Audio output on, so the playback is audible
- [ ] Total length ≤ 2:30

## 5. What the narration must never say

Do not claim, in any take:

- that a real voice bot was tested, or that a phone call was placed
- that Evon is integrated or that the caller uses a language model
- any accuracy, word error rate, or quality score
- that the noise is a field recording
- any noise figure the inspector does not show for that run: a post-Phase-0
  run applies 10 dB / 8% packet loss, a pre-Phase-0 run 25 dB / none (§2)
- that the transcript demonstrates recognition quality — with the fake
  provider it is scripted stub output
