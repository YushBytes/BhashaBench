"""The text-generation client interface.

A `Protocol`, like every other provider boundary here: clients share no
implementation, and a test double satisfies it without importing anything.

One request, one response. Retrying is the caller strategy's job, not the
client's - a client that retried internally would spend money the strategy's
attempt limit and the budget gate never saw.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.caller.llm.models import LlmCapabilities, LlmRequest, LlmResponse


@runtime_checkable
class LlmClient(Protocol):
    """Sends one generation request to one model."""

    @property
    def capabilities(self) -> LlmCapabilities:
        """What this client supports. Cheap and side-effect free."""
        ...

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Send `request` once and return the reply.

        Must not retry, and must not send anything when a limit or a disabled
        gate forbids it.

        Raises:
            LlmError: any failure, normalised. `request_sent` on the error
                says whether a request left the process.
        """
        ...

    async def close(self) -> None:
        """Release any resources. Idempotent."""
        ...


__all__ = ["LlmClient"]
