# Telephony (Phase 8) — a provider abstraction with a mocked provider only

Code: `backend/app/telephony/`.

**No real call can be placed.** There is no vendor adapter: a telephone
number and per-minute calls cost money and are not authorised, and an
adapter's wire format must be transcribed from its vendor's documentation,
not written from memory. `ExecutionMode.TELEPHONY_TEST` stays out of
`IMPLEMENTED_MODES`, so no run can claim to be a telephone test. Phase 8's
exit criterion needs a real call, so the phase stays 🟡 however much of
this exists.

## What exists

| Piece | Module | Rule |
|-------|--------|------|
| Numbers | `numbers.py` | E.164 only: `+`, a country code not starting with 0, at most 15 digits. Formatting is stripped; anything else is refused, never repaired. Logs and refusals show `+91********10`, never the full number |
| Guardrails | `guardrails.py` | Checked before the provider is contacted, every call: the number must be on `TELEPHONY_ALLOWED_NUMBERS` (empty allows nothing), and the run's calls, calls in progress and today's minutes must be under `TELEPHONY_MAX_CALLS_PER_RUN`, `TELEPHONY_MAX_CONCURRENT_CALLS` and `TELEPHONY_MAX_MINUTES_PER_DAY` |
| Provider contract | `base.py` | `place_call`, `hang_up`, `parse_event`, and capabilities that say whether the provider is `mocked` and whether it places real calls |
| Status rules | `models.py` | A vendor-neutral `ProviderCallStatus` mapped onto `CallSession.status`. This mapping, reached only from a verified provider event, is the only route to `DIALING`, `NO_ANSWER` and `BUSY`. Calls only move forward: a stale event is ignored, and nothing leaves a terminal status |
| Webhook signatures | `webhooks.py` | BhashaBench's own scheme, used by the mock - not any vendor's. HMAC-SHA256 over `<timestamp>.<raw body>`, a five-minute window against replay, a secret of at least 32 characters or nothing verifies |
| Mock provider | `mock.py` | Dials nothing. Produces the event bodies of four outcomes (answered, busy, no answer, failed), each marked `mocked`. Refused in production |
| Registry | `registry.py` | `TELEPHONY_PROVIDER` empty (telephony off) or `mock`. `twilio` is refused with the reason |

## Calls and events (`app/services/telephony_service.py`)

`place_call` reads the run's call count, the calls in progress and today's
minutes from `telephony_calls`, checks every guardrail, and only then asks
the provider to dial. A refusal is a 422 naming the limit; the provider is
never contacted. The new row stores the number **masked** - nothing
downstream needs the full one - and copies `mocked` from the provider. The
conversation's `telephony` metadata namespace (beside the caller's) records
the provider and `mocked`. Placing a call sets no status: only the
provider's events do.

`POST /api/v1/telephony/events/{provider}` takes no session - a provider
cannot sign in - and its credential is the signature, verified over the raw
body before parsing. Then:

| Event | Effect |
|-------|--------|
| Unsigned, tampered, outside the window | 401, nothing recorded |
| Not the configured provider, or an unknown call | 404 |
| Already seen (same event id) | 200, `applied: false`, nothing changes |
| Would rewind the call (a late `ringing` after `in_progress`), or arrives after it ended | Recorded with `applied: false`; status unchanged |
| Moves the call forward | The call's status, answer and end times and duration; the conversation's `CallSession.status` from `CALL_STATUS` |

`GET /api/v1/test-runs/{id}/telephony/calls` (viewer) lists a run's calls
with provider, `mocked`, masked number, status and every event as received.
It is empty for every run today. **There is no route that places a call**:
no run mode can use one, so a dial button would be a control that cannot
honestly do anything. Deleting a run deletes its calls.

## Configuration

| Variable | Default | |
|----------|---------|-|
| `TELEPHONY_PROVIDER` | empty | Empty is off; `mock` is the only provider |
| `TELEPHONY_WEBHOOK_SECRET` | empty | At least 32 characters, or no event verifies |
| `TELEPHONY_ALLOWED_NUMBERS` | empty | Comma-separated E.164; empty allows no call; one malformed entry fails startup |
| `TELEPHONY_MAX_CALLS_PER_RUN` | 3 | |
| `TELEPHONY_MAX_CONCURRENT_CALLS` | 1 | Across all runs |
| `TELEPHONY_MAX_MINUTES_PER_DAY` | 30 | Summed durations of calls created today (UTC) |

The `TWILIO_*` variables in `.env.example` are read by nothing.

## What a real adapter must add

A vendor adapter implements `TelephonyProvider`, maps its vendor's statuses
into `ProviderCallStatus`, and verifies its vendor's documented webhook
signature in its own module. Every constant it sends is cited from the
vendor's documentation, as the Gnani adapters do. Only then can
`TELEPHONY_TEST` join `IMPLEMENTED_MODES`, and only a real call to an
allow-listed number can close Phase 8.
