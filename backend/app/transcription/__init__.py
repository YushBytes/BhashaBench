"""Speech-to-text subsystem (Phase 4).

Layering, outermost first:

    app/api/v1/transcription.py     HTTP and WebSocket transport
    app/services/transcription_service.py
                                    business rules, provider-agnostic
    app/transcription/registry.py   which provider, built from settings
    app/transcription/base.py       the TranscriptionProvider interface
    app/transcription/providers/    one adapter per vendor

`models`, `errors`, `audio`, `retry` and `redaction` are shared by all of
them. Nothing above `providers/` may import a vendor module or reference a
vendor field name - that boundary is what lets Phase 11 benchmark a second
engine without touching the evaluation code.
"""
