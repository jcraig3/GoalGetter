"""Choosing a sound for a celebration (6.17).

The picker's one request lists the starter pack and the organization's own
sounds; a pack sound is copied into the organization's store the moment it is
chosen. The defaults — what plays for each kind of win when the person has no
walk-up of their own — are set here too. See `app/sounds.py`.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import assets, audio, audit, media as media_service, sound_pack, sounds as service
from app.db import get_db
from app.models import Organization, StoredAsset, UserAccount, WalkupMedia
from app.sessions import current_user, require_role

router = APIRouter(prefix="/sounds", tags=["sounds"])


class PackSound(BaseModel):
    key: str
    name: str
    description: str
    seconds: float


class OwnSound(BaseModel):
    url: str
    digest: str
    name: str | None
    seconds: float | None


class Kind(BaseModel):
    key: str
    label: str


class Sounds(BaseModel):
    pack: list[PackSound]
    #: The organization's own sounds from Assets — not people's walk-ups,
    #: which are theirs.
    library: list[OwnSound]
    #: Kind of win → `asset:` sound, for what plays when the person has none.
    defaults: dict[str, str]
    kinds: list[Kind]


class Kept(BaseModel):
    url: str
    name: str


@router.get("", response_model=Sounds)
def list_sounds(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> Sounds:
    org = db.get(Organization, actor.organization_id)
    personal = {
        media_service.asset_digest(url)
        for url in db.scalars(
            select(WalkupMedia.url)
            .join(UserAccount, UserAccount.id == WalkupMedia.user_id)
            .where(UserAccount.organization_id == org.id, WalkupMedia.url.is_not(None))
        ).all()
    }
    rows = db.scalars(
        select(StoredAsset)
        .where(
            StoredAsset.organization_id == org.id,
            StoredAsset.content_type.startswith("audio/"),
        )
        .order_by(StoredAsset.created_at.desc())
    ).all()
    return Sounds(
        pack=[
            PackSound(key=s.key, name=s.name, description=s.description, seconds=sound_pack.seconds(s.key))
            for s in sound_pack.PACK
        ],
        library=[
            OwnSound(
                url=f"{media_service.ASSET_SCHEME}{row.sha256}",
                digest=row.sha256,
                name=row.name,
                seconds=round(row.duration_ms / 1000, 1) if row.duration_ms else None,
            )
            for row in rows
            if row.sha256 not in personal
        ],
        defaults=dict(org.celebration_sounds or {}),
        kinds=[Kind(key=k, label=v) for k, v in service.KIND_LABELS.items()],
    )


@router.get("/pack/{key}")
def play_pack_sound(key: str, _actor: UserAccount = Depends(current_user)) -> Response:
    """A pack sound, to listen to before choosing it."""
    if key not in sound_pack.BY_KEY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such sound.")
    return Response(
        sound_pack.wav(key),
        media_type="audio/wav",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/pack/{key}/keep", response_model=Kept)
def keep_pack_sound(
    key: str,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> Kept:
    """Copy a pack sound into the organization's store — the moment it is
    chosen, so a wall can fetch it and Assets can say where it is used. The
    same sound twice is one copy."""
    sound = sound_pack.BY_KEY.get(key)
    if sound is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such sound.")
    data, content_type, duration_ms = audio.normalise(sound_pack.wav(key))
    row = assets.keep(
        db, actor.organization_id, data, content_type=content_type, duration_ms=duration_ms
    )
    if not row.name:
        row.name = sound.name
        row.uploaded_by_user_id = actor.id
        audit.record(db, actor=actor, action="asset.added", request=request, name=sound.name, source="pack")
    db.commit()
    return Kept(url=f"{media_service.ASSET_SCHEME}{row.sha256}", name=row.name or sound.name)


@router.put("/defaults", response_model=dict[str, str])
def set_defaults(
    payload: dict[str, str | None],
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> dict[str, str]:
    """What plays for each kind of win when the person has no walk-up music.
    The whole set, each a sound in the organization's store or null for
    silence."""
    unknown = set(payload) - set(service.KIND_LABELS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown kind of win: {', '.join(sorted(unknown))}.",
        )
    chosen = {}
    for kind, url in payload.items():
        if url:
            service.audio_row(db, actor.organization_id, url)
            chosen[kind] = url
    org = db.get(Organization, actor.organization_id)
    org.celebration_sounds = chosen
    audit.record(db, actor=actor, action="celebration_sounds.updated", request=request,
                 kinds=sorted(chosen))
    db.commit()
    return chosen
