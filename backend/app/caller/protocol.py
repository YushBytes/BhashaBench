"""The caller provider interface.

A `Protocol`, as with `TranscriptionProvider` and `SynthesisProvider`:
providers are built from settings, share no implementation, and structural
typing lets a test double satisfy the interface without importing it.

**This is the extension point for official Gnani Evon.** Phase 6 ships exactly
one implementation, `DeterministicCallerProvider`, which is a rule engine and
is named as one. No `EvonCallerProvider` exists - Gate A established that no
Gnani text-generation endpoint is documented and no hosted inference for
`gnani/gnani-evon-v3.3-30B-A3B` is advertised, so an adapter would be a
non-functional stub pretending to work, which §3B forbids.

What a future Evon provider will need, and why this interface is shaped to
give it: `decide` receives the whole `CallerContext` - persona, objective,
known facts, history, the bot's last transcript, the state and the remaining
budget - which is the prompt material an LLM caller needs, and returns a
`CallerDecision`, which is the structured output such a model would be asked
to produce. Adding it should require writing one class and one registry entry,
and touching nothing in the orchestrator, the persistence layer or the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.caller.schemas import CallerContext, CallerDecision


@dataclass(frozen=True, slots=True)
class CallerCapabilities:
    """What a caller provider can actually do.

    Declared data for the same reason the speech providers declare theirs: a
    limitation a caller hits should be readable in advance from
    `GET /api/v1/caller/providers` rather than discovered from a failure.
    """

    name: str
    """Registry name, e.g. `deterministic`."""
    display_name: str
    is_deterministic: bool
    """True when the same context always yields the same decision.

    The single most important field here. A deterministic caller makes a
    benchmark reproducible: a scenario replayed against an unchanged bot gives
    the same conversation. A model-backed caller would set this False, and any
    report built on it has to say so.
    """
    uses_language_model: bool
    """Whether a learned model generates the text. **False** for every provider
    in Phase 6 - see this module's docstring."""
    languages: frozenset[str]
    """BhashaBench language tags this provider can compose utterances in."""
    supports_code_mixing: bool
    requires_credentials: bool
    max_turns_supported: int | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)
    """Honest limitations, surfaced to clients."""

    def supports_language(self, language: str) -> bool:
        """Whether this provider can speak `language`."""
        return language in self.languages


@runtime_checkable
class CallerProvider(Protocol):
    """Decides what the simulated caller says next."""

    @property
    def capabilities(self) -> CallerCapabilities:
        """What this provider supports. Cheap and side-effect free."""
        ...

    async def decide(self, context: CallerContext) -> CallerDecision:
        """Choose the caller's next utterance.

        `async` not because a rule engine needs it, but because the interface
        has to accommodate a provider that makes a network call - and changing
        a synchronous interface to asynchronous later would ripple through the
        orchestrator and every test. Paying for it now costs nothing.

        Must not mutate `context`, and must return a decision whose `message`
        is non-empty: `CallerDecision` enforces that, so a provider cannot send
        silence to speech synthesis.

        Raises:
            CallerError: any failure, normalised.
        """
        ...

    async def close(self) -> None:
        """Release any resources. Idempotent."""
        ...


__all__ = ["CallerCapabilities", "CallerProvider"]
