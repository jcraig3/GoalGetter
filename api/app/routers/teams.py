import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.models import M365Link, M365Source, MetricFact, Office, StoredAsset, Team, UserAccount
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamRead(BaseModel):
    id: int
    name: str
    description: str | None
    color: str | None
    #: Up to twelve characters, for where the name will not fit (6.7).
    short_name: str | None = None
    #: A picture from Assets, by digest.
    logo: str | None = None
    archived: bool
    member_count: int = 0
    office_id: int | None = None
    office_name: str | None = None
    #: The Microsoft Team or channel this team follows, when it follows one.
    #: People can still be moved in and out by hand — the mirror notices and
    #: leaves those moves alone. See `app/directory/mirror.py`.
    follows: str | None = None


class TeamCreate(BaseModel):
    name: Name(200)
    office_id: int | None = None
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, max_length=7)
    short_name: str | None = Field(default=None, max_length=12)
    logo: str | None = Field(default=None, max_length=64)


class TeamUpdate(BaseModel):
    name: Name(200) | None = None
    # None means "no office"; absent means "leave it alone" — resolved with
    # model_fields_set in the handler.
    office_id: int | None = None
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, max_length=7)
    short_name: str | None = Field(default=None, max_length=12)
    logo: str | None = Field(default=None, max_length=64)


def _to_read(
    team: Team, member_count: int = 0, office_name: str | None = None
) -> TeamRead:
    return TeamRead(
        id=team.id,
        name=team.name,
        description=team.description,
        color=team.color,
        short_name=team.short_name,
        logo=team.logo,
        archived=team.archived_at is not None,
        member_count=member_count,
        office_id=team.office_id,
        office_name=office_name,
    )


def _office_name(db: DbSession, team: Team) -> str | None:
    office = db.get(Office, team.office_id) if team.office_id else None
    return office.name if office else None


def _check_office(db: DbSession, office_id: int | None, organization_id: int) -> None:
    if office_id is None:
        return
    office = db.get(Office, office_id)
    if (
        office is None
        or office.organization_id != organization_id
        or office.archived_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Office not found."
        )


def _member_count(db: DbSession, team_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(UserAccount)
            .where(
                UserAccount.team_id == team_id,
                UserAccount.hidden_at.is_(None),
            )
        )
        or 0
    )


@router.get("", response_model=list[TeamRead])
def list_teams(
    include_archived: bool = Query(default=False),
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[TeamRead]:
    # Counts come from one grouped outer join rather than a count query per
    # team — the N+1 problem again, and it shows up the moment there are 20
    # teams on screen.
    query = (
        select(Team, func.count(UserAccount.id), Office.name)
        .outerjoin(
            UserAccount,
            (UserAccount.team_id == Team.id) & UserAccount.hidden_at.is_(None),
        )
        .outerjoin(Office, Office.id == Team.office_id)
        .where(Team.organization_id == user.organization_id)
        .group_by(Team.id, Office.name)
    )
    if not include_archived:
        query = query.where(Team.archived_at.is_(None))

    rows = db.execute(query.order_by(func.lower(Team.name))).all()
    follows = dict(
        db.execute(
            select(M365Link.team_id, M365Source.name)
            .join(M365Source, M365Source.id == M365Link.source_id)
            .where(
                M365Link.organization_id == user.organization_id,
                M365Link.team_id.is_not(None),
                M365Source.gone_at.is_(None),
            )
        ).all()
    )
    out = [_to_read(team, count, office_name) for team, count, office_name in rows]
    for read in out:
        read.follows = follows.get(read.id)
    return out


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _identity(db: DbSession, org_id: int, fields: dict) -> dict:
    """A team's colour, short name and logo, checked (6.7).

    Only the keys that were sent come back, so an update leaves the others
    alone. Empty means none.
    """
    out: dict = {}
    if "color" in fields:
        colour = (fields["color"] or "").strip() or None
        if colour is not None and not _HEX.fullmatch(colour):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A team colour is written like #2563eb.",
            )
        out["color"] = colour.lower() if colour else None
    if "short_name" in fields:
        out["short_name"] = " ".join((fields["short_name"] or "").split()) or None
    if "logo" in fields:
        logo = fields["logo"] or None
        if logo is not None and db.scalar(
            select(StoredAsset.id).where(
                StoredAsset.organization_id == org_id,
                StoredAsset.sha256 == logo,
                StoredAsset.content_type.like("image/%"),
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That logo is not a picture in your Assets.",
            )
        out["logo"] = logo
    return out


@router.post("", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TeamRead:
    _check_office(db, payload.office_id, user.organization_id)
    look = _identity(db, user.organization_id, payload.model_dump(exclude_unset=True))
    team = Team(
        organization_id=user.organization_id,
        office_id=payload.office_id,
        name=payload.name,
        description=payload.description,
        color=look.get("color"),
        short_name=look.get("short_name"),
        logo=look.get("logo"),
    )
    db.add(team)
    db.commit()
    return _to_read(team, _member_count(db, team.id), _office_name(db, team))


@router.patch("/{team_id}", response_model=TeamRead)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TeamRead:
    team = _owned(db, team_id, user.organization_id)
    fields = payload.model_dump(exclude_unset=True)
    if "office_id" in fields:
        _check_office(db, fields["office_id"], user.organization_id)
    fields.update(_identity(db, user.organization_id, fields))
    # exclude_unset so an omitted field means "leave alone", not "set to null".
    for field, value in fields.items():
        setattr(team, field, value)
    db.commit()
    return _to_read(team, _member_count(db, team.id), _office_name(db, team))


@router.post("/{team_id}/archive", response_model=TeamRead)
def archive_team(
    team_id: int,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TeamRead:
    team = _owned(db, team_id, user.organization_id, allow_archived=True)
    team.archived_at = datetime.now(UTC)
    db.commit()
    return _to_read(team, _member_count(db, team.id), _office_name(db, team))


@router.post("/{team_id}/restore", response_model=TeamRead)
def restore_team(
    team_id: int,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TeamRead:
    team = _owned(db, team_id, user.organization_id, allow_archived=True)
    team.archived_at = None
    db.commit()
    return _to_read(team, _member_count(db, team.id), _office_name(db, team))


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Permanently remove a team.

    Allowed only while nothing references it. History has to keep naming the
    team that won last quarter, so once a team has members — and later, once it
    has metric facts — the correct action is archive, which hides it without
    erasing what points at it.

    Delete therefore exists for exactly one case: a team created by mistake.
    """
    team = _owned(db, team_id, user.organization_id, allow_archived=True)

    # `metric_fact.subject_team_id` is a snapshot taken at event time, so past
    # facts keep pointing at this team even after everyone has moved off it.
    # That is the whole point of the snapshot — deleting the team would leave
    # last quarter's team leaderboard naming nobody.
    facts = int(
        db.scalar(
            select(func.count())
            .select_from(MetricFact)
            .where(MetricFact.subject_team_id == team_id)
        )
        or 0
    )
    if facts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{facts:,} recorded measurements name this team. Archive it "
                "instead — that hides it while keeping its history readable."
            ),
        )

    members = _member_count(db, team_id)
    if members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{members} {'person is' if members == 1 else 'people are'} assigned to "
                "this team. Move them first, or archive the team to keep its history."
            ),
        )

    db.delete(team)
    db.commit()


def _owned(
    db: DbSession, team_id: int, organization_id: int, *, allow_archived: bool = False
) -> Team:
    team = db.get(Team, team_id)
    # 404 rather than 403 for another organization's team: confirming it exists
    # would itself leak information.
    if team is None or team.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    if team.archived_at is not None and not allow_archived:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    return team
