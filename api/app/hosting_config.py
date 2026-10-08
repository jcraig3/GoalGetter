"""HTTPS, set up in the app — and `.env` kept in step with it (Phase 20).

**The app is where hosting is set up.** Settings → Hosting saves to the
`hosting_config` row; this module turns that into Caddy's configuration and
pushes it to Caddy while it runs, over a socket only the two containers share
(`CADDY_ADMIN_SOCKET`). No restart, no file to edit. nginx's TV-only plain port
follows through a small file it watches (`NGINX_CONF`).

**`.env` is kept in step, both ways.** The hosting lines below (`MANAGED`)
are written into the server's `.env` whenever they are saved in the app, and
an edit made in `.env` shows up in the app — whichever changed last wins:

    the file differs from what was last agreed  → it was edited there: the file wins
    the app differs from what was last agreed   → it was changed here: the app wins

Only these lines, never the secrets or anything else. Without the file (not
mounted, or not writable) the app simply works on its own and says so.

**A Cloudflare tunnel, from the app too** (Phase 21). The `tunnel` service is
always running and idle; the API hands it the tunnel's token through a file
in a volume only the two share (`TUNNEL_DIR`), and the service starts,
restarts or stops `cloudflared` when that file changes. Whether it is
connected is read from cloudflared's own readiness endpoint.

**A change is tried before it is kept** (Phase 22). Saved as a trial, the
new setup runs beside the old one — Caddy serves both names, a tunnel that
was running keeps running, and nginx's plain port stays a full app — so
nothing that worked stops working. Keep makes it final; Undo, or the trial
running out, puts the old one back. One step of Undo is kept afterwards too.

**Never the Docker socket.** Nothing here starts, stops or recreates a
container: Caddy and the tunnel are always running, and only ever told what
to do.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import crypto, env_file
from app.config import get_settings
from app.models import HostingConfig, Organization

logger = logging.getLogger(__name__)

#: The socket Caddy's admin interface listens on, shared with Caddy only.
CADDY_ADMIN_SOCKET = os.environ.get("GOALGETTER_CADDY_SOCKET", "/run/caddy-admin/admin.sock")
#: The file nginx includes to know the HTTPS address (docker/web-https.sh).
NGINX_CONF = os.environ.get("GOALGETTER_NGINX_CONF", "/run/goalgetter-nginx/https.conf")
#: Where uploaded certificate files go; Caddy reads them as /certs/*.pem.
CERTS_DIR = os.environ.get("GOALGETTER_CERTS_DIR", "/hosting/certs")
#: Shared with the `tunnel` service: the token it runs with, and its log.
TUNNEL_DIR = os.environ.get("GOALGETTER_TUNNEL_DIR", "/run/goalgetter-tunnel")
#: cloudflared's metrics server, whose /ready says whether it is connected.
TUNNEL_METRICS = os.environ.get("GOALGETTER_TUNNEL_METRICS", "http://tunnel:2000")

CERTIFICATES = ("internal", "letsencrypt", "files")
DNS_PROVIDERS = ("cloudflare", "duckdns")
#: Who may serve HTTPS instead of Caddy in Docker. Only `cloudflare` is set
#: up in the app; `windows` comes from the front door's installer.
FRONT_DOORS = ("cloudflare", "windows")
#: How long a change stays on trial before it is undone by itself.
TRIAL = timedelta(minutes=15)
#: The settings a change can touch, as stored — what Undo puts back.
SETTINGS = (
    "https_on", "https_host", "certificate", "dns_provider", "dns_api_token_encrypted",
    "acme_email", "front_door", "tunnel_token_encrypted",
)
#: APP_URL as setup writes it.
DEFAULT_APP_URL = "http://localhost:8080"

#: The lines of `.env` the app keeps in step. Everything else is left alone.
MANAGED = (
    "HTTPS_HOST",
    "HTTPS_CERTIFICATE",
    "DNS_PROVIDER",
    "DNS_API_TOKEN",
    "ACME_EMAIL",
    "WEB_ADDRESS",
    "TRUSTED_PROXY_HOPS",
    "HTTPS_FRONT_DOOR",
    "CLOUDFLARE_TUNNEL_TOKEN",
)
#: What each managed line holds when nobody has set it.
UNSET = {
    "HTTPS_HOST": "",
    "HTTPS_CERTIFICATE": "internal",
    "DNS_PROVIDER": "",
    "DNS_API_TOKEN": "",
    "ACME_EMAIL": "",
    "WEB_ADDRESS": "",
    "TRUSTED_PROXY_HOPS": "1",
    "HTTPS_FRONT_DOOR": "",
    "CLOUDFLARE_TUNNEL_TOKEN": "",
}

HOST_PATTERN = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,300}$")
EMAIL_PATTERN = re.compile(r"^[^\s@{}]+@[^\s@{}]+\.[^\s@{}]+$")
#: A tunnel token: base64 of {"a": account, "t": tunnel, "s": secret}, so it
#: always starts `eyJ`. Found inside whatever was pasted — Cloudflare's page
#: offers it inside an install command.
_TUNNEL_TOKEN_IN = re.compile(r"eyJ[A-Za-z0-9+/_=-]{40,2000}")


def tunnel_token_from(text: str) -> str | None:
    """The tunnel token in what was pasted, or None if there is none."""
    for found in _TUNNEL_TOKEN_IN.findall(text or ""):
        if tunnel_id(found):
            return found
    return None


def tunnel_id(token: str) -> str | None:
    """Which tunnel a token is for — not a secret — or None if it isn't one."""
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.replace("+", "-").replace("/", "_")))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(decoded, dict) or not all(isinstance(decoded.get(k), str) for k in ("a", "t", "s")):
        return None
    return decoded["t"]


@dataclass(frozen=True)
class Hosting:
    """How HTTPS stands right now, from the app's settings and `.env`."""

    on: bool
    host: str
    certificate: str
    front_door: str
    dns_provider: str
    dns_api_token: str
    acme_email: str
    tunnel_token: str
    https_port: int
    http_port: int
    app_port: int
    #: Whether `.env` is connected (mounted and writable), so edits sync.
    env_connected: bool
    #: The setup before the last change — what Undo goes back to.
    undo_to: Hosting | None = None
    #: While the last change is on trial: when it is undone by itself.
    trial_until: datetime | None = None
    #: Whether `.env` can be read: its edits are followed even when it can't
    #: be written (`env_connected`).
    env_readable: bool = False
    #: Going back to `undo_to` would redo a change just undone.
    undo_is_redo: bool = False
    #: When a trial nobody kept was undone by itself, until the next change.
    trial_expired_at: datetime | None = None

    @property
    def on_trial(self) -> bool:
        return self.trial_until is not None and self.undo_to is not None

    @property
    def https_on(self) -> bool:
        return bool(self.host) and self.on

    @property
    def caddy_serves(self) -> bool:
        """Caddy in Docker handles HTTPS: on, and no front door outside it."""
        return self.on and bool(self.host) and not self.front_door

    @property
    def tunnel_runs(self) -> bool:
        """The `tunnel` service should be connected to Cloudflare."""
        return self.https_on and self.front_door == "cloudflare" and bool(self.tunnel_token)

    @property
    def https_address(self) -> str | None:
        if not self.https_on:
            return None
        # Through Cloudflare people reach Cloudflare, on 443 like any site.
        port = "" if self.https_port == 443 or self.front_door == "cloudflare" else f":{self.https_port}"
        return f"https://{self.host}{port}"


# ── The row ──────────────────────────────────────────────────────────────────


def _row(db: DbSession) -> HostingConfig:
    row = db.scalar(select(HostingConfig).order_by(HostingConfig.id).limit(1))
    if row is None:
        row = HostingConfig(
            https_on=False, https_host="", certificate="internal",
            dns_provider="", acme_email="", front_door="", env_snapshot=None,
        )
        db.add(row)
        db.flush()
    return row


def _org(db: DbSession) -> Organization | None:
    return db.scalar(select(Organization).order_by(Organization.id).limit(1))


# ── App ⇄ .env, one line at a time ───────────────────────────────────────────


#: The lines kept on the organisation rather than on the hosting row.
ORG_KEYS = ("WEB_ADDRESS", "TRUSTED_PROXY_HOPS")


def _app_values(row: HostingConfig, org: Organization | None) -> dict[str, str]:
    """The managed lines as the app would write them."""
    token = crypto.decrypt(row.dns_api_token_encrypted) if row.dns_api_token_encrypted else ""
    tunnel = crypto.decrypt(row.tunnel_token_encrypted) if row.tunnel_token_encrypted else ""
    return {
        "HTTPS_HOST": row.https_host if row.https_on else "",
        "HTTPS_CERTIFICATE": row.certificate,
        "DNS_PROVIDER": row.dns_provider,
        "DNS_API_TOKEN": token,
        "ACME_EMAIL": row.acme_email,
        "WEB_ADDRESS": (org.public_url or "") if org else "",
        "TRUSTED_PROXY_HOPS": "2" if org and org.proxy_mode == "proxy" else "1",
        "HTTPS_FRONT_DOOR": row.front_door,
        "CLOUDFLARE_TUNNEL_TOKEN": tunnel,
    }


def _take_from_file(key: str, value: str, row: HostingConfig, org: Organization | None) -> None:
    """One edited line of `.env`, into the app. Nonsense is ignored, not saved."""
    from app import public_url

    if key == "HTTPS_HOST":
        if value and HOST_PATTERN.match(value):
            row.https_host, row.https_on = value, True
        elif not value:
            # Empty in the file means off; the name is kept for turning it on.
            row.https_on = False
    elif key == "HTTPS_CERTIFICATE" and value in CERTIFICATES:
        row.certificate = value
    elif key == "DNS_PROVIDER" and (value in DNS_PROVIDERS or not value):
        row.dns_provider = value
    elif key == "DNS_API_TOKEN" and (not value or TOKEN_PATTERN.match(value)):
        row.dns_api_token_encrypted = crypto.encrypt(value) if value else None
    elif key == "ACME_EMAIL" and (not value or EMAIL_PATTERN.match(value)):
        row.acme_email = value
    elif key == "WEB_ADDRESS" and org is not None:
        if not value:
            org.public_url = None
        else:
            try:
                org.public_url = public_url.normalise(value)
            except ValueError:
                pass
    elif key == "HTTPS_FRONT_DOOR" and (value in FRONT_DOORS or not value):
        row.front_door = value
    elif key == "CLOUDFLARE_TUNNEL_TOKEN" and (not value or tunnel_id(value)):
        row.tunnel_token_encrypted = crypto.encrypt(value) if value else None
    elif key == "TRUSTED_PROXY_HOPS" and org is not None:
        if value == "2":
            org.proxy_mode = "proxy"
        elif org.proxy_mode == "proxy":
            org.proxy_mode = None


def sync(db: DbSession) -> bool:
    """Bring `.env` and the app into agreement. True if anything changed.

    Whichever side moved since they last agreed wins, line by line. The first
    time (nothing agreed yet), a line someone set in the file wins over the
    app's untouched default, and the app wins otherwise.
    """
    if not env_file.readable():
        return False
    writable = env_file.writable()
    if not writable:
        _say_once("hosting: .env can be read but not written; edits there are followed, the app's are not written")
    row, org = _row(db), _org(db)
    try:
        in_file = env_file.read()
    except OSError:
        return False
    agreed = row.env_snapshot
    if agreed is not None and "APP_URL" in agreed:
        agreed = _from_app_url(agreed, in_file, org)
    file_now = {key: in_file.get(key, UNSET[key]) for key in MANAGED}
    app_before = _app_values(row, org)
    settings_before = _settings_of(row)

    for key in MANAGED:
        edited_in_file = (
            file_now[key] != agreed.get(key, UNSET[key])
            if agreed is not None
            else file_now[key] != UNSET[key] and file_now[key] != app_before[key]
        )
        if edited_in_file:
            _take_from_file(key, file_now[key], row, org)

    settings_now = _settings_of(row)
    if settings_now != settings_before:
        if row.trial_until is None:
            # **Edited in the file: decided**, and the change Undo takes back.
            row.previous = settings_before
        elif settings_now == _stored(row.previous):
            # Edited back to where the trial started: that ends it.
            row.trial_until = None
        else:
            # **During a trial, a new trial from the same start** (P7-4), so
            # the old name and the way back in stay up until it is kept.
            row.trial_until = datetime.now(UTC) + TRIAL
        if org is not None:
            from app import audit

            audit.record_system(
                db, organization_id=org.id, action="hosting.changed_in_env",
                on=bool(row.https_on), host=row.https_host,
            )

    app_now = _app_values(row, org)
    if org is None:
        # **Before the first sign-in there is no organisation** to keep the
        # web address and proxy in, so those lines stay the file's — and stay
        # out of the agreement, so the file still wins once there is one.
        for key in ORG_KEYS:
            app_before.pop(key)
            app_now.pop(key)
    if not writable:
        # **Read only: the agreement is the file as last seen**, so the next
        # edit there is noticed, and the app's own changes — which can't be
        # written — are not mistaken for one.
        changed = app_now != app_before or agreed != file_now
        row.env_snapshot = file_now
        if changed:
            db.flush()
        return changed
    to_write = {key: value for key, value in app_now.items() if file_now.get(key) != value}
    if to_write:
        try:
            env_file.write(to_write)
        except (OSError, ValueError):
            logger.warning("hosting: could not write .env", exc_info=True)
            return False
    changed = app_now != app_before or bool(to_write) or agreed != app_now
    row.env_snapshot = app_now
    if changed:
        db.flush()
    return changed


def _from_app_url(agreed: dict, in_file: dict, org: Organization | None) -> dict:
    """**Once, for installs from Phases 20–22** (P7-1): `APP_URL` used to be
    mirrored onto the Advanced web address, which beats HTTPS — so an
    `APP_URL` changed with `APP_PORT` kept every link off the HTTPS address
    for good. An Advanced address that only repeats `APP_URL` came from the
    file, not from an admin: it is cleared. `APP_URL` is the fallback again."""
    from app import public_url

    if org is not None and org.public_url:
        try:
            if org.public_url == public_url.normalise(in_file.get("APP_URL") or DEFAULT_APP_URL):
                org.public_url = None
        except ValueError:
            pass
    adopted = {key: value for key, value in agreed.items() if key != "APP_URL"}
    # Agreed as the file has it, so the app's address is written, not undone.
    adopted.setdefault("WEB_ADDRESS", in_file.get("WEB_ADDRESS", ""))
    return adopted


_said: set[str] = set()


def _say_once(message: str) -> None:
    if message not in _said:
        _said.add(message)
        logger.warning(message)


def app_url() -> str:
    """`APP_URL`: the address while HTTPS is off and nothing is set under
    Advanced. From the file as it is now when it can be read, so an edit
    needs no restart."""
    if env_file.readable():
        try:
            value = env_file.read().get("APP_URL", "").strip()
        except OSError:
            value = ""
        if value:
            return value.rstrip("/")
    return get_settings().app_url.rstrip("/")


# ── The effective view ───────────────────────────────────────────────────────


def _port(values: dict[str, str], key: str, fallback: int) -> int:
    try:
        return int(values.get(key) or fallback)
    except ValueError:
        return fallback


def current(db: DbSession, *, sync_first: bool = True) -> Hosting:
    """How HTTPS stands: the app's settings, after catching up with `.env`."""
    settings = get_settings()
    connected = env_file.readable()
    if sync_first and connected:
        sync(db)
    row = _row(db)
    # Ports are not app settings — they decide which ports Docker publishes —
    # but are read from the file when it is there, so an edit is seen
    # without a restart.
    values = env_file.read() if connected else {}
    # **No .env and nothing set here yet: the environment, as before Phase 20.**
    # An install that has not mounted its .env keeps working exactly as it
    # did, from the variables Docker started it with.
    legacy = not connected and row.env_snapshot is None and not row.https_host and not row.https_on
    if legacy:
        return Hosting(
            on=settings.https_on,
            host=settings.https_host if settings.https_on else "",
            certificate=settings.https_certificate,
            front_door=settings.https_front_door or "",
            dns_provider="",
            dns_api_token="",
            acme_email="",
            tunnel_token="",
            https_port=settings.https_port,
            http_port=settings.http_port,
            app_port=settings.app_port,
            env_connected=False,
            env_readable=False,
        )
    ports = dict(
        https_port=_port(values, "HTTPS_PORT", settings.https_port),
        http_port=_port(values, "HTTP_PORT", settings.http_port),
        app_port=_port(values, "APP_PORT", settings.app_port),
        env_connected=connected and env_file.writable(),
        env_readable=connected,
    )
    undo_to = _hosting_from(row.previous, ports) if row.previous else None
    return _hosting_from(
        _settings_of(row), ports,
        undo_to=undo_to,
        undo_is_redo=bool(row.previous and row.previous.get("redo")),
        trial_until=row.trial_until,
        trial_expired_at=row.trial_expired_at,
    )


def _hosting_from(stored: dict, ports: dict, **extra) -> Hosting:
    """A Hosting from settings as stored (tokens encrypted)."""
    def secret(key: str) -> str:
        value = stored.get(key)
        return crypto.decrypt(value) if value else ""

    return Hosting(
        on=bool(stored.get("https_on")),
        host=stored.get("https_host") or "",
        certificate=stored.get("certificate") or "internal",
        front_door=stored.get("front_door") or "",
        dns_provider=stored.get("dns_provider") or "",
        dns_api_token=secret("dns_api_token_encrypted"),
        acme_email=stored.get("acme_email") or "",
        tunnel_token=secret("tunnel_token_encrypted"),
        **ports,
        **extra,
    )


def _settings_of(row: HostingConfig) -> dict:
    return {key: getattr(row, key) for key in SETTINGS}


def _stored(previous: dict | None) -> dict | None:
    """Settings kept for Undo, without the marks kept beside them."""
    return {key: previous.get(key) for key in SETTINGS} if previous else None


def _write_env(db: DbSession, row: HostingConfig) -> None:
    """The app just moved: write it to the file and agree on it now, so the
    next sync does not mistake the file's old lines for an edit. Not when the
    file can't be written: it then keeps saying what it said."""
    if not env_file.writable():
        return
    app_now = _app_values(row, _org(db))
    try:
        in_file = env_file.read()
        to_write = {k: v for k, v in app_now.items() if in_file.get(k, UNSET[k]) != v}
        env_file.write(to_write)
        row.env_snapshot = app_now
    except (OSError, ValueError):
        logger.warning("hosting: could not write .env", exc_info=True)


def save(db: DbSession, *, trial: bool = False, **changes) -> Hosting:
    """Settings saved in the app: into the row, then into `.env`.

    What they replace is kept for Undo. With `trial`, the change runs beside
    the old setup until it is kept, undone, or the trial runs out."""
    row = _row(db)
    before = _settings_of(row)
    for key, value in changes.items():
        if key in ("dns_api_token", "tunnel_token"):
            # None keeps the stored one; empty removes it.
            if value is not None:
                setattr(row, f"{key}_encrypted", crypto.encrypt(value) if value else None)
        else:
            setattr(row, key, value)
    after = _settings_of(row)
    if after != before:
        # A trial changed again stays a trial of the setup it started from.
        if row.trial_until is None:
            row.previous = before
        if trial and after != _stored(row.previous):
            row.trial_until = datetime.now(UTC) + TRIAL
        else:
            row.trial_until = None
        row.trial_expired_at = None
    db.flush()
    _write_env(db, row)
    db.flush()
    return current(db, sync_first=False)


def keep(db: DbSession) -> Hosting:
    """The change on trial is the setup now. Undo still goes back."""
    row = _row(db)
    row.trial_until = None
    row.trial_expired_at = None
    db.flush()
    return current(db, sync_first=False)


def undo(db: DbSession, *, trial: bool = False) -> Hosting | None:
    """Back to the setup before the last change — kept or on trial. The
    two swap, so undoing again redoes it. With `trial`, going back is tried
    like any change. None when there is nothing to undo."""
    row = _row(db)
    if not row.previous:
        return None
    trying = trial and row.trial_until is None
    now = _settings_of(row)
    for key in SETTINGS:
        if key in row.previous:
            setattr(row, key, row.previous[key])
    # Marked: going back to it again would redo the change just undone.
    row.previous = {**now, "redo": True}
    row.trial_until = datetime.now(UTC) + TRIAL if trying else None
    row.trial_expired_at = None
    db.flush()
    _write_env(db, row)
    db.flush()
    return current(db, sync_first=False)


# ── Caddy ────────────────────────────────────────────────────────────────────


def _tls(hosting: Hosting) -> str:
    if hosting.certificate == "letsencrypt":
        email = hosting.acme_email if EMAIL_PATTERN.match(hosting.acme_email or "") else ""
        return (
            f"tls {email}".rstrip()
            + " {\n"
            + f"\t\tdns {hosting.dns_provider} {hosting.dns_api_token}\n"
            + "\t\tresolvers 1.1.1.1 8.8.8.8\n\t}"
        )
    if hosting.certificate == "files":
        return "tls /certs/cert.pem /certs/key.pem"
    return "tls internal"


def caddyfile(hosting: Hosting) -> str:
    """Caddy's whole configuration for this setup, as a Caddyfile.

    Always carries the admin socket: a configuration without it would move
    Caddy's admin interface back to its default and cut the app off. With
    HTTPS off, or handled outside Docker, it serves nothing.
    """
    lines = [
        "{",
        f"\tadmin unix/{CADDY_ADMIN_SOCKET}|0666",
        "\tskip_install_trust",
        "\tpki {",
        "\t\tca local {",
        '\t\t\tname "GoalGetter Local Authority"',
        "\t\t}",
        "\t}",
        "}",
    ]
    # **On trial, the old site too**, so an address that worked keeps working
    # until the change is kept. Not for the same name: one name has one
    # certificate, and the new one is what is being tried.
    serving = [hosting]
    old = hosting.undo_to
    if hosting.on_trial and old and old.caddy_serves and not (hosting.caddy_serves and old.host == hosting.host):
        serving.append(old)
    for setup in serving:
        if setup.caddy_serves and HOST_PATTERN.match(setup.host):
            lines += _sites(setup)
    return "\n".join(lines) + "\n"


def _sites(hosting: Hosting) -> list[str]:
    """Caddy's two sites for one name: the redirect, and HTTPS itself."""
    port = "" if hosting.https_port == 443 else f":{hosting.https_port}"
    root_cert = (
        "\thandle /goalgetter-root.crt {\n"
        "\t\troot * /data/caddy/pki/authorities/local\n"
        "\t\trewrite * /root.crt\n"
        "\t\theader Content-Type application/x-x509-ca-cert\n"
        '\t\theader Content-Disposition "attachment; filename=goalgetter-root.crt"\n'
        "\t\tfile_server\n"
        "\t}\n"
    )
    return [
        "",
        f"http://{hosting.host} {{",
        root_cert.rstrip("\n"),
        "\thandle {",
        # 302, not 301: browsers keep a 301 for good (P7-12, as P6-2 for nginx).
        f"\t\tredir https://{hosting.host}{port}{{uri}} temporary",
        "\t}",
        "}",
        "",
        f"https://{hosting.host} {{",
        "\t" + _tls(hosting),
        root_cert.rstrip("\n"),
        "\thandle {",
        "\t\treverse_proxy web:81",
        "\t}",
        "}",
    ]


def nginx_conf(hosting: Hosting) -> str:
    """What nginx's plain port needs: the HTTPS address, or empty for off."""
    return f'set $gg_https_address "{hosting.https_address or ""}";\n'


#: Off, for nginx during a trial: the plain port a full app.
_OFF = Hosting(
    on=False, host="", certificate="internal", front_door="", dns_provider="", dns_api_token="",
    acme_email="", tunnel_token="", https_port=443, http_port=80, app_port=8080, env_connected=False,
)


#: What was last pushed, so an unchanged configuration is not pushed again.
_last: dict[str, str] = {}


def push_to_caddy(text: str) -> str | None:
    """Load a configuration into Caddy while it runs. None, or why not."""
    import httpx

    if not os.path.exists(CADDY_ADMIN_SOCKET):
        return "The HTTPS service is not running."
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=CADDY_ADMIN_SOCKET), timeout=30) as client:
            reply = client.post(
                "http://caddy/load", content=text.encode(), headers={"Content-Type": "text/caddyfile"}
            )
    except httpx.HTTPError as problem:
        return f"Could not reach the HTTPS service ({type(problem).__name__})."
    if reply.status_code >= 400:
        return reply.text.strip()[:500] or f"The HTTPS service refused it ({reply.status_code})."
    return None


def _write_nginx(text: str) -> str | None:
    """None when nginx's file says this, or why it could not be written."""
    directory = os.path.dirname(NGINX_CONF)
    if not os.path.isdir(directory):
        return None
    try:
        with open(NGINX_CONF, encoding="utf-8") as handle:
            if handle.read() == text:
                return None
    except OSError:
        pass
    # A new file renamed over the old one: nginx never reads half of it, and
    # it works whoever wrote the old one.
    temporary = f"{NGINX_CONF}.new"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, NGINX_CONF)
    except OSError as error:
        return f"couldn't tell nginx the HTTPS address: {error.strerror or error}"
    return None


def apply(hosting: Hosting, *, force: bool = False) -> str | None:
    """Make Caddy, the tunnel and nginx match. None when they do, or why not.

    nginx last: its plain port starts sending people to HTTPS only once Caddy
    has taken the change — or, through Cloudflare, once the tunnel is
    connected — so a change that doesn't work never strands that port. On
    trial it stays a full app, and a tunnel that was running keeps running."""
    old = hosting.undo_to if hosting.on_trial else None
    if hosting.tunnel_runs:
        _write_tunnel(hosting.tunnel_token)
    elif old and old.tunnel_runs:
        _write_tunnel(old.tunnel_token)
    else:
        _write_tunnel("")
    text = caddyfile(hosting)
    digest = hashlib.sha256(text.encode()).hexdigest()
    if force or _last.get("caddy") != digest:
        problem = push_to_caddy(text)
        if problem is not None:
            return problem
        _last["caddy"] = digest
    if hosting.on_trial:
        # **The way back in during a trial** is the old HTTPS name when there
        # was one (it is still served); only from plain HTTP is the plain port
        # a full app meanwhile (P7, the tester's suggestion).
        before = hosting.undo_to
        return _write_nginx(nginx_conf(before if before and before.https_on else _OFF))
    if not _answering(hosting):
        # HTTPS through a tunnel or the front door isn't answering yet (or
        # any more): the plain port stays a full app, so nobody is sent to an
        # address that doesn't answer (P7-3). The loop looks again in 30 s.
        return _write_nginx(nginx_conf(_OFF))
    return _write_nginx(nginx_conf(hosting))


def _answering(hosting: Hosting) -> bool:
    """Whatever serves HTTPS outside Caddy in Docker is up. Caddy itself has
    just taken its configuration, so it counts as answering."""
    if hosting.tunnel_runs:
        return tunnel_status(hosting)["state"] == "connected"
    if hosting.https_on and hosting.front_door == "windows":
        from app import certificate_probe

        return certificate_probe.served(hosting, fresh=True) is not None
    return True


# ── The Cloudflare tunnel (Phase 21) ─────────────────────────────────────────


def _write_tunnel(token: str) -> None:
    """Hand the `tunnel` service its token — or nothing, which stops it."""
    if not os.path.isdir(TUNNEL_DIR):
        return
    path = os.path.join(TUNNEL_DIR, "token")
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read() == token:
                return
    except OSError:
        pass
    temporary = f"{path}.new"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
        # Readable by the folder's owner — the `tunnel` service's user — even
        # where the API runs as root (the development stack).
        folder = os.stat(TUNNEL_DIR)
        try:
            os.chown(temporary, folder.st_uid, folder.st_gid)
        except OSError:
            pass
        os.replace(temporary, path)
    except OSError:
        logger.warning("hosting: could not hand the tunnel its token", exc_info=True)


#: How old the service's heartbeat may be before it counts as not running.
_ALIVE_SECONDS = 20
_LOG_ERROR = re.compile(r"\b(?:ERR|FTL)\s+(.*)")


def _last_error() -> str | None:
    """cloudflared's last error since it was last started, in its words."""
    try:
        with open(os.path.join(TUNNEL_DIR, "cloudflared.log"), encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-200:]
    except OSError:
        return None
    for line in reversed(lines):
        match = _LOG_ERROR.search(line)
        if match:
            text = match.group(1).strip()
            # The sentence, then its `error="…"` detail; the rest of
            # cloudflared's key=value fields are for its own debugging.
            sentence = re.split(r"\s+\w+=", text, maxsplit=1)[0]
            detail = re.search(r'\berror="([^"]*)"', text)
            said = f"{sentence}: {detail.group(1)}" if detail else sentence
            if _REFUSED.search(said):
                return "Cloudflare doesn't accept this token. Copy it again from the tunnel's page."
            return said[:300] or None
    return None


#: How cloudflared reports a token Cloudflare won't take.
_REFUSED = re.compile(r"Failed to get tunnel|Unauthorized|token is not valid|Invalid tunnel secret", re.I)


def tunnel_status(hosting: Hosting) -> dict:
    """`off`, `connected` (with how many connections to Cloudflare),
    `connecting`, or `problem` with why — for the Hosting tab."""
    import time

    import httpx

    if not hosting.tunnel_runs:
        return {"state": "off", "connections": 0, "problem": None}
    try:
        reply = httpx.get(f"{TUNNEL_METRICS}/ready", timeout=2)
        connections = int(reply.json().get("readyConnections") or 0) if reply.status_code == 200 else 0
    except (httpx.HTTPError, ValueError, AttributeError):
        connections = 0
    if connections:
        return {"state": "connected", "connections": connections, "problem": None}
    try:
        alive = time.time() - os.path.getmtime(os.path.join(TUNNEL_DIR, "alive")) < _ALIVE_SECONDS
    except OSError:
        alive = False
    if not alive:
        return {"state": "problem", "connections": 0, "problem": "The tunnel service isn't running."}
    error = _last_error()
    if error:
        return {"state": "problem", "connections": 0, "problem": error}
    return {"state": "connecting", "connections": 0, "problem": None}


def reconcile(db: DbSession) -> str | None:
    """The loop's work: catch up with `.env`, undo a trial nobody kept, then
    make everything match."""
    hosting = current(db)
    if hosting.on_trial and hosting.trial_until <= datetime.now(UTC):
        logger.warning("hosting: the change on trial was not kept in time; undoing it")
        tried = hosting.host if hosting.https_on else ""
        hosting = undo(db) or hosting
        # **Said where the admin will look** (P7-5): Activity and the Inbox.
        row = _row(db)
        row.trial_expired_at = datetime.now(UTC)
        org = _org(db)
        if org is not None:
            from app import audit

            audit.record_system(
                db, organization_id=org.id, action="hosting.change_expired",
                tried=tried, back_to=hosting.host if hosting.https_on else "",
            )
        db.flush()
        hosting = current(db, sync_first=False)
    db.commit()
    return apply(hosting)
