"""Telephony (Phase 8): a provider abstraction with a mocked provider only.

No real call can be placed. There is no vendor adapter: none is authorised
(a number and per-minute calls cost money), and its wire format would have
to be transcribed from vendor documentation, not written here. What exists
is everything a real adapter plugs into - numbers, guardrails checked before
dialling, signed webhooks, and the rules for turning a provider's events into
a call's status - exercised end to end by `MockTelephonyProvider`, whose
calls are labelled mocked in every record they produce.

`ExecutionMode.TELEPHONY_TEST` stays out of `IMPLEMENTED_MODES`: a mocked
call is not a telephone test, and no run may claim to be one.
"""
