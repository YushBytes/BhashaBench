# Speech providers

How BhashaBench talks to a speech-to-text engine, what Gnani Prisma actually
supports, and how to run the integration with or without credentials.

---

## Verification status — read this first

The repository's first rule is never to claim something works when it does
not. For a provider integration that means separating claims that are
routinely conflated — in particular, what a *mocked* test proves from what a
*real* API call proves.

**Last live verification: 2026-11-07**, against `https://api.vachana.ai`
with a real API key. Three Gnani API calls total.

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

**Still open on the streaming path.** The WebSocket adapter has never spoken to
Gnani. Its framing (1024 bytes), event mapping and the documented absence of
interim results are all taken from the vendor's published example. Running
`-k test_a_stream_completes_with_a_terminal_event` from the live suite is the
next verification step.

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

Shared by every layer: `models.py` (domain objects), `errors.py` (structured
failures), `audio.py` (inspection and validation), `retry.py`,
`redaction.py`.

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

## Configuration

| Variable | Purpose |
|----------|---------|
| `TRANSCRIPTION_PROVIDER` | `fake` (default) or `prisma` |
| `TRANSCRIPTION_TIMEOUT_SECONDS` | per-request timeout (default 30) |
| `TRANSCRIPTION_MAX_ATTEMPTS` | total attempts incl. the first (default 3; 1 disables retrying) |
| `TRANSCRIPTION_INITIAL_BACKOFF_SECONDS` | first retry delay before jitter (default 0.5) |
| `TRANSCRIPTION_MAX_BACKOFF_SECONDS` | ceiling on any delay, incl. `Retry-After` (default 8) |
| `TRANSCRIPTION_MAX_UPLOAD_BYTES` | largest accepted upload (default 10 MiB) |
| `TRANSCRIPTION_LIVE_TESTS` | opt in to real, billable provider calls (default false) |
| `GNANI_API_KEY` | Gnani API key, sent as `X-API-Key-ID`. **Never commit a value.** |
| `GNANI_API_BASE_URL` | REST base URL (default `https://api.vachana.ai`) |
| `GNANI_STT_MODEL` | `prisma-v3.0` (default) or `prisma-v2.5` |

The default provider is `fake`, so a fresh checkout starts and tests with no
credentials at all.

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

## Using the API

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
pytest backend/tests/test_transcription_core.py   # audio, retry, registry
pytest backend/tests/test_transcription_prisma.py # the adapter vs the contract
pytest backend/tests/test_transcription_streaming.py
pytest backend/tests/test_transcription_api.py    # service + HTTP + WebSocket
pytest backend/tests/test_transcription_security.py
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
TRANSCRIPTION_LIVE_TESTS=true GNANI_API_KEY=... pytest -m live
```

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
- Text to speech (Phase 5), caller simulation (Phase 6), audio degradation
  (Phase 7), telephony (Phase 8), orchestration (Phase 9), scoring (Phase 10).
- Any persistence of transcripts.
