"""Custom roles: make one, say what it may not do, and put people in it.

Admin only. People are added to a role from here rather than from their own
page, so nothing about how a person is edited changes: a custom role is a
narrowing an admin applies on top of the built-in role somebody already has.
See `app/roles.py` for how it is enforced.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import audit, roles
from app.db import get_db
from app.models import CustomRole, UserAccount
from app.scope import capabilities_for
from app.sessions import require_role
from app.validation import Name

router = APIRouter(prefix="/roles", tags=["roles"])

ROLE_WORD = {"agent": "an agent", "manager": "a manager", "admin": "an admin"}
ROLE_PLURAL = {"agent": "agents", "manager": "managers", "admin": "admins"}


class Capability(BaseModel):
    key: str
    label: str


class Member(BaseModel):
    id: int
    name: str


class RoleRead(BaseModel):
    id: int
    name: str
    description: str | None
    base_role: str
    removed: list[str]
    members: list[Member]


class Catalogue(BaseModel):
    """What each built-in role could have taken away."""

    removable: dict[str, list[Capability]]
    roles: list[RoleRead]


class RoleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(60)
    description: str | None = Field(default=None, max_length=300)
    base_role: Literal["agent", "manager", "admin"]
    removed: list[str] = Field(default_factory=list)


class MemberWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int


def _removable(base: str) -> list[str]:
    """What this base can lose: what the server enforces, and what it has."""
    has = set(capabilities_for(base))
    return [key for key in roles.REMOVABLE if key in has]


def _read(db: DbSession, row: CustomRole) -> RoleRead:
    members = db.scalars(
        select(UserAccount)
        .where(UserAccount.custom_role_id == row.id)
        .order_by(func.lower(UserAccount.full_name))
    ).all()
    return RoleRead(
        id=row.id, name=row.name, description=row.description, base_role=row.base_role,
        removed=list(row.removed or []),
        members=[Member(id=m.id, name=m.full_name) for m in members],
    )


def _owned(db: DbSession, actor: UserAccount, role_id: int) -> CustomRole:
    row = db.get(CustomRole, role_id)
    if row is None or row.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")
    return row


def _apply(row: CustomRole, payload: RoleWrite) -> None:
    allowed = set(_removable(payload.base_role))
    unknown = set(payload.removed) - allowed
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{ROLE_WORD[payload.base_role].capitalize()} cannot lose '{sorted(unknown)[0]}'.",
        )
    if not payload.removed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Take away at least one thing — otherwise it is just the built-in role.",
        )
    row.name = payload.name.strip()
    row.description = (payload.description or "").strip() or None
    row.base_role = payload.base_role
    row.removed = [key for key in roles.REMOVABLE if key in set(payload.removed)]


@router.get("", response_model=Catalogue)
def list_roles(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Catalogue:
    rows = db.scalars(
        select(CustomRole)
        .where(CustomRole.organization_id == actor.organization_id)
        .order_by(func.lower(CustomRole.name))
    ).all()
    return Catalogue(
        removable={
            base: [Capability(key=k, label=roles.LABELS[k]) for k in _removable(base)]
            for base in ("manager", "admin", "agent")
        },
        roles=[_read(db, row) for row in rows],
    )


def _save(db: DbSession, row: CustomRole) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is already a role with that name.") from None


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: RoleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RoleRead:
    row = CustomRole(organization_id=actor.organization_id)
    _apply(row, payload)
    db.add(row)
    audit.record(db, actor=actor, action="role.created", request=request, name=row.name, removed=row.removed)
    _save(db, row)
    return _read(db, row)


@router.patch("/{role_id}", response_model=RoleRead)
def update_role(
    role_id: int,
    payload: RoleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RoleRead:
    row = _owned(db, actor, role_id)
    if payload.base_role != row.base_role and _read(db, row).members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="People are in this role. Remove them before changing what it is based on.",
        )
    _apply(row, payload)
    audit.record(db, actor=actor, action="role.updated", request=request, name=row.name, removed=row.removed)
    _save(db, row)
    return _read(db, row)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Remove it. Its people go back to their built-in role."""
    row = _owned(db, actor, role_id)
    audit.record(db, actor=actor, action="role.deleted", request=request, name=row.name)
    db.delete(row)
    db.commit()


@router.post("/{role_id}/members", response_model=RoleRead)
def add_member(
    role_id: int,
    payload: MemberWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RoleRead:
    row = _owned(db, actor, role_id)
    person = db.get(UserAccount, payload.user_id)
    if person is None or person.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found.")
    if person.org_role != row.base_role:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{person.full_name} is {ROLE_WORD[person.org_role]}, and this role is for {ROLE_PLURAL[row.base_role]}.",
        )
    if person.id == actor.id and {"integrations.manage", "org.settings.edit"} & set(row.removed or []):
        # Taking your own settings away is how an organization loses the one
        # person who could give them back.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot put yourself in a role that takes away settings or integrations.",
        )
    person.custom_role_id = row.id
    audit.record(db, actor=actor, action="role.member_added", request=request, target=person, name=row.name)
    db.commit()
    return _read(db, row)


@router.delete("/{role_id}/members/{user_id}", response_model=RoleRead)
def remove_member(
    role_id: int,
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RoleRead:
    row = _owned(db, actor, role_id)
    person = db.get(UserAccount, user_id)
    if person is None or person.custom_role_id != row.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not in this role.")
    person.custom_role_id = None
    audit.record(db, actor=actor, action="role.member_removed", request=request, target=person, name=row.name)
    db.commit()
    return _read(db, row)
