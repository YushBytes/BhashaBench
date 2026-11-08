# Speech providers

How BhashaBench talks to a speech engine - **recognition** (Gnani Prisma,
Phase 4) and **synthesis** (Gnani Timbre, Phase 5) - what each actually
supports, and how to run them with or without credentials.

Two further provider families follow the same pattern and speak to no vendor at
all: the **caller** (Phase 6), whose design is in [CALLER.md](CALLER.md), and
the **bot adapters** (Phase 7), in [PIPELINE.md](PIPELINE.md). Both have
verification sections below.

---

## Verification status — read this first

The repository's first rule is never to claim something works when it does
not. For a provider integration that means separating claims that are
routinely conflated — in particular, what a *mocked* test proves from what a
*real* API call proves.

**Last live verification: 2026-11-07**, against `https://api.vachana.ai`
with a real API key. Four Gnani API calls in total across both phases: three
for Prisma recognition, one for Timbre synthesis.

| Capability | Status | How it was established |
|------------|--------|------------------------|
| Prisma adapter implementation | ✅ **Verified** | `app/transcription/providers/prisma.py`; 81 mocked adapter tests |
| Official API contract | ✅ **Verified** | [docs.gnani.ai](https://docs.gnani.ai), transcribed into `prisma_contract.py` and asserted by tests |
| Real API authentication | ✅ **Verified** | **Live call.** A real key accepted by the live service; no 401/402/403 |
| Real batch transcription request | ✅ **Verified** | **Live call.** `POST /stt/v3` accepted, non-error response |
| Real transcription response parsing | ✅ **Verified** | **Live call.** The live response normalised into a `TranscriptionResult` carrying a provider `request_id` |
| Real streaming transcription | ❌ **Not verified** | No live WebSocket session has been opened |
| Streaming provider behaviour | ❌ **Not verified** | Framing, event sequence and the absence of partial results are asserted against the *documentation* only |
| Recognition accuracy / language quality | ⚠️ **Not independently benchmarked** | See below — no test makes any accuracy claim |

### Text to speech — Gnani Timbre (Phase 5)

| Capability | Status | How it was established |
|------------|--------|------------------------|
| Timbre adapter implementation | ✅ **Verified** | `app/speech/providers/timbre.py`; 132 mocked adapter tests |
| Official API contract | ✅ **Verified** | [docs.gnani.ai](https://docs.gnani.ai/api/TTS/tts-inference), transcribed into `timbre_contract.py` and asserted by tests |
| Real API authentication | ✅ **Verified** | **Live call.** HTTP 200 from `api.vachana.ai`; no 401/402/403 |
| TTS scope on the shared key | ✅ **Verified** | **Live call.** The same `GNANI_API_KEY` that works for Prisma was accepted by Timbre — a 403 would have proved the opposite |
| Real synthesis request | ✅ **Verified** | **Live call.** `POST /api/v1/tts/inference` accepted; a 70,444-byte WAV carrying 70,400 bytes of PCM |
| Real audio decodability | ✅ **Verified** | **Live call.** 8 kHz, mono, 16-bit PCM, 4.400 s, parsed by the stdlib `wave` reader |
| Requested sample rate honoured | ✅ **Verified** | **Live call.** 8 kHz requested, 8 kHz returned |
| Adapter end-to-end after the WAV header fix | ✅ **Verified live** | **Live call.** The full path - request, binary response, sentinel header, measurement - returns a valid `SpeechResult`. Confirmed after the fix |
| Pronunciation / prosody / intelligibility | ⚠️ **Not evaluated** | Nobody has listened to the audio. No automated test can judge this |
| Streaming synthesis (SSE / WebSocket) | ⬜ **Not implemented** | Documented by the vendor; nothing consumes a stream before Phase 9 |

### Caller — deterministic engine (Phase 6)

**Phase 6 uses deterministic, rule-based caller orchestration. Official Gnani
Evon integration is deferred until documented access and credentials are
available.**

**Evon integration is NOT implemented or verified in this phase.**

No live call was made for Phase 6, because there is nothing to call: the caller
provider is a rule engine that runs entirely in process.

| Capability | Status | How it was established |
|------------|--------|------------------------|
| Deterministic caller implementation | ✅ **Verified** | `app/caller/providers/deterministic.py`; 342 offline tests |
| Responds differently to different bot transcripts | ✅ **Verified offline** | Five bot replies, five different rules, utterances and intents - `test_caller_rules.py` |
| Multi-turn conversation, end to end | ✅ **Verified offline** | Scripted bot, real rules, real state machine, real PostgreSQL - `test_caller_orchestrator.py` |
| Reproducibility | ✅ **Verified offline** | The same script twice produces an identical transcript |
| Legal state transitions from every state | ✅ **Verified offline** | Every non-terminal state swept against twelve shapes of reply |
| Decision validation and secret redaction | ✅ **Verified offline** | `test_caller_service.py`, including an injected credential in provider error text |
| Persistence on the Phase 2 schema | ✅ **Verified offline** | Real PostgreSQL; no migration, and `alembic check` reports no drift |
| HTTP surface and status mapping | ✅ **Verified offline** | `test_caller_api.py` through `TestClient` |
| Gnani Evon API access | ❌ **Not available** | No text-generation endpoint is published; the released model has no hosted inference provider |
| Gnani Evon adapter | ⬜ **Not implemented** | Deliberately absent. `evon` is not a registered provider and is refused by name |
| Conversation quality / naturalness | ⚠️ **Not evaluated** | A rule engine composing from fixed phrase tables. No test claims otherwise |
| Behaviour against a real voice bot | ❌ **Not verified** | Nothing in this repository has had a conversation with a voice bot |

**Code-mixing is not generated.** A scenario may declare it; the caller will
not produce it. Reviewed phrase tables exist for `ta-IN`, `hi-IN` and `en-IN`
only, and a scenario in any other catalogue language is refused rather than
answered in English.

### Bot adapters — the pipeline's view of a voice bot (Phase 7)

No live call was made for Phase 7, and no real voice bot was contacted. There
was nothing to contact: **neither shipping adapter opens a socket.**

| Capability | Status | How it was established |
|------------|--------|------------------------|
| Multi-turn audio workflow, offline | ✅ **Verified offline** | 238 tests; synthesis, degradation, storage, validation and transcription all run for real with the providers faked |
| Degradation reproducibility | ✅ **Verified offline** | Byte-identical output per profile for a fixed seed |
| Signal-to-noise accuracy | ✅ **Verified offline** | Measured by isolating the noise; within 0.5 dB across seven targets |
| Original artefact preservation | ✅ **Verified offline** | Both variants stored; the processed file names its source |
| Path-traversal resistance | ✅ **Verified offline** | An uploaded filename reaches no path |
| Timbre and Prisma through the existing services | ✅ **Verified offline** | With the offline fakes, through the Phase 4/5 service layer - no second client |
| A live Gnani call inside a pipeline run | ❌ **Not tested** | None was authorised, and an offline run needs none |
| A real voice bot conversation | ❌ **Not tested** | No external bot endpoint was available |
| Telephony | ⬜ **Not implemented** | `telephony_test` is refused |
| Recognition accuracy under degradation | ⚠️ **Not measured** | The fixtures contain no speech with reviewed ground truth |

**There is no adapter for any third-party bot API.** A real integration is an
adapter written against that bot's published interface and registered in
`app/pipeline/bots/registry.py` - the same rule as the speech providers, for
the same reason. The default adapter is the one that sends audio nowhere,
because §7 requires the default configuration to be safe.

**Simulated noise is not a recording.** `heavy_background_noise` is shaped
white noise at 7 dB SNR over a 300-3400 Hz channel. This repository contains no
field recordings, and the profiles are named for severity because severity is
what they control.

### What "verified" does and does not mean here

**Mocked vs. real.** The 223 offline transcription tests use
`httpx2.MockTransport` and a stubbed WebSocket. They prove the adapter sends
what the documentation describes and normalises every documented response —
they cannot prove Gnani agrees, because a mock cannot disagree with the fixture
that produced it. Only the rows marked **Live call** above involved the real
service.

**Accuracy is not verified, and cannot be by the current fixtures.** The
committed audio fixtures are synthesised 440 Hz tones, digital silence and
deliberately malformed files. They contain **no speech**, so they have **no
reviewed ground truth**, and no test asserts that any particular words come
back. Nothing in this repository measures word error rate, per-language
quality, or code-mixing handling. Treat the live result as "the pipe works",
not "the model is good" — benchmarking recognition quality is Phase 11's job
and needs licensed, transcribed speech.

**Still open on the recognition streaming path.** The WebSocket adapter has
never spoken to Gnani. Its framing (1024 bytes), event mapping and the
documented absence of interim results are all taken from the vendor's published
example. Running `-k test_a_stream_completes_with_a_terminal_event` from the
live suite is the next verification step.

**Audio quality is not evaluated, and no test can evaluate it.** The one live
Timbre call produced 4.4 seconds of decodable 8 kHz PCM for a Tamil sentence.
That establishes that the pipe works and the audio is well-formed. It
establishes **nothing** about pronunciation, prosody, stress, intelligibility
or accent — those need a person listening, and nobody has. Do not read
"synthesis verified" as "the Tamil sounds right".

**What the live calls cost, and what they bought.** Two calls to Timbre.

The first found a bug that 379 offline tests could not: Timbre writes a
*streaming* WAV header with `0xFFFFFFFF` in the RIFF and `data` size fields, the
ordinary convention for a writer that does not know the final length. Our WAV
inspector - added in Phase 4 to catch truncated uploads - read that as a file
declaring 2.1 billion frames and holding 35,200, and rejected every synthesised
utterance as truncated. No fixture could have caught it: the stdlib `wave`
writer always back-fills the true length, so an offline fixture never carries
that header.

The second, after the fix, confirmed the whole path. The saved artefact was then
inspected three independent ways - by hand with `struct`, by the stdlib `wave`
reader, and by our own inspector - all agreeing on 8 kHz, mono, 16-bit, 4.400 s.
It also carries real signal rather than silence: peak amplitude 25,917 of
32,767, 98.3% of samples non-zero, which rules out the failure mode where a
provider returns a correctly-formed empty file.

The sentinel rule was then checked in both directions against that same real
artefact: with the sentinel in place it is accepted and measured; with the
sentinel replaced by an honest size and the tail cut off, it is still rejected
as truncated. The allowance did not reopen the hole beside it.

---

## Architecture

```
app/api/v1/transcription.py          HTTP + WebSocket transport
        │
        ▼
app/services/transcription_service.py   business rules, provider-agnostic
        │
        ▼
app/transcription/registry.py        which provider, built from settings
        │
        ▼
app/transcription/base.py            the TranscriptionProvider interface
        │
        ├── providers/prisma.py      Gnani Prisma  (+ prisma_contract.py)
        └── providers/fake.py        offline test double
```

Synthesis mirrors it:

```
app/api/v1/speech.py                 HTTP transport
        |
app/speech/service.py                business rules, provider-agnostic
        |
app/speech/registry.py               which provider, built from settings
        |
app/speech/base.py                   the SynthesisProvider interface
        |
        +-- providers/timbre.py      Gnani Timbre  (+ timbre_contract.py)
        +-- providers/fake.py        offline test double
```

Shared by every layer: `models.py` (domain objects), `errors.py` (structured
failures), `audio.py` (inspection and validation), `retry.py`,
`redaction.py`.

**Three modules are shared between the two subsystems rather than copied.**
`transcription/redaction.py`, `transcription/retry.py` and
`transcription/audio.py` are provider-agnostic, and the speech subsystem
imports them - `retry` gained a `retryable_base` parameter so it can serve
either error family, and `audio`'s WAV inspector verifies *returned* audio as
well as uploaded audio. They live under `transcription/` for historical
reasons; when a third provider family arrives they should be promoted to a
shared package rather than copied a third time. The registries and error
hierarchies are deliberately **not** shared: a generic registry would have to
be parameterised over the protocol, the error type and the settings fields, and
a flattened error hierarchy would mean every handler checking which half of it
it was looking at.

**The rule that makes this worth doing:** nothing above `providers/` may
import a vendor module or reference a vendor field name. The service layer has
never heard of `audio_file` or `detected_language_code`. That is what lets
Phase 11 benchmark a second engine without touching the evaluation code.

### Adding a provider

1. Write an adapter implementing `TranscriptionProvider` (two methods plus
   `capabilities` and `close`).
2. Declare what it can do in a `ProviderCapabilities`.
3. Add one entry to `_FACTORIES` in `registry.py`.

Nothing in `app/services/` or `app/api/` changes. There is deliberately no
plugin discovery mechanism: "which engine produced this score?" must always be
answerable by reading the source.

### Client lifecycle

`get_service_factory` builds a **new** service, provider and
`httpx2.AsyncClient` per request. `get_transcription_service` is therefore a
dependency with `yield` that closes the service in a `finally`, so the client
is released whether the handler returned or raised. Without that, every
transcription left a connection pool to the garbage collector.

The WebSocket route does not use that dependency: it needs the service to
outlive dependency resolution for the life of the socket, and it must catch a
`ConfigurationError` *after* `accept()` so the error can be reported as a
frame. It closes its own service in its own `finally`.

Ownership is explicit. A provider closes only a client it created itself; a
client passed in through the `client=` parameter belongs to whoever passed it
(tests and the live fixture both do this) and is left open. Three tests pin
that contract down, including one asserting the registry-built provider — the
production path — does own its client.

**Known trade-off.** Because the provider is per-request, its connection pool
is never reused between requests, so each transcription pays a fresh TLS
handshake — and that lands inside the `latency_ms` this API reports. Closing is
still strictly better than leaking. The improvement is one provider per
process closed in the application lifespan; that is a deliberate change to the
dependency graph and has not been made.

### Not persisted

Phase 4 writes nothing to the database. The `TestRun`, `CallSession` and
`ConversationTurn` tables remain foundational schema. Deciding which
conversation turn a transcript belongs to is orchestration — Phase 9 — and a
table written by nothing would be schema guesswork.

A practical consequence: **the transcription endpoints work with PostgreSQL
down.** A test asserts this rather than assuming it.

---

## The verified Gnani Prisma contract

Transcribed from <https://docs.gnani.ai>. Pages consulted:
`api/introduction/introduction`, `api/introduction/quick-start`, and
`api/use-cases/real-time-compliance` (which carries the worked WebSocket
example). The constants live in
`app/transcription/providers/prisma_contract.py` and are asserted by tests.

### Transport and authentication

| | |
|---|---|
| REST base URL | `https://api.vachana.ai` |
| WebSocket base URL | `wss://api.vachana.ai` |
| Auth header | `X-API-Key-ID: <key>` |
| Auth scheme | **None** — the bare key, *not* `Bearer <key>` |

### Batch — `POST /stt/v3`

`multipart/form-data` with these fields:

| Field | Value |
|-------|-------|
| `audio_file` | the binary audio |
| `model` | `prisma-v3.0` or `prisma-v2.5` |
| `language_code` | e.g. `hi-IN` |
| `format` | optional; `transcribe` |

The documented response:

```json
{
  "success": true,
  "request_id": "<uuid>",
  "transcript": "<text>",
  "model": "prisma-v3.0",
  "detected_language_code": "hi-IN",
  "processing_time": 0.58,
  "end_to_end_latency": 0.66
}
```

BhashaBench always sends `model` explicitly. The vendor's API default is
v2.5, and v3.0 is the model documented for code-mixed Indian call audio —
which is this project's entire subject.

### Streaming — `wss://api.vachana.ai/stt/v3/stream`

Authenticated on the upgrade request's headers: `x-api-key-id`, `model`,
`language_code`, `x-sample-rate` (optional, default `16000`), `format`
(optional).

Audio: **signed 16-bit little-endian mono PCM, in frames of exactly 1024
bytes** (512 samples — 32 ms at 16 kHz, 64 ms at 8 kHz). The documentation
warns that bursting frames faster than real time degrades voice-activity
detection, so the adapter paces its sends and re-frames whatever chunk size
the caller supplies.

Server events:

| `type` | Meaning | BhashaBench event |
|--------|---------|-------------------|
| `connected` | handshake complete | *not surfaced* |
| `processing` | VAD detected end of speech | *not surfaced* |
| `transcript` | a completed segment | `final_transcript` |
| `error` | server-side error | `failed` |

**There are no partial results.** The documented schema has no `is_final`
field and no interim indicator — every `transcript` event is a settled
segment. The adapter therefore emits `final_transcript` for each one and
**never** emits `partial_transcript`, and declares
`supports_partial_results: false`. A consumer that wants live captions needs
to know this rather than wait for partials that never arrive.

`connected` and `processing` are vendor lifecycle notices with no transcript
content. They are not exposed: `started` already told the consumer the stream
is live, and inventing a public event per vendor notice would leak the
vendor's protocol into our interface.

### Audio formats

| Path | Accepted |
|------|----------|
| Batch | WAV, MP3, OGG, FLAC, AAC, M4A |
| Streaming | raw `pcm_s16le` only |

Streaming sample rates: 8000, 16000, 44100, 48000 Hz. 8 kHz is what an Indian
phone call actually arrives at.

### Documented error statuses

| Status | Meaning | Mapped to | Retried? |
|--------|---------|-----------|----------|
| 401 | missing or invalid key | `AuthenticationError` | No |
| 402 | insufficient credit | `AuthenticationError` | No |
| 403 | key lacks the scope | `AuthenticationError` | No |
| 429 | rate limited | `RateLimitError` | Yes |
| 5xx | provider fault | `ProviderUnavailableError` | Yes |
| other 4xx | our request is wrong | `TranscriptionError` | No |

### What Prisma does **not** provide

Reported as unsupported rather than synthesised:

- **Confidence scores** — absent from the documented response schema.
- **Word-level timestamps** — absent.
- **Speaker diarisation** — absent from the STT response.
- **Partial/interim results** — see above.

`confidence` and `segments` are therefore `null` in a Prisma result. Filling
them with `1.0` or `[]` would read as "the model was certain" rather than "the
provider does not report this", and every downstream metric built on it would
be quietly fictional.

### Documentation gaps

Recorded honestly rather than guessed. These are published through
`GET /api/v1/transcription/providers` as `notes`:

1. **Maximum batch duration is stated inconsistently** — the specifications
   page says 30 seconds, the quick-start says 60. No client-side duration
   limit is enforced; the provider's own rejection is surfaced instead of a
   guessed ceiling.
2. **No request body size limit is published for `POST /stt/v3`.** The 10 MB
   per-file limit documented for the batch-jobs API is applied as a
   conservative ceiling.
3. **Only `transcribe` has a published literal `format` value.** Prisma v3.0
   is described as offering four output modes — Verbatim, Transcribe,
   Code-mix, Transliterate — but the other three appear only as prose names.
   Guessing `code-mix` vs `code_mix` vs `codemix` would be inventing the
   contract, so they are declared **unsupported** until the literals are
   confirmed.
4. **`auto` and `indic-auto`** both appear as `language_code` values with no
   stated difference. Neither is exposed by BhashaBench: a benchmark that
   silently detects the language cannot report whether the bot answered in the
   language the scenario asked for.
5. **No `Retry-After` is documented for 429.** One is honoured if present
   (delay-seconds form only), otherwise the client's own backoff applies.
6. **No end-of-stream acknowledgement is documented**, so a normal socket
   close is treated as completion.

### Language support

Prisma documents **ten** languages. BhashaBench's catalogue holds **thirteen**.

| Supported by Prisma | Not supported |
|---------------------|---------------|
| `hi-IN`, `bn-IN`, `mr-IN`, `te-IN`, `ta-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `pa-IN`, `en-IN` | `ur-IN` (Urdu), `or-IN` (Odia), `as-IN` (Assamese) |

A scenario may be **authored** in Urdu, Odia or Assamese — Phase 3 allows it —
and no transcript can be produced for it. The request is refused with a
message that says so explicitly, rather than transcribing as a neighbouring
language:

> `'or-IN'` is a supported BhashaBench language, but the `'prisma'` provider
> does not transcribe it.

Those are two different mistakes and deserve two different messages. Telling a
developer "unsupported language" without saying *by the provider* sends them
looking for a typo that is not there.

Prisma's codes happen to be spelled identically to ours, so the mapping is the
identity function — written out explicitly anyway, because an identity mapping
that is *assumed* becomes a silent bug the first time a vendor spells Punjabi
`pa-Guru-IN`.

`hi-en` (Hinglish) is a documented Prisma code with no BhashaBench equivalent.
It is recorded in `prisma_contract.py` but deliberately not added to
`app/core/languages.py`: that module is the single source of truth, and
`hi-en` is not a BCP 47 tag the scenario schema accepts. Code-mixing is
already expressed in a scenario's `code_mixing` block.

---

## The verified Gnani Timbre contract

Transcribed from <https://docs.gnani.ai>. Pages consulted:
`api/TTS/tts-inference` (the REST reference and its OpenAPI schema),
`api/TTS/available-voices` (the voice catalogue) and
`api/introduction/introduction`. The constants live in
`app/speech/providers/timbre_contract.py` and are asserted by tests.

### Transport and authentication

| | |
|---|---|
| Endpoint | `POST https://api.vachana.ai/api/v1/tts/inference` |
| Request | `application/json` |
| Response | **binary audio** — not JSON |
| Auth header | `X-API-Key-ID: <key>` |
| Auth scheme | **None** — the bare key, *not* `Bearer <key>` |
| Credential | the **same** `GNANI_API_KEY` as Prisma |

One Gnani platform key, one header, both subsystems. There is deliberately no
second credential setting. Scopes are a separate matter: a key can be valid and
still lack the TTS scope, which arrives as a 403 — the adapter's message says
so explicitly, because "forbidden" on a key that demonstrably works for Prisma
is otherwise baffling.

### Request body

```json
{
  "text": "வணக்கம், உங்கள் பயிர் காப்பீட்டு விண்ணப்பத்தின் நிலையைச் சரிபார்க்கிறேன்.",
  "model": "timbre-v3.0",
  "voice": "Kalpana",
  "language": "ta-IN",
  "audio_config": {
    "sample_rate": 8000,
    "num_channels": 1,
    "sample_width": 2,
    "encoding": "linear_pcm",
    "container": "wav"
  }
}
```

`text`, `model` and `audio_config` are required; `voice`, `language` and
`speed` are optional. BhashaBench always sends `model` and `voice` explicitly —
relying on an undeclared provider default would make a run irreproducible.

### Models and voices

| Model | Voices | Languages per voice | Audio tags |
|-------|--------|---------------------|------------|
| `timbre-v3.0` (default) | 13, fully documented | all 10 | yes |
| `timbre-v2.5` | 42, **roster incomplete** | one each | no |

v3.0 is the default because every one of its voices speaks all ten languages,
so a scenario's language can change without changing the voice. v2.5's voices
are language-specific, which would force a voice choice per language.

The 13 documented v3.0 voices, with the character each is catalogued for:

| Voice | Gender | Catalogued for |
|-------|--------|----------------|
| Shivani | female | Warm, patient, empathy-first — inbound customer support |
| Lakshmi | female | Expressive, warm — storytelling and e-learning narration |
| Kalpana | female | Empathetic, composed — customer care and insurance |
| Chetana | female | Gentle, empathetic — healthcare and telecom service |
| Vasudha | female | Expressive, composed — narration and e-learning |
| Riyaa | female | Confident, lively — outbound sales and insurance |
| Tarika | female | Warm, reassuring — banking and insurance customer care |
| Avinash | male | Professional, firm, deliberate pacing — collections and BFSI |
| Shubham | male | Energetic, confident — outbound sales and lead qualification |
| Prakash | male | Steady, deliberate — payment recovery and BFSI |
| Devansh | male | Energetic, young conversational — sales and fintech |
| Yashraj | male | Warm narrative — e-learning and IVR narration |
| Harshad | male | Professional, firm — collections and payment recovery |

`GNANI_TTS_VOICE` defaults to **Kalpana**, chosen for the subject matter: the
reference scenarios are insurance, banking and delivery support calls.

**A v2.5 voice name is forwarded without validation.** The vendor documents 42
and publishes nine as examples, so rejecting an unlisted name would refuse
valid input. Only the complete v3.0 roster is validated. Voice-name case
sensitivity is undocumented, so a differently-cased name is corrected to the
published spelling rather than forwarded as typed.

### Languages

Ten documented, the same ten Prisma recognises:

`hi-IN`, `en-IN`, `ta-IN`, `te-IN`, `kn-IN`, `ml-IN`, `mr-IN`, `pa-IN`,
`bn-IN`, `gu-IN`

Plus two provider-level values:

- **`auto`** — the vendor's recommendation for mixed-script input. Exposed
  here, unlike on the recognition side: when *speaking*, the text is already
  known, so letting the provider detect the script costs nothing. When
  *recognising*, detection would destroy the benchmark's ability to check which
  language the bot replied in.
- **`hi-en`** — Hindi-English code-mixed. Not a BCP 47 tag and so not in the
  catalogue, but exposed because Phase 3 made code-mixing a first-class
  scenario axis.

**There is no Tamil-English (or any other) code-mixed value.** `hi-en` is the
only one documented, so a Tanglish line has to use `auto` or `ta-IN`.

**Three catalogue languages cannot be spoken:** `ur-IN` (Urdu), `or-IN` (Odia),
`as-IN` (Assamese) — the same three Prisma cannot recognise. A scenario may be
authored in them and no caller audio can be synthesised.

### Audio output

| Field | Values | Default |
|-------|--------|---------|
| `container` | wav, raw, mp3, ogg, mulaw, alaw | wav |
| `encoding` | linear_pcm, pcm_s16le, pcm_mulaw, pcm_alaw, oggopus | linear_pcm |
| `sample_rate` | 8000, 16000, 22050, 24000, 44100, 48000 | **vendor: 48000** |
| `num_channels` | — | 1 |
| `sample_width` | — | 2 |
| `bitrate` (mp3 only) | 32k, 64k, 96k, 128k, 192k | 128k |
| `speed` | 0.85–1.15, or `slow` / `medium` / `fast` | provider default |

**BhashaBench defaults to 8 kHz**, not the vendor's 48 kHz, because an Indian
phone call is 8 kHz mono and Phase 8 will put this audio down a telephone line.
Downsampling 48 kHz later would mean resampling the signal under test, which is
Phase 7's job to control, not a side effect of a default.

`mulaw` and `alaw` are 8 kHz G.711 telephony codecs; any other rate with them is
refused rather than sent hopefully. `bitrate` with a non-MP3 container is also
refused.

### Audio tags (v3.0 only)

Eleven inline expression tags: `<whispers>`, `<laugh>`, `<pauses>`,
`<coughs>`, `<excited>`, `<giggle>`, `<shouting>`, `<sigh>`, `<sniffles>`,
`<yawns>`, `<clears throat>`.

A tag used against a model that does not support them is **read out as a word**,
so the service refuses it rather than letting `<laugh>` be spoken aloud. An
undocumented tag is refused too. Ordinary text containing `<` — "premium is
< 10 thousand" — is not mistaken for a tag.

### Documented error statuses

| Status | Meaning | Mapped to | Retried? |
|--------|---------|-----------|----------|
| 400 | invalid parameters | `UnsupportedAudioConfigError` | No |
| 401 | missing or invalid key | `SpeechAuthenticationError` | No |
| 402 | insufficient credit | `SpeechAuthenticationError` | No |
| 403 | key lacks the TTS scope | `SpeechAuthenticationError` | No |
| 429 | rate limited | `SpeechRateLimitError` | Yes |
| 500 / 503 | provider fault | `SpeechProviderUnavailableError` | Yes |

Two different error body shapes are documented, and the adapter reads both:

```
400 / 500       {"success": false, "message": "...", "status_code": NNN}
401 / 403 / 429 {"detail": {"error_code": "...", "message": "...", ...}}
```

### Documentation gaps

Recorded in `DOCUMENTATION_GAPS` and published through
`GET /api/v1/speech/providers` as `notes`:

1. **The v2.5 voice roster is incomplete** — 42 exist, nine are published. A
   v2.5 voice is forwarded unvalidated; only v3.0's 13 are validated.
2. **Voice-name case sensitivity is unstated.** The published spelling is sent.
3. **Tag count disagrees with itself** — the product page says twelve, the REST
   reference enumerates eleven. Only the eleven are accepted, so one documented
   capability may be missing.
4. **No maximum text length is published.** `SPEECH_MAX_TEXT_CHARS` is
   BhashaBench's bound, not the vendor's.
5. **No rate or concurrency limit is published**, despite 429 being documented.
   The project owner reports a one-active-request limit; that could not be
   confirmed from any vendor page, so the adapter serialises its own calls
   conservatively with an `asyncio.Lock` and declares
   `serialises_requests: true`.
6. **No `Content-Type` is documented for `raw`.** `application/octet-stream` is
   our choice for a headerless stream.
7. **No `Retry-After` is documented for 429.** One is honoured if present.
8. **The response carries no request identifier**, unlike Prisma's — so a
   Timbre result has none to quote in a support ticket.
9. **Whether numeric and string speeds behave identically is unstated.** Both
   are forwarded as documented, without interpretation.

### The streaming WAV header

Timbre returns a WAV whose RIFF and `data` size fields are `0xFFFFFFFF` — the
ordinary convention for a writer that does not know the final length. The real
length is simply the bytes present. Our inspector treats that sentinel as
"length unknown" and measures from the payload, while still rejecting a
*plausible* declared length with bytes missing. See the verification notes
above for why one live call was worth more here than 379 offline tests.

---

## Using the speech API

### Generate audio

```bash
curl -s -X POST http://localhost:8000/api/v1/speech/generate \
  -H 'Content-Type: application/json' \
  -o caller-line.wav -D headers.txt \
  -d '{
        "text": "வணக்கம், உங்கள் பயிர் காப்பீட்டு விண்ணப்பத்தின் நிலையைச் சரிபார்க்கிறேன்.",
        "language": "ta-IN",
        "voice": "Kalpana",
        "container": "wav",
        "sample_rate_hz": 8000
      }'
```

**The success response is the audio itself**, with the container's media type —
`audio/wav` by default. Not JSON. That is the right shape for a caller that
will hand the bytes to a telephony stream: base64 inside a JSON envelope would
inflate every utterance by a third and force a decode step on the only
consumer.

Metadata therefore travels in headers:

| Header | Always? | Meaning |
|--------|---------|---------|
| `X-Speech-Provider`, `X-Speech-Model`, `X-Speech-Voice` | yes | what produced it |
| `X-Speech-Language` | yes | the value sent to the provider |
| `X-Speech-Container`, `X-Speech-Size-Bytes` | yes | |
| `X-Speech-Latency-Ms` | yes | end to end, including retries |
| `X-Speech-Attempts` | yes | provider calls made |
| `X-Speech-Requested-Sample-Rate-Hz` | yes | what was asked for |
| `X-Speech-Sample-Rate-Hz` | **only when verified** | read from the returned audio |
| `X-Speech-Duration-Seconds` | **only when measurable** | |
| `X-Speech-Channels` | **only when verified** | |
| `X-Speech-Correlation-Id` | when supplied | |

An absent measurement header means **"not measurable"**, which is a different
statement from a wrong number. A WAV carries a header, so all three are exact.
An MP3 needs a decoder, so they are omitted rather than echoed back from the
request. Keeping the requested rate alongside the verified one is what makes a
provider that ignored the request visible instead of assumed away.

Errors are JSON in the project's standard envelope:

| Status | When |
|--------|------|
| 415 | a container, encoding, sample rate, speed or audio tag the provider lacks |
| 422 | empty or over-long text, an unknown voice, or a language it cannot speak |
| 429 | the provider is rate limiting |
| 502 | provider unreachable, credentials rejected, or an unusable response |
| 504 | the provider did not respond in time |

A provider 401 surfaces as **502**, not 401 — BhashaBench's own API is
unauthenticated in this phase, so a 401 would tell the caller to fix
credentials they do not have.

### Provider capabilities

```bash
curl -s http://localhost:8000/api/v1/speech/providers
```

Lists every registered provider, **including ones that cannot currently be
constructed** — a provider missing a credential is `available: false` with the
reason, never omitted. Each entry carries the voice roster with each voice's
catalogued character (which is what makes it possible to match a voice to a
scenario persona), `voices_are_exhaustive`, the audio tags, the speed range,
`unsupported_catalogue_languages`, and `notes` with the documentation gaps.

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `TRANSCRIPTION_PROVIDER` | `fake` (default) or `prisma` |
| `TRANSCRIPTION_TIMEOUT_SECONDS` | per-request timeout (default 30) |
| `TRANSCRIPTION_MAX_ATTEMPTS` | total attempts incl. the first (default 3; 1 disables retrying) |
| `TRANSCRIPTION_INITIAL_BACKOFF_SECONDS` | first retry delay before jitter (default 0.5) |
| `TRANSCRIPTION_MAX_BACKOFF_SECONDS` | ceiling on any delay, incl. `Retry-After` (default 8) |
| `TRANSCRIPTION_MAX_UPLOAD_BYTES` | largest accepted upload (default 10 MiB) |
| `TRANSCRIPTION_LIVE_TESTS` | opt in to real, billable transcription calls (default false) |
| `SPEECH_PROVIDER` | `fake` (default) or `timbre` |
| `SPEECH_TIMEOUT_SECONDS` | per-request timeout (default 60 - synthesis is slower than recognition) |
| `SPEECH_MAX_ATTEMPTS` | total attempts incl. the first (default 3) |
| `SPEECH_INITIAL_BACKOFF_SECONDS` / `SPEECH_MAX_BACKOFF_SECONDS` | retry delay and its ceiling |
| `SPEECH_MAX_TEXT_CHARS` | longest text accepted (default 5000; **ours**, not the vendor's) |
| `SPEECH_LIVE_TESTS` | opt in to real, billable synthesis calls (default false) |
| `GNANI_TTS_MODEL` | `timbre-v3.0` (default) or `timbre-v2.5` |
| `GNANI_TTS_VOICE` | default voice (default `Kalpana`) |
| `GNANI_API_KEY` | Gnani API key, sent as `X-API-Key-ID`. **Never commit a value.** |
| `GNANI_API_BASE_URL` | REST base URL (default `https://api.vachana.ai`) |
| `GNANI_STT_MODEL` | `prisma-v3.0` (default) or `prisma-v2.5` |

Both default providers are `fake`, so a fresh checkout starts and tests with no
credentials at all. The two live-test flags are **independent**: enabling
`TRANSCRIPTION_LIVE_TESTS` cannot silently start billing you for synthesis.

**One credential for both.** Timbre reads the same `GNANI_API_KEY` and
`GNANI_API_BASE_URL` as Prisma - the vendor documents one key and one
`X-API-Key-ID` header across the platform, so a second setting would be a
variable nobody could fill in. Scopes are separate from validity: a 403 on a
key that works for Prisma means the TTS scope is missing.

### Getting a key

Sign up at [app.gnani.ai](https://app.gnani.ai) and create an API key from the
dashboard. Put it in your local `.env` — which is git-ignored — or in a GitHub
Environment. Never in a tracked file, never in `.env.example`, never in a log
line.

```bash
# .env  (git-ignored)
TRANSCRIPTION_PROVIDER=prisma
GNANI_API_KEY=<your key>
```

If `TRANSCRIPTION_PROVIDER=prisma` and `GNANI_API_KEY` is empty, provider
construction fails with a message naming the variable and suggesting the
offline fake. It does not fall back silently.

### The fake is refused in production

`TRANSCRIPTION_PROVIDER=fake` with `APP_ENV=production` fails at startup. The
fake returns scripted transcripts; a production deployment that selected it
would publish fabricated text as measurements, which is exactly the failure
this project's first rule forbids.

---

## Using the transcription API

### Batch

```bash
curl -s -X POST http://localhost:8000/api/v1/transcription \
  -F 'audio=@backend/tests/fixtures/audio/tone_8k_mono.wav' \
  -F 'language=hi-IN' \
  -F 'mode=transcribe' \
  -F 'correlation_id=run-42-turn-3'
```

```json
{
  "text": "namaste, main aapki kya madad kar sakta hoon",
  "language": "hi-IN",
  "requested_language": "hi-IN",
  "provider": "prisma",
  "model": "prisma-v3.0",
  "request_id": "3f6c1e8a-2b7d-4a19-9c21-5f0d8e6b4a73",
  "correlation_id": "run-42-turn-3",
  "mode": "transcribe",
  "latency_ms": 663.0,
  "provider_processing_ms": 580.0,
  "audio_duration_seconds": 1.0,
  "confidence": null,
  "segments": null,
  "attempts": 1,
  "empty": false
}
```

`latency_ms` is measured by BhashaBench end to end and **includes retries** —
a call that took three attempts and nine seconds does not report the 600 ms
the last attempt happened to take. `provider_processing_ms` is the provider's
own figure, converted from the seconds it reports.

`empty: true` with HTTP 200 means the provider succeeded and recognised no
speech. That is a legitimate result a voice-bot test may well assert on, not
an error.

#### Format detection

The container is identified from the file's **own bytes**. A declared content
type or filename extension is a hint from an untrusted source; the payload is
evidence. An HTML error page saved as `call.wav` is rejected with 415, and an
`encoding=mp3` declaration on a WAV file is rejected rather than trusted.

Raw `pcm_s16le` is the exception — it has no header, so it must be declared,
along with `sample_rate_hz`.

#### Error statuses

| Status | When |
|--------|------|
| 413 | over `TRANSCRIPTION_MAX_UPLOAD_BYTES` or the provider's limit |
| 415 | a format, sample rate or channel count the provider does not accept |
| 422 | invalid/corrupt audio, or a language the provider cannot transcribe |
| 429 | the provider is rate limiting |
| 502 | provider unreachable, credentials rejected, or an unusable response |
| 504 | the provider did not respond in time |

A provider 401 surfaces as **502**, not 401. BhashaBench's own API is
unauthenticated in this phase, so returning 401 would tell the caller to fix
credentials they do not have.

### Provider capabilities

```bash
curl -s http://localhost:8000/api/v1/transcription/providers
```

Describes every registered provider, **including ones that cannot currently be
constructed**. A provider missing a credential is listed as
`available: false` with the reason — never omitted, because an absent entry
and an unconfigured one look identical to a caller. The reason names the
missing setting and never its value.

Each entry carries `unsupported_catalogue_languages` (the gap between the
catalogue and that provider) and `notes` (the documentation gaps above), so a
limitation is something you can read rather than something you discover by
hitting it.

### Streaming

```
ws://localhost:8000/api/v1/transcription/stream
    ?language=hi-IN
    &sample_rate_hz=8000
    &mode=transcribe
    &correlation_id=run-42
```

Query parameters rather than headers, because browsers cannot set headers on a
WebSocket.

Protocol:

1. Connect.
2. Send **binary** frames of signed 16-bit little-endian mono PCM at the
   declared rate. Frame size is up to you — the provider's own 1024-byte
   framing is handled server-side.
3. Send the text frame `EOS` when finished, or just close.
4. Receive JSON events.

```json
{"type":"started","provider":"prisma","language":"hi-IN","sample_rate_hz":8000,"at":"..."}
{"type":"final_transcript","text":"mera order kahan hai","segment_index":0,"segment_id":"seg_7f3a92","audio_duration_ms":2340,"latency_ms":318,"at":"..."}
{"type":"completed","result":{...},"at":"..."}
```

Exactly one terminal event is always sent: `completed` or `failed`. Unset
fields are omitted, so a `final_transcript` frame does not ship a dozen nulls
on every segment of every call.

`partial_transcript` exists in the interface and arrives only from a provider
that emits interim hypotheses. **Prisma does not.**

#### Backpressure and cleanup

Audio moves from the socket to the provider through a bounded queue (32
frames). When it fills, the reader stops reading and TCP backpressure reaches
the client — nothing buffers without limit. A single inbound frame is capped
at 64 KiB, and accumulated transcript text is capped too, so a provider that
never stops emitting cannot grow the process.

A client that disconnects mid-stream closes the provider connection through
the generator's own cleanup. Abandoning the stream cancels the sender task and
closes the socket.

#### Streaming is never retried automatically

The audio has already been consumed from a one-shot iterator by the time a
failure is known. A silent retry would transcribe the tail of an utterance and
present it as the whole thing. The `failed` event carries `retryable`, and the
decision belongs to the caller that still holds the audio source.

---

## Retry behaviour

Retried (transient):

- 5xx, 429, request timeouts, connection resets and DNS failures.

**Never** retried (permanent — a retry cannot succeed and only burns quota):

- 401/402/403, invalid or corrupt audio, an unsupported format or language, a
  malformed provider response, a configuration error.

The decision comes from the error's own `retryable` flag, not from a list of
status codes maintained in the retry loop. Backoff is exponential with full
jitter, bounded by `TRANSCRIPTION_MAX_BACKOFF_SECONDS` — which also bounds a
`Retry-After` the provider asks for, because an unbounded wait taken on a
provider's word turns one throttled request into an API that appears to hang.

---

## Logging

Structured `extra` fields on the `bhashabench.transcription*` loggers:
`provider`, `operation`, `language`, `mode`, `correlation_id`, `attempts`,
`latency_ms`, `audio_bytes`, `audio_duration_seconds`, `encoding`,
`transcript_chars`, `empty_transcript`, `outcome`.

**Never logged:** the API key, any `Authorization`-class header value, the
database password, raw audio, or the transcript text. Only
`transcript_chars` — a transcript carries whatever the caller said, which may
be a card number read aloud to a bot.

Credential redaction runs in two places: inside each adapter, and again at the
HTTP and WebSocket boundaries. The adapters are the first line of defence; the
boundary is the one that still holds when a future adapter forgets.

---

## Testing

```bash
pytest                                            # whole suite, no credentials needed

# speech to text (Phase 4)
pytest backend/tests/test_transcription_core.py   # audio, retry, registry
pytest backend/tests/test_transcription_prisma.py # the adapter vs the contract
pytest backend/tests/test_transcription_streaming.py
pytest backend/tests/test_transcription_api.py    # service + HTTP + WebSocket
pytest backend/tests/test_transcription_security.py

# text to speech (Phase 5)
pytest backend/tests/test_speech_core.py          # contract, models, registry, service
pytest backend/tests/test_speech_timbre.py        # the adapter vs the contract
pytest backend/tests/test_speech_api.py           # service + HTTP + cleanup + security
```

Every one of those runs offline against the fake provider. No credential, no
network, no database. That is what lets CI reject a broken transcription path
on a pull request from a fork.

### The fake provider

A *scripted* fake, not a stub that always succeeds. Every failure the real
adapter can produce is reachable deterministically — 401, 429, timeout, reset
connection, malformed body, mid-stream disconnect, cancellation — because a
retry policy and an error-mapping layer are only as trustworthy as the
failures they have actually been driven through.

It declares `supports_partial_results: true`, making it the one provider that
exercises the interim-hypothesis path Prisma cannot.

### Live provider tests

```bash
# transcription only
TRANSCRIPTION_LIVE_TESTS=true GNANI_API_KEY=... pytest -m live

# synthesis only
SPEECH_LIVE_TESTS=true GNANI_API_KEY=... pytest -m live

# one specific test, which is how to keep the bill to a single call
SPEECH_LIVE_TESTS=true GNANI_API_KEY=... \
  pytest -m live -k test_one_short_line_synthesises_end_to_end
```

Set `SPEECH_LIVE_AUDIO_DIR=<dir>` to have the synthesis smoke test write its
audio there and print the measured properties. Local only, nothing is uploaded -
the point is that a paid call should leave something listenable behind.

**These make real, billable calls.** Nothing runs unless both the flag and a
key are present; with either missing every test skips with a reason naming
what is absent. CI sets neither.

They use the shortest committed fixtures — one second of audio — for exactly
that reason. `TestLiveLanguageCoverage` makes ten calls; run it deliberately.

What they verify that nothing else can: that the key authenticates, that
Gnani accepts the request shape, that the documented framing works, and that
no partial events arrive. After a run, update the verification table at the
top of this document.

**Run so far (2026-11-07):** `test_a_fixture_file_transcribes_end_to_end` and
`test_authentication_succeeds_with_the_configured_key`, both passing — three
calls in total, including one against an earlier fixture defect. The streaming
and ten-language tests have **not** been run.

A note on the fixture, because it bit once: `live_provider` is
**function-scoped** and injects a client with keep-alive disabled. Each test
drives its own `asyncio.run`, which closes its event loop on return; a shared
provider's pooled connection then belongs to a dead loop, and the second test
in the module fails with `RuntimeError: Event loop is closed` — which reads
like an authentication failure and is not one. A pooled socket surviving the
loop also reaches pytest as `PytestUnraisableExceptionWarning`, which
`filterwarnings = ["error"]` turns into a failing exit code even when the test
itself passed. One provider per test, no keep-alive, no orphaned socket.

### Audio fixtures

`backend/tests/fixtures/audio/` — regenerate with
`python backend/tests/fixtures/audio/generate.py`.

**None of them contain speech.** They are synthesised tones, silence and
deliberately malformed files, so **none has an expected transcript**. No
licensed Indian-language speech recordings have been supplied to this
repository, and writing ground truth for audio nobody has listened to would
put fabricated expectations into the suite. See
[`backend/tests/fixtures/audio/README.md`](../backend/tests/fixtures/audio/README.md)
for provenance, licensing and how to add real recordings.

---

## Not in this phase

- Prisma's asynchronous **batch-jobs** pipeline (`/stt/v3/batch/jobs`) for long
  or many files. Phase 4's single-shot REST path covers its exit criterion.
- The three output modes whose literal wire values are unpublished.
- Automatic language detection (`auto` / `indic-auto`).
- Caller simulation (Phase 6), audio degradation (Phase 7), telephony
  (Phase 8), orchestration (Phase 9), scoring (Phase 10).
- Any persistence of transcripts or generated audio.
- **Timbre streaming** (SSE and WebSocket). Both are documented by the vendor
  and neither is implemented: nothing consumes a stream before Phase 9, and an
  unused transport is an untested transport.
- Timbre voice cloning, which the vendor documents separately.
- The three Timbre output modes whose literal wire values are unpublished.
