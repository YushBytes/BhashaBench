# BhashaBench text bot protocol — `bhashabench-text-bot/1`

The HTTP contract a chatbot implements so BhashaBench can hold a conversation
with it. **Text only.** A run over this protocol is a `text_bot_test`: it
measures what the bot says, and establishes nothing about speech recognition,
synthesis, audio quality or telephony. Audio and streaming are later phases.

`backend/reference_bot/` is a working implementation, used by the tests and
for local end-to-end runs: `python -m reference_bot` from `backend/`.

## Transport and authentication

- HTTPS, except to a loopback address during development, or to a
  private-network address with `BOT_HTTP_ALLOW_PLAIN_PRIVATE` (development only;
  the local Docker stack uses it for its reference bot).
- Redirects are never followed, by either adapter.
- Every `/v1` request carries `Authorization: Bearer <token>`. BhashaBench
  reads the token from `BOT_HTTP_TOKEN`; it never appears in a URL, a log
  line, run evidence or an API response.
- BhashaBench sends `X-Correlation-ID: <run id>:<turn index>` on every
  request. Echo it if you can; it lets the two sides' logs be joined.
- BhashaBench does not follow redirects. A `3xx` is reported as an error.

## Endpoints

### `GET /health`

No authentication. `200` with `{"status": "ok", "protocol": "bhashabench-text-bot/1"}`.

### `POST /v1/sessions`

Request: `{"language": "hi-IN", "metadata": {"run_id": "..."}}` — a BCP 47
tag from BhashaBench's catalogue and up to 20 string pairs.

`201`: `{"session_id": "<opaque, 1-200 chars>", "greeting": "<text>" | null}`.
A greeting, when present, is recorded in the run's evidence as
`bot_greeting`. It is not a turn: the caller speaks first.

### `POST /v1/sessions/{session_id}/turns`

Request: `{"text": "<caller utterance>", "turn_index": <int >= 0>}`, plus an
`Idempotency-Key` header.

`200`: `{"text": "<bot reply>", "end_session": false, "turn_index": <echo>}`.

An empty `text` is a valid reply and is recorded as the bot saying nothing —
a bot defect, not a transport failure. `end_session: true` means the bot has
closed the conversation.

**Idempotency.** A turn whose `Idempotency-Key` the session has already seen
must return the stored reply without advancing the conversation. BhashaBench
retries a turn only after a connection failure or a `502`/`503`/`504`, and
always with the same key, so a bot that honours this is never sent the same
utterance twice in effect.

### `DELETE /v1/sessions/{session_id}`

`204`. `404` for an unknown session. BhashaBench calls this when the
conversation ends, whoever ended it.

## Errors

Any non-2xx response carries:

```json
{"error": {"code": "session_not_found", "message": "no such session"}}
```

| Status | Meaning to BhashaBench |
|--------|------------------------|
| `401`, `403` | Authentication failed. Not retried |
| `404` | Unknown session. Not retried |
| `409` | Session ended or turn limit reached. Not retried |
| `422` | BhashaBench sent something malformed — our defect. Not retried |
| `429` | Rate limited. Not retried within a turn; reported |
| `502`, `503`, `504` | Transient. Retried with the same idempotency key, bounded |
| other `5xx` | Bot failure. Not retried |

A `2xx` whose body is not JSON, or lacks `text` as a string, is a malformed
response: reported as a bot defect, never repaired.

## Limits BhashaBench enforces on a bot

| Limit | Default | Setting |
|-------|---------|---------|
| Whole-request timeout | 10 s | `BOT_HTTP_TIMEOUT_SECONDS` |
| Response body | 64 KiB | — |
| Reply text | 4000 characters | — |
| Attempts per turn | 2 | `BOT_HTTP_MAX_ATTEMPTS` |
| Hosts | none | `BOT_HTTP_ALLOWED_HOSTS` (see `docs/SECURITY.md`) |

---

# `bhashabench-voice-bot/1` — streaming voice (Phase 9)

The audio counterpart of the text protocol: one WebSocket per conversation,
caller audio streamed in real time, the bot answering whenever it chooses -
including over the caller. BhashaBench's own protocol, not any vendor's.
Implemented by `backend/reference_bot/voice.py` and consumed by the
`ws_voice` adapter (`backend/app/pipeline/bots/ws_voice.py`).

## Connection

`GET /v1/voice` upgraded to a WebSocket, with `Authorization: Bearer
<token>` on the handshake. A missing or wrong token is refused before the
handshake completes (close code 1008). The URL passes the same outbound
guard as the text adapter (`BOT_HTTP_ALLOWED_HOSTS`).

## Messages

Text frames are JSON control messages; binary frames are audio.

| Direction | Message | Meaning |
|-----------|---------|---------|
| BhashaBench → bot | `{"type":"start","protocol":"bhashabench-voice-bot/1","language":"hi-IN","sample_rate_hz":16000,"encoding":"pcm_s16le","frame_ms":20,"run_id":"..."}` | First message. A bot that cannot serve the format answers `error` and closes |
| bot → BhashaBench | `{"type":"ready","protocol":"bhashabench-voice-bot/1"}` | Accepts the session |
| BhashaBench → bot | binary, 640 bytes | 20 ms of the caller's speech: 16 kHz mono signed 16-bit little-endian PCM, sent in real time |
| BhashaBench → bot | `{"type":"caller_turn_end","turn_index":n}` | The caller has finished (or yielded) |
| bot → BhashaBench | binary, at most 2560 bytes | The bot's speech, same format, at any time |
| bot → BhashaBench | `{"type":"turn_end","turn_index":n}` | Optional: the bot has finished its turn |
| either | `{"type":"hangup","reason":"..."}` | Ends the conversation |

## Turn-taking, as BhashaBench measures it

Per turn the adapter applies `TurnPolicy` (`app/pipeline/streaming.py`) and
records which rule ended the turn:

| `ended_by` | When |
|------------|------|
| `bot_signal` | The bot spoke and sent `turn_end` after the caller finished |
| `end_of_turn_silence` | The bot spoke, then stayed below the voice threshold for 700 ms |
| `silence_timeout` | The bot never spoke within 5 s of the caller finishing. Recorded as the bot saying nothing - an empty bot turn - and no silence is fabricated |
| `deadline` | The bot was still speaking 30 s after it started: cut off |
| `bot_hangup` | The bot hung up |

- **Latency** is from the caller's last frame being sent to the first
  *voiced* bot frame arriving, on BhashaBench's monotonic clock. Negative
  means the bot started before the caller finished.
- **Barge-in**: a voiced bot frame before `caller_turn_end`. The caller then
  yields - its remaining frames are not sent - and the turn records
  `barge_in: true` and `caller_truncated: true`.
- **Caller barge-in** (opt-in per run, `caller_barge_in_after_ms`): once the
  bot has spoken that long after `caller_turn_end`, BhashaBench sends more
  caller frames over the bot's speech - the start of the caller's own turn
  audio, re-sent, 600 ms by default - **without** another `caller_turn_end`.
  A bot that handles barge-in stops its audio and may send `turn_end`. The
  turn records `caller_barge_in`: `sent`, `sent_after_bot_speech_ms`,
  `bot_voiced_ms_after`, `bot_stopped_after_ms` (to the bot's last voiced
  frame after the interruption) and `bot_yielded` (stopped within
  `yield_window_ms`, 500 by default). From outside, a reply that was about
  to end anyway is indistinguishable from yielding; the evidence carries
  that `limitation`, and the remedy is a comparison run without barge-in. If the bot's turn ends before it has
  spoken that long, nothing is sent and `not_sent_reason` says so. This
  tests whether the bot yields to speech, not whether it understands what
  was said. The reference bot's `yields_to_caller` option implements the
  well-behaved side.
- **Voice activity is energy-based** (RMS ≥ -45 dBFS by default). A loud
  non-speech noise counts as speech; the threshold is recorded with every
  turn so a reader can tell a silent bot from a deaf detector.
- **Real time.** Frames are paced at 20 ms. Nothing is accelerated, in tests
  either: faster-than-real-time streaming would make the latencies fiction.

Every bot turn's evidence is on its `bot_exchange` stage event in
`GET /test-runs/{id}/report`: `ended_by`, `bot_latency_ms`, `barge_in`,
`caller_truncated`, `bot_audio_seconds`, `bot_speaking_wall_seconds` and the
policy.

## What is not claimed

Only the reference bot has been driven over this protocol; no third-party
bot has been tested. Transcription of the bot's audio and synthesis of the
caller's are still per utterance, not streamed.
