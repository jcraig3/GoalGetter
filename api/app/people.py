"""Who may see whose profile, and what of it (Phase 9).

A profile has two halves. **The public half** is what somebody has earned:
their badges, their wins and shout-outs, their season points and tier. Wins
were announced on the TVs already, figure and all, so nothing here is newly
revealed. **The private half** is how they are doing: their goals, their
totals and where they rank on each board.

    public   everyone in the organization — unless the organization has
             turned profiles off, when it is the private rule below
    private  the person, and whoever may see them under `users.view`:
             an admin everyone, a manager their own team

The second rule is the one every other page about a person uses
(`scope.visible_user_ids`), so a custom role based on Manager that keeps
"View people" sees private halves within its scope, and one that loses it
sees none. Nothing here is a new kind of permission.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.models import Organization, UserAccount
from app.scope import can_see_user, has_capability

#: The ability the client checks before drawing a name as a link to a profile.
PEOPLE_VIEW = "people.view"


def may_see_private(db: DbSession, actor: UserAccount, person: UserAccount) -> bool:
    """Goals and numbers: the person themselves, or somebody who manages them."""
    if person.organization_id != actor.organization_id:
        return False
    if actor.id == person.id:
        return True
    return has_capability(actor, "users.view") and can_see_user(db, actor, person.id)


def may_see_profile(db: DbSession, actor: UserAccount, person: UserAccount) -> bool:
    """The public half. Hidden accounts — bots, test users — have no profile."""
    if person.organization_id != actor.organization_id or person.hidden_at is not None:
        return False
    org = db.get(Organization, actor.organization_id)
    if org is not None and org.profiles_public:
        return True
    return may_see_private(db, actor, person)


def links_to_profiles(db: DbSession, user: UserAccount) -> bool:
    """Whether names should be links for this person, on every page.

    **Only where every link would open.** With profiles public, that is
    everybody. With them off, an admin — who sees everyone — still gets links;
    a manager does not, because a name on an organization-wide board may be
    somebody outside their team, and a link that opens on "not found" is the
    dead end this is meant to prevent. Their team is on the Users page.
    """
    org = db.get(Organization, user.organization_id)
    if org is not None and org.profiles_public:
        return True
    return user.org_role == "admin"
