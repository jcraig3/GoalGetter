"""Microsoft Teams → GoalGetter teams and offices: the admin's side of it.

One page answers three questions, in this order: *what does Microsoft Teams
have* (the tree, each line with a "use as" choice), *where is everybody
compared with it* (the comparison), and *what would change* (the moves). The
engine is `app/directory/mirror.py`; this module only shapes it for a page.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.db import get_db
from app.directory import mirror
from app.directory import sync as directory_sync
from app.models import (
    M365Link,
    M365Member,
    M365Source,
    MirrorPlacement,
    OauthClient,
    Office,
    Team,
    UserAccount,
)
from app.sessions import require_role

router = APIRouter(prefix="/admin/directory/mirror", tags=["directory"])


class LinkRead(BaseModel):
    target: Literal["team", "office"]
    id: int
    name: str


class SourceRead(BaseModel):
    id: int
    kind: Literal["team", "channel"]
    name: str
    #: For a channel: standard, private or shared.
    membership: str | None = None
    parent_id: int | None = None
    #: How many people the last read found. None when their members have not
    #: been read — nothing is linked to it yet.
    people: int | None = None
    standard_channels: int = 0
    #: Whether it can be used as a team or office. **A standard channel cannot**:
    #: everybody in its Team is in it, so it could only ever repeat the Team.
    #: Listed anyway, so an admin looking for one finds it and is told why.
    linkable: bool = True
    gone: bool = False
    link: LinkRead | None = None


class Named(BaseModel):
    id: int
    name: str
    office_id: int | None = None


class PersonRead(BaseModel):
    user_id: int
    name: str
    email: str
    status: str
    team_id: int | None
    team: str | None
    office: str | None
    teams_team_id: int | None
    teams_team: str | None
    #: For a conflict: every team Microsoft Teams puts them in.
    teams_choices: list[str]
    teams_office: str | None
    #: The office field in Entra, which is free text.
    m365_office: str
    sources: list[str]
    #: Their office here is not the one Microsoft Teams implies.
    office_differs_teams: bool
    #: Their office here is not the one Entra's office field names.
    office_differs_m365: bool


class OfficeChangeRead(BaseModel):
    team: str
    from_office: str | None
    to_office: str


class MirrorRead(BaseModel):
    #: Whether directory sync reads a Microsoft tenant at all. Everything here
    #: needs it; the page says so rather than showing empty lists.
    available: bool
    auto: bool
    read_at: datetime | None
    #: What could not be read last time — a permission to grant, usually.
    note: str | None
    sources: list[SourceRead]
    teams: list[Named]
    offices: list[Named]
    people: list[PersonRead]
    office_changes: list[OfficeChangeRead]
    counts: dict[str, int]
    not_yet_here: int


def _connection(db: DbSession, org_id: int) -> OauthClient | None:
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id,
            OauthClient.provider == "microsoft",
            OauthClient.directory_sync_enabled.is_(True),
        )
    )


def _need_connection(db: DbSession, org_id: int) -> OauthClient:
    connection = _connection(db, org_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Switch on tenant user sync first — this reads the same Microsoft 365 connection.",
        )
    return connection


def _read(db: DbSession, org_id: int) -> MirrorRead:
    connection = _connection(db, org_id)
    teams = {
        t.id: t
        for t in db.scalars(select(Team).where(Team.organization_id == org_id))
    }
    offices = {
        o.id: o
        for o in db.scalars(select(Office).where(Office.organization_id == org_id))
    }

    sources = db.scalars(
        select(M365Source)
        .where(M365Source.organization_id == org_id)
        .order_by(func.lower(M365Source.name))
    ).all()
    links = {
        link.source_id: link
        for link in db.scalars(select(M365Link).where(M365Link.organization_id == org_id))
    }
    counts = dict(
        db.execute(
            select(M365Member.source_id, func.count())
            .join(M365Source, M365Source.id == M365Member.source_id)
            .where(M365Source.organization_id == org_id)
            .group_by(M365Member.source_id)
        ).all()
    )
    standard: dict[int, int] = {}
    for s in sources:
        if s.kind == "channel" and s.membership == "standard" and s.parent_id:
            standard[s.parent_id] = standard.get(s.parent_id, 0) + 1

    def link_of(source: M365Source) -> LinkRead | None:
        link = links.get(source.id)
        if link is None:
            return None
        if link.target == "team" and link.team_id in teams:
            return LinkRead(target="team", id=link.team_id, name=teams[link.team_id].name)
        if link.target == "office" and link.office_id in offices:
            return LinkRead(target="office", id=link.office_id, name=offices[link.office_id].name)
        return None

    listed = [
        SourceRead(
            id=s.id, kind=s.kind, name=s.name, membership=s.membership,
            parent_id=s.parent_id,
            # Nobody counted is "not read" only when nothing ever was.
            people=counts.get(s.id, 0) if (s.id in links or s.id in counts) else None,
            standard_channels=standard.get(s.id, 0),
            linkable=not (s.kind == "channel" and s.membership == "standard"),
            gone=s.gone_at is not None,
            link=link_of(s),
        )
        for s in sources
        # Something gone and unlinked is history nobody needs to see.
        if not (s.gone_at is not None and s.id not in links)
    ]

    decided = mirror.picture(db, org_id)

    def team_name(team_id: int | None) -> str | None:
        return teams[team_id].name if team_id in teams else None

    def office_name(office_id: int | None) -> str | None:
        return offices[office_id].name if office_id in offices else None

    people: list[PersonRead] = []
    tally: dict[str, int] = {s: 0 for s in mirror.STATUSES}
    for p in decided.people:
        tally[p.status] += 1
        here_office_id = teams[p.team_id].office_id if p.team_id in teams else None
        here_office = office_name(here_office_id)
        teams_office = office_name(p.teams_office_id)
        people.append(
            PersonRead(
                user_id=p.user_id, name=p.name, email=p.email, status=p.status,
                team_id=p.team_id, team=team_name(p.team_id), office=here_office,
                teams_team_id=p.teams_team_id, teams_team=team_name(p.teams_team_id),
                teams_choices=[n for n in (team_name(t) for t in p.teams_choices) if n],
                teams_office=teams_office,
                m365_office=p.m365_office,
                sources=p.sources,
                office_differs_teams=bool(teams_office) and not mirror.offices_match(here_office, teams_office),
                office_differs_m365=bool(p.m365_office) and not mirror.offices_match(here_office, p.m365_office),
            )
        )

    return MirrorRead(
        available=connection is not None,
        auto=bool(connection and connection.directory_mirror_teams),
        read_at=connection.teams_read_at if connection else None,
        note=connection.teams_read_note if connection else None,
        sources=listed,
        teams=[
            Named(id=t.id, name=t.name, office_id=t.office_id)
            for t in sorted(teams.values(), key=lambda t: t.name.lower())
            if t.archived_at is None
        ],
        offices=[
            Named(id=o.id, name=o.name)
            for o in sorted(offices.values(), key=lambda o: o.name.lower())
            if o.archived_at is None
        ],
        people=people,
        office_changes=[
            OfficeChangeRead(
                team=team_name(c.team_id) or "",
                from_office=office_name(c.from_office_id),
                to_office=office_name(c.to_office_id) or "",
            )
            for c in decided.office_changes
        ],
        counts=tally,
        not_yet_here=decided.not_yet_here,
    )


@router.get("", response_model=MirrorRead)
def read_mirror(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """What Microsoft Teams has, where everybody is compared with it, and what
    a mirror would change — before anything moves."""
    return _read(db, actor.organization_id)


@router.post("/read", response_model=MirrorRead)
def read_from_microsoft(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Read every Team and every channel now, so one can be picked.

    The one read of everything: a scheduled sync asks only about what is
    linked. Moves nobody.
    """
    connection = _need_connection(db, actor.organization_id)
    directory_sync.read_teams_structure(
        db, connection, now=datetime.now(UTC), everything=True
    )
    db.commit()
    return _read(db, actor.organization_id)


class LinkWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_as: Literal["nothing", "team", "office"]
    #: The existing team or office. Absent means make one named after the
    #: Microsoft Team or channel — or use the one already called that.
    id: int | None = None
    name: str | None = Field(default=None, max_length=200)


@router.put("/sources/{source_id}", response_model=MirrorRead)
def set_link(
    source_id: int,
    payload: LinkWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Use a Microsoft Team or channel as a GoalGetter team, an office, or
    nothing.

    **Linking moves nobody.** It changes the comparison; people move when an
    admin applies it, or on the next sync if that is switched on. Unlinking
    leaves the team and everybody in it exactly as they are.
    """
    org_id = actor.organization_id
    connection = _need_connection(db, org_id)
    source = db.get(M365Source, source_id)
    if source is None or source.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    existing = db.scalar(select(M365Link).where(M365Link.source_id == source.id))
    if payload.use_as == "nothing":
        if existing is not None:
            audit.record(
                db, actor=actor, action="m365.unlinked", request=request,
                source=source.name, use_as=existing.target,
            )
            db.delete(existing)
            db.commit()
        return _read(db, org_id)

    if source.gone_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{source.name} is no longer in Microsoft Teams.",
        )
    if source.kind == "channel" and source.membership == "standard":
        # Its people are its Team's, so it could only ever repeat the Team.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A standard channel has exactly its Team's people. Use the Team instead.",
        )

    name = (payload.name or source.name).strip()[:200] or source.name[:200]
    if payload.use_as == "team":
        target = _team_for(db, org_id, payload.id, name)
        other = db.scalar(select(M365Link).where(M365Link.team_id == target.id))
    else:
        target = _office_for(db, org_id, payload.id, name)
        other = db.scalar(select(M365Link).where(M365Link.office_id == target.id))
    if other is not None and other.source_id != source.id:
        taken = db.get(M365Source, other.source_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{target.name} already follows {taken.name if taken else 'another source'}.",
        )

    if existing is None:
        existing = M365Link(organization_id=org_id, source_id=source.id, target=payload.use_as)
        db.add(existing)
    existing.target = payload.use_as
    existing.team_id = target.id if payload.use_as == "team" else None
    existing.office_id = target.id if payload.use_as == "office" else None
    audit.record(
        db, actor=actor, action="m365.linked", request=request,
        source=source.name, use_as=payload.use_as, name=target.name,
    )
    db.flush()

    # Read who is in it now, so the comparison is right straight away rather
    # than after the next sync. Only this source — see `structure.py`.
    directory_sync.read_teams_structure(db, connection, now=datetime.now(UTC))
    db.commit()
    return _read(db, org_id)


def _team_for(db: DbSession, org_id: int, team_id: int | None, name: str) -> Team:
    if team_id is not None:
        team = db.get(Team, team_id)
        if team is None or team.organization_id != org_id or team.archived_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
        return team
    # The team already called this, if there is one — a second "Phoenix Sales"
    # beside the first would be two teams nobody can tell apart.
    team = db.scalar(
        select(Team).where(
            Team.organization_id == org_id,
            func.lower(Team.name) == name.lower(),
            Team.archived_at.is_(None),
        )
    )
    if team is None:
        team = Team(organization_id=org_id, name=name)
        db.add(team)
        db.flush()
    return team


def _office_for(db: DbSession, org_id: int, office_id: int | None, name: str) -> Office:
    if office_id is not None:
        office = db.get(Office, office_id)
        if office is None or office.organization_id != org_id or office.archived_at is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found.")
        return office
    office = db.scalar(
        select(Office).where(
            Office.organization_id == org_id,
            func.lower(Office.name) == name.lower(),
            Office.archived_at.is_(None),
        )
    )
    if office is None:
        office = Office(organization_id=org_id, name=name)
        db.add(office)
        db.flush()
    return office


@router.post("/apply", response_model=MirrorRead)
def apply_mirror(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Move people as the comparison says — worked out again now, not trusted
    from the page. Team only; a role is never changed here."""
    done = mirror.apply(db, actor.organization_id)
    for person in done.moves:
        audit.record(
            db, actor=actor, action="team.mirror_moved", request=request,
            person=person.name,
            team_id=audit.changed(person.team_id, person.teams_team_id),
        )
    db.commit()
    return _read(db, actor.organization_id)


def _person(db: DbSession, actor: UserAccount, user_id: int) -> UserAccount:
    user = db.get(UserAccount, user_id)
    if user is None or user.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return user


@router.post("/people/{user_id}/follow", response_model=MirrorRead)
def follow_teams(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Put one person where Microsoft Teams says, and let the mirror look after
    them again."""
    user = _person(db, actor, user_id)
    before = user.team_id
    moved = mirror.follow(db, actor.organization_id, user.id)
    if moved is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Microsoft Teams does not say one place for them — move them by hand.",
        )
    if before != user.team_id:
        audit.record(
            db, actor=actor, action="user.team_changed", request=request, target=user,
            team_id=audit.changed(before, user.team_id),
        )
    db.commit()
    return _read(db, actor.organization_id)


@router.post("/people/{user_id}/keep", response_model=MirrorRead)
def keep_here(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Keep one person on the team they are on, whatever Microsoft Teams says."""
    user = _person(db, actor, user_id)
    mirror.keep(db, user)
    audit.record(db, actor=actor, action="team.mirror_kept", request=request, target=user)
    db.commit()
    return _read(db, actor.organization_id)


@router.delete("/people/{user_id}/keep", response_model=MirrorRead)
def stop_keeping(
    user_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Undo "Keep here": they are the mirror's again, and the comparison says
    what it would do with them."""
    user = _person(db, actor, user_id)
    row = db.get(MirrorPlacement, user.id)
    if row is not None and row.pinned:
        db.delete(row)
        db.commit()
    return _read(db, actor.organization_id)


class MirrorAuto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


@router.put("/auto", response_model=MirrorRead)
def set_mirror_auto(
    payload: MirrorAuto,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MirrorRead:
    """Let each directory sync apply the mirror by itself. Hand moves are left
    alone either way."""
    connection = _need_connection(db, actor.organization_id)
    connection.directory_mirror_teams = payload.on
    audit.record(db, actor=actor, action="team.mirror_auto", request=request, on=str(payload.on))
    db.commit()
    return _read(db, actor.organization_id)
