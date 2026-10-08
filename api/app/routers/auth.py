import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import mail, mfa, sign_in, tokens
from app.db import get_db
from app.models import Organization, SsoConfig, UserAccount
from app.net import visitor_ip
from app.rate_limit import (
    clear_failures,
    is_locked_out,
    record_attempt,
    seconds_until_unlock,
)
from app.scope import capabilities_for
from app.security import NewPassword, hash_password, verify_password
from app.sessions import COOKIE_NAME, create_session, current_user, revoke_session

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when no account matches, so a request for an address that
# doesn't exist costs the same time as one that does. Without this, response
# timing reveals which email addresses are real — a way to enumerate everyone
# who works at the company.
#
# It must be a REAL hash. A hand-written placeholder like "$2b$12$" + "."*53
# is malformed, so bcrypt rejects it instantly instead of doing the work — and
# a nonexistent account then answers measurably faster, which is the exact leak
# this is meant to close. Measured at a 43ms gap before this was fixed.
#
# Hashing a random string at import costs ~250ms once at startup.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def _humanize(seconds: int) -> str:
    """"in 3 minutes" reads better than "in 172 seconds"."""
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CurrentUser(BaseModel):
    id: int
    email: str
    full_name: str
    #: What people call them. Sent with the session so their own account page
    #: can show it without a second request for a record it already has.
    nickname: str = ""
    #: Sent with the session so somebody's own account page can show it without
    #: a second request for a record it already has.
    birthday_month: int | None = None
    birthday_day: int | None = None
    org_role: str
    organization_id: int
    team_id: int | None = None
    # Resolved server-side so the UI never reimplements the permission rules.
    # Adding a role later changes one map on the server and the interface
    # follows, instead of every component growing another role comparison.
    capabilities: list[str] = []
    #: Content hash of their photo, or null for initials. Here so the shell can
    #: draw a face on first paint rather than after a second request.
    photo_digest: str | None = None
    #: Whether "use the default" would change anything. Sent rather than
    #: inferred, because a photo being present says nothing about *which* of the
    #: two slots it came from.
    has_custom_photo: bool = False
    #: Whether they can sign in with a password at all. Somebody who only
    #: ever signs in with Microsoft has none, so "Change password" — which
    #: asks for the current one — could never work for them (QA-33).
    has_password: bool = True
    #: Their password was set by an admin (11.2): the app shows nothing but
    #: "choose your own" until they do, and the server refuses the rest.
    must_change_password: bool = False


def _capabilities(user: UserAccount) -> list[str]:
    """The role's abilities, plus `people.view` where names should be links
    to profiles (9.3) — decided by the organization's switch, so it needs the
    session the user was loaded in."""
    from sqlalchemy.orm import object_session

    from app import people

    found = capabilities_for(user.org_role, user)
    db = object_session(user)
    if db is not None and people.links_to_profiles(db, user):
        found = sorted({*found, people.PEOPLE_VIEW})
    return found


def _current_user(user: UserAccount) -> CurrentUser:
    return CurrentUser(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        nickname=user.nickname,
        birthday_month=user.birthday_month,
        birthday_day=user.birthday_day,
        org_role=user.org_role,
        organization_id=user.organization_id,
        team_id=user.team_id,
        capabilities=_capabilities(user),
        photo_digest=user.photo_digest,
        has_custom_photo=user.custom_photo_image_id is not None,
        has_password=user.password_hash is not None,
        must_change_password=user.must_change_password,
    )


@router.post(
    "/login",
    response_model=CurrentUser,
    responses={202: {"description": "The password was right; a second step is owed."}},
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
) -> CurrentUser | JSONResponse:
    # One message for every failure mode: wrong password, no such account,
    # suspended account, rate limited. Telling them apart would confirm which
    # addresses exist, which are disabled, and which are under attack.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password.",
    )

    ip = visitor_ip(request, db)

    if is_locked_out(db, payload.email, ip):
        # Says plainly that the account is locked, rather than repeating
        # "incorrect password" — otherwise the user keeps clicking and nothing
        # appears to happen.
        #
        # This is safe to disclose only because addresses that DO NOT EXIST
        # lock out on exactly the same terms (verified: 5 recorded attempts for
        # an unknown address). So the message says "this identifier has had 5
        # recent failures" — which the attacker already knows, having caused
        # them — and reveals nothing about whether an account exists.
        #
        # Because the state is now explicit, there is no longer anything to
        # hide with a constant-time dummy hash. Returning immediately is both
        # honest and cheaper: a locked-out attempt costs no bcrypt work, so the
        # limit protects CPU as well as the account.
        wait = seconds_until_unlock(db, payload.email, ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many sign-in attempts. Try again in {_humanize(wait)}.",
            # The standard header for this, so any HTTP client can back off
            # correctly without parsing the message.
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(
        select(UserAccount).where(
            func.lower(UserAccount.email) == payload.email.lower()
        )
    )

    def fail() -> HTTPException:
        record_attempt(db, payload.email, ip, succeeded=False)
        db.commit()
        return invalid

    if user is None:
        verify_password(payload.password, _DUMMY_HASH)  # keep timing constant
        raise fail()

    if not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise fail()

    if user.status != "active" or user.hidden_at is not None:
        raise fail()

    # Enforce "require SSO" here, where the decision is made: anyone can POST
    # to this endpoint whatever the page draws. It binds people in the
    # directory and never an admin — `app/sign_in.py` says why — and refuses
    # with the same words as a wrong password, so this says nothing about who
    # is in the directory (11.1).
    if sign_in.must_use_sso(db, user):
        raise fail()
    # The password was right, so saying why is no leak (Phase 28).
    if sign_in.leaders_only_refuses(db, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=sign_in.LEADERS_ONLY)

    record_attempt(db, payload.email, ip, succeeded=True)
    # A correct password clears the account's failures, so earlier typos don't
    # count against someone who has since signed in.
    clear_failures(db, payload.email)

    # **Two-step sign-in: the password was right, and that is not a session.**
    # 202 with a challenge — encrypted, five minutes long — and nothing else;
    # `routers/mfa.py` turns it into a session once a code (or a new
    # authenticator, when one is required) is given.
    org = db.get(Organization, user.organization_id)
    stage = "code" if mfa.is_enabled(user) else "setup" if org and org.require_mfa else None
    if stage is not None:
        db.commit()
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"mfa": stage, "challenge": mfa.challenge_for(user, stage)},
        )

    user.last_login_at = datetime.now(UTC)
    create_session(db, user, request, response)
    db.commit()

    return _current_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
) -> None:
    """Always succeeds, even without a valid session — logging out should never
    fail or reveal whether the session was real."""
    revoke_session(db, request.cookies.get(COOKIE_NAME), response)
    db.commit()


class AcceptInviteRequest(BaseModel):
    token: str
    password: NewPassword


@router.post("/accept-invite", response_model=CurrentUser)
def accept_invite(
    payload: AcceptInviteRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
) -> CurrentUser:
    """Set a password from an invitation link and sign in.

    One message for every failure — missing token, wrong purpose, expired,
    already-activated account. Distinguishing them would tell someone holding a
    stale link whether it was ever real, and whether the account exists.
    """
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="This invitation link is no longer valid. Ask an administrator for a new one.",
    )

    user_id = tokens.consume(db, payload.token, "invite")
    if user_id is None:
        # consume() may have deleted an expired row, so the commit matters.
        db.commit()
        raise invalid

    user = db.get(UserAccount, user_id)
    if user is None or user.hidden_at is not None or user.status == "suspended":
        db.commit()
        raise invalid

    user.password_hash = hash_password(payload.password)
    user.status = "active"
    user.last_login_at = datetime.now(UTC)

    # Signed in immediately: they have just proved control of the invited
    # address and chosen a password, so making them type it again adds nothing.
    create_session(db, user, request, response)
    db.commit()

    return _current_user(user)


class AuthProviders(BaseModel):
    """What sign-in methods the login page should offer.

    Public on purpose — it reveals only which buttons to draw, which anyone
    can see by loading the login page anyway. Making the UI guess, or shipping
    the answer in the bundle, would mean a rebuild every time an admin toggles
    SSO.
    """

    #: Always true now (11.1): somebody outside the directory signs in with a
    #: password whatever SSO requires. Kept so an older page still draws it.
    local: bool
    sso_enabled: bool
    sso_button_label: str
    #: SSO is required of people in the directory — so the page leads with
    #: the button and says the form is for everybody else.
    sso_required: bool = False
    #: Mail can be sent, so "Forgot password?" emails a link (Phase 14);
    #: otherwise the page says to ask an admin. Says nothing about accounts.
    self_reset: bool = False


def _can_send(db: DbSession) -> bool:
    org_id = db.scalar(select(Organization.id).order_by(Organization.id).limit(1))
    return org_id is not None and mail.can_send(db, org_id)


@router.get("/providers", response_model=AuthProviders)
def providers(db: DbSession = Depends(get_db)) -> AuthProviders:
    config = db.scalar(select(SsoConfig).where(SsoConfig.enabled.is_(True)))
    return AuthProviders(
        # The form is always offered: requiring SSO binds the directory, and
        # admins and people set up by hand still sign in with a password. Who
        # may is decided in `login`, never by what this page is told.
        local=True,
        sso_required=bool(config and config.require_sso),
        self_reset=_can_send(db),
        sso_enabled=bool(config),
        sso_button_label=config.button_label if config else "Sign in with SSO",
    )


@router.get("/me", response_model=CurrentUser)
def me(user: UserAccount = Depends(current_user)) -> CurrentUser:
    """Who am I? Used by the frontend on load to decide whether to show the
    app or the login screen."""
    return _current_user(user)
