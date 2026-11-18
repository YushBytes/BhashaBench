"""Phase 15 observability: request ids on every response and log line, and
JSON log lines that a shipper can index without parsing."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import (
    JsonFormatter,
    RequestIdFilter,
    configure,
    request_id_from,
    reset_request_id,
    set_request_id,
)


class TestRequestIds:
    def test_every_response_carries_one(self, client: TestClient) -> None:
        response = client.get("/health")
        assert len(response.headers["x-request-id"]) == 32

    def test_a_safe_caller_id_is_echoed(self, client: TestClient) -> None:
        response = client.get("/api/v1/languages", headers={"X-Request-ID": "trace-abc_123"})
        assert response.headers["x-request-id"] == "trace-abc_123"

    @pytest.mark.parametrize("unsafe", ["a" * 65, "has space", "inject\r\nX-Evil: 1", "<script>"])
    def test_an_unsafe_caller_id_is_replaced(self, unsafe: str) -> None:
        replaced = request_id_from(unsafe)
        assert replaced != unsafe and len(replaced) == 32

    def test_errors_carry_one_too(self, client: TestClient) -> None:
        assert "x-request-id" in client.get("/api/v1/no-such-route").headers

    def test_log_records_get_the_current_id(self) -> None:
        record = logging.LogRecord("t", logging.INFO, "", 0, "hello", None, None)
        token = set_request_id("req-1")
        try:
            RequestIdFilter().filter(record)
        finally:
            reset_request_id(token)
        assert record.request_id == "req-1"  # type: ignore[attr-defined]
        outside = logging.LogRecord("t", logging.INFO, "", 0, "hello", None, None)
        RequestIdFilter().filter(outside)
        assert outside.request_id == "-"  # type: ignore[attr-defined]


class TestJsonLogs:
    def _line(self, message: str, **extra: object) -> dict:
        record = logging.LogRecord("bhashabench.x", logging.WARNING, "", 0, message, None, None)
        record.__dict__.update(extra)
        record.request_id = "req-9"  # type: ignore[attr-defined]
        return json.loads(JsonFormatter().format(record))

    def test_one_object_with_the_standard_fields_and_extras(self) -> None:
        line = self._line("run finished", run_id="r1", status="completed")
        assert line["level"] == "WARNING" and line["logger"] == "bhashabench.x"
        assert line["request_id"] == "req-9"
        assert (line["run_id"], line["status"]) == ("r1", "completed")
        assert line["ts"].endswith("+00:00")

    def test_credentials_are_redacted_in_message_and_extras(self) -> None:
        line = self._line(
            "auth failed token=bbs_AbCdEf0123456789-_xyz", detail="password=hunter2hunter2"
        )
        assert "bbs_AbCdEf" not in json.dumps(line) and "hunter2" not in json.dumps(line)

    def test_configure_never_removes_another_handler(self) -> None:
        root = logging.getLogger()
        foreign = logging.NullHandler()
        root.addHandler(foreign)
        try:
            configure(json_format=True, level=logging.INFO)
            configure(json_format=False, level=logging.INFO)
            ours = [h for h in root.handlers if getattr(h, "_bhashabench", False)]
            assert foreign in root.handlers and len(ours) == 1
        finally:
            root.removeHandler(foreign)

    def test_the_setting_accepts_only_text_or_json(self) -> None:
        with pytest.raises(ValueError):
            Settings(log_format="xml", _env_file=None)
