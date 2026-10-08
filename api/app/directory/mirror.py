"""Keeping GoalGetter teams and offices in step with Microsoft Teams.

An admin links a Microsoft Team, or a private or shared channel, to a
GoalGetter **team** or **office** (see `M365Link`). The people in it then belong
there. Microsoft 365 is one source of truth and GoalGetter is the other: people
can still be moved here by hand, and the mirror respects that.

**The mirror only undoes its own work.** It records where it put each person
(`MirrorPlacement`). If somebody's team no longer matches that record, an admin
moved them — and the mirror leaves them there and lists them, instead of quietly
moving them back on the next sync. "Follow Teams" hands them back to the mirror;
"Keep here" pins them and stops listing them as something to resolve.

How a person's place is decided, from the sources they are in:

    a linked channel beats its own linked Team   the channel is the finer grain
    one team left                                 that is where they belong
    two or more                                   a conflict, left for a person
    none, and on a mirrored team here             they left the Microsoft Team

**Offices come through teams.** A person here has a team, and a team has an
office, so an office is never assigned to a person directly. A channel linked
as a team, inside a Team linked as an office, puts its GoalGetter team in that
office. A Team linked as an office on its own is used to *compare*: somebody in
it whose team is in a different office is shown as a difference.

**Team only, never role.** A group containing a manager would otherwise demote
them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.directory.rules import normalise
from app.models import (
    DirectoryPerson,
    M365Link,
    M365Member,
    M365Source,
    MirrorPlacement,
    Office,
    Team,
    UserAccount,
)

__all__ = ["Person", "Picture", "OfficeChange", "apply", "follow", "keep", "picture"]

#: What a person's row says, in the order the comparison sorts them.
STATUSES = (
    "conflict",       # in two linked sources that disagree
    "moved_by_hand",  # the mirror placed them, and somebody moved them since
    "only_here",      # on a mirrored team here, and not in its Microsoft Team
    "would_move",     # the mirror will move them
    "kept",           # moved by hand, and an admin said keep them there
    "in_step",        # where Microsoft Teams says
    "not_linked",     # in nothing that is linked
    "not_in_m365",    # has no directory row at all
)

#: The statuses that are somebody's decision.
DECISIONS = ("conflict", "moved_by_hand", "only_here")


@dataclass
class Person:
    user_id: int
    name: str
    email: str
    status: str
    team_id: int | None
    #: Where Microsoft Teams says they belong. None with `status` "conflict"
    #: means "more than one" — see `teams_choices`.
    teams_team_id: int | None = None
    teams_choices: list[int] = field(default_factory=list)
    #: The office Microsoft Teams implies, through the team or an office link.
    teams_office_id: int | None = None
    #: What the directory's own "office" field says — free text, typed in Entra.
    m365_office: str = ""
    #: The linked sources they are in, by name.
    sources: list[str] = field(default_factory=list)


@dataclass
class OfficeChange:
    team_id: int
    from_office_id: int | None
    to_office_id: int


@dataclass
class Picture:
    people: list[Person] = field(default_factory=list)
    office_changes: list[OfficeChange] = field(default_factory=list)
    #: People in a linked source with no GoalGetter account yet. They arrive
    #: when their account is approved.
    not_yet_here: int = 0

    @property
    def moves(self) -> list[Person]:
        return [p for p in self.people if p.status == "would_move"]


@dataclass
class _Linked:
    source: M365Source
    link: M365Link
    members: set[str]


def _linked(db: DbSession, org_id: int) -> list[_Linked]:
    rows = db.execute(
        select(M365Link, M365Source)
        .join(M365Source, M365Source.id == M365Link.source_id)
        .where(M365Link.organization_id == org_id, M365Source.gone_at.is_(None))
    ).all()
    if not rows:
        return []
    members: dict[int, set[str]] = defaultdict(set)
    ids = [source.id for _, source in rows]
    # A standard channel is never linked, so every linked source has its own rows.
    for member in db.scalars(select(M365Member).where(M365Member.source_id.in_(ids))):
        members[member.source_id].add(member.person_external_id)
    out: list[_Linked] = []
    for link, source in rows:
        # A link to an archived team or office does nothing until it is back.
        if link.team_id is not None:
            team = db.get(Team, link.team_id)
            if team is None or team.archived_at is not None:
                continue
        if link.office_id is not None:
            office = db.get(Office, link.office_id)
            if office is None or office.archived_at is not None:
                continue
        out.append(_Linked(source=source, link=link, members=members[source.id]))
    return out


def picture(db: DbSession, org_id: int) -> Picture:
    """Everyone, where they are, where Microsoft Teams says they belong, and
    what a mirror would do about it — without doing anything."""
    out = Picture()
    linked = _linked(db, org_id)
    team_links = [x for x in linked if x.link.target == "team"]
    office_links = [x for x in linked if x.link.target == "office"]
    mirrored_teams = {x.link.team_id for x in team_links}

    # Offices through the Team a linked channel sits in.
    office_of_source = {x.source.id: x.link.office_id for x in office_links}
    team_office: dict[int, int] = {}
    for x in team_links:
        parent_office = office_of_source.get(x.source.parent_id) if x.source.parent_id else None
        if parent_office is not None and x.link.team_id is not None:
            team_office[x.link.team_id] = parent_office
    for team_id, office_id in sorted(team_office.items()):
        team = db.get(Team, team_id)
        if team is not None and team.office_id != office_id:
            out.office_changes.append(
                OfficeChange(team_id=team_id, from_office_id=team.office_id, to_office_id=office_id)
            )

    def office_after(team_id: int | None) -> int | None:
        if team_id is None:
            return None
        if team_id in team_office:
            return team_office[team_id]
        team = db.get(Team, team_id)
        return team.office_id if team else None

    directory = {
        row.user_account_id: row
        for row in db.scalars(
            select(DirectoryPerson).where(
                DirectoryPerson.organization_id == org_id,
                DirectoryPerson.archived_at.is_(None),
            )
        )
        if row.user_account_id is not None
    }
    placements = {
        row.user_id: row
        for row in db.scalars(
            select(MirrorPlacement)
            .join(UserAccount, UserAccount.id == MirrorPlacement.user_id)
            .where(UserAccount.organization_id == org_id)
        )
    }
    users = db.scalars(
        select(UserAccount).where(
            UserAccount.organization_id == org_id,
            UserAccount.hidden_at.is_(None),
            UserAccount.status != "deactivated",
        )
    ).all()

    # People in something linked who have no account here yet.
    with_accounts = {row.external_id for row in directory.values()}
    waiting: set[str] = set()
    for x in linked:
        waiting |= x.members - with_accounts
    out.not_yet_here = len(waiting)

    for user in users:
        row = directory.get(user.id)
        person = Person(
            user_id=user.id, name=user.full_name, email=user.email,
            status="not_in_m365", team_id=user.team_id,
        )
        out.people.append(person)
        if row is None or not row.enabled:
            continue
        person.m365_office = row.office_location or ""
        me = row.external_id

        mine = [x for x in team_links if me in x.members]
        # The finer grain wins: a channel over the Team it is in.
        parents = {x.source.parent_id for x in mine if x.source.parent_id}
        mine = [x for x in mine if x.source.id not in parents]
        offices = [x for x in office_links if me in x.members]
        person.sources = sorted(x.source.name for x in [*mine, *offices])

        choices = sorted({x.link.team_id for x in mine if x.link.team_id is not None})
        office_ids = sorted({x.link.office_id for x in offices if x.link.office_id is not None})

        current = user.team_id
        placed = placements.get(user.id)
        pinned_here = placed is not None and placed.pinned and placed.team_id == current

        if len(choices) > 1:
            # "Keep here" is also how a conflict is settled.
            person.status = "kept" if pinned_here else "conflict"
            person.teams_choices = choices
            continue

        desired = choices[0] if choices else None
        person.teams_team_id = desired
        person.teams_office_id = office_after(desired) if desired else (
            office_ids[0] if len(office_ids) == 1 else None
        )

        if desired is None and current not in mirrored_teams:
            person.status = "not_linked"
        elif desired == current:
            person.status = "in_step"
        elif pinned_here:
            person.status = "kept"
        elif placed is not None and placed.team_id != current:
            person.status = "moved_by_hand"
        elif desired is None and placed is None:
            # On a linked team, never put there by the mirror, and not in the
            # Microsoft Team. Not the mirror's work, so not the mirror's to undo.
            person.status = "only_here"
        else:
            person.status = "would_move"

    order = {status: i for i, status in enumerate(STATUSES)}
    out.people.sort(key=lambda p: (order[p.status], p.name.lower()))
    return out


def _place(db: DbSession, user: UserAccount, team_id: int | None, *, pinned: bool = False) -> None:
    row = db.get(MirrorPlacement, user.id)
    if team_id is None and not pinned:
        # Out of every mirrored team: no longer the mirror's to look after.
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(MirrorPlacement(user_id=user.id, team_id=team_id, pinned=pinned))
    else:
        row.team_id = team_id
        row.pinned = pinned


def apply(db: DbSession, org_id: int) -> Picture:
    """Make the moves the picture describes, **worked out again now** rather
    than trusting whatever a browser was shown a minute ago.

    Also records where everybody in step is, so a later hand move is noticed —
    and sets the office of each team a channel link puts in one.
    """
    decided = picture(db, org_id)
    for change in decided.office_changes:
        team = db.get(Team, change.team_id)
        if team is not None:
            team.office_id = change.to_office_id
    for person in decided.people:
        if person.status not in ("would_move", "in_step"):
            continue
        user = db.get(UserAccount, person.user_id)
        if user is None:
            continue
        if person.status == "would_move":
            user.team_id = person.teams_team_id
        _place(db, user, person.teams_team_id)
    # In a Team linked as an office, on no team: in that office, waiting for
    # one (Phase 28) — counted among its agents, with a warning.
    for person in decided.people:
        if person.teams_team_id is None and person.teams_office_id is not None:
            user = db.get(UserAccount, person.user_id)
            if user is not None and user.team_id is None and user.office_id is None:
                user.office_id = person.teams_office_id
    db.flush()
    return decided


def follow(db: DbSession, org_id: int, user_id: int) -> Person | None:
    """Hand one person back to the mirror: move them where Microsoft Teams says.

    Refused (None) for a conflict — which of two teams is right is not
    something to guess.
    """
    person = next((p for p in picture(db, org_id).people if p.user_id == user_id), None)
    if person is None or person.status in ("conflict", "not_in_m365", "not_linked"):
        return None
    if person.teams_choices:
        # Kept through a conflict: following would have to pick a side.
        return None
    user = db.get(UserAccount, user_id)
    user.team_id = person.teams_team_id
    _place(db, user, person.teams_team_id)
    db.flush()
    return person


def keep(db: DbSession, user: UserAccount) -> None:
    """Keep one person where they are, and stop listing them as a decision."""
    _place(db, user, user.team_id, pinned=True)
    db.flush()


def offices_match(a: str | None, b: str | None) -> bool:
    """Whether two office names are the same office, the way directory rules
    compare them."""
    return normalise(a or "") == normalise(b or "")
