"""The HTTP text bot adapter, over real localhost sockets.

Two servers: the reference bot for the protocol's happy paths, and a small
fault-injecting ASGI app for everything a real bot can get wrong. Each test
drives its own `asyncio.run` with its own adapter, and the adapter disables
keep-alive, so no pooled connection outlives the loop that opened it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.outbound import OutboundPolicy
from app.pipeline.bots.http_text import MAX_BODY_BYTES, HttpBotConfig, HttpTextBotAdapter
from app.pipeline.errors import (
    BotAuthenticationError,
    BotProtocolError,
    BotTargetRefusedError,
    BotTimeoutError,
    BotUnavailableError,
)
from reference_bot.app import BotConfig, create_app
from tests.socket_server import serve, unused_port

TOKEN = "http-adapter-test-token-0123456789"
LOOPBACK = OutboundPolicy.from_setting("127.0.0.1,localhost", allow_loopback=True)
RUN = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _adapter(base_url: str, *, token: str = TOKEN, **overrides: Any) -> HttpTextBotAdapter:
    config = HttpBotConfig(
        base_url=base_url,
        token=SecretStr(token),
        policy=overrides.pop("policy", LOOPBACK),
        timeout_seconds=overrides.pop("timeout_seconds", 5.0),
        max_attempts=overrides.pop("max_attempts", 2),
        backoff_seconds=0.0,
    )
    return HttpTextBotAdapter(config, **overrides)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


class FaultBot:
    """An ASGI app whose behaviour per path is set by the test."""

    def __init__(self) -> None:
        self.behaviour: dict[str, list[dict[str, Any]]] = {}
        self.seen: list[dict[str, Any]] = []

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        self.seen.append(
            {
                "path": scope["path"],
                "raw_path": scope.get("raw_path"),
                "headers": headers,
                "body": body,
            }
        )
        steps = self.behaviour.get(scope["path"], [])
        step = steps.pop(0) if len(steps) > 1 else (steps[0] if steps else {"status": 404})
        if step.get("delay"):
            await asyncio.sleep(step["delay"])
        raw = step.get("raw")
        if raw is None:
            raw = json.dumps(step.get("json", {})).encode()
        out_headers = [(b"content-type", b"application/json")]
        out_headers += [(k.encode(), v.encode()) for k, v in step.get("headers", {}).items()]
        await send(
            {"type": "http.response.start", "status": step["status"], "headers": out_headers}
        )
        await send({"type": "http.response.body", "body": raw})


@pytest.fixture
def fault() -> Iterator[tuple[FaultBot, str]]:
    app = FaultBot()
    with serve(app) as url:
        yield app, url


SESSION_OK = {"status": 201, "json": {"session_id": "s1", "greeting": None}}


class TestAgainstTheReferenceBot:
    def test_a_whole_conversation(self, bot_url: str) -> None:
        async def go() -> list[Any]:
            adapter = _adapter(bot_url)
            try:
                session = await adapter.open_session(run_id=RUN, language="en-IN")
                first = await adapter.send_text(
                    "Hello, I am calling about my request",
                    session_id=session.session_id,
                    run_id=RUN,
                    turn_index=0,
                )
                second = await adapter.send_text(
                    "It is 447219", session_id=session.session_id, run_id=RUN, turn_index=1
                )
                third = await adapter.send_text(
                    "Thank you", session_id=session.session_id, run_id=RUN, turn_index=2
                )
                await adapter.close_session(session_id=session.session_id, run_id=RUN)
                return [session, first, second, third]
            finally:
                await adapter.close()

        session, first, second, third = _run(go())
        assert session.greeting is None
        assert "reference number" in first.text
        assert "447219" in second.text
        assert third.end_session is True
        assert all(r.received_from_bot for r in (first, second, third))
        assert all(r.latency_ms > 0 for r in (first, second, third))
        assert first.correlation_id == f"{RUN}:0"

    def test_a_wrong_token_is_an_authentication_failure_that_does_not_echo_it(
        self, bot_url: str
    ) -> None:
        wrong = "not-the-token-but-long-enough-00"

        async def go() -> None:
            adapter = _adapter(bot_url, token=wrong)
            try:
                await adapter.open_session(run_id=RUN, language="en-IN")
            finally:
                await adapter.close()

        with pytest.raises(BotAuthenticationError, match="401") as caught:
            _run(go())
        assert wrong not in str(caught.value)
        assert TOKEN not in str(caught.value)

    def test_concurrent_sessions_stay_separate(self, bot_url: str) -> None:
        async def one(i: int) -> tuple[str, str]:
            adapter = _adapter(bot_url)
            try:
                session = await adapter.open_session(run_id=RUN, language="en-IN")
                reply = await adapter.send_text(
                    f"My number is {10000 + i}",
                    session_id=session.session_id,
                    run_id=RUN,
                    turn_index=0,
                )
                return session.session_id, reply.text
            finally:
                await adapter.close()

        async def go() -> list[tuple[str, str]]:
            return await asyncio.gather(*(one(i) for i in range(12)))

        results = _run(go())
        assert len({sid for sid, _ in results}) == 12
        for i, (_, text) in enumerate(results):
            assert str(10000 + i) in text

    def test_an_empty_token_is_refused_before_any_request(self, bot_url: str) -> None:
        with pytest.raises(BotAuthenticationError, match="BOT_HTTP_TOKEN"):
            _adapter(bot_url, token="")


class TestFaults:
    def test_the_request_carries_auth_correlation_and_idempotency(
        self, fault: tuple[FaultBot, str]
    ) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [{"status": 200, "json": {"text": "ok"}}]

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=3)
            finally:
                await adapter.close()

        _run(go())
        headers = app.seen[-1]["headers"]
        assert headers["authorization"] == f"Bearer {TOKEN}"
        assert headers["x-correlation-id"] == f"{RUN}:3"
        assert headers["idempotency-key"] == f"{RUN}:3"
        assert json.loads(app.seen[-1]["body"]) == {"text": "hi", "turn_index": 3}

    def test_a_transient_503_is_retried_with_the_same_key(
        self, fault: tuple[FaultBot, str]
    ) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [
            {"status": 503, "json": {}},
            {"status": 200, "json": {"text": "recovered"}},
        ]

        async def go() -> Any:
            adapter = _adapter(url)
            try:
                return await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        reply = _run(go())
        assert (reply.text, reply.attempts) == ("recovered", 2)
        keys = [s["headers"]["idempotency-key"] for s in app.seen]
        assert keys == [f"{RUN}:0", f"{RUN}:0"]

    def test_retries_are_bounded(self, fault: tuple[FaultBot, str]) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [{"status": 503, "json": {}}]

        async def go() -> None:
            adapter = _adapter(url, max_attempts=3)
            try:
                await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        with pytest.raises(BotUnavailableError, match="503"):
            _run(go())
        assert len(app.seen) == 3

    def test_session_creation_is_not_retried_on_a_status(self, fault: tuple[FaultBot, str]) -> None:
        """No idempotency key, so a retry could open a second session."""
        app, url = fault
        app.behaviour["/v1/sessions"] = [{"status": 503, "json": {}}]

        async def go() -> None:
            adapter = _adapter(url, max_attempts=3)
            try:
                await adapter.open_session(run_id=RUN, language="en-IN")
            finally:
                await adapter.close()

        with pytest.raises(BotUnavailableError):
            _run(go())
        assert len(app.seen) == 1

    @pytest.mark.parametrize(
        "step",
        [
            {"status": 200, "raw": b"not json"},
            {"status": 200, "json": {"reply": "wrong field"}},
            {"status": 200, "json": {"text": 42}},
            {"status": 200, "json": {"text": "ok", "end_session": "yes"}},
            {"status": 200, "json": {"text": "x" * 4001}},
            {"status": 200, "raw": b"[1, 2, 3]"},
        ],
    )
    def test_a_malformed_reply_is_a_protocol_error(
        self, fault: tuple[FaultBot, str], step: dict[str, Any]
    ) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [step]

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        with pytest.raises(BotProtocolError):
            _run(go())

    def test_an_empty_reply_is_valid_and_is_the_bot_saying_nothing(
        self, fault: tuple[FaultBot, str]
    ) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [{"status": 200, "json": {"text": ""}}]

        async def go() -> Any:
            adapter = _adapter(url)
            try:
                return await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        assert _run(go()).text == ""

    def test_a_server_error_is_reported_with_the_bots_redacted_message(
        self, fault: tuple[FaultBot, str]
    ) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [
            {
                "status": 500,
                "json": {"error": {"code": "boom", "message": "db down api_key=supersecret123"}},
            }
        ]

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        with pytest.raises(BotUnavailableError, match="500") as caught:
            _run(go())
        assert "boom" in str(caught.value)
        assert "supersecret123" not in str(caught.value)
        assert len(app.seen) == 1, "a plain 500 is not retried"

    def test_a_slow_bot_times_out(self, fault: tuple[FaultBot, str]) -> None:
        app, url = fault
        app.behaviour["/v1/sessions/s1/turns"] = [
            {"status": 200, "json": {"text": "late"}, "delay": 2.0}
        ]

        async def go() -> None:
            adapter = _adapter(url, timeout_seconds=0.3)
            try:
                await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        with pytest.raises(BotTimeoutError, match=r"0\.3s"):
            _run(go())

    def test_a_redirect_is_not_followed(self, fault: tuple[FaultBot, str]) -> None:
        app, url = fault
        app.behaviour["/v1/sessions"] = [
            {"status": 307, "json": {}, "headers": {"location": "http://169.254.169.254/latest"}}
        ]

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.open_session(run_id=RUN, language="en-IN")
            finally:
                await adapter.close()

        with pytest.raises(BotProtocolError, match="redirect"):
            _run(go())
        assert len(app.seen) == 1

    def test_an_oversized_body_is_refused(self, fault: tuple[FaultBot, str]) -> None:
        app, url = fault
        big = json.dumps({"text": "x" * (MAX_BODY_BYTES + 10)}).encode()
        app.behaviour["/v1/sessions/s1/turns"] = [{"status": 200, "raw": big}]

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.send_text("hi", session_id="s1", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        with pytest.raises(BotProtocolError, match="exceeded"):
            _run(go())

    def test_a_session_id_is_one_path_segment(self, fault: tuple[FaultBot, str]) -> None:
        """A hostile session id cannot walk the bot's URL space."""
        app, url = fault

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.send_text("hi", session_id="../../admin", run_id=RUN, turn_index=0)
            finally:
                await adapter.close()

        # The fault bot has no route for it, so the 404 is a protocol error.
        with pytest.raises(BotProtocolError, match="404"):
            _run(go())
        assert app.seen[-1]["raw_path"] == b"/v1/sessions/..%2F..%2Fadmin/turns"


class TestDestination:
    def test_an_unreachable_host_is_unavailable_after_bounded_retries(self) -> None:
        url = f"http://127.0.0.1:{unused_port()}"

        async def go() -> None:
            adapter = _adapter(url, max_attempts=2)
            try:
                await adapter.open_session(run_id=RUN, language="en-IN")
            finally:
                await adapter.close()

        with pytest.raises(BotUnavailableError, match="could not connect"):
            _run(go())

    def test_a_host_outside_the_allowlist_is_refused_at_construction(self) -> None:
        with pytest.raises(BotTargetRefusedError, match="allowlist"):
            _adapter("https://bot.example.com", policy=OutboundPolicy(frozenset()))

    def test_loopback_without_the_opt_in_is_refused(self, bot_url: str) -> None:
        with pytest.raises(BotTargetRefusedError, match="loopback"):
            _adapter(bot_url, policy=OutboundPolicy.from_setting("127.0.0.1"))

    @pytest.mark.parametrize(
        "url",
        ["http://169.254.169.254/", "http://[::ffff:169.254.169.254]/", "file:///etc/passwd"],
    )
    def test_ssrf_targets_are_refused(self, url: str) -> None:
        permissive = OutboundPolicy.from_setting(
            "169.254.169.254,::ffff:169.254.169.254", allow_loopback=True, allow_private=True
        )
        with pytest.raises(BotTargetRefusedError):
            _adapter(url, policy=permissive)

    def test_a_name_that_rebinds_to_metadata_is_refused_before_the_request(self) -> None:
        answers = iter([["93.184.216.34"], ["169.254.169.254"]])
        policy = OutboundPolicy.from_setting("bot.example.com")
        adapter = _adapter(
            "https://bot.example.com", policy=policy, resolver=lambda h, p: next(answers)
        )

        async def go() -> None:
            try:
                await adapter.open_session(run_id=RUN, language="en-IN")
            finally:
                await adapter.close()

        with pytest.raises(BotTargetRefusedError, match="metadata"):
            _run(go())

    def test_the_adapter_refuses_audio(self, bot_url: str) -> None:
        async def go() -> None:
            adapter = _adapter(bot_url)
            try:
                await adapter.send_turn(b"RIFF")
            finally:
                await adapter.close()

        with pytest.raises(BotProtocolError, match="text only"):
            _run(go())

    def test_capabilities_say_text_only_and_external(self, bot_url: str) -> None:
        adapter = _adapter(bot_url)
        _run(adapter.close())
        caps = adapter.capabilities
        assert caps.contacts_external_system is True
        assert caps.requires_credentials is True
        assert caps.accepts_containers == frozenset()


class TestCredentialHygiene:
    def test_the_token_never_appears_in_logs_or_errors(
        self, fault: tuple[FaultBot, str], caplog: pytest.LogCaptureFixture
    ) -> None:
        app, url = fault
        app.behaviour["/v1/sessions"] = [{"status": 403, "json": {}}]
        caplog.set_level(logging.DEBUG)

        async def go() -> None:
            adapter = _adapter(url)
            try:
                await adapter.open_session(run_id=RUN, language="en-IN")
            finally:
                await adapter.close()

        with pytest.raises(BotAuthenticationError) as caught:
            _run(go())
        assert TOKEN not in str(caught.value)
        assert TOKEN not in repr(caught.value)
        assert TOKEN not in caplog.text

    def test_the_config_does_not_reveal_the_token(self) -> None:
        config = HttpBotConfig(
            base_url="http://127.0.0.1:1", token=SecretStr(TOKEN), policy=LOOPBACK
        )
        assert TOKEN not in repr(config)
