"""How the reference bot decides what to say. Deterministic, and nothing else.

A reply script is an ordered list of rules; the first rule whose condition
matches the caller's text wins, exactly like the caller's own rule engine.
The bot is not intelligent and does not pretend to be: it exists so the HTTP
adapter, the engine and the evaluation have a real process on a real socket to
talk to, whose behaviour a test can predict.

A script can be loaded from JSON (`REFERENCE_BOT_SCRIPT_PATH`), so an operator
can make the bot refuse, mishear or loop without editing code:

    {"rules": [
       {"contains_any": ["refund"], "reply": "I cannot help with refunds."},
       {"has_number": true, "reply": "Reference {number} is confirmed."},
       {"reply": "Sorry, could you repeat that?"}
    ], "greeting": "Hello, how can I help?"}

`{number}` is replaced by the longest digit run in the caller's text.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DIGIT_RUN = re.compile(r"\d[\d\s-]*\d|\d")
MAX_RULES = 200
MAX_REPLY_CHARS = 2000


class ScriptError(ValueError):
    """A reply script that cannot be used, with the reason."""


@dataclass(frozen=True, slots=True)
class Rule:
    reply: str
    contains_any: tuple[str, ...] = ()
    has_number: bool | None = None
    end_session: bool = False

    def matches(self, text: str, number: str | None) -> bool:
        if self.contains_any and not any(k in text for k in self.contains_any):
            return False
        return self.has_number is None or self.has_number == (number is not None)


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    end_session: bool
    rule_index: int


@dataclass(frozen=True, slots=True)
class Script:
    rules: tuple[Rule, ...]
    greeting: str | None = None

    def respond(self, caller_text: str) -> Reply:
        text = unicodedata.normalize("NFKC", caller_text).casefold()
        runs = [re.sub(r"[\s-]", "", m) for m in _DIGIT_RUN.findall(text)]
        number = max(runs, key=len) if runs else None
        for index, rule in enumerate(self.rules):
            if rule.matches(text, number):
                return Reply(rule.reply.replace("{number}", number or ""), rule.end_session, index)
        # `load` guarantees a final unconditional rule, so this is unreachable.
        raise ScriptError("no rule matched and the script has no fallback")  # pragma: no cover


DEFAULT_SCRIPT_DATA: dict[str, Any] = {
    "greeting": None,
    "rules": [
        {
            "contains_any": ["thank", "bye", "धन्यवाद", "நன்றி"],
            "has_number": False,
            "reply": "You are welcome. Goodbye.",
            "end_session": True,
        },
        {
            "has_number": True,
            "reply": "Thank you. Your request with reference {number} is confirmed.",
        },
        {
            "contains_any": ["hello", "namaste", "नमस्ते", "calling", "help", "request"],
            "reply": (
                "Hello, thank you for calling. Could you please tell me your reference number?"
            ),
        },
        {"reply": "Sorry, I did not understand. Could you please repeat that?"},
    ],
}
"""A helpline that asks for a reference number, confirms it, and says goodbye."""


def load(data: dict[str, Any]) -> Script:
    """Validate a script mapping.

    Raises:
        ScriptError: malformed, oversized, or with no final unconditional rule.
    """
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ScriptError("a script is an object with a 'rules' list")
    raw_rules = data["rules"]
    if not raw_rules or len(raw_rules) > MAX_RULES:
        raise ScriptError(f"a script needs between 1 and {MAX_RULES} rules")
    rules: list[Rule] = []
    for i, raw in enumerate(raw_rules):
        if not isinstance(raw, dict) or not isinstance(raw.get("reply"), str):
            raise ScriptError(f"rule {i} needs a string 'reply'")
        unknown = set(raw) - {"reply", "contains_any", "has_number", "end_session"}
        if unknown:
            raise ScriptError(f"rule {i} has unknown keys {sorted(unknown)}")
        reply = raw["reply"].strip()
        if not reply or len(reply) > MAX_REPLY_CHARS:
            raise ScriptError(f"rule {i}'s reply must be 1-{MAX_REPLY_CHARS} characters")
        keywords = raw.get("contains_any", [])
        if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
            raise ScriptError(f"rule {i}'s 'contains_any' must be a list of strings")
        has_number = raw.get("has_number")
        if has_number is not None and not isinstance(has_number, bool):
            raise ScriptError(f"rule {i}'s 'has_number' must be true or false")
        rules.append(
            Rule(
                reply=reply,
                contains_any=tuple(unicodedata.normalize("NFKC", k).casefold() for k in keywords),
                has_number=has_number,
                end_session=bool(raw.get("end_session", False)),
            )
        )
    last = rules[-1]
    if last.contains_any or last.has_number is not None:
        raise ScriptError("the last rule must be unconditional, so every message gets a reply")
    greeting = data.get("greeting")
    if greeting is not None and (not isinstance(greeting, str) or not greeting.strip()):
        raise ScriptError("'greeting' must be a non-empty string or null")
    return Script(tuple(rules), greeting.strip() if greeting else None)


def load_path(path: str | Path) -> Script:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScriptError(f"could not read the script at {path}: {exc}") from exc
    return load(data)


DEFAULT_SCRIPT = load(DEFAULT_SCRIPT_DATA)
