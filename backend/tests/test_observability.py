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


class TestMetrics:
    TOKEN = "metrics-token-for-tests-0123456789"

    def _client(self, settings: Settings, token: str = "") -> TestClient:
        from pydantic import SecretStr

        from app.core.config import get_settings
        from app.main import create_app
        from tests.conftest import authenticate_without_database

        configured = settings.model_copy(update={"metrics_token": SecretStr(token)})
        app = create_app(settings=configured)
        app.dependency_overrides[get_settings] = lambda: configured
        authenticate_without_database(app)
        return TestClient(app)

    def test_off_unless_a_token_is_set(self, settings: Settings) -> None:
        with self._client(settings) as client:
            assert client.get("/metrics").status_code == 404

    def test_the_token_is_required(self, settings: Settings) -> None:
        with self._client(settings, self.TOKEN) as client:
            assert client.get("/metrics").status_code == 401
            wrong = client.get("/metrics", headers={"Authorization": "Bearer nope"})
            assert wrong.status_code == 401

    def test_requests_are_counted_by_method_and_status_class(self, settings: Settings) -> None:
        with self._client(settings, self.TOKEN) as client:
            client.get("/health")
            client.get("/api/v1/no-such-route")
            body = client.get("/metrics", headers={"Authorization": f"Bearer {self.TOKEN}"}).text
        assert 'bhashabench_http_requests_total{method="GET",status_class="2xx"}' in body
        assert 'bhashabench_http_requests_total{method="GET",status_class="4xx"}' in body
        assert "bhashabench_http_request_seconds_count" in body
        assert "bhashabench_rate_limited_total 0" in body

    def test_the_render_is_valid_prometheus_text(self) -> None:
        from app.core.metrics import Metrics

        metrics = Metrics()
        metrics.observe("POST", 429, 0.01)
        text = metrics.render({"completed": 3, "failed": 1})
        assert 'bhashabench_test_runs{status="completed"} 3' in text
        assert "bhashabench_rate_limited_total 1" in text
        for line in text.strip().splitlines():
            assert line.startswith("#") or " " in line
