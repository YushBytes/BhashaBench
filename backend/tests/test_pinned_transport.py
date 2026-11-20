"""DNS rebinding: the socket goes to the address that was checked.

The decisive tests use a hostname that does not exist in real DNS
(`*.rebind.test`, a reserved TLD). The fake resolver maps it to 127.0.0.1. If
a client resolved the name again when connecting, as both did before
`app/core/pinned.py`, the connection would fail on a name lookup; it
succeeds only because the socket is opened to the pinned address.

A resolver that answers loopback at construction and the metadata address at
request time shows the other half: each request is checked afresh, and the
address it connects to is the one that request's check approved.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator

import httpcore2
import pytest
from pydantic import SecretStr

from app.core.outbound import OutboundPolicy, OutboundTarget, OutboundTargetRefusedError
from app.core.pinned import PinnedNetworkBackend, open_pinned_socket
from app.pipeline.bots.http_text import HttpBotConfig, HttpTextBotAdapter
from app.pipeline.bots.ws_voice import connect_pinned
from app.pipeline.errors import BotTargetRefusedError
from reference_bot.app import BotConfig, create_app
from tests.socket_server import serve

TOKEN = "pinned-transport-test-token-0123456789"
RUN = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


@pytest.fixture(scope="module")
def bot_url() -> Iterator[str]:
    with serve(create_app(BotConfig(token=TOKEN))) as url:
        yield url


def _port(url: str) -> int:
    return int(url.rsplit(":", 1)[1].split("/", 1)[0])


def _policy(host: str) -> OutboundPolicy:
    return OutboundPolicy.from_setting(host, allow_loopback=True)


class TestHttpAdapterIsPinned:
    def test_a_name_unknown_to_real_dns_connects_through_the_pinned_address(
        self, bot_url: str
    ) -> None:
        host = "bot.rebind.test"
        adapter = HttpTextBotAdapter(
            HttpBotConfig(
                base_url=f"http://{host}:{_port(bot_url)}",
                token=SecretStr(TOKEN),
                policy=_policy(host),
                max_attempts=1,
            ),
            # One resolution at construction, then exactly one per request.
            resolver=_sequence(["127.0.0.1", "127.0.0.1"]),
        )
        session = asyncio.run(adapter.open_session(run_id=RUN, language="hi-IN"))
        assert session.session_id

    def test_a_rebinding_answer_at_request_time_is_refused_not_followed(self, bot_url: str) -> None:
        host = "bot.rebind.test"
        resolver = _sequence(["127.0.0.1", "169.254.169.254"])
        adapter = HttpTextBotAdapter(
            HttpBotConfig(
                base_url=f"http://{host}:{_port(bot_url)}",
                token=SecretStr(TOKEN),
                policy=_policy(host),
                max_attempts=1,
            ),
            resolver=resolver,
        )
        with pytest.raises(BotTargetRefusedError, match="metadata"):
            asyncio.run(adapter.open_session(run_id=RUN, language="hi-IN"))

    def test_environment_proxies_are_ignored(
        self, bot_url: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A proxy would resolve the host itself - the second resolution
        # pinning removes. A dead proxy makes any use of it fail loudly.
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        adapter = HttpTextBotAdapter(
            HttpBotConfig(
                base_url=bot_url,
                token=SecretStr(TOKEN),
                policy=_policy("127.0.0.1"),
                max_attempts=1,
            )
        )
        session = asyncio.run(adapter.open_session(run_id=RUN, language="hi-IN"))
        assert session.session_id


class TestPinnedBackend:
    TARGET = OutboundTarget(
        url="https://bot.example.com/", scheme="https", host="bot.example.com",
        port=443, addresses=("93.184.216.34",),
    )  # fmt: skip

    @pytest.mark.parametrize(
        ("host", "port"), [("evil.example.org", 443), ("bot.example.com", 8443), ("127.0.0.1", 443)]
    )
    def test_a_host_or_port_that_was_not_checked_is_refused(self, host: str, port: int) -> None:
        backend = PinnedNetworkBackend(self.TARGET, inner=_NeverConnects())
        with pytest.raises(OutboundTargetRefusedError, match=r"only bot.example.com:443"):
            asyncio.run(backend.connect_tcp(host, port))
        assert backend.dialled == []

    def test_the_checked_host_dials_the_pinned_address_not_the_name(self) -> None:
        inner = _NeverConnects()
        backend = PinnedNetworkBackend(self.TARGET, inner=inner)
        with pytest.raises(httpcore2.ConnectError):
            asyncio.run(backend.connect_tcp("BOT.example.com.", 443))
        assert inner.dialled == ["93.184.216.34"]

    def test_unix_sockets_are_never_a_destination(self) -> None:
        backend = PinnedNetworkBackend(self.TARGET)
        with pytest.raises(OutboundTargetRefusedError):
            asyncio.run(backend.connect_unix_socket("/var/run/docker.sock"))

    def test_every_pinned_address_is_tried_in_order(self) -> None:
        inner = _NeverConnects()
        target = OutboundTarget(
            url="https://bot.example.com/", scheme="https", host="bot.example.com",
            port=443, addresses=("93.184.216.34", "2606:2800:220:1::248"),
        )  # fmt: skip
        with pytest.raises(httpcore2.ConnectError):
            asyncio.run(
                PinnedNetworkBackend(target, inner=inner).connect_tcp("bot.example.com", 443)
            )
        assert inner.dialled == ["93.184.216.34", "2606:2800:220:1::248"]


class TestVoiceAdapterIsPinned:
    def test_a_websocket_to_an_unknown_name_connects_through_the_pinned_address(
        self, bot_url: str
    ) -> None:
        host = "voice.rebind.test"
        url = f"ws://{host}:{_port(bot_url)}/v1/voice"

        async def handshake() -> dict:
            socket = await connect_pinned(
                url,
                _policy(host),
                headers={"Authorization": f"Bearer {TOKEN}"},
                timeout_seconds=5,
                resolver=lambda h, p: ["127.0.0.1"],
            )
            try:
                await socket.send(json.dumps({
                    "type": "start", "protocol": "bhashabench-voice-bot/1", "language": "hi-IN",
                    "sample_rate_hz": 16000, "encoding": "pcm_s16le", "frame_ms": 20,
                    "run_id": str(RUN),
                }))  # fmt: skip
                return json.loads(await socket.recv())
            finally:
                await socket.close()

        assert asyncio.run(handshake())["type"] == "ready"

    @pytest.mark.parametrize("address", ["169.254.169.254", "::ffff:169.254.169.254", "fe80::1"])
    def test_a_refused_address_never_opens_a_socket(self, address: str) -> None:
        with pytest.raises(BotTargetRefusedError):
            asyncio.run(
                connect_pinned(
                    "ws://voice.rebind.test:80/v1/voice",
                    _policy("voice.rebind.test"),
                    headers={},
                    timeout_seconds=2,
                    resolver=lambda h, p: [address],
                )
            )

    def test_a_pinned_socket_connects_only_to_listed_addresses(self, bot_url: str) -> None:
        target = OutboundTarget(
            url=bot_url, scheme="http", host="voice.rebind.test", port=_port(bot_url),
            addresses=("127.0.0.1",),
        )  # fmt: skip

        async def peer() -> tuple[str, int]:
            sock = await open_pinned_socket(target, timeout_seconds=5)
            try:
                return sock.getpeername()[:2]
            finally:
                sock.close()

        assert asyncio.run(peer()) == ("127.0.0.1", _port(bot_url))


def _sequence(answers: list[str]):  # noqa: ANN202 - a test resolver
    calls = iter(answers)

    def resolve(host: str, port: int) -> list[str]:
        return [next(calls)]

    return resolve


class _NeverConnects(httpcore2.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.dialled: list[str] = []

    async def connect_tcp(self, host: str, port: int, **_: object) -> httpcore2.AsyncNetworkStream:
        self.dialled.append(host)
        raise httpcore2.ConnectError(f"refused {host}")

    async def sleep(self, seconds: float) -> None:  # pragma: no cover
        await asyncio.sleep(seconds)
