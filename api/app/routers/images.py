"""Serving a stored asset, and uploading the ones that are pictures.

**`GET /{digest}` serves anything in the store** — a photograph, a logo, a wall
background, somebody's walk-up clip — because a content-addressed store has one
way to hand bytes back and the content type comes off the row. The upload
routes below are image-shaped on purpose: each names the normaliser it runs, and
audio has its own because a sound is not checked the way a picture is.


**Content-addressed, so caching can be honest.** The path carries the SHA-256 of
the bytes, which means the answer for a given URL can never change — so it is
marked immutable and a browser stops asking. A new photo is a new hash and a new
URL, and the old one keeps working for anything still pointing at it.

**Behind a session.** These are photographs of staff, among other things. A
wall authenticates with the token in its own URL instead — see
`display_feed.display_asset`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import assets, audit, images, video
from app.db import get_db
from app.models import StoredAsset, UserAccount
from app.sessions import current_user, require_role

router = APIRouter(prefix="/images", tags=["images"])

#: Kept for anything that imported it from here; the value lives with the
#: store now, beside the one function that sends it.
CACHE_CONTROL = assets.CACHE_CONTROL


@router.get("/{digest}")
def read_image(
    digest: str,
    request: Request,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> Response:
    """The bytes, or a 404.

    Scoped to the caller's organization: the hash is not a secret, and two
    tenants holding the same stock photo must not become a way to confirm that.
    """
    row = db.scalar(
        select(StoredAsset).where(
            StoredAsset.organization_id == actor.organization_id,
            StoredAsset.sha256 == digest,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Range-aware, because a background can now be a video — see
    # `assets.respond`.
    return assets.respond(row, request.headers.get("range"))


class Uploaded(BaseModel):
    """Where the bytes ended up.

    The digest is the whole answer: an appearance layer stores it and the wall
    builds a URL from it. Size comes back so an editor can say "that is a very
    wide logo" without decoding the file a second time.
    """

    digest: str
    width: int
    height: int
    #: For a video: how long one loop is.
    duration_ms: int | None = None


#: What may be uploaded here, and how each is normalised.
#:
#: **Named kinds rather than free-form processing options.** A logo keeps its
#: shape and its transparency; a background is fitted to a television and
#: flattened. Those are two decisions, not six parameters, and naming them is
#: what stops a caller asking for a transparent 4K JPEG.
KINDS = {
    "logo": (images.store_logo, images.MAX_UPLOAD_BYTES, images.ImageProblem),
    "background": (
        images.store_background, images.MAX_UPLOAD_BYTES, images.ImageProblem,
    ),
    # A video behind a wall, the ad-free alternative to a YouTube loop. Kept
    # as the file was uploaded — see `app/video.py` for what is checked
    # instead of normalised.
    "background-video": (
        video.store_background, video.MAX_UPLOAD_BYTES, video.VideoProblem,
    ),
}


@router.post("/{kind}", response_model=Uploaded, status_code=status.HTTP_201_CREATED)
async def upload(
    kind: str,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> Uploaded:
    """Store a logo or a background and hand back its hash.

    A manager may upload a background — for an announcement (Phase 25) — but
    the organization's logo stays an admin's.

    **Admin only, and not tied to any one setting.** The same file is wanted by
    the organization's brand, by a channel and by a single screen, so this
    stores it and says where it went rather than writing it into one of them —
    which is what lets the same background be reused without a second copy.

    **The image is the body, not a multipart form**, the same as a photograph:
    a browser sends a `File` as a body just as happily, and nothing here trusts
    the declared content type anyway. The bytes are decoded to find out what
    they are.
    """
    found = KINDS.get(kind)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown image kind. Expected one of: {', '.join(KINDS)}.",
        )
    if kind == "logo" and actor.org_role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin sets the logo.")

    store, limit, problem_type = found

    # Checked before reading: `await request.body()` pulls the whole thing into
    # memory, so a refusal afterwards has already paid for what it is refusing.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"The largest file accepted here is {limit // (1024 * 1024)} MB.",
        )

    raw = await request.body()
    try:
        row = store(db, actor.organization_id, raw)
    except problem_type as problem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
        ) from None

    audit.record(db, actor=actor, action=f"image.{kind}_uploaded", request=request)
    db.commit()
    return Uploaded(
        digest=row.sha256,
        width=row.width or 0,
        height=row.height or 0,
        duration_ms=row.duration_ms,
    )
