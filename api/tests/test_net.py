"""Working out who actually connected.

An IP allowlist is only as good as the address it compares against, and behind
a proxy that address comes from a header the client can set. Most of what is
below is attempts to forge one.
"""

from dataclasses import dataclass

import pytest

from app.net import client_ip, in_any, real_client_ip, visitor_ip

#: Matches the shipped default.
TRUSTED = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8"


@dataclass
class FakeClient:
    host: str


class FakeRequest:
    """Enough of a Request to answer both questions this module asks."""

    def __init__(self, peer: str | None, forwarded: str | None = None):
        self.client = FakeClient(peer) if peer else None
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


# ── Containment ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("10.1.2.3", True),
        ("172.16.5.5", True),
        ("192.168.1.1", True),
        ("127.0.0.1", True),
        ("8.8.8.8", False),
        ("172.32.0.1", False),  # just outside 172.16/12
        ("", False),
        (None, False),
        ("not-an-address", False),
    ],
)
def test_containment(address, expected):
    assert in_any(address, TRUSTED) is expected


def test_a_malformed_entry_is_skipped_not_fatal():
    """A typo in one entry must not stop the application booting, and the
    entries that did parse still do their job."""
    assert in_any("10.1.2.3", "nonsense,10.0.0.0/8") is True
    assert in_any("8.8.8.8", "nonsense,10.0.0.0/8") is False


def test_a_bare_address_works_as_a_network():
    assert in_any("203.0.113.7", "203.0.113.7") is True
    assert in_any("203.0.113.8", "203.0.113.7") is False


# ── Looking through a proxy ──────────────────────────────────────────────────
#
# The shape that matters: nginx uses `$proxy_add_x_forwarded_for`, so it
# **appends** the peer it saw. A forged header therefore arrives as
# "<whatever the client wrote>, <the client's real address>" — and the last
# entry is the only part the client could not write.


def through_nginx(real_client: str, forged: str | None = None) -> FakeRequest:
    """A request as the API actually receives it behind nginx."""
    chain = f"{forged}, {real_client}" if forged else real_client
    return FakeRequest(peer="172.21.0.5", forwarded=chain)


def test_behind_a_proxy_the_appended_hop_is_the_client():
    assert real_client_ip(through_nginx("203.0.113.9"), TRUSTED) == "203.0.113.9"


def test_a_forged_hop_is_ignored():
    """The bug this replaced.

    The old version walked right until it found a hop outside the trusted
    ranges. On Docker the real client arrives from a private address too —
    172.21.0.1 is inside 172.16.0.0/12 — so the walk skipped the genuine hop
    as "another proxy" and returned the forged one. A live request with
    `X-Forwarded-For: 203.0.113.9` got a 200.
    """
    request = through_nginx("172.21.0.1", forged="203.0.113.9")
    assert real_client_ip(request, TRUSTED) == "172.21.0.1"


def test_a_client_cannot_prepend_a_whole_fake_chain():
    request = through_nginx("172.21.0.1", forged="203.0.113.9, 198.51.100.4, 10.0.0.1")
    assert real_client_ip(request, TRUSTED) == "172.21.0.1"


def test_a_direct_connection_ignores_the_header_entirely():
    """Anybody can set the header. Believed on a direct connection, an
    allowlist would look like protection and provide none."""
    request = FakeRequest(peer="203.0.113.9", forwarded="10.0.0.5")
    assert real_client_ip(request, TRUSTED) == "203.0.113.9"


def test_two_proxies_count_two_hops():
    """A load balancer in front of nginx: each appends, so the client is two
    places from the end."""
    request = FakeRequest(
        peer="172.21.0.5", forwarded="203.0.113.9, 10.0.0.7"
    )
    assert real_client_ip(request, TRUSTED, proxy_hops=2) == "203.0.113.9"


def test_a_short_chain_falls_back_to_the_peer():
    """Configured for two proxies, only one appeared. The peer is the proxy and
    will not match an office allowlist — failing closed is the right
    direction."""
    request = FakeRequest(peer="172.21.0.5", forwarded="203.0.113.9")
    assert real_client_ip(request, TRUSTED, proxy_hops=2) == "172.21.0.5"


def test_no_header_falls_back_to_the_peer():
    assert real_client_ip(FakeRequest(peer="172.21.0.5"), TRUSTED) == "172.21.0.5"


def test_a_malformed_hop_gives_up_on_the_chain():
    """Garbage makes positions meaningless — we can no longer count backwards
    to a known slot, so nothing in the header is evidence."""
    request = FakeRequest(peer="172.21.0.5", forwarded="203.0.113.9, junk")
    assert real_client_ip(request, TRUSTED) == "172.21.0.5"


def test_no_client_at_all_is_none():
    assert real_client_ip(FakeRequest(peer=None), TRUSTED) is None
    assert real_client_ip(None, TRUSTED) is None


def test_an_empty_trusted_list_trusts_nothing():
    """Turning the setting off must fail closed, not open."""
    request = through_nginx("203.0.113.9")
    assert real_client_ip(request, "") == "172.21.0.5"


# ── The socket peer, and the visitor (P5-1) ──────────────────────────────────


def test_client_ip_is_still_the_socket_peer():
    request = FakeRequest(peer="172.18.0.5", forwarded="203.0.113.9")
    assert client_ip(request) == "172.18.0.5"


def test_the_visitor_behind_nginx_is_the_last_hop():
    """What sign-in limits, sessions and the activity log record now. The
    socket peer was always nginx, which made one limit for everybody."""
    request = FakeRequest(peer="172.18.0.5", forwarded="198.51.100.4, 203.0.113.9")
    assert visitor_ip(request) == "203.0.113.9"


def test_a_visitor_cannot_choose_their_address():
    """Prepending is ignored: only the hop nginx appended is read."""
    assert visitor_ip(FakeRequest(peer="172.18.0.5", forwarded="1.2.3.4, 203.0.113.9")) == "203.0.113.9"


def test_straight_from_the_visitor_is_the_peer():
    assert visitor_ip(FakeRequest(peer="203.0.113.9", forwarded="1.2.3.4")) == "203.0.113.9"


@pytest.mark.parametrize("forwarded", [None, "not-an-address"])
def test_unknown_is_none_not_the_proxy(forwarded):
    """A limit keyed on nginx's address locks everybody out; on none, it is
    skipped and the per-email limit still guards the account."""
    assert visitor_ip(FakeRequest(peer="172.18.0.5", forwarded=forwarded)) is None


def test_no_request_or_no_peer_is_none():
    assert visitor_ip(None) is None
    assert visitor_ip(FakeRequest(peer=None)) is None


# ── Docker standing in for the visitor (P6-1) ────────────────────────────────


@pytest.fixture
def docker_desktop(monkeypatch):
    """As on Docker Desktop: every device arrives as the gateway, 172.21.0.1."""
    from app import net

    monkeypatch.setattr(net, "docker_gateways", lambda: frozenset({"172.21.0.1"}))


def test_docker_s_gateway_is_not_a_visitor(docker_desktop):
    """Counted as one visitor, twenty wrong passwords from anybody would lock
    out everybody — the P5-1 lockout at another address."""
    assert visitor_ip(FakeRequest(peer="172.21.0.6", forwarded="172.21.0.1")) is None


def test_a_device_whose_address_survives_is_still_seen(docker_desktop):
    """Docker on Linux keeps devices' addresses: only the gateway is unknown."""
    assert visitor_ip(FakeRequest(peer="172.21.0.6", forwarded="192.168.1.55")) == "192.168.1.55"


def test_more_addresses_can_be_named_unknown(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "unknown_visitor_ips", "10.9.0.1")
    assert visitor_ip(FakeRequest(peer="172.21.0.6", forwarded="10.9.0.1")) is None


def test_the_gateway_is_read_from_the_routing_table(tmp_path, monkeypatch):
    import builtins

    from app import net

    table = tmp_path / "route"
    table.write_text(
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
        "eth0\t00000000\t010015AC\t0003\t0\t0\t0\t00000000\n"
        "eth0\t000015AC\t00000000\t0001\t0\t0\t0\t0000FFFF\n"
    )
    real_open = builtins.open
    monkeypatch.setattr(
        builtins, "open",
        lambda path, *a, **k: real_open(table, *a, **k) if path == "/proc/net/route" else real_open(path, *a, **k),
    )
    net.docker_gateways.cache_clear()
    net.docker_networks.cache_clear()
    try:
        assert net.docker_gateways() == frozenset({"172.21.0.1"})
        # Its own network too: every address in it is a container.
        assert net.docker_networks() == ("172.21.0.0/16",)
    finally:
        net.docker_gateways.cache_clear()
        net.docker_networks.cache_clear()


def test_an_address_inside_docker_is_never_a_visitor(monkeypatch):
    """nginx's own address, as sessions before Phase 15 recorded it."""
    from app import net

    monkeypatch.setattr(net, "docker_networks", lambda: ("172.21.0.0/16",))
    assert net.hidden_by_docker("172.21.0.6") is True
    assert net.hidden_by_docker("192.168.1.55") is False
