"""Simulated caller subsystem (Phase 6).

Layering, outermost first:

    app/api/v1/caller.py              HTTP transport
    app/caller/orchestrator.py        conversation lifecycle
    app/caller/service.py             one turn: decide, then synthesise
    app/caller/registry.py            which provider, built from settings
    app/caller/protocol.py            the CallerProvider interface
    app/caller/providers/             one implementation per strategy

`schemas`, `state`, `analysis` and `errors` are shared by all of them. SQL
lives in `app/repositories/caller_conversations.py`, per the layering rule in
CLAUDE.md - not in this package.

**Phase 6 uses deterministic, rule-based caller orchestration. Official Gnani
Evon integration is deferred until documented access and credentials are
available.** `protocol.py` is the extension point; nothing here pretends to be
a language model.

Reuses rather than reimplements: `app/speech/` for caller audio,
`app/transcription/` for bot audio, and the existing
`TestRun -> CallSession -> ConversationTurn` tables for persistence. No new
table and no migration.
"""
