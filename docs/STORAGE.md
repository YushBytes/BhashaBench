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
