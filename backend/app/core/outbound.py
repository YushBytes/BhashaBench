"""Where this process may send a request it was told to send.

Every outbound request whose destination comes from configuration an operator
controls - an external bot's base URL today, a webhook target later - passes
through here first. A request to a vendor whose base URL is a cited constant
(Prisma, Timbre, Sarvam) does not need it; one to a URL someone typed does.

The threat is server-side request forgery: a configured URL that points at
something the server can reach and the operator should not, such as the cloud
metadata service, the database, or another service on the private network.
Four controls, in order, each sufficient to refuse:

1. **Shape.** `http` or `https` only; no userinfo (`https://user:pass@host`
   smuggles a credential and confuses naive parsers); no fragment.
2. **Allowlist.** The host must be named in the policy, exactly or by a
   `*.suffix` wildcard. Nothing is allowed by default.
3. **Address.** The host is resolved, and **every** address it resolves to
   must be publicly routable. Loopback and private ranges are refused unless
   the policy opts in, which only development and tests do. Link-local,
   multicast, reserved, unspecified and the metadata addresses are refused
   always - there is no flag for them, because no legitimate bot lives there.
4. **Transport.** Plain `http` is accepted only for a loopback target, or a
   private one when the policy sets `allow_plain_private` (development only;
   the settings refuse it when deployed). A bearer token sent in clear over a
   network is a credential published.

Redirects are not followed by the clients that use this module (`httpx` with
`follow_redirects=False`; the WebSocket adapter overrides `websockets`'
redirect handling), so a permitted host cannot bounce a request to a
forbidden one.

**Residual risk, stated:** resolution happens immediately before each request,
not inside the socket connect, so a hostile DNS server could answer
differently between the check and the connect (rebinding). The allowlist is
the primary control for that reason: an operator who allowlists a host is
trusting its DNS. Pinning the resolved address into the transport would close
the gap and is recorded in `docs/SECURITY.md` as future work.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

ALWAYS_FORBIDDEN: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("169.254.0.0/16"),  # link-local, incl. 169.254.169.254
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS metadata over IPv6
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("0.0.0.0/8"),  # "this network"
)
"""Refused whatever the policy says. No bot under test lives at these."""

Resolver = Callable[[str, int], Iterable[str]]
"""Host and port in, address strings out. Injected so tests need no DNS."""


class OutboundTargetRefusedError(ValueError):
    """The destination is not one this process may contact.

    The message names the rule that refused it and never echoes a credential:
    userinfo is detected and reported, not quoted.
    """


@dataclass(frozen=True, slots=True)
class OutboundPolicy:
    """What a family of outbound requests may reach."""

    allowed_hosts: frozenset[str]
    """Lower-case hostnames or IP literals, or `*.example.com` for any
    subdomain of example.com (not example.com itself). Empty refuses all."""
    allow_loopback: bool = False
    """Development and tests only: lets a localhost reference bot be reached."""
    allow_private: bool = False
    """RFC 1918 and unique-local IPv6. For a bot on the operator's own LAN."""
    allow_plain_private: bool = False
    """Development only: accept plain http/ws to a private address as well as
    loopback, for a bot on a local container network. Never widens which
    addresses are reachable - `allow_private` still decides that."""

    @classmethod
    def from_setting(
        cls,
        hosts: str,
        *,
        allow_loopback: bool = False,
        allow_private: bool = False,
        allow_plain_private: bool = False,
    ) -> OutboundPolicy:
        """Build from a comma-separated setting such as `BOT_HTTP_ALLOWED_HOSTS`."""
        names = frozenset(h.strip().lower().rstrip(".") for h in hosts.split(",") if h.strip())
        return cls(
            names,
            allow_loopback=allow_loopback,
            allow_private=allow_private,
            allow_plain_private=allow_plain_private,
        )

    def host_is_listed(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        for entry in self.allowed_hosts:
            if entry.startswith("*."):
                if host.endswith(entry[1:]) and host != entry[2:]:
                    return True
            elif host == entry:
                return True
        return False


@dataclass(frozen=True, slots=True)
class OutboundTarget:
    """A URL that passed every check, with what the checks established."""

    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


def _default_resolver(host: str, port: int) -> Iterable[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _normalise(address: str) -> IpAddress:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) is the IPv4 address; judge
    # it as such or it walks past every IPv4 rule.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def classify(address: str, policy: OutboundPolicy) -> str | None:
    """Why `address` is refused under `policy`, or `None` if it is allowed."""
    ip = _normalise(address)
    if any(ip in net for net in ALWAYS_FORBIDDEN if net.version == ip.version):
        return f"{ip} is a link-local or cloud-metadata address"
    # Loopback before "reserved": Python files ::1 under the reserved ::/8
    # block, so the other order refuses IPv6 localhost even when allowed.
    if ip.is_loopback:
        return None if policy.allow_loopback else f"{ip} is a loopback address"
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return f"{ip} is not a unicast destination"
    if ip.is_private:
        return None if policy.allow_private else f"{ip} is a private-network address"
    if not ip.is_global:
        return f"{ip} is not publicly routable"
    return None


def check_url(
    url: str, policy: OutboundPolicy, *, resolver: Resolver = _default_resolver
) -> OutboundTarget:
    """Validate `url` against `policy`, resolving its host.

    Raises:
        OutboundTargetRefusedError: any rule refused it.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise OutboundTargetRefusedError(f"the URL is malformed: {exc}") from exc
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise OutboundTargetRefusedError(f"scheme '{scheme or '(none)'}' is not http or https")
    if parts.username is not None or parts.password is not None:
        raise OutboundTargetRefusedError(
            "the URL carries userinfo; credentials belong in a header setting, not the URL"
        )
    if parts.fragment:
        raise OutboundTargetRefusedError("the URL has a fragment")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise OutboundTargetRefusedError("the URL has no host")
    if not policy.host_is_listed(host):
        raise OutboundTargetRefusedError(
            f"host '{host}' is not in the allowlist; add it to the allowed-hosts setting "
            "deliberately if it is the system under test"
        )
    effective_port = port or (443 if scheme == "https" else 80)

    try:
        addresses = tuple(dict.fromkeys(resolver(host, effective_port)))
    except OSError as exc:
        raise OutboundTargetRefusedError(f"host '{host}' did not resolve") from exc
    if not addresses:
        raise OutboundTargetRefusedError(f"host '{host}' resolved to no address")

    plain_ok = True
    for address in addresses:
        reason = classify(address, policy)
        if reason is not None:
            raise OutboundTargetRefusedError(
                f"host '{host}' resolves to a refused address: {reason}"
            )
        ip = _normalise(address)
        plain_ok = plain_ok and (ip.is_loopback or (policy.allow_plain_private and ip.is_private))

    if scheme == "http" and not plain_ok:
        raise OutboundTargetRefusedError(
            "plain http is accepted only for a loopback target (or a private one with "
            "BOT_HTTP_ALLOW_PLAIN_PRIVATE in development); use https so the "
            "credential is not sent in clear"
        )
    return OutboundTarget(
        url=url.strip(), scheme=scheme, host=host, port=effective_port, addresses=addresses
    )


__all__ = [
    "ALWAYS_FORBIDDEN",
    "OutboundPolicy",
    "OutboundTarget",
    "OutboundTargetRefusedError",
    "check_url",
    "classify",
]
