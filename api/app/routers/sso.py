import logging
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import oidc, providers, public_url, sign_in
from app.crypto import decrypt
from app.db import get_db
from app.models import OauthClient, SsoConfig, UserAccount
from app.sessions import create_session, secure_cookie

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/sso", tags=["auth"])

FLOW_COOKIE = "gg_sso_flow"
CALLBACK_PATH = "/api/auth/sso/callback"


def _config(db: DbSession) -> SsoConfig | None:
    """Read config fresh on every request.

    Deliberately not cached: an admin saving new settings must take effect
    immediately, which is the entire reason this lives in the database rather
    than in environment variables.
    """
    return db.scalar(select(SsoConfig).where(SsoConfig.enabled.is_(True)))


def _connection(db: DbSession, config: SsoConfig) -> OauthClient | None:
    """The provider connection this deployment signs people in with.

    The credential is no longer part of `sso_config` — one app registration serves
    signing in and reading data, so it is held once on `oauth_client`. Read on the
    same request as the config, for the same reason: an admin who has just fixed a
    typo expects the next sign-in to use it.
    """
    if not config.provider:
        return None
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == config.organization_id,
            OauthClient.provider == config.provider,
        )
    )


def _issuer(config: SsoConfig, connection: OauthClient | None) -> str:
    """Where to discover the provider's endpoints.

    Derived from the tenant id for Microsoft and taken verbatim for anything else,
    in `app.providers` — one place decides, so the issuer a token is validated
    against cannot drift from the one the sign-in was started at.
    """
    if connection is None:
        return ""
    return providers.issuer_for(
        config.provider or "",
        tenant_id=connection.tenant_id or "",
        stored=connection.issuer or "",
    )


def _fail(message: str) -> RedirectResponse:
    """Send the browser back to the login page with a readable message.

    This is a redirect flow, so returning a JSON error would leave the user
    staring at raw text in the address bar. The message is deliberately vague
    about *why* — details go to the log, not to the person at the keyboard.
    """
    return RedirectResponse(f"/login?error={quote(message)}", status_code=303)


@router.get("/start")
def start(request: Request, db: DbSession = Depends(get_db)) -> RedirectResponse:
    config = _config(db)
    connection = _connection(db, config) if config else None
    issuer = _issuer(config, connection) if config else ""
    if not config or connection is None or not issuer:
        return _fail("Single sign-on is not configured.")

    try:
        document = oidc.discover(issuer)
    except Exception as exc:
        logger.warning("OIDC discovery failed for %s", issuer, exc_info=exc)
        return _fail("Could not reach the identity provider.")

    flow = oidc.new_flow_state()
    next_path = request.query_params.get("next", "/")
    # Only relative paths: an absolute URL here would turn the login flow into
    # an open redirect that could bounce users to an attacker's site.
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"

    response = RedirectResponse(
        oidc.authorization_url(
            document,
            client_id=connection.client_id,
            redirect_uri=f"{public_url.get(db)}{CALLBACK_PATH}",
            scopes=config.scopes,
            flow=flow,
        ),
        status_code=303,
    )
    response.set_cookie(
        FLOW_COOKIE,
        oidc.seal_flow(flow, next_path),
        httponly=True,
        secure=secure_cookie(request),
        # Must be "lax", not "strict": the provider redirects the browser back
        # to us cross-site, and a strict cookie would not be sent on that
        # request — so the state check would fail every time.
        samesite="lax",
        max_age=oidc.FLOW_TTL_SECONDS,
        path="/",
    )
    return response


@router.get("/callback")
def callback(request: Request, db: DbSession = Depends(get_db)) -> RedirectResponse:
    sealed = request.cookies.get(FLOW_COOKIE)
    if not sealed:
        return _fail("Sign-in session expired. Please try again.")

    try:
        flow, next_path = oidc.open_flow(sealed)
    except ValueError as exc:
        # One message for both "expired" and "tampered", with the reason logged
        # rather than shown. Passing str(exc) through put an internal crypto
        # error into the browser's address bar — meaningless to a user, and it
        # told an attacker their tampering had been detected as tampering
        # rather than as an ordinary timeout.
        logger.info("Rejected SSO flow cookie: %s", exc)
        return _fail("Sign-in session expired. Please try again.")

    # The provider reports its own failures here (consent denied, etc.).
    if error := request.query_params.get("error"):
        logger.info("OIDC provider returned error: %s", error)
        return _fail("The identity provider rejected the sign-in.")

    # Compare BEFORE doing anything with the code. A mismatch means this
    # callback did not originate from the flow we started.
    if request.query_params.get("state") != flow.state:
        return _fail("Sign-in verification failed. Please try again.")

    code = request.query_params.get("code")
    if not code:
        return _fail("The identity provider did not return an authorization code.")

    config = _config(db)
    connection = _connection(db, config) if config else None
    issuer = _issuer(config, connection) if config else ""
    if not config or connection is None or not issuer:
        return _fail("Single sign-on is not configured.")

    try:
        document = oidc.discover(issuer)
        tokens = oidc.exchange_code(
            document,
            code=code,
            redirect_uri=f"{public_url.get(db)}{CALLBACK_PATH}",
            client_id=connection.client_id,
            client_secret=decrypt(connection.client_secret_encrypted),
            code_verifier=flow.code_verifier,
        )
        claims = oidc.verify_id_token(
            document,
            tokens["id_token"],
            client_id=connection.client_id,
            issuer=issuer,
            nonce=flow.nonce,
        )
    except Exception as exc:
        # Detail to the log, not the browser — provider errors can echo back
        # request parameters.
        logger.warning("OIDC callback failed", exc_info=exc)
        return _fail("Could not complete sign-in with the identity provider.")

    subject = claims.get("sub")
    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    if not subject:
        return _fail("The identity provider did not return a user identifier.")

    user = _resolve_user(db, config, subject=subject, claims=claims, email=email)
    if user is None:
        return _fail("You do not have an account here. Ask an administrator for access.")

    # After the account is found or made, so a new account gets its role from
    # its groups on its very first sign-in rather than starting as an agent.
    from app import sso_roles

    sso_roles.apply(db, config, user, claims, email)

    from app import sign_in

    if sign_in.leaders_only_refuses(db, user):
        db.commit()
        return _fail(sign_in.LEADERS_ONLY)

    user.last_login_at = datetime.now(UTC)
    response = RedirectResponse(next_path, status_code=303)
    create_session(db, user, request, response)
    db.commit()
    response.delete_cookie(FLOW_COOKIE, path="/")
    return response


def _resolve_user(
    db: DbSession,
    config: SsoConfig,
    *,
    subject: str,
    claims: dict,
    email: str,
) -> UserAccount | None:
    """Find the local account this identity belongs to.

    Matched on the provider's `sub` first, falling back to email once. `sub` is
    stable and unique forever; email addresses get changed when people marry or
    the company rebrands its domain. Matching on email alone would silently
    create a second account for the same person.
    """
    user = db.scalar(
        select(UserAccount).where(UserAccount.external_subject_id == subject)
    )

    if user is None and email:
        user = db.scalar(
            select(UserAccount).where(func.lower(UserAccount.email) == email)
        )
        if user is not None:
            # First SSO sign-in for an existing local account: remember the
            # subject so later sign-ins match on it directly.
            user.external_subject_id = subject

    # **Invited, then signed in with their work account**: that is the
    # invitation accepted, not a reason to refuse them. It was refused, because
    # only `active` gets past the check below.
    if user is not None:
        sign_in.activate(db, user)

    if user is None:
        if not config.auto_provision or not email:
            return None
        user = UserAccount(
            organization_id=config.organization_id,
            email=email,
            full_name=claims.get("name") or email,
            org_role="agent",
            status="active",
            external_subject_id=subject,
            # No password_hash: this account can only ever sign in via SSO.
        )
        db.add(user)
        db.flush()

    if user.status != "active" or user.hidden_at is not None:
        return None

    return user
