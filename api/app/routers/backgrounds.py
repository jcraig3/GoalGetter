"""The background library.

Admin only, like every other appearance setting: a background is part of what
goes on a public wall, and choosing one is the same decision as choosing the
screen's colours.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import audit, backgrounds as library
from app.appearance import LENIENT, Appearance, Background, resolve
from app.db import get_db
from app.models import Organization, SavedBackground, StoredAsset, UserAccount
from app.models.background_library import CATEGORIES
from app.sessions import require_role
from app.validation import Name

router = APIRouter(prefix="/backgrounds", tags=["backgrounds"])


class EntryRead(BaseModel):
    #: `bundled:<key>` or `saved:<id>` — one id space for the picker, so a
    #: bundled background and a kept one can sit on the same shelf.
    id: str
    name: str
    category: str
    background: dict
    bundled: bool
    created_at: datetime | None = None


class LibraryRead(BaseModel):
    categories: list[str]
    entries: list[EntryRead]


@router.get("", response_model=LibraryRead)
def read_library(
    # Managers browse it for an announcement's background (Phase 25).
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> LibraryRead:
    """Everything on the shelves: what ships, then what this organization kept.

    The brand shelf is built from the organization's colours as they are *now*,
    which is why it is computed here rather than stored.
    """
    org = db.get(Organization, actor.organization_id)
    brand = resolve(org.appearance)

    saved = db.scalars(
        select(SavedBackground)
        .where(SavedBackground.organization_id == org.id)
        .order_by(SavedBackground.created_at.desc())
    ).all()

    return LibraryRead(
        categories=[*CATEGORIES, "assets"],
        entries=[
            *_from_assets(db, org),
            *(
                EntryRead(
                    id=f"saved:{row.id}",
                    name=row.name,
                    category=row.category,
                    # Lenient, like `resolve`: an entry kept before colours
                    # were checked drops the bad value rather than failing the
                    # whole library.
                    background=Appearance.model_validate(
                        {"background": row.background}, context={LENIENT: True}
                    ).background.model_dump(exclude_none=True),
                    bundled=False,
                    created_at=row.created_at,
                )
                for row in saved
            ),
            *(
                EntryRead(
                    id=f"bundled:{preset.id}",
                    name=preset.name,
                    category=preset.category,
                    background=preset.background,
                    bundled=True,
                )
                for preset in library.bundled_for(brand)
            ),
        ],
    )


def _from_assets(db: DbSession, org: Organization) -> list[EntryRead]:
    """**Your photos & video** (6.9): pictures and footage from Assets.

    Photographs and video only — a picture with transparency is art, not a
    backdrop, and people's photographs are theirs, not a wall's. Dimmed a
    little, as an uploaded background is, because the words go over them.
    """
    from app import asset_library

    photos = asset_library.photo_ids(db, org)
    rows = db.scalars(
        select(StoredAsset)
        .where(
            StoredAsset.organization_id == org.id,
            StoredAsset.content_type.in_(("image/jpeg", "video/mp4")),
        )
        .order_by(StoredAsset.created_at.desc())
    ).all()
    out = []
    for row in rows:
        if row.id in photos:
            continue
        kind = "video" if row.content_type == "video/mp4" else "image"
        out.append(
            EntryRead(
                id=f"asset:{row.sha256}",
                name=row.name or ("Video" if kind == "video" else "Photograph"),
                category="assets",
                background={"kind": kind, "asset": row.sha256, "dim": 0.35},
                bundled=True,
                created_at=row.created_at,
            )
        )
    return out


class EntryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(60)
    category: str
    #: Validated strictly through the same model a screen uses, so a library
    #: entry is never something a screen would refuse.
    background: Background


def _check(payload: EntryWrite) -> None:
    if payload.category not in CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Choose one of: {', '.join(CATEGORIES)}.",
        )
    # Nothing to keep. "None" and "inherit" are the absence of a background,
    # and a library entry that draws nothing is a swatch that looks broken.
    if payload.background.kind in (None, "none", "inherit"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="There is no background to keep.",
        )
    if payload.background.kind in ("image", "video", "youtube") and not payload.background.asset:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Upload or choose the file before keeping it.",
        )


def _entry(row: SavedBackground) -> EntryRead:
    return EntryRead(
        id=f"saved:{row.id}", name=row.name, category=row.category,
        background=row.background, bundled=False, created_at=row.created_at,
    )


@router.post("", response_model=EntryRead, status_code=status.HTTP_201_CREATED)
def keep(
    payload: EntryWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> EntryRead:
    """Keep a background so it can be used again."""
    _check(payload)
    row = SavedBackground(
        organization_id=actor.organization_id,
        name=payload.name.strip(),
        category=payload.category,
        background=payload.background.model_dump(exclude_none=True),
        created_by_user_id=actor.id,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A background with that name is already in the library.",
        ) from None
    audit.record(
        db, actor=actor, action="background.kept", request=request, name=row.name
    )
    db.commit()
    return _entry(row)


def _saved(db: DbSession, actor: UserAccount, entry_id: int) -> SavedBackground:
    row = db.get(SavedBackground, entry_id)
    if row is None or row.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not in the library."
        )
    return row


@router.patch("/{entry_id}", response_model=EntryRead)
def update(
    entry_id: int,
    payload: EntryWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> EntryRead:
    """Rename, re-shelve or change a kept background.

    **Changes no wall already using it** — choosing an entry copied it onto the
    screen. That is the point: nothing on a television should move because
    somebody tidied the library.
    """
    row = _saved(db, actor, entry_id)
    _check(payload)
    row.name = payload.name.strip()
    row.category = payload.category
    row.background = payload.background.model_dump(exclude_none=True)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A background with that name is already in the library.",
        ) from None
    audit.record(
        db, actor=actor, action="background.updated", request=request, name=row.name
    )
    db.commit()
    return _entry(row)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    entry_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Take a background off the shelf. Walls using it keep it."""
    row = _saved(db, actor, entry_id)
    audit.record(
        db, actor=actor, action="background.removed", request=request, name=row.name
    )
    db.delete(row)
    db.commit()
