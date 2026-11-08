"""Which bot adapters exist, and how one is built.

One entry per adapter, explicitly. Mirrors `app/transcription/registry.py` and
`app/caller/registry.py`: no discovery, no entry points, no dynamic import.

**The default is `scripted`, and that is a safety decision.** §7 requires that
the default configuration must not send audio to arbitrary external
destinations, so the default adapter is the one that sends audio nowhere at
all. Choosing an adapter that contacts an external system has to be a
deliberate act of configuration.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from app.pipeline.bots.manual import PROVIDER_NAME as MANUAL_ADAPTER
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.protocol import BotAdapter, BotCapabilities
from app.pipeline.bots.scripted import PROVIDER_NAME as SCRIPTED_ADAPTER
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.errors import PipelineConfigurationError

DEFAULT_ADAPTER = SCRIPTED_ADAPTER


def _build_scripted(replies: Sequence[bytes] | None) -> BotAdapter:
    return ScriptedBotAdapter(replies or ())


def _build_manual(replies: Sequence[bytes] | None) -> BotAdapter:
    # Scripted replies are meaningless here: the whole point of this adapter
    # is that the audio arrives later. Ignoring them silently would hide a
    # configuration mistake, so say so.
    if replies:
        raise PipelineConfigurationError(
            "the manual adapter takes no scripted replies; bot audio is "
            "supplied one turn at a time through the run's bot-audio endpoint"
        )
    return ManualBotAdapter()


_FACTORIES: dict[str, Callable[[Sequence[bytes] | None], BotAdapter]] = {
    SCRIPTED_ADAPTER: _build_scripted,
    MANUAL_ADAPTER: _build_manual,
}
# No entry for a real voice bot. Adding one means writing an adapter against
# that bot's documented interface; this project does not guess at one.


def available_adapters() -> tuple[str, ...]:
    """Every registered adapter name, sorted."""
    return tuple(sorted(_FACTORIES))


def build_adapter(name: str, *, replies: Sequence[bytes] | None = None) -> BotAdapter:
    """Build the named adapter.

    Raises:
        PipelineConfigurationError: no such adapter.
    """
    key = (name or "").strip().casefold()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise PipelineConfigurationError(
            f"'{name}' is not a known bot adapter; available adapters are "
            f"{list(available_adapters())}. A real voice bot needs an adapter "
            "written against its published interface - this project does not "
            "invent one."
        )
    return factory(replies)


def describe_adapters() -> tuple[BotCapabilities, ...]:
    """Capabilities of every registered adapter."""
    return tuple(build_adapter(name).capabilities for name in available_adapters())


__all__ = [
    "DEFAULT_ADAPTER",
    "MANUAL_ADAPTER",
    "SCRIPTED_ADAPTER",
    "available_adapters",
    "build_adapter",
    "describe_adapters",
]
