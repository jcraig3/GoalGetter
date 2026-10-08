"""Login rate limiting.

bcrypt at cost 12 already caps guessing at roughly a handful of attempts per
second, which is friction but not a defence. This adds a real ceiling.

Two independent limits, because they stop different attacks:

  per account — one address guessed repeatedly
  per IP      — one attacker spraying many addresses, where no single account
                ever reaches its own limit
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import LoginAttempt

WINDOW = timedelta(minutes=5)
MAX_FAILURES_PER_EMAIL = 5
MAX_FAILURES_PER_IP = 20

# Why 5 minutes rather than the more common 15:
#
# The threat is guessing a password, and the maths says either is fine. Five
# attempts per 5 minutes is ~1,440 guesses a day; per 15 minutes it is ~480.
# Against a 12-character minimum and bcrypt at cost 12, both round to zero
# chance — the difference is not security, it is how long a real person is
# locked out after mistyping their password five times.
#
# A 15-minute lockout for a typo generates support requests. Shorten the window
# rather than raising the attempt count: more attempts genuinely does help an
# attacker, a shorter window barely does.

# Attempts older than this are pruned. Long enough to investigate an incident,
# short enough that the table stays small.
RETENTION = timedelta(days=30)


def _recent_failures(db: DbSession, column, value: str | None) -> int:
    if value is None:
        return 0
    since = datetime.now(UTC) - WINDOW
    return (
        db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                column == value,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at >= since,
            )
        )
        or 0
    )


#: The range an admin may set each to (Phase 17): tight enough to matter,
#: loose enough that a typo-prone office is not locked out all day.
ACCOUNT_RANGE = (3, 20)
DEVICE_RANGE = (10, 200)


def limits(db: DbSession) -> tuple[int, int]:
    """(per account, per device) in the window — Settings, else the defaults."""
    from app.models import Organization

    row = db.execute(
        select(Organization.sign_in_limit_account, Organization.sign_in_limit_device)
        .order_by(Organization.id)
        .limit(1)
    ).first()
    account, device = row if row else (None, None)
    return account or MAX_FAILURES_PER_EMAIL, device or MAX_FAILURES_PER_IP


def is_locked_out(db: DbSession, email: str, ip: str | None) -> bool:
    """Has this email or address exhausted its allowance?

    Checked before the password is verified, so a locked-out attempt costs no
    bcrypt work — the limit protects CPU as well as the account.
    """
    per_account, per_device = limits(db)
    if _recent_failures(db, LoginAttempt.email, email.lower()) >= per_account:
        return True
    return _recent_failures(db, LoginAttempt.ip_address, ip) >= per_device


def seconds_until_unlock(db: DbSession, email: str, ip: str | None) -> int:
    """How long until the oldest failure leaves the window.

    Attempts expire individually, so the lock lifts as soon as the earliest one
    ages out — not all at once. Returning this lets the UI count down instead
    of leaving someone guessing.
    """
    since = datetime.now(UTC) - WINDOW
    oldest = db.scalar(
        select(func.min(LoginAttempt.attempted_at)).where(
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at >= since,
            (LoginAttempt.email == email.lower())
            | (LoginAttempt.ip_address == ip if ip else False),
        )
    )
    if oldest is None:
        return 0
    remaining = (oldest + WINDOW) - datetime.now(UTC)
    return max(1, int(remaining.total_seconds()))


def record_attempt(db: DbSession, email: str, ip: str | None, *, succeeded: bool) -> None:
    db.add(
        LoginAttempt(
            email=email.lower(),
            ip_address=ip,
            succeeded=succeeded,
            attempted_at=datetime.now(UTC),
        )
    )


def clear_failures(db: DbSession, email: str) -> None:
    """Wipe an account's failures after a correct password.

    Without this, five typos earlier in the day would still count against
    someone who has since signed in successfully.
    """
    db.query(LoginAttempt).filter(
        LoginAttempt.email == email.lower(),
        LoginAttempt.succeeded.is_(False),
    ).delete(synchronize_session=False)


def prune(db: DbSession) -> int:
    """Delete attempts past the retention window. Called by a scheduled job
    once one exists; safe to run manually until then."""
    cutoff = datetime.now(UTC) - RETENTION
    deleted = (
        db.query(LoginAttempt)
        .filter(LoginAttempt.attempted_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted)
