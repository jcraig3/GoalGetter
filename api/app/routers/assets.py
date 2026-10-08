"""Organization → Assets (6.3). See `app/asset_library.py`.

Upload, browse, rename and remove the images, video and sound an organization
holds. Serving the bytes stays where it was — `GET /api/images/{digest}` for a
signed-in page and the display's own route for a wall — because a file in the
library is the same file wherever it is used.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import asset_library, assets, audio, audit, images, video
from app.db import get_db
from app.models import Organization, StoredAsset, UserAccount
from app.sessions import require_role

router = APIRouter(prefix="/assets", tags=["assets"])

#: The largest file the library takes: the video limit, the biggest of the three.
MAX_BYTES = max(images.MAX_UPLOAD_BYTES, video.MAX_UPLOAD_BYTES, audio.MAX_UPLOAD_BYTES)


class UsageRead(BaseModel):
    label: str
    link: str


class AssetRead(BaseModel):
    digest: str
    kind: str
    content_type: str
    byte_size: int
    width: int | None
    height: int | None
    duration_ms: int | None
    name: str | None
    created_at: datetime
    #: Everywhere it is used. Empty means it can be removed.
    used_in: list[UsageRead]
    #: For a person's photograph (the Profile pics shelf): whose it is, and
    #: whether it was uploaded here or synced from Microsoft 365.
    photo_of: str | None = None
    photo_source: str | None = None


class AssetRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)


def _read(
    row: StoredAsset, used: list[asset_library.Usage], owner: tuple[str, str] | None = None
) -> AssetRead:
    return AssetRead(
        photo_of=owner[0] if owner else None,
        photo_source=owner[1] if owner else None,
        digest=row.sha256,
        kind=asset_library.kind_of(row),
        content_type=row.content_type,
        byte_size=row.byte_size,
        width=row.width,
        height=row.height,
        duration_ms=row.duration_ms,
        name=row.name,
        created_at=row.created_at,
        used_in=[UsageRead(label=u.label, link=u.link) for u in used],
    )


def _org(db: DbSession, actor: UserAccount) -> Organization:
    return db.get(Organization, actor.organization_id)


def _owned(db: DbSession, actor: UserAccount, digest: str) -> StoredAsset:
    row = db.scalar(
        select(StoredAsset).where(
            StoredAsset.organization_id == actor.organization_id,
            StoredAsset.sha256 == digest,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    return row


@router.get("", response_model=list[AssetRead])
def list_assets(
    photos: bool = False,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[AssetRead]:
    """Every file, newest first; with `?photos=true`, people's photographs
    too, labelled with whose they are (Phase 27) — the pickers leave them out.
    Managers too, to pick from for an announcement
    (Phase 25); renaming and removing stay an admin's."""
    org = _org(db, actor)
    owners = asset_library.photo_owners(db, org)
    used = asset_library.usages(db, org)
    rows = db.scalars(
        select(StoredAsset)
        .where(StoredAsset.organization_id == org.id)
        .order_by(StoredAsset.created_at.desc(), StoredAsset.id.desc())
    ).all()
    return [
        _read(row, used.get(row.sha256, []), owners.get(row.id))
        for row in rows
        if photos or row.id not in owners
    ]


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> AssetRead:
    """Add a picture, a video or a sound to the library.

    **The file is the body**, as everywhere else uploads happen here, with its
    name in `X-File-Name`. What it is comes from the bytes, not the name or
    the browser's claim: the declared type only picks which check runs first,
    and each check decides for itself.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"The largest file accepted is {MAX_BYTES // (1024 * 1024)} MB.",
        )
    raw = await request.body()
    claimed = (request.headers.get("content-type") or "").split("/", 1)[0]

    def as_image():
        if len(raw) > images.MAX_UPLOAD_BYTES:
            raise images.ImageProblem(
                f"A picture can be up to {images.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )
        return images.store_library_image(db, actor.organization_id, raw)

    def as_video():
        if len(raw) > video.MAX_UPLOAD_BYTES:
            raise video.VideoProblem(
                f"A video can be up to {video.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            )
        return video.store_background(db, actor.organization_id, raw)

    def as_audio():
        data, content_type, duration_ms = audio.normalise(raw)
        return assets.keep(
            db, actor.organization_id, data,
            content_type=content_type, duration_ms=duration_ms,
        )

    tries = {"image": as_image, "video": as_video, "audio": as_audio}
    order = [claimed] if claimed in tries else []
    order += [kind for kind in tries if kind not in order]

    row = None
    reason = None
    for kind in order:
        try:
            row = tries[kind]()
            break
        except (images.ImageProblem, video.VideoProblem, audio.AudioProblem) as problem:
            # The claimed kind's own sentence is the one worth showing: a PNG
            # that fails as a picture should not be told it is a bad MP3.
            reason = reason or str(problem)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=reason
            or "That is not a picture (PNG, JPEG, WebP), a video (MP4) or a sound.",
        )

    name = unquote(request.headers.get("x-file-name") or "").strip()
    if name and not row.name:
        # Without the extension: the library says what kind it is already.
        row.name = (name.rsplit(".", 1)[0] if "." in name else name)[:120] or None
    if row.uploaded_by_user_id is None:
        row.uploaded_by_user_id = actor.id
    audit.record(db, actor=actor, action="asset.uploaded", request=request, name=row.name)
    db.commit()
    used = asset_library.usages(db, _org(db, actor))
    return _read(row, used.get(row.sha256, []))


@router.patch("/{digest}", response_model=AssetRead)
def rename_asset(
    digest: str,
    payload: AssetRename,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> AssetRead:
    row = _owned(db, actor, digest)
    row.name = " ".join(payload.name.split())
    db.commit()
    used = asset_library.usages(db, _org(db, actor))
    return _read(row, used.get(row.sha256, []))


@router.delete("/{digest}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    digest: str,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Remove a file nothing uses.

    **Refused while anything uses it**, and the refusal names what: deleting
    a background a channel is showing would leave a television drawing an
    empty rectangle in front of the whole floor.
    """
    org = _org(db, actor)
    row = _owned(db, actor, digest)
    if row.id in asset_library.photo_ids(db, org):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That is somebody's photo. Change it on their page.",
        )
    used = asset_library.usages(db, org).get(row.sha256, [])
    if used:
        where = "; ".join(u.label for u in used[:3])
        more = f" and {len(used) - 3} more" if len(used) > 3 else ""
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Still in use: {where}{more}. Change those first.",
        )
    audit.record(db, actor=actor, action="asset.deleted", request=request, name=row.name)
    db.delete(row)
    db.commit()
