# BhashaBench text bot protocol — `bhashabench-text-bot/1`

The HTTP contract a chatbot implements so BhashaBench can hold a conversation
with it. **Text only.** A run over this protocol is a `text_bot_test`: it
measures what the bot says, and establishes nothing about speech recognition,
synthesis, audio quality or telephony. Audio and streaming are later phases.

`backend/reference_bot/` is a working implementation, used by the tests and
for local end-to-end runs: `python -m reference_bot` from `backend/`.

## Transport and authentication

- HTTPS, except to a loopback address during development.
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
A greeting, when present, is recorded as the bot's first turn.

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
