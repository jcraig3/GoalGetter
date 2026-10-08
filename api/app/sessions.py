"""Session creation, validation, and the current_user dependency."""

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import get_settings
from app.db import get_db
from app.models import Session, UserAccount
from app.net import visitor_ip

COOKIE_NAME = "gg_session"

# 32 bytes of randomness. Long enough that guessing is not a threat, so the
# token needs no signing or expiry encoded in it — the database row is the
# source of truth.
TOKEN_BYTES = 32


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: DbSession, user: UserAccount, request: Request, response: Response
) -> None:
    """Issue a session and set the cookie."""
    from app import sign_in

    # The last door for every way in (Phase 28); each route says so earlier,
    # in its own way, too.
    if sign_in.leaders_only_refuses(db, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=sign_in.LEADERS_ONLY)
    settings = get_settings()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.session_lifetime_days)

    db.add(
        Session(
            user_id=user.id,
            token_hash=_hash_token(token),
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
            ip_address=visitor_ip(request, db),
            user_agent=(request.headers.get("user-agent") or "")[:400] or None,
        )
    )

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        # JavaScript cannot read this cookie, so an XSS bug cannot steal the
        # session. This is the main reason for cookies over localStorage.
        httponly=True,
        # HTTPS only. See the note in config.py.
        secure=secure_cookie(request),
        # The browser won't send this cookie on cross-site requests, which
        # blocks the basic CSRF attack. Safe to use "lax" rather than "strict"
        # because nginx serves the app and the API on one origin.
        samesite="lax",
        path="/",
        max_age=settings.session_lifetime_days * 24 * 60 * 60,
    )


def secure_cookie(request: Request) -> bool:
    """Whether a cookie set on this request should be HTTPS-only.

    Always when `SECURE_COOKIES` says so; otherwise whenever the browser came
    in over HTTPS (Phase 13) — Caddy says so in `X-Forwarded-Proto`. So turning
    HTTPS on protects the cookie with nothing else to remember, and the plain
    address TVs use keeps working.
    """
    if get_settings().secure_cookies:
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def revoke_session(db: DbSession, token: str | None, response: Response) -> None:
    """Delete the session row and clear the cookie."""
    if token:
        session = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
        if session:
            db.delete(session)
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(
    request: Request,
    db: DbSession = Depends(get_db),
) -> UserAccount:
    """Resolve the signed-in user, or reject the request with 401.

    Declaring this on an endpoint is what makes it require authentication:

        def create_goal(user: UserAccount = Depends(current_user)): ...

    The endpoint body cannot run without a valid session, so authentication is
    part of the signature rather than something each function remembers to do.
    """
    unauthenticated = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in."
    )

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise unauthenticated

    session = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
    if session is None:
        raise unauthenticated

    now = datetime.now(UTC)
    if session.expires_at <= now:
        # Expired sessions are removed on encounter rather than left to
        # accumulate. A scheduled sweep for sessions nobody returns to comes
        # with the job scheduler.
        db.delete(session)
        db.commit()
        raise unauthenticated

    user = db.get(UserAccount, session.user_id)
    # Permissions are re-read from the database on every request, so suspending
    # an account or changing a role takes effect immediately rather than
    # whenever a token happens to expire.
    from app import sign_in

    if (
        user is None
        or user.status != "active"
        or user.hidden_at is not None
        or sign_in.leaders_only_refuses(db, user)
    ):
        db.delete(session)
        db.commit()
        raise unauthenticated

    settings = get_settings()
    lifetime = timedelta(days=settings.session_lifetime_days)
    session.last_used_at = now
    # Sliding expiry, extended only past the halfway mark. Extending on every
    # request would mean a database write per request for no real benefit.
    if session.expires_at - now < lifetime / 2:
        session.expires_at = now + lifetime
    db.commit()

    # **A password somebody else chose opens one door** (11.2): choosing their
    # own. Enforced here rather than by the page, which only decides what to
    # draw — an admin who set it knows it, and so may anybody it was sent to.
    if user.must_change_password and request.url.path not in FIRST_PASSWORD_PATHS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Choose your own password first.",
        )

    return user


#: All a temporary password reaches: who you are, and choosing a new one.
#: Signing out needs no session at all.
FIRST_PASSWORD_PATHS = frozenset({"/api/auth/me", "/api/auth/choose-password"})


def require_role(*allowed: str) -> Callable[[UserAccount], UserAccount]:
    """Builds a dependency that rejects anyone outside `allowed`.

        @router.get("/sso", dependencies=[Depends(require_role("admin"))])

    A factory rather than one dependency per role, so adding a role never means
    adding a function. The role is re-read from the database on every request
    via current_user, so a demotion takes effect immediately.

    This is the coarse check at the edge. Row-level scoping — which agents a
    manager may see — is enforced separately in the service layer, because only
    that layer knows what "their team" means.
    """

    def check(request: Request, user: UserAccount = Depends(current_user)) -> UserAccount:
        if user.org_role not in allowed:
            # 403, not 404: the caller is authenticated and the resource
            # exists — they simply may not perform this action. 404 is for
            # resources outside their scope, where confirming existence would
            # itself leak information.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to do that.",
            )
        # A custom role narrows the built-in one: the capability this request
        # needs, if its role took that away, is refused here — the one place
        # every guarded endpoint passes through. See `app/roles.py`.
        if user.custom_role_id is not None:
            from app import roles

            needed = roles.capability_for(request.method, request.url.path)
            if needed is not None and needed in roles.removed_for(user):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your role does not include that.",
                )
        return user

    return check
