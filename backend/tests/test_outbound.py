"""The outbound-request guard: shape, allowlist, address and transport rules."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.core.outbound import OutboundPolicy, OutboundTargetRefusedError, check_url, classify


def _resolver(mapping: dict[str, list[str]]) -> Callable[[str, int], list[str]]:
    def resolve(host: str, port: int) -> list[str]:
        if host not in mapping:
            raise OSError("no such host")
        return mapping[host]

    return resolve


PUBLIC = _resolver({"bot.example.com": ["93.184.216.34"]})
POLICY = OutboundPolicy.from_setting("bot.example.com")


class TestShape:
    @pytest.mark.parametrize(
        "url",
        [
            "ftp://bot.example.com/",
            "file:///etc/passwd",
            "gopher://bot.example.com/",
            "bot.example.com/path",
            "javascript:alert(1)",
        ],
    )
    def test_only_http_and_https_are_accepted(self, url: str) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="scheme"):
            check_url(url, POLICY, resolver=PUBLIC)

    def test_userinfo_is_refused_without_echoing_it(self) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="userinfo") as excinfo:
            check_url("https://admin:hunter2@bot.example.com/", POLICY, resolver=PUBLIC)
        assert "hunter2" not in str(excinfo.value)

    def test_a_fragment_is_refused(self) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="fragment"):
            check_url("https://bot.example.com/#x", POLICY, resolver=PUBLIC)

    def test_a_malformed_port_is_refused(self) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="malformed"):
            check_url("https://bot.example.com:99999/", POLICY, resolver=PUBLIC)

    def test_a_public_allowlisted_https_url_passes(self) -> None:
        target = check_url("https://bot.example.com/v1", POLICY, resolver=PUBLIC)
        assert (target.host, target.port, target.addresses) == (
            "bot.example.com",
            443,
            ("93.184.216.34",),
        )


class TestAllowlist:
    def test_an_empty_allowlist_refuses_everything(self) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="allowlist"):
            check_url("https://bot.example.com/", OutboundPolicy(frozenset()), resolver=PUBLIC)

    def test_an_unlisted_host_is_refused_before_it_is_resolved(self) -> None:
        def boom(host: str, port: int) -> list[str]:
            raise AssertionError("resolution must not happen for an unlisted host")

        with pytest.raises(OutboundTargetRefusedError, match="allowlist"):
            check_url("https://evil.example.org/", POLICY, resolver=boom)

    def test_a_wildcard_matches_subdomains_but_not_the_apex(self) -> None:
        policy = OutboundPolicy.from_setting("*.example.com")
        resolver = _resolver({"a.example.com": ["93.184.216.34"], "example.com": ["93.184.216.34"]})
        check_url("https://a.example.com/", policy, resolver=resolver)
        with pytest.raises(OutboundTargetRefusedError, match="allowlist"):
            check_url("https://example.com/", policy, resolver=resolver)

    def test_a_suffix_lookalike_does_not_match(self) -> None:
        policy = OutboundPolicy.from_setting("*.example.com")
        with pytest.raises(OutboundTargetRefusedError, match="allowlist"):
            check_url("https://evilexample.com/", policy, resolver=PUBLIC)

    def test_host_matching_ignores_case_and_a_trailing_dot(self) -> None:
        check_url("https://BOT.Example.COM./", POLICY, resolver=PUBLIC)

    def test_an_unresolvable_host_is_refused(self) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="did not resolve"):
            check_url("https://bot.example.com/", POLICY, resolver=_resolver({}))


class TestAddresses:
    @pytest.mark.parametrize(
        "address",
        [
            "169.254.169.254",  # AWS/GCP/Azure metadata
            "100.100.100.200",  # Alibaba metadata
            "fd00:ec2::254",  # AWS metadata, IPv6
            "fe80::1",
            "0.0.0.0",
            "224.0.0.1",
            "240.0.0.1",
        ],
    )
    def test_metadata_link_local_and_non_unicast_are_refused_even_when_permissive(
        self, address: str
    ) -> None:
        permissive = OutboundPolicy(frozenset(), allow_loopback=True, allow_private=True)
        assert classify(address, permissive) is not None

    @pytest.mark.parametrize("address", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
    def test_loopback_needs_the_opt_in(self, address: str) -> None:
        assert classify(address, POLICY) is not None
        assert classify(address, OutboundPolicy(frozenset(), allow_loopback=True)) is None

    @pytest.mark.parametrize("address", ["10.0.0.5", "172.16.3.4", "192.168.1.1", "fd12::1"])
    def test_private_ranges_need_the_opt_in(self, address: str) -> None:
        assert classify(address, POLICY) is not None
        assert classify(address, OutboundPolicy(frozenset(), allow_private=True)) is None

    def test_carrier_grade_nat_is_refused(self) -> None:
        assert classify("100.64.0.1", OutboundPolicy(frozenset(), allow_private=True)) is not None

    def test_a_listed_name_that_resolves_to_metadata_is_refused(self) -> None:
        """DNS that points an allowlisted name at the metadata service."""
        resolver = _resolver({"bot.example.com": ["93.184.216.34", "169.254.169.254"]})
        with pytest.raises(OutboundTargetRefusedError, match="metadata"):
            check_url("https://bot.example.com/", POLICY, resolver=resolver)

    def test_a_decimal_ip_literal_is_judged_by_what_it_resolves_to(self) -> None:
        policy = OutboundPolicy.from_setting("2130706433")
        with pytest.raises(OutboundTargetRefusedError, match="loopback"):
            check_url(
                "http://2130706433/", policy, resolver=_resolver({"2130706433": ["127.0.0.1"]})
            )


class TestTransport:
    def test_http_to_a_public_host_is_refused(self) -> None:
        with pytest.raises(OutboundTargetRefusedError, match="plain http"):
            check_url("http://bot.example.com/", POLICY, resolver=PUBLIC)

    def test_http_to_loopback_is_allowed_when_loopback_is(self) -> None:
        policy = OutboundPolicy.from_setting("localhost", allow_loopback=True)
        target = check_url(
            "http://localhost:8099/", policy, resolver=_resolver({"localhost": ["127.0.0.1"]})
        )
        assert target.port == 8099

    def test_http_to_a_private_host_is_refused(self) -> None:
        policy = OutboundPolicy.from_setting("lan-bot", allow_private=True)
        with pytest.raises(OutboundTargetRefusedError, match="plain http"):
            check_url("http://lan-bot/", policy, resolver=_resolver({"lan-bot": ["10.1.2.3"]}))

    def test_the_real_resolver_handles_localhost(self) -> None:
        policy = OutboundPolicy.from_setting("localhost", allow_loopback=True)
        target = check_url("http://localhost:1/", policy)
        assert target.addresses
