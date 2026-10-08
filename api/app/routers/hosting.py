"""How this deployment is served, and setting it up (Phases 13, 19–21).

What the Hosting tab shows — whether HTTPS is on, the root certificate, the
address for TVs, what to register in Azure — and where it is changed: HTTPS
and the Cloudflare tunnel are saved here and applied at once by
`app/hosting_config.py`. Admin only: it names the server's addresses.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, hosting_config, public_url
from app.config import get_settings
from app.db import get_db
from app.models import Session, UserAccount
from app.net import forwarded_chain, hidden_by_docker, proxy_hops, real_client_ip, visitor_ip
from app.sessions import require_role

router = APIRouter(prefix="/hosting", tags=["hosting"])

SSO_CALLBACK = "/api/auth/sso/callback"


class TunnelStatus(BaseModel):
    #: off | connecting | connected | problem
    state: str
    #: Connections open to Cloudflare; it keeps four when healthy.
    connections: int = 0
    #: Why it isn't connected, in cloudflared's words.
    problem: str | None = None


class Hosting(BaseModel):
    https: bool
    #: https://goals.internal — null while HTTPS is off.
    https_address: str | None
    #: internal | letsencrypt | files — null while HTTPS is off.
    certificate: str | None
    #: For `internal`: where a device downloads the authority to trust.
    root_certificate_url: str | None
    #: Plain HTTP, for a TV that cannot trust a private certificate.
    tv_address: str | None
    #: What to add to the Azure app registration for Microsoft sign-in.
    sso_redirect: str
    #: Whether GoalGetter can tell devices apart by address on this host
    #: (P6-1). False on Docker Desktop, which shows every device as Docker's
    #: own address: sign-in attempts are then limited per account only, and a
    #: channel's network list cannot be checked.
    addresses_visible: bool = True
    #: **The connection check** (Phase 17): who GoalGetter thinks this very
    #: request came from — the admin's own device, or null.
    you_appear_as: str | None = None
    #: `visible`, `docker` (hidden by Docker Desktop) or `unknown`.
    connection: str = "unknown"
    #: How many addresses X-Forwarded-For carried: 1 straight through nginx
    #: or Caddy, 2 behind a proxy of the organization's own.
    proxies_seen: int = 0
    #: How many proxies GoalGetter believes are in front, and where that
    #: comes from: `settings` or `env`.
    proxy_hops: int = 1
    proxy_hops_from: str = "env"
    #: `windows` when the HTTPS front door runs outside Docker.
    front_door: str | None = None
    #: The sign-in limits in force, per account and per device.
    sign_in_limits: list[int] = []
    #: **The status card** (Phase 19): the address links are built from, and
    #: where it comes from — `settings` (Advanced → Web address), `https`, or
    #: `env` (APP_URL).
    web_address: str = ""
    web_address_from: str = "env"
    #: The certificate visitors actually get, read from the HTTPS address:
    #: null while HTTPS is off or the address cannot be reached.
    certificate_valid_until: datetime | None = None
    certificate_issuer: str | None = None
    #: Whether the server's .env is connected, so edits there and here stay
    #: in step (Phase 20).
    env_connected: bool = False
    #: Through a Cloudflare tunnel: whether it is connected (Phase 21).
    tunnel: TunnelStatus | None = None
    #: A change on trial, waiting to be kept or undone (Phase 22).
    trial_until: datetime | None = None
    #: nginx's plain port, which TVs use (P7-10).
    app_port: int = 8080


class UndoTo(BaseModel):
    on: bool
    host: str
    #: internal | letsencrypt | files | cloudflare
    choice: str
    #: Going back would redo a change just undone.
    redo: bool = False


class HttpsSettings(BaseModel):
    """HTTPS as set up in the app (Phase 20). The token is never sent back."""

    on: bool
    host: str
    certificate: str
    dns_provider: str
    has_dns_api_token: bool
    acme_email: str
    #: Who handles HTTPS when Caddy in Docker does not: `cloudflare` (a
    #: tunnel, set up here), `windows` (its installer), or null.
    front_door: str | None
    #: A tunnel token is saved — never sent back — and which tunnel it is for.
    has_tunnel_token: bool = False
    tunnel_id: str | None = None
    https_port: int
    http_port: int
    #: nginx's plain port: the address once HTTPS is off, and TVs' always.
    app_port: int = 8080
    #: Uploaded certificate files: who they are for, and until when.
    files: dict | None = None
    env_connected: bool
    #: While the last change is on trial: when it is undone by itself.
    trial_until: datetime | None = None
    #: What Undo goes back to, or null when there is nothing to undo.
    undo_to: UndoTo | None = None
    #: Advanced → Web address, when set: links keep using it whatever HTTPS is.
    web_address_override: str | None = None
    #: `.env` can be read (edits there are followed) though perhaps not
    #: written (`env_connected`) — P7-2.
    env_readable: bool = False


class HttpsUpdate(BaseModel):
    on: bool
    host: str = ""
    certificate: str = "internal"
    dns_provider: str = ""
    #: Null keeps the stored token; empty removes it.
    dns_api_token: str | None = None
    acme_email: str = ""
    #: "" for Caddy in Docker, or `cloudflare` for a tunnel (Phase 21).
    front_door: str = ""
    #: The tunnel token, or whatever Cloudflare's page offered with it in —
    #: the token is found inside. Null keeps the stored one.
    tunnel_token: str | None = Field(default=None, max_length=5000)
    #: Try it beside the old setup until kept or undone (Phase 22).
    trial: bool = False


class CheckRequest(HttpsUpdate):
    #: The name this browser reached GoalGetter by, to compare DNS against.
    seen_at: str = Field(default="", max_length=253)


class Check(BaseModel):
    key: str
    #: ok | warn | fail | wait
    state: str
    label: str
    detail: str | None = None


class UndoRequest(BaseModel):
    #: Try the setup it goes back to, as with any change.
    trial: bool = False


class Checks(BaseModel):
    checks: list[Check]
    #: While a change is on trial: when it is undone by itself.
    trial_until: datetime | None = None


class HttpsApplied(BaseModel):
    settings: HttpsSettings
    #: Why the HTTPS service did not take it, or null when it did.
    problem: str | None = None


def _addresses_visible(db: DbSession, request: Request) -> bool:
    """Whether any device's real address has reached GoalGetter lately.

    This request first: if the admin's own address is visible, they are.
    Otherwise the last month's sessions — on Linux the server's own browser
    arrives as Docker's address while everybody else's devices do not, so
    one look at your own connection is not the whole answer.
    """
    if visitor_ip(request, db):
        return True
    since = datetime.now(UTC) - timedelta(days=30)
    recent = db.scalars(
        select(Session.ip_address)
        .where(Session.ip_address.is_not(None), Session.created_at >= since)
        .limit(500)
    ).all()
    return any(not hidden_by_docker(str(address)) for address in recent)


@router.get("", response_model=Hosting)
def read_hosting(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Hosting:
    current = hosting_config.current(db)
    db.commit()
    host = current.host if current.https_on else None
    port = "" if current.http_port == 80 else f":{current.http_port}"
    # Through Cloudflare the certificate is Cloudflare's, trusted everywhere,
    # and the name leads to Cloudflare rather than to this server — so there
    # is no root certificate to hand out, and TVs need the server's own
    # address, which only the admin knows.
    cloudflare = current.front_door == "cloudflare"
    internal = bool(host) and current.certificate == "internal" and not cloudflare
    return Hosting(
        https=bool(host),
        https_address=current.https_address,
        certificate=("cloudflare" if cloudflare else current.certificate) if host else None,
        root_certificate_url=f"http://{host}{port}/goalgetter-root.crt" if internal else None,
        tv_address=_tv_address(current),
        sso_redirect=f"{public_url.get(db)}{SSO_CALLBACK}",
        addresses_visible=_addresses_visible(db, request),
        env_connected=current.env_connected,
        tunnel=TunnelStatus(**hosting_config.tunnel_status(current)) if current.tunnel_runs else None,
        trial_until=current.trial_until if current.on_trial else None,
        app_port=current.app_port,
        **_connection(db, request, current),
        **_status(db, current),
    )


def _tv_address(current: hosting_config.Hosting) -> str | None:
    """Where TVs go: the HTTPS name on the plain port. During a trial, the
    setup that is certain until it is kept (P7-17)."""
    setup = current.undo_to if current.on_trial else current
    if setup is None or not setup.https_on or setup.front_door == "cloudflare":
        # Through Cloudflare the name leads to Cloudflare, not this server:
        # TVs use the server's own address, which only the admin knows.
        return None
    return f"http://{setup.host}:{current.app_port}"


def _status(db: DbSession, current) -> dict:
    from app import certificate_probe

    chosen = public_url.chosen(db)
    https = current.https_address
    served = certificate_probe.served(current)
    return {
        "web_address": public_url.get(db),
        "web_address_from": "settings" if chosen else "https" if https else "env",
        "certificate_valid_until": served.valid_until if served else None,
        "certificate_issuer": served.issuer if served else None,
    }


def _connection(db: DbSession, request: Request, current) -> dict:
    from app import rate_limit
    from app.models import Organization

    seen = visitor_ip(request, db)
    settings = get_settings()
    hops = proxy_hops(db)
    last = real_client_ip(request, settings.trusted_proxy_ips, hops)
    mode = db.scalar(select(Organization.proxy_mode).order_by(Organization.id).limit(1))
    return {
        "you_appear_as": seen,
        "connection": "visible" if seen else "docker" if hidden_by_docker(last) else "unknown",
        "proxies_seen": len(forwarded_chain(request)),
        "proxy_hops": hops,
        "proxy_hops_from": "settings" if mode else "env",
        "front_door": current.front_door or None,
        "sign_in_limits": list(rate_limit.limits(db)),
    }


# ── HTTPS, set up here (Phase 20) ────────────────────────────────────────────


def _files_summary() -> dict | None:
    """Who the uploaded certificate is for, and until when, or None."""
    from cryptography import x509

    path = os.path.join(hosting_config.CERTS_DIR, "cert.pem")
    try:
        with open(path, "rb") as handle:
            cert = x509.load_pem_x509_certificate(handle.read())
    except (OSError, ValueError):
        return None
    try:
        names = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.DNSName
        )
    except x509.ExtensionNotFound:
        names = []
    return {"names": list(names), "valid_until": cert.not_valid_after_utc.isoformat()}


def _choice(hosting: hosting_config.Hosting) -> str:
    return "cloudflare" if hosting.front_door == "cloudflare" else hosting.certificate


def _settings_out(current: hosting_config.Hosting, db: DbSession) -> HttpsSettings:
    old = current.undo_to
    return HttpsSettings(
        on=current.on,
        host=current.host,
        certificate=current.certificate,
        dns_provider=current.dns_provider,
        has_dns_api_token=bool(current.dns_api_token),
        acme_email=current.acme_email,
        front_door=current.front_door or None,
        has_tunnel_token=bool(current.tunnel_token),
        tunnel_id=hosting_config.tunnel_id(current.tunnel_token) if current.tunnel_token else None,
        https_port=current.https_port,
        http_port=current.http_port,
        app_port=current.app_port,
        files=_files_summary(),
        env_connected=current.env_connected,
        trial_until=current.trial_until if current.on_trial else None,
        undo_to=UndoTo(on=old.https_on, host=old.host, choice=_choice(old), redo=current.undo_is_redo) if old else None,
        web_address_override=public_url.chosen(db),
        env_readable=current.env_readable,
    )


@router.get("/https", response_model=HttpsSettings)
def read_https(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> HttpsSettings:
    current = hosting_config.current(db)
    db.commit()
    return _settings_out(current, db)


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _check_certificate(payload: HttpsUpdate, before: hosting_config.Hosting) -> None:
    """For Caddy in Docker: the certificate choice has what it needs."""
    if payload.certificate not in hosting_config.CERTIFICATES:
        raise _refuse("Choose where the certificate comes from.")
    if payload.certificate == "letsencrypt":
        if payload.dns_provider not in hosting_config.DNS_PROVIDERS:
            raise _refuse("Choose Cloudflare or DuckDNS for Let's Encrypt.")
        token = payload.dns_api_token if payload.dns_api_token is not None else before.dns_api_token
        if not token or not hosting_config.TOKEN_PATTERN.match(token):
            raise _refuse("Paste the API token from your DNS provider.")
        if payload.acme_email and not hosting_config.EMAIL_PATTERN.match(payload.acme_email):
            raise _refuse("That email address doesn't look right.")
    if payload.certificate == "files" and _files_summary() is None:
        raise _refuse("Upload the certificate and its key first.")


@router.put("/https", response_model=HttpsApplied)
def update_https(
    payload: HttpsUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> HttpsApplied:
    """Save HTTPS and apply it at once: Caddy is reconfigured while it runs,
    the tunnel started or stopped, nginx's TV-only port follows, and `.env`
    is written to match. With `trial`, it runs beside the old setup until
    kept or undone."""
    before = hosting_config.current(db, sync_first=False)
    host, tunnel, tunnel_token = _proposal(payload, before)
    if payload.on:
        if tunnel:
            if not (tunnel_token or before.tunnel_token):
                raise _refuse("Paste the tunnel token from Cloudflare.")
        else:
            _check_certificate(payload, before)

    current = hosting_config.save(
        db,
        trial=payload.trial,
        https_on=payload.on,
        https_host=host or before.host,
        front_door="cloudflare" if tunnel else "",
        tunnel_token=tunnel_token,
        certificate=payload.certificate if payload.certificate in hosting_config.CERTIFICATES else "internal",
        dns_provider=payload.dns_provider if payload.dns_provider in hosting_config.DNS_PROVIDERS else "",
        dns_api_token=payload.dns_api_token,
        acme_email=payload.acme_email.strip(),
    )
    audit.record(
        db, actor=actor, action="hosting.https_changed", request=request,
        on=payload.on, host=host, certificate="cloudflare" if tunnel else payload.certificate,
    )
    db.commit()
    problem = hosting_config.apply(current, force=True)
    return HttpsApplied(settings=_settings_out(current, db), problem=problem)


def _proposal(payload: HttpsUpdate, before: hosting_config.Hosting) -> tuple[str, bool, str | None]:
    """The name, whether it is a tunnel, and the tunnel token pasted — or a
    refusal in words."""
    host = payload.host.strip().lower()
    if before.front_door == "windows":
        raise _refuse(
            "HTTPS is handled by the Windows front door. Remove it first "
            "(windows\\install-front-door.ps1 -Remove)."
        )
    tunnel_token = None
    if payload.tunnel_token is not None and payload.tunnel_token.strip():
        tunnel_token = hosting_config.tunnel_token_from(payload.tunnel_token)
        if tunnel_token is None:
            raise _refuse("That isn't a tunnel token. Copy it from Cloudflare — it starts with eyJ.")
    if payload.on and (not hosting_config.HOST_PATTERN.match(host) or "://" in host):
        raise _refuse("Enter just the name, like goals.internal — no https:// and no port.")
    return host, payload.front_door == "cloudflare", tunnel_token


@router.post("/check", response_model=Checks)
def check_change(
    payload: CheckRequest,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Checks:
    """Before switching over: what can be known without changing anything —
    the name in DNS, the DNS provider's token, the certificate files, the
    tunnel token. Nothing is saved."""
    from app import hosting_checks

    before = hosting_config.current(db, sync_first=False)
    host, tunnel, tunnel_token = _proposal(payload, before)
    checks = hosting_checks.before_switching(
        on=payload.on,
        host=host,
        choice="cloudflare" if tunnel else payload.certificate,
        dns_provider=payload.dns_provider,
        dns_token=payload.dns_api_token if payload.dns_api_token is not None else before.dns_api_token,
        tunnel_token=tunnel_token or before.tunnel_token,
        seen_at=payload.seen_at.strip(),
    )
    return Checks(checks=[Check(**c) for c in checks])


@router.get("/trial", response_model=Checks)
def read_trial(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Checks:
    """While a change is tried: whether it works, as the server sees it.
    Asked every few seconds by the page."""
    from app import hosting_checks

    current = hosting_config.current(db, sync_first=False)
    return Checks(
        checks=[Check(**c) for c in hosting_checks.during_trial(current)],
        trial_until=current.trial_until if current.on_trial else None,
    )


@router.post("/keep", response_model=HttpsApplied)
def keep_change(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> HttpsApplied:
    """The change on trial becomes the setup: the old site goes, and the
    plain port serves TVs only if HTTPS is on."""
    if not hosting_config.current(db, sync_first=False).on_trial:
        raise _refuse("There is no change waiting to be kept.")
    current = hosting_config.keep(db)
    audit.record(db, actor=actor, action="hosting.change_kept", request=request, host=current.host)
    db.commit()
    problem = hosting_config.apply(current, force=True)
    return HttpsApplied(settings=_settings_out(current, db), problem=problem)


@router.post("/undo", response_model=HttpsApplied)
def undo_change(
    request: Request,
    payload: UndoRequest | None = None,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> HttpsApplied:
    """Back to the setup before the last change, whether it was kept or is
    still on trial — tried first, with `trial`, like any change."""
    before = hosting_config.current(db, sync_first=False)
    if before.front_door == "windows" or (before.undo_to and before.undo_to.front_door == "windows"):
        # The front door is its installer's to switch, like every other change
        # while it is set (P7-6).
        raise _refuse(
            "HTTPS is handled by the Windows front door, which its installer sets up and removes "
            "(windows\\install-front-door.ps1 -Remove)."
        )
    current = hosting_config.undo(db, trial=bool(payload and payload.trial))
    if current is None:
        raise _refuse("There is nothing to undo.")
    audit.record(db, actor=actor, action="hosting.change_undone", request=request, host=current.host)
    db.commit()
    problem = hosting_config.apply(current, force=True)
    return HttpsApplied(settings=_settings_out(current, db), problem=problem)


class CertificateUpload(BaseModel):
    #: The files' contents. PEM is text, so the page reads each file and
    #: sends what is in it — no multipart form, as with every upload here.
    certificate: str = Field(max_length=200_000)
    key: str = Field(max_length=200_000)


@router.post("/certificate", response_model=HttpsSettings)
def upload_certificate(
    payload: CertificateUpload,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> HttpsSettings:
    """Certificate files from IT, uploaded in the browser instead of copied
    into a folder. Checked before anything is written: a certificate, its
    own key, and not expired."""
    from datetime import UTC, datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert_bytes = payload.certificate.encode()
    key_bytes = payload.key.encode()
    try:
        cert = x509.load_pem_x509_certificate(cert_bytes)
    except ValueError:
        raise _refuse("That isn't a certificate in PEM format (it starts with -----BEGIN CERTIFICATE-----).")
    try:
        private = serialization.load_pem_private_key(key_bytes, password=None)
    except (ValueError, TypeError):
        raise _refuse("That isn't an unencrypted private key in PEM format.")
    if private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ) != cert.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ):
        raise _refuse("That key doesn't belong to that certificate.")
    if cert.not_valid_after_utc <= datetime.now(UTC):
        raise _refuse("That certificate has expired.")

    try:
        os.makedirs(hosting_config.CERTS_DIR, exist_ok=True)
        for name, data in (("key.pem", key_bytes), ("cert.pem", cert_bytes)):
            path = os.path.join(hosting_config.CERTS_DIR, name)
            # The key readable by its owner only, from the moment it exists.
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if name == "key.pem" else 0o644)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
        try:
            os.chmod(os.path.join(hosting_config.CERTS_DIR, "key.pem"), 0o600)
        except OSError:
            pass  # A Windows folder shared into Docker has no such modes.
    except OSError:
        raise _refuse("The app can't write to volumes/certs on this server. Copy the two files there instead.")
    audit.record(db, actor=actor, action="hosting.certificate_uploaded", request=request)
    db.commit()
    current = hosting_config.current(db, sync_first=False)
    if current.caddy_serves and current.certificate == "files":
        hosting_config.apply(current, force=True)
    return _settings_out(current, db)


@router.get("/tunnel", response_model=TunnelStatus)
def read_tunnel(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TunnelStatus:
    """Whether the Cloudflare tunnel is connected — asked every few seconds
    by the page right after it is turned on."""
    return TunnelStatus(**hosting_config.tunnel_status(hosting_config.current(db, sync_first=False)))


@router.delete("/web-address", response_model=HttpsSettings)
def clear_web_address(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> HttpsSettings:
    """Advanced → Web address, cleared — so links follow HTTPS. One press
    from the guided change's warning (P7-1)."""
    from app.models import Organization

    org = db.scalar(select(Organization).order_by(Organization.id).limit(1))
    if org is not None and org.public_url:
        audit.record(db, actor=actor, action="hosting.web_address_cleared", request=request, was=org.public_url)
        org.public_url = None
        db.flush()
    current = hosting_config.current(db)
    db.commit()
    return _settings_out(current, db)
