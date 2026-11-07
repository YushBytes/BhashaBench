"""Credential redaction for logs, errors and API responses.

The threat this addresses is mundane and common: a provider echoes the request
back in an error body, or a client library puts the request headers into an
exception message, and the API key ends up in a log aggregator that a wider
audience can read than the `.env` file ever had.

Redaction happens at the boundary where provider text enters our own strings.
It is a second line of defence, not the first - the first is never putting a
credential into a message. Both are cheap; only one of them survives a
refactor by someone who has not read this module.
"""

from __future__ import annotations

import re

PLACEHOLDER = "***REDACTED***"

# Header names whose values are always secret. Matched case-insensitively
# because the Prisma REST and WebSocket docs spell the same header with
# different capitalisation (`X-API-Key-ID` and `x-api-key-id`).
SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "x-api-key-id",
        "api-key",
        "cookie",
        "set-cookie",
    }
)

# `key=value`, `"key": "value"` and `key: value` spellings of a secret-looking
# field, so a credential is caught whether it arrives as a query string, a JSON
# body or a header dump.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(?P<name>
        api[_-]?key(?:[_-]?id)?
      | access[_-]?token
      | refresh[_-]?token
      | authorization
      | secret(?:[_-]?key)?
      | password
      | passwd
    )\b
    # A JSON key carries its own closing quote before the colon
    # (`"api_key": "..."`). Without allowing it, the most common serialised
    # form of a leaked credential slips through.
    (?P<keyquote>["']?)
    (?P<sep>\s*[:=]\s*|\s+)
    # An auth scheme is part of the syntax, not part of the secret: redacting
    # `Bearer` and leaving the token behind is the worst of both outcomes.
    (?P<scheme>(?:bearer|basic|token)\s+)?
    (?P<quote>["']?)
    (?P<value>[^\s"',;&}\]]+)
    (?P=quote)
    """
)

# A bare `Bearer <token>` with no preceding field name - how an Authorization
# header looks once it has been flattened into a log line.
_BARE_SCHEME = re.compile(r"(?i)\b(bearer|basic|token)\s+([A-Za-z0-9._\-+/=]{8,})")

_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]+):([^/\s@]+)@")


def _replace_assignment(match: re.Match[str]) -> str:
    """Rebuild a matched assignment with its value replaced.

    Everything except the value is preserved, because the surrounding syntax
    is what makes a redacted log line still readable - and the field name is
    often the most useful part of it.
    """
    quote = match.group("quote")
    return (
        f"{match.group('name')}{match.group('keyquote')}{match.group('sep')}"
        f"{match.group('scheme') or ''}{quote}{PLACEHOLDER}{quote}"
    )


def redact(text: object) -> str:
    """Return `text` with anything credential-shaped replaced.

    Accepts `object` because the usual callers are exception instances and
    provider response bodies, and the alternative is a `str()` call at every
    call site that is easy to forget.
    """
    value = text if isinstance(text, str) else str(text)
    value = _URL_CREDENTIALS.sub(rf"\1\2:{PLACEHOLDER}@", value)
    value = _ASSIGNMENT.sub(_replace_assignment, value)
    return _BARE_SCHEME.sub(rf"\1 {PLACEHOLDER}", value)


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of `headers` safe to log.

    The key *names* are preserved: knowing that `x-api-key-id` was sent is
    exactly what you need when diagnosing a 401, and the name is not the
    secret.
    """
    return {
        name: (PLACEHOLDER if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def mask_secret(secret: str | None, *, keep: int = 4) -> str:
    """Describe a credential without disclosing it.

    Returns a fingerprint like `***abcd` (last `keep` characters) so two
    environments can be told apart in a log without the value being usable.
    Short secrets are masked entirely rather than mostly revealed.
    """
    if not secret:
        return "<unset>"
    if len(secret) <= keep * 2:
        return PLACEHOLDER
    return f"***{secret[-keep:]}"


__all__ = ["PLACEHOLDER", "SENSITIVE_HEADERS", "mask_secret", "redact", "redact_headers"]
