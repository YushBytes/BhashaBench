"""Run the reference text bot: `python -m reference_bot` from `backend/`.

Configuration is from the environment only:

    REFERENCE_BOT_TOKEN        required, 16+ characters (see generate_token)
    REFERENCE_BOT_SCRIPT_PATH  optional JSON reply script
    REFERENCE_BOT_HOST         default 127.0.0.1 - loopback, deliberately
    REFERENCE_BOT_PORT         default 8090

The token is never printed. Binding beyond loopback is a deliberate act.
"""

from __future__ import annotations

import os
import sys

import uvicorn

from reference_bot.app import BotConfig, create_app
from reference_bot.responder import DEFAULT_SCRIPT, ScriptError, load_path


def main() -> int:
    token = os.environ.get("REFERENCE_BOT_TOKEN", "")
    if len(token) < 16:
        print(
            "REFERENCE_BOT_TOKEN must be set to at least 16 characters. Generate one with:\n"
            '  python -c "from reference_bot.app import generate_token; print(generate_token())"',
            file=sys.stderr,
        )
        return 2
    script = DEFAULT_SCRIPT
    path = os.environ.get("REFERENCE_BOT_SCRIPT_PATH")
    if path:
        try:
            script = load_path(path)
        except ScriptError as exc:
            print(f"REFERENCE_BOT_SCRIPT_PATH: {exc}", file=sys.stderr)
            return 2
    app = create_app(BotConfig(token=token, script=script))
    uvicorn.run(
        app,
        host=os.environ.get("REFERENCE_BOT_HOST", "127.0.0.1"),
        port=int(os.environ.get("REFERENCE_BOT_PORT", "8090")),
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
