# Connect your chatbot

BhashaBench tests a chatbot you **already run**. It does not build or host a
bot. You give it an address and a token; it calls your bot as a caller would,
and records what happened.

This guide covers what your bot has to implement, what you enter, what the
connection check proves (and what it does not), and how to run your first
test. The API is described in `README.md` ("Connected bots").

## 1. Choose how your bot is reached

Two protocols are supported. Both are BhashaBench's own, documented in
[`BOT_PROTOCOL.md`](BOT_PROTOCOL.md). A bot that does not speak one of them
needs a small adapter service in front of it that does. BhashaBench does not
speak any vendor's API directly, and does not claim to.

| You have | Protocol | What a run tests | Run mode |
|----------|----------|------------------|----------|
| A text chatbot behind an HTTP API | `http`: `bhashabench-text-bot/1` | What the bot **says**: task completion, the words of each reply, latency per turn. Nothing about speech, because no audio moves | `text_bot_test` |
| A real-time voice bot | `ws_voice`: `bhashabench-voice-bot/1` over a WebSocket | What the bot **hears and says aloud**: BhashaBench synthesises the caller, streams 16 kHz PCM in 20 ms frames in real time, records the bot's audio and transcribes it | `external_bot_test` |

Not supported, said plainly:

- **A phone number.** No telephony provider is integrated (`TELEPHONY.md`).
- **A vendor's API as-is** (a hosted bot platform's own REST or WebSocket
  format). Put a thin service in front of it that speaks one of the two
  protocols. `backend/reference_bot/` is a working example of both, in about
  600 lines of Python.
- **An SDK package.** None is published. The protocols are small enough to
  implement directly; the reference bot is the template.

## 2. Implement the protocol

**Text bot (`http`).** Four endpoints under your base URL:

```
GET    /health                              (no auth)
POST   /v1/sessions                         -> 201 {"session_id": "...", "greeting": null}
POST   /v1/sessions/{session_id}/turns      {"text": "...", "turn_index": 0}
                                            -> 200 {"text": "...", "end_session": false}
DELETE /v1/sessions/{session_id}            -> 204
```

**Voice bot (`ws_voice`).** One WebSocket. BhashaBench sends
`{"type":"start","protocol":"bhashabench-voice-bot/1","language":"hi-IN","sample_rate_hz":16000,"encoding":"pcm_s16le","frame_ms":20,...}`.
You answer `{"type":"ready"}` (or `{"type":"error","message":"..."}` and close
if you cannot serve that format), then exchange binary 20 ms PCM frames.

Both require `Authorization: Bearer <token>` on every request and refuse a
wrong token with 401 or 403. Full details, errors and limits:
[`BOT_PROTOCOL.md`](BOT_PROTOCOL.md).

To try the flow before writing anything, run the reference bot locally:

```bash
cd backend
REFERENCE_BOT_TOKEN=<16+ characters> python -m reference_bot   # http://127.0.0.1:8090
```

## 3. What you enter

| Field | Example | Notes |
|-------|---------|-------|
| Name | `Support bot (staging)` | Unique within the project |
| Protocol | `http` or `ws_voice` | Decides the run mode |
| URL | `https://bot.example.com` (http) / `wss://bot.example.com/v1/voice` (ws_voice) | Must be `https://` or `wss://`. Plain `http://`/`ws://` works only for a bot on your own machine in development |
| Token | 16 to 4096 characters, no spaces | Sent as `Authorization: Bearer <token>` |
| Default language | `hi-IN` | Used by the connection check |

Rules, so a form never accepts something no run could use:

- The URL may not contain a username or password (put the credential in the
  token field, where it is encrypted) or a `#fragment`.
- **Where it may point.** A deployed BhashaBench reaches only public
  addresses: localhost, private networks (10.x, 172.16–31.x, 192.168.x),
  link-local addresses and cloud metadata services are refused, including
  through a hostname that resolves to them, an IPv4-mapped IPv6 address or a
  redirect (redirects are never followed). The address that was checked is
  the one connected to, so changing DNS between the check and the connection
  has no effect.

## 4. How your token is stored

- Encrypted with AES-256-GCM before it reaches the database, under a key
  derived from the server's `SECRET_KEY`, and bound to that one integration.
- **Never shown again.** Every screen and API response shows only its last
  four characters (`…a1b2`). To change it, replace it.
- Sent only to your bot, only in the `Authorization` header. It is redacted
  from errors and never written to logs or run evidence.
- If the server's `SECRET_KEY` is rotated, stored tokens cannot be read; the
  integration says so and asks you to enter the token again.

## 5. Check the connection

Saving contacts nothing, so a saved integration is **unverified**. The
connection check calls your bot through exactly the code a run uses:

| Protocol | The check does | It proves | It does not prove |
|----------|----------------|-----------|-------------------|
| `http` | Opens a session, sends one turn ("Hello, this is a BhashaBench connection check."), closes the session | Reachable, token accepted, session lifecycle, reply shape | How well the bot answers a real scenario |
| `ws_voice` | Opens the WebSocket, sends `start` in the run's audio format, waits for `ready`, hangs up | Reachable, token accepted, protocol and audio format accepted | That the bot replies with audio, or yields when interrupted; a run measures those |

Each capability is shown as **verified**, **failed** (or not carried by the
protocol: text bots carry no audio), or **not checked**. "Not checked" is not
a pass.

| Outcome | Meaning | What to do |
|---------|---------|------------|
| `connected` | Every step above succeeded | Run a test |
| `authentication_failed` | Your bot refused the token (401/403) | Replace the token |
| `target_refused` | BhashaBench's safety rules refused the URL before connecting (a private or metadata address, a name that does not resolve, plain http to a public host) | Use a public `https://`/`wss://` address |
| `unreachable` | Nothing accepted the connection | Check the URL, port and that the bot is running |
| `timeout` | No answer within the configured timeout (10 s by default) | Check the bot's health |
| `protocol_error` | Something answered, but not in this protocol | Check the path and protocol |
| `session_rejected` | A voice bot refused `start`, usually the audio format | Accept 16 kHz `pcm_s16le` in 20 ms frames |

Changing the URL or replacing the token sets the integration back to
**unverified**: the previous check proved nothing about the new values.

## 6. Run a test

Only a **connected** integration can be selected for a run, and only from
its own project. Pick a scenario, a language and (for voice) audio
conditions, and start the run. The run records which integration it used
(name, host and when it was last checked). Its turns show what your bot
actually said; a voice run also keeps the audio.

Over the API:

```bash
POST /api/v1/projects/{project_id}/bot-integrations   # save (unverified)
POST /api/v1/bot-integrations/{id}/check               # connected?
POST /api/v1/test-runs  {"suite_id": "...", "scenario_id": "...",
                         "mode": "text_bot_test", "bot_integration_id": "{id}"}
POST /api/v1/test-runs/{run_id}/start
```

## 7. No bot yet? Use the demo

The **offline simulation** runs a scenario against a scripted reply file on
the server. It is labelled "offline simulation" everywhere: nothing leaves
the server, the replies are fixtures, and no figure from it describes a real
bot. Use it to learn the workflow, then connect your own.
