"""Bot adapters: how the pipeline obtains the bot's side of a conversation.

Two adapters ship in Phase 7, and neither opens a socket:

- `scripted` replays fixture audio. The default, because a default that sent
  audio to an external destination would be unsafe.
- `manual` stores the caller's audio and waits for an operator to post the
  bot's reply back.

A real integration is a third adapter written against a real bot's published
interface and added to `_FACTORIES` in `registry.py`. There is no plugin
discovery, for the same reason the speech subsystems have none: "which bot
produced this conversation?" must be answerable by reading the source.
"""

from app.pipeline.bots.manual import ManualBotAdapter
from app.pipeline.bots.protocol import BotAdapter, BotCapabilities, BotReply
from app.pipeline.bots.scripted import ScriptedBotAdapter

__all__ = [
    "BotAdapter",
    "BotCapabilities",
    "BotReply",
    "ManualBotAdapter",
    "ScriptedBotAdapter",
]
