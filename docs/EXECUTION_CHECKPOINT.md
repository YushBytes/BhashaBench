# Execution checkpoint

The resume point for continuous execution of the remaining phases, under the
owner's standing authorisation of 2026-11-16 (see `CLAUDE.md`, "Phase
discipline"). Updated as units land. Phase numbers are the original ones.

**To resume:** read this file, run `git status`, confirm
`git rev-parse HEAD` equals `git rev-parse origin/main`, check the latest
GitHub Actions run, then start the first unchecked task below. Never trust a
figure here over the repository: re-measure it.

## Hard limits (unchanged by the authorisation)

- No live provider call (Sarvam, Gnani, telephony) in tests, CI or by hand.
- No spending: no paid infrastructure, domain, subscription, credits or number.
- Never read, print or edit `.env`.
- The `GNANI_API_KEY` exposed in a session transcript on 2026-11-16 is treated
  as compromised. Rotation is the owner's manual task.

## Execution order

Dependencies decide the order: evaluation needs the conversation evidence,
reporting needs evaluation, tenancy must exist before the frontend's
project pages, and deployment needs everything.

1. Early Phase 9 prerequisite — HTTP reference bot and adapter (text only).
2. Phase 7 — remaining audio conditions reachable from a scenario.
3. Phase 11 — deterministic evaluation (WER/CER, task completion, latency),
   judge abstraction with an offline fake.
4. Phase 12 — analytics, run comparison, regression, CSV/JSON export.
5. Phase 14 (part 1) — users, sessions, workspaces, projects, authorisation.
6. Phase 10 — storage abstraction, recordings, retention and deletion.
7. Phase 8 — telephony abstraction, mocked provider, signed webhooks.
8. Phase 9 — background execution, latency evidence, recovery.
9. Phase 13 — frontend against the real API.
10. Phase 14 (part 2) — security scanning, headers, rate limits, CI gates.
11. Phase 15 — production images, configuration, runbooks, deployment plan.

## Progress

| Unit | Commit | CI |
|------|--------|----|
| Hide exported provider credentials from offline tests | `b1e1c26` | ✅ 43897753071 |
| Hold the Gnani key as a masked `SecretStr` | `007e283` | ✅ 43911871562 |
| Record the owner's authorisation and this checkpoint | `33091ee` | ✅ |
| Outbound-request guard against SSRF | `02b1ff7` | ✅ 43913687809 |
| Reference text bot and `bhashabench-text-bot/1` | `b98b944` | ✅ 43915170226 |
| HTTP text bot adapter | `f9eed46` | ✅ 43916620115 |
| `text_bot_test` runs through the adapter, engine and API | `47b61eb` | ✅ 43920069081 |

**Early Phase 9 prerequisite: complete.** Text only; verified against the
reference bot on localhost.

| Phase 7 unit | Commit | CI |
|------|--------|----|
| Jitter, dropout, truncation and silence transformations | `a74ce2b` | ✅ 43921296391 |
| Scenario-declared channel conditions and per-run overrides | `a47c3b3` | ✅ 43922977070 |
| Exact G.711 codec; Phase 7 closed | `7825496` | ✅ 43924088839 |

**Phase 7: complete** (synthetic noise; no recorded noise beds).

| Phase 11 unit | Commit | CI |
|------|--------|----|
| Normalisation, WER/CER, metric registry | `git log --grep "normalisation, WER"` | ✅ 43925429634 |
| Append-only evaluations and references (migration `1c40c48f72cf`) | see log | ✅ 43927628576 |
| Evaluator with reasoned verdict | see log | ✅ 43928854156 |
| Evaluation API | see log | ✅ 43930963986 |
| Offline LLM judge; Phase 11 closed | see log | ✅ 43932115730 |

**Phase 11: complete** (deterministic; judge offline-only, not validated
against human labels).

| Phase 12 unit | Commit | CI |
|------|--------|----|
| Index test runs for reporting (migration `6c64d84df105`) | `32e66f2` | ✅ 44056197928 (pushed with the next unit) |
| Aggregates, comparison, regression, trend, export | `37e8ec9` | ✅ 44056197928 |

**Phase 12: complete** (signed artefact URLs moved to Phase 10; no PDF).

| Phase 10 unit | Commit | CI |
|------|--------|----|
| Blob storage contract and local adapter; `.gitignore` anchored | `b32f5bf` | ✅ |
| Full-conversation recording linked to turn artefacts | `519e40e` | ✅ |
| Run deletion and the retention sweep | `a56b132` | ✅ |
| Signed expiring audio links; `PIPELINE_SERVE_ARTEFACTS` retired; Phase 10 closed | `1541ab2` | see log |

**Phase 10: complete** (local filesystem only; recordings assembled, not
captured live; the sweep is not scheduled).

| Phase 8 unit | Commit | CI |
|------|--------|----|
| Provider contract, guardrails, signed webhooks, mock provider | `6f5bf8c` | see log |
| `telephony_calls` (migration `bcf146f6c696`), event handling, webhook and call listing | `97a5b0c` | see log |

**Phase 8: partial by rule** (no real call is authorised).

| Phase 9 unit | Commit | CI |
|------|--------|----|
| Background execution, crash finishing, automatic recovery; `bbs_` token redaction | `b3ea14a` | see log |
| Streaming voice protocol, `ws_voice` adapter, reference bot voice endpoint; Phase 9 closed | this commit | see log |

**Phase 9: complete** (STT/TTS per utterance; energy VAD; reference bot only).

## Next task

Phase 13: the frontend against the real API - metric and comparison views
built only from the Phase 12 analytics endpoints, run auto-refresh (now that
runs execute in the background), scenario and suite management, workspace
and member views, recording playback, and a frontend test suite.

Deferred to Phase 14 part 2: rate limiting, security headers,
dependency/secret scanning (dev-only `minimatch` and `picomatch` advisories
open), and the regression gate.

## Outstanding issues

- Phase 6 cannot close until a live, cost-bounded call is authorised.
- Phase 8 cannot close without an authorised real call.
- Deployment target: none provisioned; anything paid needs the owner.
- A local smoke-test account `e2e-smoke@example.test` (workspace `e2e-smoke`,
  no data) exists in the developer database from the 2026-11-17 check.
