"""Choosing the piece you move round a game board.

Yours always; somebody else's if you manage them — the same reach walk-up
music has, and for the same reason: plenty of people never open their own
settings. Unlike walk-up music, the organization's "choose your own" switch
does not apply. That switch exists because a floor tires of hearing one
person's song nine hundred times, and nobody tires of seeing a car.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DbSession

from app import audit, game_boards
from app.db import get_db
from app.models import GameToken, UserAccount
from app.scope import can_see_user
from app.sessions import current_user

router = APIRouter(tags=["game boards"])


class FamilyRead(BaseModel):
    family: str
    token: str
    options: list[str]


def _subject(db: DbSession, actor: UserAccount, user_id: int | None) -> int:
    if user_id is None or user_id == actor.id:
        return actor.id
    if actor.org_role not in ("admin", "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed.")
    person = db.get(UserAccount, user_id)
    if (
        person is None
        or person.organization_id != actor.organization_id
        or not can_see_user(db, actor, person.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found.")
    return person.id


def _families(db: DbSession, user_id: int) -> list[FamilyRead]:
    return [
        FamilyRead(
            family=family,
            token=(
                row.token
                if (row := db.get(GameToken, (user_id, family)))
                else game_boards.DEFAULT_TOKEN
            ),
            options=list(options),
        )
        for family, options in game_boards.FAMILIES.items()
    ]


@router.get("/me/tokens", response_model=list[FamilyRead])
def read_tokens(
    user_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[FamilyRead]:
    return _families(db, _subject(db, actor, user_id))


class TokenWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    token: str


@router.put("/me/tokens", response_model=list[FamilyRead])
def write_token(
    payload: TokenWrite,
    request: Request,
    user_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[FamilyRead]:
    """Choose a piece for one family of board.

    Choosing the default removes the row rather than storing it, so "their own
    face" is the absence of a choice — which keeps it the default if the
    default ever changes.
    """
    subject_id = _subject(db, actor, user_id)
    options = game_boards.FAMILIES.get(payload.family)
    if options is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown kind of board."
        )
    if payload.token not in options:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Choose one of: {', '.join(options)}.",
        )

    row = db.get(GameToken, (subject_id, payload.family))
    if payload.token == game_boards.DEFAULT_TOKEN:
        if row is not None:
            db.delete(row)
    elif row is None:
        db.add(GameToken(user_id=subject_id, family=payload.family, token=payload.token))
    else:
        row.token = payload.token

    if subject_id != actor.id:
        # Somebody else's, so it is written down — the same rule walk-up music
        # follows when a manager sets it.
        audit.record(
            db, actor=actor, action="game_token.changed", request=request,
            family=payload.family, token=payload.token,
        )
    db.commit()
    return _families(db, subject_id)
