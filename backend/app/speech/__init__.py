"""Text-to-speech subsystem (Phase 5).

Layering, outermost first:

    app/api/v1/speech.py        HTTP transport
    app/speech/service.py       business rules, provider-agnostic
    app/speech/registry.py      which provider, built from settings
    app/speech/base.py          the SynthesisProvider interface
    app/speech/providers/       one adapter per vendor

`models` and `errors` are shared by all of them. Nothing above `providers/`
may import a vendor module or reference a vendor field name.

Three pieces are reused from `app/transcription/` rather than copied:
`redaction`, `retry` and `audio` (its WAV inspector verifies returned audio).
When a third provider family arrives, those three should be promoted to a
shared package; duplicating them now would be the start of two drifting
copies.
"""
