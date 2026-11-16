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

## Next task

Phase 11, deterministic evaluation first: a metric registry with documented
definitions, WER and CER with Indic-aware normalisation, task completion from
the caller's recorded outcome, latency from recorded per-turn timings, and
evaluation results persisted per run with their evaluator version.

## Outstanding issues

- Phase 6 cannot close until a live, cost-bounded call is authorised.
- Phase 8 cannot close without an authorised real call.
- Deployment target: none provisioned; anything paid needs the owner.
