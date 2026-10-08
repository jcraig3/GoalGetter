from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.models import MetricFact, Office, Team, UserAccount
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/offices", tags=["offices"])


class OfficeRead(BaseModel):
    id: int
    name: str
    description: str | None
    archived: bool
    team_count: int = 0
    # Agents reach an office through their team, so this is a two-hop count.
    # Shown because "how many people are in Phoenix" is the question an office
    # actually answers.
    agent_count: int = 0
    #: Of those, in the office with no team yet (Phase 28).
    unteamed_count: int = 0


class UnteamedPerson(BaseModel):
    id: int
    full_name: str
    email: str
    department: str


class OfficeCreate(BaseModel):
    name: Name(200)
    description: str | None = Field(default=None, max_length=500)


class OfficeUpdate(BaseModel):
    name: Name(200) | None = None
    description: str | None = Field(default=None, max_length=500)


def _to_read(
    office: Office, team_count: int = 0, agent_count: int = 0, unteamed: int = 0
) -> OfficeRead:
    return OfficeRead(
        unteamed_count=unteamed,
        id=office.id,
        name=office.name,
        description=office.description,
        archived=office.archived_at is not None,
        team_count=team_count,
        agent_count=agent_count + unteamed,
    )


def _unteamed(db: DbSession, org_id: int) -> dict[int, int]:
    """Office → how many people are in it with no team (Phase 28)."""
    return dict(
        db.execute(
            select(UserAccount.office_id, func.count())
            .where(
                UserAccount.organization_id == org_id,
                UserAccount.office_id.is_not(None),
                UserAccount.team_id.is_(None),
                UserAccount.hidden_at.is_(None),
            )
            .group_by(UserAccount.office_id)
        ).all()
    )


def _counts(db: DbSession, office_id: int) -> tuple[int, int]:
    teams = int(
        db.scalar(
            select(func.count())
            .select_from(Team)
            .where(Team.office_id == office_id, Team.archived_at.is_(None))
        )
        or 0
    )
    agents = int(
        db.scalar(
            select(func.count())
            .select_from(UserAccount)
            .join(Team, Team.id == UserAccount.team_id)
            .where(
                Team.office_id == office_id,
                Team.archived_at.is_(None),
                UserAccount.hidden_at.is_(None),
            )
        )
        or 0
    )
    return teams, agents


@router.get("", response_model=list[OfficeRead])
def list_offices(
    include_archived: bool = Query(default=False),
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[OfficeRead]:
    # Both counts in the same query as the offices themselves. Two separate
    # subqueries rather than one join chain, because joining teams and users in
    # a single pass would multiply rows and inflate the team count by the
    # number of agents on each team.
    team_counts = (
        select(Team.office_id, func.count(Team.id).label("teams"))
        .where(Team.archived_at.is_(None))
        .group_by(Team.office_id)
        .subquery()
    )
    agent_counts = (
        select(Team.office_id, func.count(UserAccount.id).label("agents"))
        .join(UserAccount, UserAccount.team_id == Team.id)
        .where(Team.archived_at.is_(None), UserAccount.hidden_at.is_(None))
        .group_by(Team.office_id)
        .subquery()
    )

    query = (
        select(
            Office,
            func.coalesce(team_counts.c.teams, 0),
            func.coalesce(agent_counts.c.agents, 0),
        )
        .outerjoin(team_counts, team_counts.c.office_id == Office.id)
        .outerjoin(agent_counts, agent_counts.c.office_id == Office.id)
        .where(Office.organization_id == user.organization_id)
    )
    if not include_archived:
        query = query.where(Office.archived_at.is_(None))

    rows = db.execute(query.order_by(func.lower(Office.name))).all()
    unteamed = _unteamed(db, user.organization_id)
    return [_to_read(o, t, a, unteamed.get(o.id, 0)) for o, t, a in rows]


@router.get("/{office_id}/unteamed", response_model=list[UnteamedPerson])
def list_unteamed(
    office_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[UnteamedPerson]:
    """The people in this office who aren't on a team yet (Phase 28)."""
    return [
        UnteamedPerson(id=u.id, full_name=u.full_name, email=u.email, department=u.department or "")
        for u in db.scalars(
            select(UserAccount)
            .where(
                UserAccount.organization_id == actor.organization_id,
                UserAccount.office_id == office_id,
                UserAccount.team_id.is_(None),
                UserAccount.hidden_at.is_(None),
            )
            .order_by(func.lower(UserAccount.full_name))
        ).all()
    ]


@router.post("", response_model=OfficeRead, status_code=status.HTTP_201_CREATED)
def create_office(
    payload: OfficeCreate,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> OfficeRead:
    _name_free(db, user.organization_id, payload.name)
    office = Office(
        organization_id=user.organization_id,
        name=payload.name,
        description=payload.description,
    )
    db.add(office)
    db.commit()
    return _to_read(office)


@router.patch("/{office_id}", response_model=OfficeRead)
def update_office(
    office_id: int,
    payload: OfficeUpdate,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> OfficeRead:
    office = _owned(db, office_id, user.organization_id)
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("name"):
        _name_free(db, user.organization_id, fields["name"], office.id)
    for field, value in fields.items():
        setattr(office, field, value)
    db.commit()
    return _to_read(office, *_counts(db, office.id))


def _name_free(db: DbSession, org_id: int, name: str, itself: int | None = None) -> None:
    """Refuse a name another office in use already has, ignoring case (QA-7).

    Checked first for the message; the unique index is what actually decides.
    """
    clash = db.scalar(
        select(Office.id).where(
            Office.organization_id == org_id,
            Office.archived_at.is_(None),
            func.lower(Office.name) == name.lower(),
            Office.id != (itself or 0),
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"There is already an office called “{name}”.",
        )


@router.post("/{office_id}/archive", response_model=OfficeRead)
def archive_office(
    office_id: int,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> OfficeRead:
    office = _owned(db, office_id, user.organization_id, allow_archived=True)
    office.archived_at = datetime.now(UTC)
    db.commit()
    return _to_read(office, *_counts(db, office.id))


@router.post("/{office_id}/restore", response_model=OfficeRead)
def restore_office(
    office_id: int,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> OfficeRead:
    office = _owned(db, office_id, user.organization_id, allow_archived=True)
    _name_free(db, user.organization_id, office.name, office.id)
    office.archived_at = None
    db.commit()
    return _to_read(office, *_counts(db, office.id))


@router.delete("/{office_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_office(
    office_id: int,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Permanently remove an office, only while no team points at it.

    Same rule as teams: history must keep naming the office a leaderboard
    belonged to, so once anything references it the correct action is archive.
    """
    office = _owned(db, office_id, user.organization_id, allow_archived=True)

    # `metric_fact.subject_office_id` is a snapshot taken at write time, so past
    # facts keep naming this office even after every team has moved out of it.
    # That is the point of the snapshot — deleting the office would leave last
    # quarter's office board naming nobody.
    facts = int(
        db.scalar(
            select(func.count())
            .select_from(MetricFact)
            .where(MetricFact.subject_office_id == office_id)
        )
        or 0
    )
    if facts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{facts:,} recorded measurements name this office. Archive it "
                "instead — that hides it while keeping its history readable."
            ),
        )

    teams, _ = _counts(db, office_id)
    if teams:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{teams} {'team is' if teams == 1 else 'teams are'} assigned to this "
                "office. Move them first, or archive the office to keep its history."
            ),
        )
    db.delete(office)
    db.commit()


def _owned(
    db: DbSession, office_id: int, organization_id: int, *, allow_archived: bool = False
) -> Office:
    office = db.get(Office, office_id)
    if office is None or office.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Office not found."
        )
    if office.archived_at is not None and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Office not found."
        )
    return office
