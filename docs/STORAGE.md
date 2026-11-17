# Storage (Phase 10)

Code: `backend/app/storage/` (the contract and the adapter) and
`backend/app/caller/artefacts.py` (audio naming on top of it).

## The contract

`BlobStore` stores bytes under relative keys: `put`, `get`, `exists`,
`size`, `delete` (idempotent), `delete_prefix` and `keys`. Every adapter
passes keys through `validate_key`, which refuses an empty or over-long key,
an absolute path, a backslash, a NUL, and any `..`, `.` or empty segment, so
no adapter depends on its callers' discipline.

## Backends

| `STORAGE_BACKEND` | Status |
|-------------------|--------|
| `local` | **Implemented.** Files under `CALLER_AUDIO_STORAGE_DIR`. The resolved path must stay inside the resolved root, which also defeats a symlink planted inside the root. Writes go to a temporary file in the same directory and are renamed into place, so a reader never sees half an artefact |
| anything else | **Refused at startup** with the reason. An S3-compatible adapter would need a paid bucket and the `boto3` dependency, neither authorised; an adapter that cannot be exercised would be a claim rather than a capability |

A deployment keeps artefacts on a persistent volume mounted at the storage
directory. Moving to object storage is an owner decision with a cost: an
S3-compatible bucket is billed per GB stored and per request, and that price
must be confirmed with the chosen provider before anything is provisioned.

## Audio on top of it

`AudioArtefactStore` keeps the audio-specific rules - names built only from a
conversation UUID, a turn index, a speaker, a whitelisted variant and a
whitelisted container; a 25 MB cap per object - and delegates the bytes. It
is constructed either from a root (the local adapter, which every existing
caller uses) or from any `BlobStore`. `delete_conversation` removes every
file of one conversation and reports how many.

## The full-conversation recording

When a pipeline run reaches any terminal state, `RunEngine._finish`
assembles `{conversation_id}/conversation.wav` from the turn artefacts and
records a manifest in the run's metadata (`app/pipeline/recording.py`):

- **Assembled, not captured.** Turns are concatenated in order after the
  run, 16-bit mono at 16 kHz. No silence is inserted between them, so
  inter-turn timing is not represented - inventing gaps would look like a
  latency measurement.
- **What was on the line.** A caller turn contributes its degraded variant
  when one exists (what the bot heard), otherwise the original.
- **Linked.** Each segment names its turn, speaker, variant, start, duration
  and `source_reference`, the per-turn artefact it came from, which remains
  the evidence.
- **Excluded, never filled.** A turn that is not 16-bit PCM WAV, or is gone
  from storage, is listed in `excluded` with its reason.
- **Never fatal.** A run's outcome does not depend on assembly: a failure is
  recorded as `status: failed` with a redacted reason. A run that exchanged
  no audio records `not_applicable`.

`GET /test-runs/{id}/recording` returns the manifest (404 until the run
finishes); `GET /test-runs/{id}/recording/audio` streams it, with the same
access and environment rules as per-turn audio. It lives under the
conversation's prefix, so deleting the conversation's artefacts deletes it.

## Deletion and retention

`app/services/retention_service.py`. Deleting a run removes the run row and,
by `ON DELETE CASCADE`, its conversations, turns, evaluations and reviewed
references; then every stored audio file of its conversations, the recording
included. The suite and its scenarios are untouched.

- **Only finished runs.** A run still in flight is refused (409); close a
  stuck one with `bhashabench runs recover-stale` first.
- **Never the protected historical runs**, by request or by retention.
- **Rows first, then files.** The database delete commits before any file
  is removed, so a failure leaves orphaned audio (removed by a re-run)
  rather than a run whose evidence is gone. Files that could not be removed
  are listed in the response, never hidden.
- **The engine's own store.** The API deletes through the store the run's
  audio was written through.

| How | Who | What |
|-----|-----|------|
| `DELETE /api/v1/test-runs/{id}` | `admin` or `owner` of the run's workspace | One run. Not reversible |
| `bhashabench runs purge [--older-than 30d] [--apply]` | Whoever holds database credentials | Every finished run that finished longer ago than the period. Dry run unless `--apply` |

**Retention is off by default.** `RETENTION_DAYS` unset keeps everything;
the sweep needs a period (the setting or `--older-than`, whole days) *and*
`--apply` before it deletes anything. There is no timer: scheduling the
sweep (cron, a platform job) is a deployment decision, documented in the
deployment plan.
