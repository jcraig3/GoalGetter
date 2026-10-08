"""Changing and resetting passwords.

Two paths, because they answer different questions.

**Change** — "I know my password and want a new one." Self-service, requires
the current password, available to everyone.

**Reset** — "I have forgotten my password." An admin issues a single-use link
and hands it over.

**Forgot** — "I have forgotten it, and there is no admin to hand." Self-service
from the sign-in page (Phase 14), and only ever by email: the link goes to the
address on the account and never comes back in the response, or anybody could
request one for the admin and be handed it. So it exists only where mail can
be sent — the sign-in page asks `/auth/providers` and says "ask an admin"
otherwise. Three more rules make it safe to leave open to the world, each
said where it is enforced in `forgot_password`.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit, mail, sign_in, tokens
from app.db import SessionFactory, get_db, get_session_factory
from app.models import LoginAttempt, Organization, Session, UserAccount, UserToken
from app.net import visitor_ip
from app.rate_limit import clear_failures, is_locked_out, record_attempt, seconds_until_unlock
from app.scope import can_see_user
from app.security import NewPassword, hash_password, verify_password
from app.sessions import COOKIE_NAME, _hash_token, current_user, require_role

router = APIRouter(tags=["passwords"])

RESET_PATH = "/reset-password"

# The one rule for every password set anywhere: `security.NewPassword` (11.4).


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: NewPassword


class ResetPasswordRequest(BaseModel):
    token: str
    password: NewPassword


class ChoosePasswordRequest(BaseModel):
    password: NewPassword


class TemporaryPasswordRequest(BaseModel):
    password: NewPassword


class ResetLink(BaseModel):
    user_id: int
    email: str
    # Returned so an admin can copy it, exactly like an invitation. Deliberately
    # not emailed: many internal deployments have no SMTP on day one, and the
    # tool has to be fully usable without it.
    reset_link: str

    #: Same rule as an invitation: the link comes back whether or not it was also
    #: emailed, because an admin standing next to somebody should not have to wait
    #: for a mail server to agree.
    emailed: bool = False
    email_detail: str | None = None
    #: The link uses localhost, so it opens only on the computer that made it.
    link_is_local: bool = False


def _end_other_sessions(db: DbSession, user_id: int, keep_token_hash: str | None) -> None:
    """Sign the user out everywhere except where they are right now.

    A password change is the standard response to "someone else may have my
    password". If their other sessions survived it, the change would achieve
    nothing against exactly the threat it exists for.
    """
    query = db.query(Session).filter(Session.user_id == user_id)
    if keep_token_hash is not None:
        query = query.filter(Session.token_hash != keep_token_hash)
    query.delete(synchronize_session=False)


@router.post("/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """Set a new password, proving the current one first."""
    # The current-password check is a guessing oracle against a session that
    # may have been left open on a shared machine, so it is rate limited on the
    # same counter as sign-in.
    if is_locked_out(db, user.email, None):
        wait = seconds_until_unlock(db, user.email, None)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again shortly.",
            headers={"Retry-After": str(wait)},
        )

    if not user.password_hash or not verify_password(
        payload.current_password, user.password_hash
    ):
        record_attempt(db, user.email, None, succeeded=False)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That is not your current password.",
        )

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must be different from the current one.",
        )

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    clear_failures(db, user.email)

    # Their current session survives; every other one is ended.
    token = request.cookies.get(COOKIE_NAME)
    _end_other_sessions(db, user.id, _hash_token(token) if token else None)

    # No value in the details — recording a password anywhere, even hashed,
    # in a table every admin can read would be indefensible.
    audit.record(db, actor=user, action="password.changed", request=request, target=user)
    db.commit()


@router.post("/users/{user_id}/reset-password", response_model=ResetLink)
def issue_reset_link(
    user_id: int,
    request: Request,
    # Admin only, deliberately narrower than invitations.
    #
    # A manager may invite a NEW person, because that creates an account nobody
    # was using. Resetting an ACTIVE account's password is different: it is
    # taking over someone's account and locking them out of it. The escalation
    # is small — an agent sees less than their manager does — but the ability to
    # impersonate a specific person is not something a team lead needs, and it
    # is far easier to grant this later than to withdraw it.
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ResetLink:
    """Issue a single-use reset link for someone who is locked out."""
    user = db.get(UserAccount, user_id)
    if (
        user is None
        or user.organization_id != actor.organization_id
        or user.hidden_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if not can_see_user(db, actor, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if sign_in.must_use_sso(db, user):
        # **Not a link that cannot work** (11.3): their password would be
        # refused at sign-in, so a reset would only look like help.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SSO_ONLY)

    if user.status == "invited":
        # They have never set a password, so there is nothing to reset. Sending
        # them a reset link would work, but "resend invitation" is the action
        # that matches what actually happened, and keeps the two flows honest.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That account has not been activated yet. Resend the invitation instead.",
        )

    raw = tokens.issue(db, user.id, "password_reset")
    audit.record(
        db, actor=actor, action="password.reset_issued", request=request, target=user
    )
    db.commit()

    # After the commit, so a message can never describe a link that then failed
    # to save.
    link = tokens.link(raw, RESET_PATH, request, db)
    sent = mail.send(
        db,
        user.organization_id,
        to=user.email,
        subject="Reset your GoalGetter password",
        body=(
            f"Hello {user.full_name},\n\n"
            "Somebody at your organization asked for a password reset. Open this "
            f"link to choose a new one:\n\n{link}\n\n"
            "The link works once and expires shortly. If you were not expecting "
            "this, you can ignore it — your password has not changed.\n"
        ),
    )

    return ResetLink(
        user_id=user.id,
        email=user.email,
        reset_link=link,
        emailed=sent.ok,
        email_detail=None if sent.ok or not sent.attempted else sent.detail,
        link_is_local=tokens.is_local(link),
    )


#: A dead reset link. Points at both ways to a new one (Phase 14).
EXPIRED = (
    "This reset link is no longer valid. Request a new one with “Forgot password?” "
    "on the sign-in page, or ask an administrator."
)

SSO_ONLY = (
    "They are in your directory and single sign-on is required, so they sign in "
    "with their work account — a password would not let them in."
)


@router.post("/auth/choose-password", status_code=status.HTTP_204_NO_CONTENT)
def choose_password(
    payload: ChoosePasswordRequest,
    request: Request,
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """Replace a password an admin set with one of their own (11.2).

    No current password asked for: they typed it to get this session a moment
    ago, and asking again proves nothing. Only while one is owed — otherwise
    this would be "change password" without the proof that endpoint asks for.
    """
    if not user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Use Change password on your account page.",
        )
    if user.password_hash and verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose a different password from the one you were given.",
        )

    user.password_hash = hash_password(payload.password)
    user.must_change_password = False
    clear_failures(db, user.email)
    # Anywhere else the temporary one was used is signed out.
    token = request.cookies.get(COOKIE_NAME)
    _end_other_sessions(db, user.id, _hash_token(token) if token else None)
    audit.record(db, actor=user, action="password.chosen", request=request, target=user)
    db.commit()


@router.post("/users/{user_id}/temporary-password", status_code=status.HTTP_204_NO_CONTENT)
def set_temporary_password(
    user_id: int,
    payload: TemporaryPasswordRequest,
    request: Request,
    # Admin only (decided 5 Oct), like reset links and for the same reason: a
    # password you chose for somebody is a way to be them.
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Set somebody's password by hand, to be replaced at first sign-in (11.2).

    The other way to set somebody up, beside an emailed link: for the person
    standing next to you, or a deployment with no mail server. They are asked
    to choose their own the moment they sign in, and nothing else opens until
    they do, so the admin's choice is never their password for long.
    """
    user = db.get(UserAccount, user_id)
    if (
        user is None
        or user.organization_id != actor.organization_id
        or user.hidden_at is not None
        or not can_see_user(db, actor, user.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use Change password on your account page.",
        )
    if sign_in.must_use_sso(db, user):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SSO_ONLY)

    set_temporary(db, user, payload.password)
    audit.record(
        db, actor=actor, action="password.temporary_set", request=request, target=user
    )
    db.commit()


def set_temporary(db: DbSession, user: UserAccount, password: str) -> None:
    """A password they must replace at first sign-in. Shared with inviting."""
    user.password_hash = hash_password(password)
    user.must_change_password = True
    if user.status == "invited":
        user.status = "active"
    # An outstanding invitation or reset link would be a second way in, set
    # by nobody now looking at it.
    db.query(UserToken).filter(
        UserToken.user_id == user.id,
        UserToken.purpose.in_(("invite", "password_reset")),
    ).delete(synchronize_session=False)
    # Whoever was signed in as them is not any more.
    _end_other_sessions(db, user.id, None)
    clear_failures(db, user.email)


class ForgotRequest(BaseModel):
    #: A string, not EmailStr (P5-13): a malformed address got pydantic's own
    #: 422. It gets the same answer as every other now, and nothing is sent.
    email: str = Field(max_length=320)


#: The one answer, whatever happened: telling them apart would say which
#: addresses have accounts here.
FORGOT_ANSWER = (
    "If that address has an account, a link to choose a new password is on its "
    "way. It works once, for two hours."
)
#: Requests per address, and per network address, in an hour: enough for a
#: typo and a retry, not enough to fill somebody's inbox.
FORGOT_PER_EMAIL = 3
FORGOT_PER_IP = 20
FORGOT_WINDOW = timedelta(hours=1)


def _too_many(db: DbSession, email: str, ip: str | None) -> bool:
    since = datetime.now(UTC) - FORGOT_WINDOW
    recent = select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.attempted_at >= since
    )
    if (db.scalar(recent.where(LoginAttempt.email == f"reset:{email}")) or 0) >= FORGOT_PER_EMAIL:
        return True
    return bool(ip) and (
        db.scalar(recent.where(LoginAttempt.ip_address == ip, LoginAttempt.email.like("reset:%")))
        or 0
    ) >= FORGOT_PER_IP


@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    payload: ForgotRequest,
    request: Request,
    background: BackgroundTasks,
    db: DbSession = Depends(get_db),
    sessions: SessionFactory = Depends(get_session_factory),
) -> dict:
    """Email a reset link to somebody who has forgotten their password.

    **The same answer every time** — no account, a suspended one, somebody who
    must use Microsoft, too many requests, no mail server: all "if that address
    has an account…". Anything else says who works here.

    **Sent after the answer**, in the background, so the time it takes does not
    say whether an email went either.

    **The link is built from the address in Settings, never from this
    request.** Anybody can send this request with any `Origin`; building from
    it would let a stranger have a real reset link, mailed to a real person,
    point at their own site ("password reset poisoning").

    Counted in the sign-in attempts table under `reset:<email>` and marked
    succeeded, so it never counts towards locking anybody out of signing in.
    """
    email = payload.email.strip().lower()
    ip = visitor_ip(request, db)
    answer = {"detail": FORGOT_ANSWER}
    if not mail.looks_like_an_address(email):
        return answer

    if _too_many(db, email, ip):
        return answer
    db.add(LoginAttempt(email=f"reset:{email}", ip_address=ip, succeeded=True,
                        attempted_at=datetime.now(UTC)))

    user = db.scalar(select(UserAccount).where(func.lower(UserAccount.email) == email))
    if (
        user is None
        or user.hidden_at is not None
        or user.status not in ("active", "invited")
        or sign_in.must_use_sso(db, user)
        or not mail.can_send(db, user.organization_id)
    ):
        db.commit()
        return answer

    # Somebody still invited has nothing to reset: what they need is the
    # invitation again, so that is what goes.
    invited = user.status == "invited"
    raw = tokens.issue(db, user.id, "invite" if invited else "password_reset")
    link = tokens.link(raw, "/accept-invite" if invited else RESET_PATH, None, db)
    audit.record(db, actor=user, action="password.reset_requested", request=request, target=user)
    db.commit()

    org = db.get(Organization, user.organization_id)
    background.add_task(
        _send_forgot, sessions, user.organization_id, user.email, user.full_name,
        org.name if org else "GoalGetter", link, invited,
    )
    return answer


def _send_forgot(
    sessions: SessionFactory, organization_id: int, to: str, name: str,
    org_name: str, link: str, invited: bool,
) -> None:
    """After the answer has gone: its own session, as a background task must."""
    if invited:
        subject, opening = (
            "Your GoalGetter invitation",
            "You asked to sign in to GoalGetter. You have not set a password yet, "
            "so here is your invitation again. Open this link to choose one:",
        )
    else:
        subject, opening = (
            "Reset your GoalGetter password",
            "Somebody — hopefully you — asked to reset your password. Open this "
            "link to choose a new one:",
        )
    with sessions() as db:
        mail.send(
            db, organization_id, to=to, subject=subject,
            body=(
                f"Hello {name},\n\n{opening}\n\n{link}\n\n"
                f"The link works once and expires soon. If you did not ask for "
                f"this, ignore this email — your password has not changed.\n\n"
                f"— GoalGetter at {org_name}\n"
            ),
        )


class ResetCheck(BaseModel):
    token: str


@router.post("/auth/reset-password/check", status_code=status.HTTP_204_NO_CONTENT)
def check_reset_link(payload: ResetCheck, db: DbSession = Depends(get_db)) -> None:
    """Whether a reset link still works, asked when its page opens.

    The same single answer as the reset itself, so it says no more about a
    stale link than using it would. Nothing is spent.
    """
    user_id = tokens.valid(db, payload.token, "password_reset")
    user = db.get(UserAccount, user_id) if user_id is not None else None
    if user is None or user.hidden_at is not None or user.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=EXPIRED,
        )


@router.post("/auth/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    db: DbSession = Depends(get_db),
) -> None:
    """Set a new password from a reset link.

    One message for every failure — missing token, wrong purpose, expired,
    suspended account. Distinguishing them would tell someone holding a stale
    link whether it was ever real, and whether the account exists.

    Unlike accepting an invitation, this does NOT sign them in. A reset is the
    response to a possible compromise, and the safe assumption is that the link
    may have been read by someone other than its owner. Making them sign in
    with the new password proves they are the one who chose it.
    """
    invalid = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=EXPIRED)

    user_id = tokens.consume(db, payload.token, "password_reset")
    if user_id is None:
        # consume() may have deleted an expired row, so the commit matters.
        db.commit()
        raise invalid

    user = db.get(UserAccount, user_id)
    if user is None or user.hidden_at is not None or user.status == "suspended":
        db.commit()
        raise invalid

    user.password_hash = hash_password(payload.password)
    user.must_change_password = False
    user.status = "active"

    # Every session, including any the attacker may hold. Nothing is kept:
    # whoever triggered this is not signed in yet.
    _end_other_sessions(db, user.id, None)
    # A reset also clears the lockout — otherwise someone locked out by an
    # attacker's guessing could not use their new password until it expired.
    clear_failures(db, user.email)

    audit.record(db, actor=user, action="password.reset_completed", request=request, target=user)
    db.commit()
