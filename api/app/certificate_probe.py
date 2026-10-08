"""What certificate the HTTPS address is actually serving (Phase 19).

For the Hosting tab's status card: "Certificate · valid until 12 Jan". Read by
connecting to the HTTPS address the way a browser would and looking at the
certificate it is handed — so it reports what visitors get, whichever of the
setups is serving it, rather than what a setting says should be there.

Not a check that the certificate is *trusted* (GoalGetter's own authority is
trusted by nobody until a device installs it); only what it is and until when.
Short timeouts and a five-minute memory, so a page load never waits long.
"""

from __future__ import annotations

import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.x509.oid import NameOID


TIMEOUT = 2.0
REMEMBER_FOR = 300.0
#: Nothing answering is remembered briefly: it is often a moment ago, as a
#: change was being switched over (P7-9).
REMEMBER_NOTHING_FOR = 15.0


@dataclass(frozen=True)
class Served:
    valid_until: datetime
    issuer: str


_cache: dict[str, tuple[float, Served | None]] = {}


def _where(hosting) -> list[tuple[str, int]]:
    """Where to knock, in order: what serves HTTPS depends on the setup."""
    port = hosting.https_port
    if hosting.front_door == "windows":
        # Caddy on the Windows host, outside Docker.
        return [("host.docker.internal", port)]
    if hosting.front_door == "cloudflare":
        # Cloudflare answers for the name, out on the internet.
        return [(hosting.host, 443)]
    # Caddy in Docker, reached by its service name on the internal network.
    return [("https", 443), (hosting.host, port)]


def _issuer(cert: x509.Certificate) -> str:
    # The organisation first: Let's Encrypt's common name is a code ("R11").
    names = cert.issuer.get_attributes_for_oid(NameOID.ORGANIZATION_NAME) or cert.issuer.get_attributes_for_oid(
        NameOID.COMMON_NAME
    )
    # Caddy names its own authority's certificates "<name> - ECC Intermediate".
    return re.sub(r" - (\d{4} )?ECC (Intermediate|Root)$", "", str(names[0].value)) if names else ""


def _knock(host: str, port: int, name: str) -> Served | None:
    context = ssl.create_default_context()
    # What is served, not whether it is trusted: see the module docstring.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT) as raw:
            with context.wrap_socket(raw, server_hostname=name) as tls:
                der = tls.getpeercert(binary_form=True)
    except (OSError, ssl.SSLError, ValueError):
        return None
    if not der:
        return None
    cert = x509.load_der_x509_certificate(der)
    return Served(valid_until=cert.not_valid_after_utc, issuer=_issuer(cert))


def served(hosting, *, fresh: bool = False) -> Served | None:
    """The certificate visitors get, or None when HTTPS is off or unreachable.
    `fresh` knocks again rather than remembering — while a change is tried."""
    if not hosting.https_on:
        return None
    name = hosting.host
    remembered = _cache.get(name)
    memory = REMEMBER_FOR if remembered and remembered[1] else REMEMBER_NOTHING_FOR
    if not fresh and remembered and time.monotonic() - remembered[0] < memory:
        return remembered[1]
    found = None
    for host, port in _where(hosting):
        found = _knock(host, port, name)
        if found:
            break
    _cache[name] = (time.monotonic(), found)
    return found
