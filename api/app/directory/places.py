"""Offices and teams from Microsoft 365's Office and Department (Phase 28).

An admin picks, for each office value synced users have, an office here (an
existing one or a new one named after it), and for each department a team.
People are then sorted into them — now, and after every sync.

**Only people who aren't placed yet.** Somebody already on a team was put
there by a person or by the Teams mirror, and stays. Somebody matched to an
office but no team belongs to the office (`UserAccount.office_id`) and is
counted among its agents, with a warning until they are on a team.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.directory.rules import normalise
from app.models import Office, Team, UserAccount


def _people(db: DbSession, org_id: int) -> list[UserAccount]:
    return list(
        db.scalars(
            select(UserAccount).where(
                UserAccount.organization_id == org_id, UserAccount.hidden_at.is_(None)
            )
        ).all()
    )


def values(db: DbSession, org_id: int) -> dict[str, list[dict]]:
    """Each office and department synced people have, how many, and where it goes."""
    people = _people(db, org_id)
    offices = {
        normalise(o.m365_office): o.id
        for o in db.scalars(
            select(Office).where(Office.organization_id == org_id, Office.m365_office.is_not(None))
        ).all()
    }
    teams = {
        normalise(t.m365_department): t.id
        for t in db.scalars(
            select(Team).where(Team.organization_id == org_id, Team.m365_department.is_not(None))
        ).all()
    }

    def listed(field: str, linked: dict[str, int], key: str) -> list[dict]:
        spelt: dict[str, str] = {}
        counts: Counter[str] = Counter()
        for person in people:
            raw = (getattr(person, field) or "").strip()
            if raw:
                spelt.setdefault(normalise(raw), raw)
                counts[normalise(raw)] += 1
        return [
            {"value": spelt[n], "people": counts[n], key: linked.get(n)}
            for n in sorted(counts, key=lambda n: spelt[n].lower())
        ]

    return {
        "offices": listed("office_location", offices, "office_id"),
        "departments": listed("department", teams, "team_id"),
    }


def link_office(db: DbSession, org_id: int, value: str, office_id: int | None) -> None:
    """Send an office value to an office — a new one named after it when
    `office_id` is None — or, with `office_id` 0, to nowhere."""
    for office in db.scalars(
        select(Office).where(Office.organization_id == org_id, Office.m365_office.is_not(None))
    ).all():
        if normalise(office.m365_office) == normalise(value):
            office.m365_office = None
    if office_id == 0:
        db.flush()
        return
    office = db.get(Office, office_id) if office_id else None
    if office is None or office.organization_id != org_id:
        office = db.scalar(
            select(Office).where(Office.organization_id == org_id, Office.name == value.strip())
        ) or Office(organization_id=org_id, name=value.strip()[:200])
        db.add(office)
    office.m365_office = value.strip()
    db.flush()
    apply(db, org_id)


def link_department(db: DbSession, org_id: int, value: str, team_id: int | None) -> None:
    """Send a department to a team — a new one named after it when `team_id`
    is None — or, with `team_id` 0, to nowhere."""
    for team in db.scalars(
        select(Team).where(Team.organization_id == org_id, Team.m365_department.is_not(None))
    ).all():
        if normalise(team.m365_department) == normalise(value):
            team.m365_department = None
    if team_id == 0:
        db.flush()
        return
    team = db.get(Team, team_id) if team_id else None
    if team is None or team.organization_id != org_id:
        team = db.scalar(
            select(Team).where(Team.organization_id == org_id, Team.name == value.strip())
        ) or Team(organization_id=org_id, name=value.strip()[:200])
        db.add(team)
    team.m365_department = value.strip()
    db.flush()
    apply(db, org_id)


def apply(db: DbSession, org_id: int) -> int:
    """Place everybody not yet placed whose office or department is linked.
    Returns how many moved."""
    offices = {
        normalise(o.m365_office): o
        for o in db.scalars(
            select(Office).where(
                Office.organization_id == org_id,
                Office.m365_office.is_not(None),
                Office.archived_at.is_(None),
            )
        ).all()
    }
    teams = {
        normalise(t.m365_department): t
        for t in db.scalars(
            select(Team).where(
                Team.organization_id == org_id,
                Team.m365_department.is_not(None),
                Team.archived_at.is_(None),
            )
        ).all()
    }
    moved = 0
    for person in _people(db, org_id):
        office = offices.get(normalise(person.office_location or ""))
        if person.team_id is None:
            team = teams.get(normalise(person.department or ""))
            if team is not None:
                person.team_id = team.id
                # A new team made from a department lands in the person's office.
                if team.office_id is None and office is not None:
                    team.office_id = office.id
                moved += 1
                continue
            if office is not None and person.office_id is None:
                person.office_id = office.id
                moved += 1
    db.flush()
    return moved
