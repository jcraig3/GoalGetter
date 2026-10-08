"""Who can see whom, and who can do what.

Two separate questions, deliberately kept apart:

    scope        — WHICH people's data may this requester see?
    capabilities — WHICH actions may they perform at all?

An admin has both. A manager can edit goals, but only for their own team, so
the capability says "yes" and the scope narrows it to the right rows.
"""

from sqlalchemy import and_, false, or_, select
from sqlalchemy.orm import Session as DbSession

from app.models import UserAccount

# Returned by visible_user_ids for an actor who may see everyone, so callers do
# not have to load every id just to express "no restriction".
EVERYONE = None

VisibleUsers = list[int] | None


def visible_user_ids(db: DbSession, actor: UserAccount) -> VisibleUsers:
    """The set of users whose data `actor` may see.

    Returns EVERYONE (None) for an admin — meaning "apply no filter" — rather
    than a list of every id, so a 5,000-person organization does not build a
    5,000-element IN clause on every request.

        admin    everyone in the organization
        manager  their own team, plus agents on no team, plus themselves
        agent    themselves

    Managers see unassigned agents on purpose. Without that, a manager could
    never pull a newly invited person onto their team — they would be invisible
    until an admin placed them, which is the setup failure this product should
    be surfacing, not hiding.

    Resolved per request, not cached at sign-in, so moving someone between
    teams takes effect on the manager's next request rather than at their next
    login.
    """
    if actor.org_role == "admin":
        return EVERYONE

    if actor.org_role == "manager":
        # Their team, OR an AGENT on no team.
        #
        # Written as an explicit or_() because a Python ternary here silently
        # picks one branch: `A if cond else B` evaluates to a single condition,
        # so a manager with a team saw only their team and never the unassigned
        # agents this is supposed to include. The docstring said one thing and
        # the query did another — caught by checking the actual output.
        on_their_team = (
            UserAccount.team_id == actor.team_id
            if actor.team_id is not None
            else false()
        )
        # `org_role == "agent"` matters more than it looks. Without it the
        # condition is "anyone on no team", which includes admins — and an
        # admin has no team by default. A manager could then see that admin,
        # and if the account were still `invited`, reissue its invitation link
        # and set its password. Recruiting is meant to reach new agents, not
        # every unplaced account in the organization.
        unplaced_agent = and_(
            UserAccount.team_id.is_(None), UserAccount.org_role == "agent"
        )
        rows = db.scalars(
            select(UserAccount.id).where(
                UserAccount.organization_id == actor.organization_id,
                UserAccount.hidden_at.is_(None),
                or_(on_their_team, unplaced_agent),
            )
        ).all()
        return sorted({*rows, actor.id})

    return [actor.id]


def can_see_user(db: DbSession, actor: UserAccount, user_id: int) -> bool:
    visible = visible_user_ids(db, actor)
    return visible is EVERYONE or user_id in visible


# ── Capabilities ─────────────────────────────────────────────────────────────
#
# Returned to the client so the UI never reimplements the rules. Adding a role
# later — or custom roles — changes this map, and the interface follows without
# touching a component.
#
# The client uses these to decide what to *render*. Every one of them is also
# enforced server-side; hiding a button protects nothing.

_CAPABILITIES: dict[str, set[str]] = {
    "admin": {
        "users.view",
        "users.invite",
        "users.assign_team",
        "users.manage_roles",
        "users.suspend",
        # **Widened from admin-only deliberately.** A face looks like the one
        # personal part of a profile, and letting a colleague change it would
        # invent a prank — true of colleagues, not of whoever manages the roster.
        # Most people here never sign in, because a directory sync made their
        # account, so "they can upload their own" is not an answer for the
        # majority. Everybody may still change their own; see
        # `routers/users.py::_may_change_photo`.
        "users.edit_photo",
        # Admin only, deliberately narrower than users.invite: inviting
        # creates an account nobody was using, resetting takes over one
        # somebody is.
        "users.reset_password",
        "teams.view",
        "teams.manage",
        "offices.view",
        "offices.manage",
        "org.settings.edit",
        "integrations.manage",
        "metrics.view",
        "metrics.manage",
        "metrics.correct",
        "goals.manage",
        "goals.view",
        "leaderboards.manage",
        "leaderboards.view",
        "competitions.manage",
        "competitions.view",
        # The reporting tab. Not a second way to read other people's numbers —
        # every answer on it is a list of people to talk to, which is a job
        # rather than a view, and agents hold no part of that job.
        # Handing over a prize somebody won on the wheel. The same two roles
        # the server's check names; it is usually the winner's manager who is
        # standing near their desk.
        "wheel.hand_over",
        "reporting.view",
        "recognition.send",
        # Announcements for the TVs (Phase 25): the same people as shout-outs.
        "announcements.send",
    },
    "manager": {
        "metrics.view",
        # Scoped by visible_user_ids to their own team plus unassigned agents.
        # Agents hold no write path to metric data at all — see
        # documentation/06-metrics-engine.md#data-entry.
        "metrics.correct",
        # Setting goals is the job the manager role exists for. Scope narrows
        # it to their own team and the agents on it.
        "goals.manage",
        "goals.view",
        # A manager may build boards for their own team. Publishing one to the
        # whole organization stays admin-only — that is publishing their
        # team's numbers to everyone, which is not theirs to decide.
        "leaderboards.manage",
        "leaderboards.view",
        # Running a contest between their own people is the same job as setting
        # them goals. Settling one early stays admin-only: it freezes a result
        # somebody will be asked to justify.
        "competitions.manage",
        "competitions.view",
        "users.view",
        "users.invite",
        # Scoped by visible_user_ids to their own team plus unassigned agents.
        "users.assign_team",
        # Uploading a headshot for somebody who will never sign in to do it
        # themselves. See the note on the admin set.
        "users.edit_photo",
        "teams.view",
        "offices.view",
        # Recognising somebody is the most useful thing a manager can do here
        # that costs nothing. Scoped to people they can already see — a
        # shout-out is a broadcast, and it must not become a way to discover
        # who works in another office.
        # The reporting tab. Not a second way to read other people's numbers —
        # every answer on it is a list of people to talk to, which is a job
        # rather than a view, and agents hold no part of that job.
        # Handing over a prize somebody won on the wheel. The same two roles
        # the server's check names; it is usually the winner's manager who is
        # standing near their desk.
        "wheel.hand_over",
        "reporting.view",
        "recognition.send",
        # Announcements for the TVs (Phase 25): the same people as shout-outs.
        "announcements.send",
    },
    "agent": {
        # Agents see their own goals and their team's — being measured against
        # a target you cannot see is the opposite of what this product is for.
        "goals.view",
        # Agents view boards. That is the entire point of a leaderboard, and
        # the one place per-person scope is deliberately relaxed.
        "leaderboards.view",
        # And the contests they are in. Entering one is consent to be ranked in
        # it; not seeing where you stand would make the contest pointless.
        "competitions.view",
        "metrics.view",
        "teams.view",
        "offices.view",
    },
}


def capabilities_for(role: str, user: UserAccount | None = None) -> list[str]:
    """What a role may do — narrowed by `user`'s custom role, when given."""
    base = set(_CAPABILITIES.get(role, set()))
    if user is not None:
        from app import roles

        base = roles.effective(user, base)
    return sorted(base)


def has_capability(actor: UserAccount, capability: str) -> bool:
    return capability in capabilities_for(actor.org_role, actor)
