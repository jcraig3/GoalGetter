"""Single-use links for invitations and password resets."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import public_url
from app.models import UserToken
# Imported rather than redeclared, so the code and the database CHECK
# constraint can never disagree about what a valid purpose is.
from app.models.user_token import TOKEN_PURPOSES

# Long enough that guessing is not a threat, so the value needs no signing —
# the database row is the source of truth.
TOKEN_BYTES = 32

# An invitation is handed over deliberately and may sit in someone's inbox over
# a weekend. A reset answers a possible compromise, so it lives just long enough
# to be used once.
TTL = {
    "invite": timedelta(days=7),
    "password_reset": timedelta(hours=2),
}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(db: DbSession, user_id: int, purpose: str) -> str:
    """Create a token and return the raw value — the only time it exists.

    Any existing token for the same user and purpose is deleted first, so
    resending an invitation invalidates the previous link. Otherwise an admin
    who resent an invite would leave two working links, and revoking one would
    not revoke the other.
    """
    if purpose not in TOKEN_PURPOSES:
        # Caught here rather than at the database. A typo'd purpose otherwise
        # surfaces as a CheckViolation from deep inside a commit, with no clue
        # which call site produced it.
        raise ValueError(
            f"Unknown token purpose {purpose!r}. Expected one of: "
            f"{', '.join(TOKEN_PURPOSES)}"
        )

    db.query(UserToken).filter(
        UserToken.user_id == user_id,
        UserToken.purpose == purpose,
    ).delete(synchronize_session=False)

    raw = secrets.token_urlsafe(TOKEN_BYTES)
    now = datetime.now(UTC)
    db.add(
        UserToken(
            user_id=user_id,
            token_hash=_hash(raw),
            purpose=purpose,
            created_at=now,
            expires_at=now + TTL[purpose],
        )
    )
    return raw


def consume(db: DbSession, raw: str, purpose: str) -> int | None:
    """Validate and spend a token, returning its user id.

    Single use: the row is deleted, so a link cannot be replayed even if it is
    still in someone's browser history or a Slack message.

    Returns None for missing, wrong-purpose, and expired alike. The caller must
    not distinguish them — "this invitation expired" versus "no such invitation"
    tells an attacker whether a token they hold was ever real.
    """
    token = db.scalar(select(UserToken).where(UserToken.token_hash == _hash(raw)))
    if token is None or token.purpose != purpose:
        return None

    user_id = token.user_id
    expired = token.expires_at <= datetime.now(UTC)
    # Deleted either way: an expired token has no further use, and leaving it
    # would let someone keep probing the same value.
    db.delete(token)
    return None if expired else user_id


def valid(db: DbSession, raw: str, purpose: str) -> int | None:
    """The token's user if it would be accepted now, without spending it.

    For a page to say "this link has expired" when it opens, instead of after
    somebody has typed a new password twice (QA-29). Same answer for missing,
    wrong-purpose and expired, for the reason `consume` gives.
    """
    token = db.scalar(select(UserToken).where(UserToken.token_hash == _hash(raw)))
    if token is None or token.purpose != purpose:
        return None
    return None if token.expires_at <= datetime.now(UTC) else token.user_id


def link(raw: str, path: str, request: Request | None = None, db: DbSession | None = None) -> str:
    """Build the absolute URL an admin copies or an email contains."""
    return f"{base_url(request, db)}{path}?token={raw}"


def base_url(request: Request | None = None, db: DbSession | None = None) -> str:
    """Where the app is, for a link somebody else will open.

    **The address set in Settings, when there is one** (11.7) — the admin said
    where the app is, and that is the end of it.

    Otherwise **the address the admin is using**, from the browser's `Origin` — so a link
    made on the office server's address is that address, with no setting to
    keep in step. `Host` cannot say it: nginx passes it without the port.

    `APP_URL` instead when there is no request to ask, when the browser sent
    nothing usable, or when the admin is on `localhost` and `APP_URL` names a
    real address — a link to localhost opens on nobody's computer but theirs.

    Trusted because only a signed-in admin's own request reaches here, and the
    session cookie is not sent cross-site: the Origin is their address bar.
    Microsoft's redirect addresses do not come from here; they must match what
    is registered exactly, so they stay `APP_URL`.
    """
    if db is not None and (chosen := public_url.chosen(db)):
        return chosen
    configured = public_url.default(db)
    origin = (request.headers.get("origin") or "").rstrip("/") if request else ""
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
        return configured
    if is_local(origin) and not is_local(configured):
        return configured
    return origin


def is_local(url: str) -> bool:
    """Whether a link only opens on the computer that made it."""
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.") or host.endswith(".localhost")


def prune(db: DbSession) -> int:
    """Delete expired tokens. Called by a scheduled job once one exists."""
    deleted = (
        db.query(UserToken)
        .filter(UserToken.expires_at < datetime.now(UTC))
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted)
