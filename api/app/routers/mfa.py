"""Two-step sign-in: the second step of a password sign-in, and managing your
own authenticator.

Two halves. The **sign-in half** takes the challenge a correct password
produced and finishes signing in — with a code, or, when the organization
requires two-step sign-in and this account has none, by setting one up there
and then. The **account half** is for somebody already signed in: turn it on,
see how many recovery codes are left, make new ones, turn it off.

**Rate-limited like passwords**, on the account rather than the address typed:
six digits is a million guesses, and five tries per window keeps it that way.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, mfa
from app.db import get_db
from app.models import Organization, UserAccount
from app.net import visitor_ip
from app.rate_limit import clear_failures, is_locked_out, record_attempt, seconds_until_unlock
from app.routers.auth import CurrentUser, _current_user, _humanize
from app.sessions import create_session, current_user, require_role

router = APIRouter(prefix="/auth", tags=["auth"])


class Challenge(BaseModel):
    challenge: str = Field(max_length=4000)


class ChallengeCode(Challenge):
    code: str = Field(max_length=40)


class Code(BaseModel):
    code: str = Field(max_length=40)


class SetupRead(BaseModel):
    #: For typing in by hand when a camera is not an option.
    secret: str
    #: What the QR code holds.
    uri: str


class EnabledRead(BaseModel):
    user: CurrentUser | None = None
    #: Shown once. Each works one time in place of a code.
    recovery_codes: list[str]


class StatusRead(BaseModel):
    enabled: bool
    #: Whether the organization requires it for password sign-in.
    required: bool
    #: Whether this account signs in with a password at all — SSO-only
    #: accounts get their second step from the identity provider.
    has_password: bool
    recovery_left: int


def _limit_key(user_id: int) -> str:
    return f"mfa:{user_id}"


def _from_challenge(db: DbSession, request: Request, token: str, stage: str) -> UserAccount:
    try:
        user_id, found = mfa.open_challenge(token)
    except ValueError as problem:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(problem)) from None
    user = db.get(UserAccount, user_id)
    if found != stage or user is None or user.status != "active" or user.hidden_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in again.")
    ip = visitor_ip(request, db)
    if is_locked_out(db, _limit_key(user.id), ip):
        wait = seconds_until_unlock(db, _limit_key(user.id), ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many codes tried. Try again in {_humanize(wait)}.",
            headers={"Retry-After": str(wait)},
        )
    return user


def _wrong_code(db: DbSession, request: Request, user: UserAccount) -> HTTPException:
    record_attempt(db, _limit_key(user.id), visitor_ip(request, db), succeeded=False)
    db.commit()
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="That code did not work.")


def _signed_in(db: DbSession, request: Request, response: Response, user: UserAccount) -> CurrentUser:
    clear_failures(db, _limit_key(user.id))
    user.last_login_at = datetime.now(UTC)
    create_session(db, user, request, response)
    db.commit()
    return _current_user(user)


# ── The second step of signing in ───────────────────────────────────────────


@router.post("/login/mfa", response_model=CurrentUser)
def login_code(
    payload: ChallengeCode,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
) -> CurrentUser:
    """Finish signing in with a code from the authenticator, or a recovery code."""
    user = _from_challenge(db, request, payload.challenge, "code")
    if not mfa.verify(db, user, payload.code):
        raise _wrong_code(db, request, user)
    return _signed_in(db, request, response, user)


@router.post("/login/mfa/setup", response_model=SetupRead)
def login_setup(
    payload: Challenge,
    request: Request,
    db: DbSession = Depends(get_db),
) -> SetupRead:
    """Required and not set up yet: a secret to scan, before signing in."""
    user = _from_challenge(db, request, payload.challenge, "setup")
    secret, uri = mfa.begin_setup(db, user)
    db.commit()
    return SetupRead(secret=secret, uri=uri)


@router.post("/login/mfa/enable", response_model=EnabledRead)
def login_enable(
    payload: ChallengeCode,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
) -> EnabledRead:
    """Confirm the new authenticator with a code, and sign in."""
    user = _from_challenge(db, request, payload.challenge, "setup")
    codes = mfa.confirm_setup(db, user, payload.code)
    if codes is None:
        raise _wrong_code(db, request, user)
    audit.record(db, actor=user, action="mfa.enabled", request=request, target=user)
    return EnabledRead(user=_signed_in(db, request, response, user), recovery_codes=codes)


# ── Your own account ────────────────────────────────────────────────────────


def _required(db: DbSession, user: UserAccount) -> bool:
    org = db.get(Organization, user.organization_id)
    return bool(org and org.require_mfa)


@router.get("/mfa", response_model=StatusRead)
def mfa_status(
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> StatusRead:
    return StatusRead(
        enabled=mfa.is_enabled(user),
        required=_required(db, user),
        has_password=bool(user.password_hash),
        recovery_left=len(user.mfa_recovery_hashes or []),
    )


@router.post("/mfa/setup", response_model=SetupRead)
def mfa_setup(
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> SetupRead:
    secret, uri = mfa.begin_setup(db, user)
    db.commit()
    return SetupRead(secret=secret, uri=uri)


@router.post("/mfa/enable", response_model=EnabledRead)
def mfa_enable(
    payload: Code,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> EnabledRead:
    codes = mfa.confirm_setup(db, user, payload.code)
    if codes is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code did not work. Check the app and try again.")
    audit.record(db, actor=user, action="mfa.enabled", request=request, target=user)
    db.commit()
    return EnabledRead(recovery_codes=codes)


@router.post("/mfa/recovery-codes", response_model=EnabledRead)
def mfa_new_codes(
    payload: Code,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> EnabledRead:
    """New recovery codes, replacing the old ones — with a current code, so a
    session left open on somebody's desk cannot mint them."""
    if not mfa.verify(db, user, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code did not work.")
    codes = mfa.new_recovery_codes(db, user)
    audit.record(db, actor=user, action="mfa.recovery_codes", request=request, target=user)
    db.commit()
    return EnabledRead(recovery_codes=codes)


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
def mfa_disable(
    payload: Code,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    if _required(db, user) and user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your organization requires two-step sign-in. Set up a new authenticator instead of turning it off.",
        )
    if not mfa.verify(db, user, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code did not work.")
    mfa.disable(db, user)
    audit.record(db, actor=user, action="mfa.disabled", request=request, target=user)
    db.commit()


class Unenrolled(BaseModel):
    id: int
    full_name: str


@router.get("/mfa/unenrolled", response_model=list[Unenrolled])
def mfa_unenrolled(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[Unenrolled]:
    """People who sign in with a password and have not set up two-step.

    **What "required" leaves out, said out loud.** The switch asks for a code
    at the next password sign-in, so until then these people are exactly as
    they were — and an admin who signs in with Microsoft, and is never asked,
    reasonably wonders whether it is on at all (QA-32). Somebody with no
    password — Microsoft only, or an invitation never accepted — has nothing
    this applies to, so is not listed.
    """
    people = db.scalars(
        select(UserAccount)
        .where(
            UserAccount.organization_id == actor.organization_id,
            UserAccount.status == "active",
            UserAccount.hidden_at.is_(None),
            UserAccount.password_hash.is_not(None),
            UserAccount.mfa_secret_encrypted.is_(None),
        )
        .order_by(UserAccount.full_name)
    ).all()
    return [Unenrolled(id=p.id, full_name=p.full_name) for p in people]


@router.post("/mfa/{user_id}/reset", status_code=status.HTTP_204_NO_CONTENT)
def mfa_reset(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """For somebody who lost their phone and their recovery codes. They sign
    in with their password next time — and set up again if it is required."""
    user = db.get(UserAccount, user_id)
    if user is None or user.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    mfa.disable(db, user)
    audit.record(db, actor=actor, action="mfa.reset", request=request, target=user)
    db.commit()
