"""Who may sign in with a password (Phase 11).

**"Require single sign-on" is about the company directory, not everybody.**
It used to refuse a password to anybody who was not an admin, which left no way
in for people the company works with but does not employ — a contractor, an
agency's closer — who have no work account to sign in with. So it now binds
exactly the people who have one:

- **Somebody synced from the directory**, which is what a tenant user means
  here (decided 5 Oct), or
- **somebody who has already signed in with SSO**, who has proved it.

And never an admin, whichever of those they are: the break-glass path. A typo
in the issuer URL otherwise locks everyone out of a self-hosted deployment with
no support line, and the only way back is editing the database by hand. The
trade is that admin accounts stay password-attackable, which is why rate
limiting matters most for exactly these accounts.

**Nothing here is said to somebody signing in.** A refused password gets the
same "Incorrect email or password" as a wrong one: telling them apart would
tell a stranger which addresses are in the directory.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import DirectoryPerson, SsoConfig, UserAccount


def requiring_sso(db: DbSession, organization_id: int) -> SsoConfig | None:
    """The organization's SSO settings when they require it, else None."""
    return db.scalar(
        select(SsoConfig).where(
            SsoConfig.organization_id == organization_id,
            SsoConfig.enabled.is_(True),
            SsoConfig.require_sso.is_(True),
        )
    )


def _in_directory(db: DbSession, user_ids: Iterable[int]) -> set[int]:
    ids = set(user_ids)
    if not ids:
        return set()
    return set(
        db.scalars(
            select(DirectoryPerson.user_account_id).where(
                DirectoryPerson.user_account_id.in_(ids),
                # Gone from the directory is no longer in it: whoever kept
                # them on did so on purpose, and they need a way in.
                DirectoryPerson.archived_at.is_(None),
            )
        )
    )


def must_use_sso_among(db: DbSession, organization_id: int, users: list[UserAccount]) -> set[int]:
    """Which of these people may not use a password — one query, for a list."""
    if requiring_sso(db, organization_id) is None:
        return set()
    candidates = [u for u in users if u.org_role != "admin"]
    linked = {u.id for u in candidates if u.external_subject_id}
    return linked | _in_directory(db, (u.id for u in candidates if u.id not in linked))


LEADERS = ("admin", "manager")


def leaders_only_refuses(db: DbSession, user: UserAccount) -> bool:
    """Whether "Only admins and managers can sign in" keeps this person out
    (Phase 28) — by any method, and their open sessions too."""
    if user.org_role in LEADERS:
        return False
    from app.models import Organization

    org = db.get(Organization, user.organization_id)
    return bool(org and org.sign_in_leaders_only)


LEADERS_ONLY = "Only admins and managers can sign in here."


def must_use_sso(db: DbSession, user: UserAccount) -> bool:
    """Whether a password is refused to this person."""
    return user.id in must_use_sso_among(db, user.organization_id, [user])


def ready_status(db: DbSession, user: UserAccount) -> str:
    """`active` for an account with a way in, `invited` for one still waiting.

    A way in is a password, an SSO sign-in already made, or a place in the
    directory — whose people sign in with the work account they have. Missing
    the last one turned a directory person back on as `invited`, which the SSO
    sign-in refuses: locked out of the one way in they were meant to use.
    """
    if user.password_hash or user.external_subject_id or _in_directory(db, [user.id]):
        return "active"
    return "invited"


def activate(db: DbSession, user: UserAccount) -> None:
    """An invitation overtaken: they signed in with SSO, or the directory
    found them. Active, and the emailed link withdrawn — a second way in that
    nobody is waiting on any more."""
    from app.models import UserToken

    if user.status != "invited":
        return
    user.status = "active"
    db.query(UserToken).filter(
        UserToken.user_id == user.id, UserToken.purpose == "invite"
    ).delete(synchronize_session=False)
