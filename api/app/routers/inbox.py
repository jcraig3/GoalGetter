"""The admin's inbox (6.2). See `app/inbox.py`."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app import dismissals, shared_notices
from app import inbox as service
from app.db import get_db
from app.models import Organization, UserAccount
from app.sessions import require_role

router = APIRouter(prefix="/inbox", tags=["inbox"])


class ItemKey(BaseModel):
    key: str


def _said(item: service.Item) -> dict:
    out = {**asdict(item), "since": item.since.isoformat() if item.since else None}
    # Worked out again on dismissing; nothing for the page to send back.
    out.pop("fingerprint")
    return out


@router.get("")
def read_inbox(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> dict:
    """What needs an admin right now. Admin only: every item is a fix only an
    admin can make, and some name things — sources, errors — that are not
    everybody's business."""
    org = db.get(Organization, actor.organization_id)
    found = service.build(db, org)
    # Put away until it changes, or tomorrow (12.2) — this admin's only.
    shown, away = dismissals.split(db, org, actor, "inbox", found.items, service.Item.mark)
    return {
        "items": [_said(item) for item in shown],
        # Listed, not lost: a dismissal is "not now", and the page offers them.
        "dismissed": [_said(item) for item in away],
        # The badge counts what is still asking for attention.
        "count": len(shown),
    }


@router.post("/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_item(
    payload: ItemKey,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Put an item away as it is now, until it changes or tomorrow (12.2).

    The item is worked out again here rather than taken from the page, so
    what is remembered is what is true, not what a stale tab was showing.
    """
    org = db.get(Organization, actor.organization_id)
    item = next((i for i in service.build(db, org).items if i.key == payload.key), None)
    if item is None:
        # Fixed in the meantime: nothing left to put away.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That is already gone.")
    dismissals.dismiss(db, org, actor, "inbox", item.mark())
    # And Home's banner about the same thing, once nothing is left of it (P4-9).
    shared_notices.put_away_together(db, org, actor, "inbox", item.key)
    db.commit()


@router.post("/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_item(
    payload: ItemKey,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Bring a put-away item back now: the Undo, or "Show" on the list."""
    dismissals.restore(db, actor, "inbox", payload.key)
    shared_notices.bring_back_together(db, actor, "inbox", payload.key)
    db.commit()
