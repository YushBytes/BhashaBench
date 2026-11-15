"""The language-model side of the caller, independent of any vendor.

Two layers, and the split is the design:

* **A text-generation client** (`LlmClient`): messages in, text and usage out.
  It knows nothing about callers, scenarios or state machines. One
  implementation per vendor lives in `app/caller/llm/clients/`, and that is
  the only place a vendor's wire format may appear.
* **A caller strategy** (`app/caller/providers/llm.py`): builds the prompt from
  a `CallerContext`, parses and validates the reply, enforces the limits, and
  falls back to the deterministic caller when generation fails. It knows
  nothing about any vendor.

So adding a vendor is writing a client and a registry entry, and changing how
the caller behaves never touches a vendor module.

What is deliberately not here: any way to reach the scenario's
`expected_outcomes`. The prompt is built from `CallerContext`, which has no
such field, so the marking scheme cannot reach a model by any path through
this package.
"""
