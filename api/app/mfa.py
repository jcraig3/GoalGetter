"""Two-step sign-in: what an account's authenticator can do, and the short-lived
proof that the password step was passed.

**The challenge is not a session.** After a correct password, somebody with
two-step sign-in gets a challenge — encrypted, five minutes long, naming the
account and the step still owed — and nothing else. Only a code (or, when setup
is required, a confirmed new authenticator) turns it into a session. A stolen
challenge on its own signs nobody in.

See `app/totp.py` for the codes themselves.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession

from app import crypto, totp
from app.models import UserAccount

__all__ = [
    "CHALLENGE_SECONDS",
    "begin_setup",
    "challenge_for",
    "confirm_setup",
    "disable",
    "is_enabled",
    "open_challenge",
    "verify",
]

CHALLENGE_SECONDS = 300
ISSUER = "GoalGetter"

#: What a challenge still needs: a code from the authenticator, or setting one up.
STAGES = ("code", "setup")


def is_enabled(user: UserAccount) -> bool:
    return bool(user.mfa_secret_encrypted)


def challenge_for(user: UserAccount, stage: str) -> str:
    return crypto.encrypt(
        json.dumps({"uid": user.id, "stage": stage, "exp": time.time() + CHALLENGE_SECONDS})
    )


def open_challenge(token: str) -> tuple[int, str]:
    """(user id, stage), or ValueError for anything expired or forged."""
    try:
        held = json.loads(crypto.decrypt(token))
    except (ValueError, TypeError):
        raise ValueError("That sign-in could not be verified. Start again.") from None
    if not isinstance(held, dict) or held.get("exp", 0) < time.time():
        raise ValueError("That took too long. Sign in again.")
    if held.get("stage") not in STAGES or not isinstance(held.get("uid"), int):
        raise ValueError("That sign-in could not be verified. Start again.")
    return held["uid"], held["stage"]


def verify(db: DbSession, user: UserAccount, code: str) -> bool:
    """A code from the authenticator, or an unused recovery code. Either one is
    spent: the authenticator's step is remembered, the recovery code is gone."""
    if not user.mfa_secret_encrypted:
        return False
    secret = crypto.decrypt(user.mfa_secret_encrypted)
    step = totp.matching_step(secret, code, after_step=user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        db.flush()
        return True
    hashed = totp.hash_recovery(code)
    remaining = list(user.mfa_recovery_hashes or [])
    if hashed in remaining:
        remaining.remove(hashed)
        user.mfa_recovery_hashes = remaining
        db.flush()
        return True
    return False


def begin_setup(db: DbSession, user: UserAccount) -> tuple[str, str]:
    """A new secret to scan, held as pending until a code confirms it —
    so starting again never breaks an authenticator that already works."""
    secret = totp.new_secret()
    user.mfa_pending_secret_encrypted = crypto.encrypt(secret)
    db.flush()
    return secret, totp.otpauth_uri(secret, account=user.email, issuer=ISSUER)


def confirm_setup(db: DbSession, user: UserAccount, code: str) -> list[str] | None:
    """Make the pending secret the real one, if the code proves the app has it.
    Returns fresh recovery codes, shown once."""
    if not user.mfa_pending_secret_encrypted:
        return None
    secret = crypto.decrypt(user.mfa_pending_secret_encrypted)
    step = totp.matching_step(secret, code)
    if step is None:
        return None
    user.mfa_secret_encrypted = user.mfa_pending_secret_encrypted
    user.mfa_pending_secret_encrypted = None
    user.mfa_enabled_at = datetime.now(UTC)
    user.mfa_last_step = step
    return new_recovery_codes(db, user)


def new_recovery_codes(db: DbSession, user: UserAccount) -> list[str]:
    codes = totp.new_recovery_codes()
    user.mfa_recovery_hashes = [totp.hash_recovery(code) for code in codes]
    db.flush()
    return codes


def disable(db: DbSession, user: UserAccount) -> None:
    user.mfa_secret_encrypted = None
    user.mfa_pending_secret_encrypted = None
    user.mfa_enabled_at = None
    user.mfa_recovery_hashes = []
    user.mfa_last_step = None
    db.flush()
