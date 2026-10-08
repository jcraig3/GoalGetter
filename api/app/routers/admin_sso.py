import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import providers, sso_roles
from app.db import get_db
from app.models import OauthClient, SsoConfig, UserAccount
from app.sessions import require_role

router = APIRouter(prefix="/admin/sso", tags=["admin"])

DISCOVERY_PATH = "/.well-known/openid-configuration"


class RoleRule(BaseModel):
    group: str = Field(max_length=200)
    role: str


class SsoSettings(BaseModel):
    """What the admin screen shows.

    **No credential in here at all any more, and that is the point.** The client id
    and secret belong to the provider connection, which is edited on the
    Integrations page and serves signing in, reading spreadsheets and — later —
    syncing people from the same app registration. This endpoint is now only about
    the behaviour of signing in.

    `issuer` and `connected` are reported rather than accepted: they are read off
    the connection so the screen can say *why* SSO cannot be enabled yet without
    the admin having to go and look.
    """

    enabled: bool
    provider: str | None
    #: Derived from the connection. Shown, never submitted.
    issuer: str | None
    #: Whether the named connection exists and holds a secret.
    connected: bool
    scopes: str
    button_label: str
    auto_provision: bool
    require_sso: bool
    #: Roles from groups. See `app/sso_roles.py`.
    role_sync: bool = False
    role_rules: list[RoleRule] = []


class SsoUpdate(BaseModel):
    enabled: bool = False
    #: Which provider connection signs people in. None unpoints it.
    provider: str | None = Field(default=None, max_length=64)
    scopes: str = "openid profile email"
    button_label: str = Field(default="Sign in with SSO", max_length=100)
    auto_provision: bool = False
    require_sso: bool = False
    #: Absent leaves them as they are — an older screen saving the rest of the
    #: sign-in settings must not wipe the group rules.
    role_sync: bool | None = None
    role_rules: list[RoleRule] | None = None


class TestResult(BaseModel):
    ok: bool
    detail: str
    authorization_endpoint: str | None = None


def _get_or_create(db: DbSession, organization_id: int) -> SsoConfig:
    config = db.scalar(
        select(SsoConfig).where(SsoConfig.organization_id == organization_id)
    )
    if config is None:
        config = SsoConfig(organization_id=organization_id)
        db.add(config)
        db.flush()
    return config


def _connection(db: DbSession, config: SsoConfig) -> OauthClient | None:
    if not config.provider:
        return None
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == config.organization_id,
            OauthClient.provider == config.provider,
        )
    )


def _issuer_of(config: SsoConfig, connection: OauthClient | None) -> str:
    if connection is None:
        return ""
    return providers.issuer_for(
        config.provider or "",
        tenant_id=connection.tenant_id or "",
        stored=connection.issuer or "",
    )


def _to_settings(config: SsoConfig, connection: OauthClient | None) -> SsoSettings:
    issuer = _issuer_of(config, connection)
    return SsoSettings(
        enabled=config.enabled,
        provider=config.provider,
        issuer=issuer or None,
        connected=bool(connection and connection.client_secret_encrypted and issuer),
        scopes=config.scopes,
        button_label=config.button_label,
        auto_provision=config.auto_provision,
        require_sso=config.require_sso,
        role_sync=config.role_sync,
        role_rules=[RoleRule(**rule) for rule in (config.role_rules or [])],
    )


@router.get("", response_model=SsoSettings)
def get_sso(
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SsoSettings:
    config = _get_or_create(db, user.organization_id)
    connection = _connection(db, config)
    db.commit()
    return _to_settings(config, connection)


@router.put("", response_model=SsoSettings)
def update_sso(
    payload: SsoUpdate,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SsoSettings:
    config = _get_or_create(db, user.organization_id)

    if payload.provider is not None and not providers.capability(payload.provider, "sso"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{payload.provider!r} cannot be used to sign in.",
        )

    config.provider = payload.provider or None
    config.scopes = payload.scopes
    config.button_label = payload.button_label
    config.auto_provision = payload.auto_provision
    config.require_sso = payload.require_sso
    if payload.role_rules is not None:
        try:
            config.role_rules = sso_roles.check_rules([r.model_dump() for r in payload.role_rules])
        except ValueError as problem:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)) from None
    if payload.role_sync is not None:
        if payload.role_sync and not (config.role_rules or []):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Add at least one group rule before switching roles from groups on.",
            )
        config.role_sync = payload.role_sync

    connection = _connection(db, config)

    # Refusing to enable a half-configured provider is the difference between an
    # error the admin sees now and one every user hits at their next login. The
    # message names the missing half, because the fix is on a different page and
    # "SSO is not configured" would not say which page.
    if payload.enabled:
        if connection is None or not connection.client_secret_encrypted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Connect this provider first — signing in uses the same "
                    "application registration as everything else."
                ),
            )
        if not _issuer_of(config, connection):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "That connection has no issuer yet. Add the directory (tenant) "
                    "ID, or the issuer URL, on the Integrations page."
                ),
            )

    config.enabled = payload.enabled
    db.commit()
    return _to_settings(config, connection)


@router.post("/test", response_model=TestResult)
def test_sso(
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TestResult:
    """Fetch the provider's discovery document.

    Run while the admin is still looking at the screen, so a wrong issuer is
    caught here rather than at someone's next sign-in attempt.
    """
    config = _get_or_create(db, user.organization_id)
    connection = _connection(db, config)
    issuer = _issuer_of(config, connection)
    db.commit()

    if not issuer:
        return TestResult(
            ok=False,
            detail=(
                "No identity provider is connected yet. Connect one on the "
                "Integrations page."
            ),
        )

    url = f"{issuer}{DISCOVERY_PATH}"
    try:
        # Short timeout: this is a person waiting on a button, and a provider
        # that takes 10 seconds to answer is a failure worth reporting.
        response = httpx.get(url, timeout=5.0, follow_redirects=True)
    except httpx.RequestError as exc:
        return TestResult(ok=False, detail=f"Could not reach {url} ({type(exc).__name__}).")

    if response.status_code != 200:
        return TestResult(ok=False, detail=f"{url} returned HTTP {response.status_code}.")

    try:
        document = response.json()
    except ValueError:
        return TestResult(ok=False, detail="Discovery document was not valid JSON.")

    missing = [
        field
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri")
        if field not in document
    ]
    if missing:
        return TestResult(ok=False, detail=f"Discovery document is missing: {', '.join(missing)}.")

    return TestResult(
        ok=True,
        detail="Provider reachable and the discovery document looks valid.",
        authorization_endpoint=document["authorization_endpoint"],
    )
