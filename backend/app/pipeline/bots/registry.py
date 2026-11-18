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

from pydantic import SecretStr

from app.core.config import Settings
from app.core.outbound import OutboundPolicy
from app.pipeline.bots.http_text import CAPABILITIES as HTTP_CAPABILITIES
from app.pipeline.bots.http_text import PROVIDER_NAME as HTTP_ADAPTER
from app.pipeline.bots.http_text import HttpBotConfig, HttpTextBotAdapter
from app.pipeline.bots.manual import PROVIDER_NAME as MANUAL_ADAPTER
from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.protocol import BotAdapter, BotCapabilities
from app.pipeline.bots.scripted import PROVIDER_NAME as SCRIPTED_ADAPTER
from app.pipeline.bots.scripted import ScriptedBotAdapter
from app.pipeline.errors import PipelineConfigurationError

DEFAULT_ADAPTER = SCRIPTED_ADAPTER


def _build_scripted(replies: Sequence[bytes] | None, settings: Settings | None) -> BotAdapter:
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


def fixture_text_replies_from_path(path: str | Path, *, count: int) -> tuple[str, ...]:
    """Read bot replies as text, one per line, for `offline_simulation`.

    The text counterpart of `fixture_replies_from_path`, named by
    `PIPELINE_FIXTURE_BOT_TEXT_PATH` - again an environment setting that no
    client value reaches. Blank lines and lines starting with `#` are skipped
    so a fixture can carry a comment. The remaining lines are used in order and
    repeated from the top to `count`, which the caller sizes from the turn
    ceiling, so a run ends on its budget rather than on an exhausted script.

    Raises:
        PipelineConfigurationError: the path is missing, unreadable as UTF-8,
            or holds no reply.
    """
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise PipelineConfigurationError(
            f"PIPELINE_FIXTURE_BOT_TEXT_PATH is set to '{path}', which is not a "
            "readable file. Point it at a UTF-8 text file with one bot reply per "
            "line, or unset it."
        )
    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PipelineConfigurationError(
            f"PIPELINE_FIXTURE_BOT_TEXT_PATH '{path}' is not valid UTF-8."
        ) from exc
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not lines:
        raise PipelineConfigurationError(
            f"PIPELINE_FIXTURE_BOT_TEXT_PATH '{path}' holds no replies. An empty "
            "script is not a bot saying nothing - it is a broken fixture."
        )
    return tuple(lines[i % len(lines)] for i in range(count))


def _build_manual(replies: Sequence[bytes] | None, settings: Settings | None) -> BotAdapter:
    # Scripted replies are meaningless here: the whole point of this adapter
    # is that the audio arrives later. Ignoring them silently would hide a
    # configuration mistake, so say so.
    if replies:
        raise PipelineConfigurationError(
            "the manual adapter takes no scripted replies; bot audio is "
            "supplied one turn at a time through the run's bot-audio endpoint"
        )
    return ManualBotAdapter()


def http_unavailable_reason(settings: Settings | None) -> str | None:
    """Why the `http` adapter cannot be built from `settings`, or `None`.

    Names settings, never values.
    """
    if settings is None:
        return "no settings were supplied to configure the HTTP bot adapter"
    if not settings.bot_http_base_url.strip():
        return "BOT_HTTP_BASE_URL is not set"
    if not settings.bot_http_token.get_secret_value():
        return "BOT_HTTP_TOKEN is not set"
    if not settings.bot_http_allowed_hosts.strip():
        return "BOT_HTTP_ALLOWED_HOSTS is empty, so no bot host may be contacted"
    return None


def ws_voice_unavailable_reason(settings: Settings | None) -> str | None:
    """Why the `ws_voice` adapter cannot be built, or `None`. Names settings only."""
    if settings is None or not settings.bot_ws_url.strip():
        return "BOT_WS_URL is not set"
    return http_unavailable_reason(
        settings.model_copy(update={"bot_http_base_url": settings.bot_ws_url})
    )


def adapter_unavailable_reason(name: str, settings: Settings | None) -> str | None:
    """Why the named adapter cannot be used on this deployment, or `None`."""
    if name == HTTP_ADAPTER:
        return http_unavailable_reason(settings)
    if name == "ws_voice":
        return ws_voice_unavailable_reason(settings)
    return None


def _build_http(replies: Sequence[bytes] | None, settings: Settings | None) -> BotAdapter:
    if replies:
        raise PipelineConfigurationError("the http adapter takes no scripted replies")
    reason = http_unavailable_reason(settings)
    if reason is not None or settings is None:
        raise PipelineConfigurationError(f"the http bot adapter is not configured: {reason}")
    policy = OutboundPolicy.from_setting(
        settings.bot_http_allowed_hosts,
        allow_loopback=settings.bot_http_allow_loopback,
        allow_private=settings.bot_http_allow_private,
    )
    config = HttpBotConfig(
        base_url=settings.bot_http_base_url.strip(),
        token=SecretStr(settings.bot_http_token.get_secret_value()),
        policy=policy,
        timeout_seconds=settings.bot_http_timeout_seconds,
        max_attempts=settings.bot_http_max_attempts,
    )
    return HttpTextBotAdapter(config)  # type: ignore[return-value] - a TextBotAdapter


def _build_ws_voice(replies: Sequence[bytes] | None, settings: Settings | None) -> BotAdapter:
    from app.pipeline.bots.ws_voice import VoiceBotConfig, WebSocketVoiceBotAdapter

    if replies:
        raise PipelineConfigurationError("the ws_voice adapter takes no scripted replies")
    reason = ws_voice_unavailable_reason(settings)
    if reason is not None or settings is None:
        raise PipelineConfigurationError(f"the ws_voice bot adapter is not configured: {reason}")
    policy = OutboundPolicy.from_setting(
        settings.bot_http_allowed_hosts,
        allow_loopback=settings.bot_http_allow_loopback,
        allow_private=settings.bot_http_allow_private,
    )
    return WebSocketVoiceBotAdapter(  # type: ignore[return-value]
        VoiceBotConfig(
            url=settings.bot_ws_url.strip(),
            token=SecretStr(settings.bot_http_token.get_secret_value()),
            policy=policy,
        )
    )


WS_VOICE_ADAPTER = "ws_voice"

_FACTORIES: dict[str, Callable[[Sequence[bytes] | None, Settings | None], BotAdapter]] = {
    SCRIPTED_ADAPTER: _build_scripted,
    MANUAL_ADAPTER: _build_manual,
    HTTP_ADAPTER: _build_http,
    WS_VOICE_ADAPTER: _build_ws_voice,
}
"""`http` and `ws_voice` are the only adapters that contact anything, and both
speak the project's own documented protocols (docs/BOT_PROTOCOL.md) rather
than any vendor's. A vendor bot gets an adapter written against its
documentation."""


def available_adapters() -> tuple[str, ...]:
    """Every registered adapter name, sorted."""
    return tuple(sorted(_FACTORIES))


def build_adapter(
    name: str,
    *,
    replies: Sequence[bytes] | None = None,
    settings: Settings | None = None,
) -> BotAdapter:
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
    return factory(replies, settings)


def describe_adapters() -> tuple[BotCapabilities, ...]:
    """Capabilities of every registered adapter, without configuring any.

    The http adapter's capabilities are static, so listing it neither needs
    its settings nor opens a client.
    """
    from app.pipeline.bots.ws_voice import CAPABILITIES as WS_VOICE_CAPABILITIES

    static = {HTTP_ADAPTER: HTTP_CAPABILITIES, WS_VOICE_ADAPTER: WS_VOICE_CAPABILITIES}
    return tuple(
        static[name] if name in static else build_adapter(name).capabilities
        for name in available_adapters()
    )


__all__ = [
    "DEFAULT_ADAPTER",
    "HTTP_ADAPTER",
    "MANUAL_ADAPTER",
    "SCRIPTED_ADAPTER",
    "WS_VOICE_ADAPTER",
    "adapter_unavailable_reason",
    "available_adapters",
    "build_adapter",
    "describe_adapters",
    "fixture_replies_from_path",
    "http_unavailable_reason",
]
