"""Reading the client's address off a request.

One function, because two tables store it in an `INET` column and Postgres
rejects anything that is not a valid address. A malformed value there does not
degrade gracefully — the INSERT raises, and the request it was recording fails
with a 500. An audit trail that can break the thing it observes is worse than
no audit trail.
"""

import ipaddress
from functools import lru_cache

from fastapi import Request


@lru_cache
def docker_gateways() -> frozenset[str]:
    """Docker's own address on this container's network: 172.21.0.1, say.

    **What a visitor looks like when Docker has hidden them** (P6-1). Docker
    Desktop, on Windows and Mac, runs the containers inside a hidden Linux
    machine and copies each connection into it, so every device in the office
    arrives from this one address. Docker on Linux keeps devices' addresses;
    there only the server's own traffic arrives from it. Either way, this
    address is never a visitor — it is Docker.

    Read once from the kernel's routing table (the default route's gateway).
    Empty outside a container, or wherever the table cannot be read.
    """
    found: set[str] = set()
    try:
        with open("/proc/net/route", encoding="ascii") as table:
            rows = table.read().splitlines()[1:]
    except OSError:
        return frozenset()
    for row in rows:
        fields = row.split()
        # Destination 0.0.0.0 is the default route; its gateway is Docker's.
        if len(fields) > 2 and fields[1] == "00000000" and fields[2] != "00000000":
            try:
                found.add(str(ipaddress.IPv4Address(bytes.fromhex(fields[2])[::-1])))
            except ValueError:
                continue
    return frozenset(found)


@lru_cache
def docker_networks() -> tuple[str, ...]:
    """Docker's own network on this container, e.g. 172.21.0.0/16.

    Every address in it is a container — nginx, Caddy, the API — never a
    device. Sessions recorded before Phase 15 hold nginx's address, which is
    in here; so would anything else that reached the API from inside Docker.
    Read from the same routing table: the routes with no gateway.
    """
    found: list[str] = []
    try:
        with open("/proc/net/route", encoding="ascii") as table:
            rows = table.read().splitlines()[1:]
    except OSError:
        return ()
    for row in rows:
        fields = row.split()
        if len(fields) > 7 and fields[1] != "00000000" and fields[2] == "00000000":
            try:
                network = ipaddress.IPv4Address(bytes.fromhex(fields[1])[::-1])
                mask = ipaddress.IPv4Address(bytes.fromhex(fields[7])[::-1])
                found.append(str(ipaddress.IPv4Network(f"{network}/{mask}", strict=False)))
            except ValueError:
                continue
    return tuple(found)


def hidden_by_docker(address: str | None) -> bool:
    """Whether an address is Docker, rather than a visitor: its gateway (what
    every device looks like on Docker Desktop), anything else on its own
    network, or an address named in UNKNOWN_VISITOR_IPS."""
    from app.config import get_settings

    if not address:
        return False
    if address in docker_gateways():
        return True
    if in_any(address, ",".join(docker_networks())):
        return True
    return in_any(address, get_settings().unknown_visitor_ips)


def client_ip(request: Request | None) -> str | None:
    """The peer address, or None if there isn't a valid one.

    Returning None rather than raising or storing a placeholder: "we do not
    know where this came from" is a true statement, and it keeps the column
    honest. A placeholder string would be indistinguishable from a real address
    when someone is reading the log to answer a question.

    Note this is the *socket* peer. Behind nginx that is the proxy, not the end
    user — see the note in nginx/conf.d/default.conf about X-Forwarded-For.
    Trusting a client-supplied header here would let anyone forge the address
    in the audit log, so it is deliberately not read.
    """
    if request is None or request.client is None:
        return None

    host = request.client.host
    try:
        ipaddress.ip_address(host)
    except ValueError:
        # Not an address at all — a unix socket path, or a test client naming
        # itself. Better to record nothing than to fail the request.
        return None
    return host


def proxy_hops(db=None) -> int:
    """How many proxies stand in front, counting nginx: 1, or 2 behind the
    organization's own (Phase 17).

    **Settings first** (Settings → Hosting → "A proxy in front"), so an admin
    can change it without editing `.env` and restarting; `TRUSTED_PROXY_HOPS`
    otherwise. Asked with a database session where one is to hand — every
    sign-in, session and log entry has one.
    """
    from sqlalchemy import select

    from app.config import get_settings
    from app.models import Organization

    if db is not None:
        mode = db.scalar(select(Organization.proxy_mode).order_by(Organization.id).limit(1))
        if mode == "proxy":
            return 2
        if mode == "direct":
            return 1
    return get_settings().trusted_proxy_hops


def visitor_ip(request: Request | None, db=None) -> str | None:
    """The real visitor's address, or None when it cannot be known (P5-1).

    For everything that is about *who* is asking: sign-in limits, sessions,
    the activity log. `client_ip` is the socket peer, which behind nginx is
    always nginx — so "20 failures per address" was 20 for the whole company,
    and anybody could keep every password sign-in locked out by failing 20
    times every five minutes.

    **None rather than nginx's address when it cannot be known** — a proxy we
    trust that sent no usable header, or fewer hops than configured. A limit
    keyed on an unknown address is skipped (the per-email limit still guards
    the account); one keyed on the proxy's address is a lock on everybody.

    Counted by position like `real_client_ip`, and with the same settings, so
    nothing a client prepends to the header is ever read.
    """
    from app.config import get_settings

    settings = get_settings()
    peer = client_ip(request)
    if request is None or peer is None:
        return None
    if not in_any(peer, settings.trusted_proxy_ips):
        # Straight from the visitor: the socket peer is them.
        return peer
    found = real_client_ip(request, settings.trusted_proxy_ips, proxy_hops(db))
    # `real_client_ip` falls back to the peer when the header is missing,
    # malformed or too short — which here is the proxy, not a visitor.
    if found == peer:
        return None
    # **Docker standing in for the visitor is not the visitor either** (P6-1).
    # On Docker Desktop every device arrives as Docker's gateway; counted as
    # one visitor, twenty wrong passwords from anybody would lock out
    # everybody — the P5-1 lockout again, at another address.
    if hidden_by_docker(found):
        return None
    return found


def _networks(spec: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a comma-separated list of addresses or CIDRs, skipping nonsense.

    Skipping rather than raising: a typo in one entry of a proxy list must not
    stop the application booting, and the entries that did parse still do their
    job. A malformed entry simply never matches.
    """
    out = []
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(ipaddress.ip_network(piece, strict=False))
        except ValueError:
            continue
    return out


def in_any(address: str | None, spec: str) -> bool:
    """Is `address` inside any network in `spec`?"""
    if not address:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in _networks(spec))


def forwarded_chain(request: Request | None) -> list[str]:
    """The addresses in X-Forwarded-For, as sent. For the connection check in
    Settings, which says how many proxies a request came through."""
    if request is None:
        return []
    return [hop.strip() for hop in request.headers.get("x-forwarded-for", "").split(",") if hop.strip()]


def real_client_ip(
    request: Request | None, trusted_proxies: str, proxy_hops: int = 1
) -> str | None:
    """Who actually connected, looking through a known number of proxies.

    Distinct from `client_ip`, which stays the socket peer and is what the
    audit log records — an address nobody can influence is the right thing to
    keep in a log. This one decides whether a wall screen is on the office
    network, where the socket peer behind nginx is useless because it is
    always nginx.

    **Position, not inspection.** An earlier version walked the chain from the
    right and returned the first hop that was not in the trusted ranges. That
    is a well-known idea and it is wrong here, because on Docker the *real*
    client also arrives from a private address — 172.21.0.1 sits inside
    172.16.0.0/12 — so the walk skipped the genuine hop as "another proxy" and
    returned whatever the caller had prepended. A live test forged
    `X-Forwarded-For: 203.0.113.9` and got a 200.

    Counting hops is not a heuristic. nginx *appends* the peer it saw
    (`$proxy_add_x_forwarded_for`), so with one proxy in front the last entry
    is the truth and everything to its left is whatever the client chose to
    send. With a load balancer in front of nginx, `proxy_hops` is 2, and so on.

    The header is still only read when the connection itself came from a
    trusted address — otherwise anybody reaching the API directly could claim
    to be inside the building.
    """
    peer = client_ip(request)
    if request is None or not in_any(peer, trusted_proxies):
        # Direct connection, or a proxy we do not trust. The socket peer is the
        # only thing worth believing.
        return peer

    chain: list[str] = []
    for hop in request.headers.get("x-forwarded-for", "").split(","):
        hop = hop.strip()
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            # Garbage anywhere in the chain makes positions meaningless: we can
            # no longer count backwards to a known slot.
            return peer
        chain.append(hop)

    if len(chain) < proxy_hops:
        # Fewer hops than configured. Something is not the shape we were told,
        # so fall back to the peer — which is the proxy, and will not match an
        # office allowlist. Failing closed is the right direction here.
        return peer

    return chain[-proxy_hops]
