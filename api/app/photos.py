"""Whose face goes next to whose name.

**Two slots, one answer.** The directory has a photograph and a person may have
chosen a different one; the chosen one wins, and clearing it falls back to the
directory rather than to nothing. That is the whole of the rule, and it is here
rather than spread across the four places that render an avatar.

**Initials are not a failure case.** Most deployments will have people the
directory has no photo of, and `Avatar` has drawn initials since long before this
existed. `digest_of` returning `None` means "draw what you drew before", not
"something went wrong".
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app import images
from app.models import StoredAsset, UserAccount

__all__ = ["digest_of", "forget_custom", "set_custom", "set_tenant"]


def digest_of(db: DbSession, user: UserAccount) -> str | None:
    """The image to show for this person, or `None` for initials.

    Chosen over tenant, because somebody choosing a photograph of themselves is
    a more recent and more deliberate statement than whatever HR uploaded when
    they joined.
    """
    image_id = user.custom_photo_image_id or user.tenant_photo_image_id
    if image_id is None:
        return None
    row = db.get(StoredAsset, image_id)
    return row.sha256 if row else None


def set_custom(db: DbSession, user: UserAccount, raw: bytes) -> StoredAsset:
    """Store what somebody uploaded and point their account at it."""
    row = images.store(db, user.organization_id, raw)
    user.custom_photo_image_id = row.id
    db.flush()
    return row


def forget_custom(db: DbSession, user: UserAccount) -> None:
    """Back to the directory's photograph, or to initials.

    **The image row is left alone.** It is content-addressed and may be somebody
    else's photograph too; deleting it here would be deleting a row this account
    does not own. Unreferenced images are cheap and rare, and reaping them is a
    job for a sweep that can see every reference, not for an endpoint that can
    see one.
    """
    user.custom_photo_image_id = None
    db.flush()


def set_tenant(
    db: DbSession, user: UserAccount, raw: bytes, *, etag: str | None
) -> StoredAsset | None:
    """Store a photograph the directory supplied.

    Returns `None` when the bytes are not a usable image, rather than raising:
    one unreadable photo in a tenant of four hundred must not stop the sync. The
    etag is still recorded, so the same bad photo is not fetched again every
    night.
    """
    try:
        row = images.store(db, user.organization_id, raw)
    except images.ImageProblem:
        user.tenant_photo_etag = etag
        db.flush()
        return None

    user.tenant_photo_image_id = row.id
    user.tenant_photo_etag = etag
    db.flush()
    return row
