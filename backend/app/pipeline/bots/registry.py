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
from pathlib import Path

from app.pipeline.bots.manual import PROVIDER_NAME as MANUAL_ADAPTER
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.protocol import BotAdapter, BotCapabilities
from app.pipeline.bots.scripted import PROVIDER_NAME as SCRIPTED_ADAPTER
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.errors import PipelineConfigurationError

DEFAULT_ADAPTER = SCRIPTED_ADAPTER


def _build_scripted(replies: Sequence[bytes] | None) -> BotAdapter:
    return ScriptedBotAdapter(replies or ())


def fixture_replies_from_path(path: str | Path, *, count: int) -> tuple[bytes, ...]:
    """Read one audio file and repeat it as a scripted bot's replies.

    `AUDIO_FIXTURE_TEST` is only usable from the API if the scripted adapter
    has something to replay, and the API had no way to give it any: the route
    built the adapter with no replies, so every such run failed on turn 0.
    This is how an operator supplies that fixture.

    The file is named by `PIPELINE_FIXTURE_AUDIO_PATH`, an environment setting.
    **No client value reaches this function** - there is no request field for
    it - so a caller cannot ask the server to read an arbitrary path.

    `count` is sized from `CALLER_MAX_TURNS` by the caller rather than guessed:
    the turn budget is the lower of that ceiling and the scenario's own
    `max_turns`, so a run always terminates on the budget before it can
    exhaust the replies. Exhaustion therefore stays an error, loudly, instead
    of being softened into a silent stop.

    The payload is one `bytes` object referenced `count` times, not copied.

    Raises:
        PipelineConfigurationError: the path is missing, is not a file, or is
            empty. A misconfigured fixture fails here with a message naming
            the path, rather than resurfacing as the turn-0 failure it exists
            to fix.
    """
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise PipelineConfigurationError(
            f"PIPELINE_FIXTURE_AUDIO_PATH is set to '{path}', which is not a "
            "readable file. Point it at a WAV file the scripted adapter can "
            "replay, or unset it to leave fixture runs unconfigured."
        )
    payload = resolved.read_bytes()
    if not payload:
        raise PipelineConfigurationError(
            f"PIPELINE_FIXTURE_AUDIO_PATH is set to '{path}', which is empty. "
            "An empty reply is not a bot saying nothing - it is a broken "
            "fixture, and the two must not look alike."
        )
    return (payload,) * count


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
    "fixture_replies_from_path",
]
