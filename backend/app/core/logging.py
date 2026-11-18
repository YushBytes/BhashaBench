"""Request IDs and structured logs (Phase 15).

Every request gets an id: the caller's `X-Request-ID` when it is short and
safe (letters, digits, `-`, `_`, at most 64), otherwise a new UUID. It is
echoed in the response's `X-Request-ID` and attached to every log record
written while the request is handled, so one failing request can be found
across lines - and an operator can quote the id from a browser's network tab.

`LOG_FORMAT=json` writes one JSON object per line (timestamp, level, logger,
message, request_id, and any `extra` fields), which a log shipper can index
without parsing. The default `text` keeps the readable format for
development. Values pass through the shared redactor, so a credential that
reaches a log message is masked in either format.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from app.transcription.redaction import redact

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


def request_id_from(header: str | None) -> str:
    return header if header and _SAFE_ID.fullmatch(header) else uuid.uuid4().hex


def set_request_id(value: str | None) -> contextvars.Token[str | None]:
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    _request_id.reset(token)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": getattr(record, "request_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and key != "request_id":
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure(*, json_format: bool, level: int) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if json_format
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s")
    )
    handler._bhashabench = True  # type: ignore[attr-defined]
    root = logging.getLogger()
    # Replace only our own handler: others (a test runner's capture, a
    # platform agent's) belong to whoever installed them.
    root.handlers[:] = [h for h in root.handlers if not getattr(h, "_bhashabench", False)]
    root.addHandler(handler)
    root.setLevel(level)


__all__ = [
    "REQUEST_ID_HEADER",
    "JsonFormatter",
    "RequestIdFilter",
    "configure",
    "current_request_id",
    "request_id_from",
    "reset_request_id",
    "set_request_id",
]
