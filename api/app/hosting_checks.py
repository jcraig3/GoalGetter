"""Checks for a hosting change: before switching over, and while it is tried
(Phase 22).

Each check is `{key, state, label, detail}`, `state` one of `ok`, `warn`,
`fail` or `wait`. None of them blocks anything: a change is tried beside the
old setup and can be undone, so the checks say what is likely to go wrong and
the admin decides. What only the admin's own device can tell — whether it can
open the new address, through its DNS, the firewall and its trust in the
certificate — the page checks itself.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Timeout
from datetime import datetime

import httpx

from app import certificate_probe, hosting_config

#: Name lookups have no timeout of their own; this gives them one.
_lookups = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hosting-dns")
LOOKUP_SECONDS = 3.0
WEB_SECONDS = 5.0


def _check(key: str, state: str, label: str, detail: str | None = None) -> dict:
    return {"key": key, "state": state, "label": label, "detail": detail}


def resolve(name: str) -> list[str] | None:
    """The addresses a name has, as this server's DNS gives them — or None."""
    try:
        found = _lookups.submit(socket.getaddrinfo, name, None, proto=socket.IPPROTO_TCP).result(LOOKUP_SECONDS)
    except (OSError, Timeout, UnicodeError):
        return None
    addresses: list[str] = []
    for *_, address in found:
        if address[0] not in addresses:
            addresses.append(address[0])
    return addresses or None


def _is_local(name: str) -> bool:
    if name in ("localhost", "") or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name.strip("[]")).is_loopback
    except ValueError:
        return False


def _dns(host: str, choice: str, seen_at: str) -> dict:
    found = resolve(host)
    if not found:
        if choice == "cloudflare":
            return _check("dns", "warn", f"{host} isn't in DNS yet", "Adding the public hostname in Cloudflare creates it.")
        return _check("dns", "warn", f"{host} isn't in DNS yet", "Add a record pointing it at this server.")
    shown = ", ".join(found[:3])
    if choice == "cloudflare" or _is_local(seen_at) or seen_at.lower() == host:
        return _check("dns", "ok", f"{host} → {shown}")
    # **Compared with how this browser reached the server**: the one address
    # the server can be sure is its own, since Docker hides the rest.
    here = resolve(seen_at) or []
    if here and not set(found) & set(here):
        return _check(
            "dns", "warn", f"{host} → {shown}",
            f"You're on {seen_at}{' (' + ', '.join(here[:2]) + ')' if here != [seen_at] else ''}, which isn't one of those.",
        )
    return _check("dns", "ok", f"{host} → {shown}", "The address you're on" if here else None)


def _cloudflare_token(token: str) -> dict:
    try:
        reply = httpx.get(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {token}"},
            timeout=WEB_SECONDS,
        )
        body = reply.json()
    except (httpx.HTTPError, ValueError):
        return _check("token", "warn", "Couldn't reach Cloudflare to check the token")
    if reply.status_code == 200 and body.get("success") and (body.get("result") or {}).get("status") == "active":
        return _check("token", "ok", "Cloudflare accepts the token")
    return _check("token", "fail", "Cloudflare doesn't accept this token", "Make one from the Edit zone DNS template.")


def _duckdns_token(token: str, host: str) -> dict:
    if not host.endswith(".duckdns.org"):
        return _check("token", "fail", "A DuckDNS name ends in .duckdns.org")
    name = host.removesuffix(".duckdns.org").rsplit(".", 1)[-1]
    try:
        # Clearing the TXT record proves the token without touching the
        # address the name points at. Let's Encrypt sets it when it needs it.
        reply = httpx.get(
            "https://www.duckdns.org/update",
            params={"domains": name, "token": token, "txt": "goalgetter-check", "clear": "true"},
            timeout=WEB_SECONDS,
        )
    except httpx.HTTPError:
        return _check("token", "warn", "Couldn't reach DuckDNS to check the token")
    if reply.text.strip().startswith("OK"):
        return _check("token", "ok", "DuckDNS accepts the token")
    return _check("token", "fail", f"DuckDNS doesn't accept this token for {name}")


def _covers(names: list[str], host: str) -> bool:
    for name in names:
        name = name.lower()
        if name == host:
            return True
        if name.startswith("*.") and host.count(".") == name.count(".") and host.endswith(name[1:]):
            return True
    return False


def _files(host: str) -> dict:
    from cryptography import x509

    try:
        with open(os.path.join(hosting_config.CERTS_DIR, "cert.pem"), "rb") as handle:
            cert = x509.load_pem_x509_certificate(handle.read())
    except (OSError, ValueError):
        return _check("files", "fail", "Upload the certificate and its key")
    try:
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.DNSName
        )
    except x509.ExtensionNotFound:
        names = []
    until = cert.not_valid_after_utc.strftime("%d %b %Y").lstrip("0")
    if _covers(list(names), host):
        return _check("files", "ok", f"The certificate covers {host}", f"Valid until {until}")
    return _check("files", "fail", f"The certificate isn't for {host}", f"It's for {', '.join(names) or 'no name'}.")


def before_switching(
    *, on: bool, host: str, choice: str, dns_provider: str, dns_token: str, tunnel_token: str, seen_at: str
) -> list[dict]:
    """What can be known before anything changes."""
    if not on:
        return []
    checks = [_dns(host, choice, seen_at.lower())]
    if choice == "letsencrypt":
        if not dns_token:
            checks.append(_check("token", "fail", "Paste the API token"))
        elif dns_provider == "cloudflare":
            checks.append(_cloudflare_token(dns_token))
        elif dns_provider == "duckdns":
            checks.append(_duckdns_token(dns_token, host))
    elif choice == "files":
        checks.append(_files(host))
    elif choice == "cloudflare":
        found = hosting_config.tunnel_id(tunnel_token) if tunnel_token else None
        # Only its shape can be checked here: Cloudflare says yes or no once
        # the tunnel starts (P7-13).
        checks.append(
            _check("tunnel_token", "ok", "Looks like a tunnel token", f"Tunnel {found[:8]}… · Cloudflare checks it when you switch over")
            if found
            else _check("tunnel_token", "fail", "Paste the tunnel token")
        )
    return checks


def _date(when: datetime) -> str:
    return when.strftime("%d %b %Y").lstrip("0")


def during_trial(hosting: hosting_config.Hosting) -> list[dict]:
    """Whether the setup being tried works, as far as the server can tell."""
    if not hosting.https_on:
        return []
    if hosting.front_door == "cloudflare":
        status = hosting_config.tunnel_status(hosting)
        if status["state"] == "connected":
            return [_check("tunnel", "ok", "The tunnel is connected", f"{status['connections']} connections to Cloudflare")]
        if status["state"] == "problem":
            return [_check("tunnel", "fail", "The tunnel isn't connected", status["problem"])]
        return [_check("tunnel", "wait", "Connecting the tunnel…")]
    served = certificate_probe.served(hosting, fresh=True)
    if served is None:
        detail = "A Let's Encrypt certificate can take a minute or two." if hosting.certificate == "letsencrypt" else None
        return [_check("served", "wait", "Waiting for HTTPS to answer…", detail)]
    # GoalGetter's own certificates last hours and renew themselves: no date.
    until = None if hosting.certificate == "internal" else f"Valid until {_date(served.valid_until)}"
    return [_check("served", "ok", f"HTTPS answers · {served.issuer or 'certificate'}", until)]
