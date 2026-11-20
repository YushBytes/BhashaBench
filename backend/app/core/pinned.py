"""Connect to the address that was checked, and to nothing else.

`app/core/outbound.py` decides whether a URL may be contacted, and resolves
its host to do so. Before this module existed the clients then resolved the
host *again* when they connected, so a hostile DNS server could answer the
check with a public address and the connect with `127.0.0.1` or the metadata
service (DNS rebinding). This module closes that window: the addresses
`check_url` established are handed to the transport, and the transport
connects to one of them by IP. No second resolution happens.

Two clients, two mechanisms:

- **HTTP** (`httpx2`): `PinnedNetworkBackend` replaces the connection pool's
  network backend. `connect_tcp` is told the URL's host; it refuses any host
  or port it was not pinned to, and otherwise connects to a pinned address.
  TLS still verifies the certificate against the *hostname*, because the
  pool takes the SNI name from the request's origin, not from the socket.
- **WebSocket** (`websockets`): `open_pinned_socket` returns a TCP socket
  already connected to a pinned address, passed as `sock=`. The library then
  performs TLS with `server_hostname` set from the URI and sends the URI's
  `Host`, and it skips proxy discovery when handed a socket.

Both clients are built with **environment proxies disabled**. A proxy taken
from `HTTPS_PROXY` would make the proxy resolve the host, which is the
second resolution this module exists to remove.
"""

from __future__ import annotations

import asyncio
import socket
import typing

import httpcore2
import httpx2
from httpx2._config import create_ssl_context

from app.core.outbound import OutboundTarget, OutboundTargetRefusedError


class PinnedNetworkBackend(httpcore2.AsyncNetworkBackend):
    """An httpcore network backend that dials only pinned addresses."""

    def __init__(
        self, target: OutboundTarget, *, inner: httpcore2.AsyncNetworkBackend | None = None
    ) -> None:
        self._target = target
        self._inner = inner or httpcore2.AnyIOBackend()
        self.dialled: list[str] = []
        """Every address a connection was attempted to, in order. Evidence for tests."""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - the httpcore interface
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        if host.lower().rstrip(".").strip("[]") != self._target.host.strip("[]") or (
            port != self._target.port
        ):
            raise OutboundTargetRefusedError(
                f"a connection to {host}:{port} was attempted, but only "
                f"{self._target.host}:{self._target.port} was checked"
            )
        last: Exception | None = None
        for address in self._target.addresses:
            self.dialled.append(address)
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                last = exc
        assert last is not None  # addresses is never empty: check_url refuses that
        raise last

    async def connect_unix_socket(self, *args: typing.Any, **kwargs: typing.Any) -> typing.NoReturn:
        raise OutboundTargetRefusedError("unix sockets are never an outbound destination")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PinnedAsyncTransport(httpx2.AsyncHTTPTransport):
    """`httpx2.AsyncHTTPTransport` whose pool dials only `target`'s addresses.

    The parent builds the request and maps errors; only the pool is
    replaced, so behaviour other than *where the socket goes* is unchanged.
    Keep-alive is off, matching the adapters, so no pooled connection can
    outlive the event loop that opened it.
    """

    def __init__(self, target: OutboundTarget) -> None:
        super().__init__(trust_env=False, limits=httpx2.Limits(max_keepalive_connections=0))
        self.backend = PinnedNetworkBackend(target)
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=create_ssl_context(verify=True, trust_env=False),
            max_keepalive_connections=0,
            network_backend=self.backend,
        )


def pinned_client(target: OutboundTarget, *, timeout_seconds: float) -> httpx2.AsyncClient:
    """An `AsyncClient` for one checked target: pinned, no redirects, no env proxies."""
    return httpx2.AsyncClient(
        transport=PinnedAsyncTransport(target),
        follow_redirects=False,
        trust_env=False,
        timeout=timeout_seconds,
    )


async def open_pinned_socket(target: OutboundTarget, *, timeout_seconds: float) -> socket.socket:
    """A non-blocking TCP socket connected to one of `target`'s addresses.

    Tries each pinned address in order and raises the last `OSError` if none
    accepts. Never resolves a name: every address here is an IP literal.
    """
    loop = asyncio.get_running_loop()
    last: OSError | None = None
    for address in target.addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            async with asyncio.timeout(timeout_seconds):
                await loop.sock_connect(sock, (address.split("%", 1)[0], target.port))
        except (OSError, TimeoutError) as exc:
            sock.close()
            last = exc if isinstance(exc, OSError) else OSError(f"connect to {address} timed out")
            continue
        return sock
    assert last is not None
    raise last


__all__ = ["PinnedAsyncTransport", "PinnedNetworkBackend", "open_pinned_socket", "pinned_client"]
