"""Cosmetics: something to spend points on that other people can see.

**The test a cosmetic has to pass is whether anybody else notices it.** A
purchase only its owner can see is a receipt. So both kinds here are drawn
where other people look: a ring goes round somebody's face everywhere it
appears — the wall included — and a title sits under their name.

Bought once, kept for good, worn one of each kind at a time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app import points as point_service
from app.models import Organization, Unlock, Unlockable, UserAccount

__all__ = [
    "AlreadyOwned",
    "Worn",
    "buy",
    "equip",
    "unequip",
    "valid_value",
    "worn_by",
]

#: A ring is a colour, and only a colour. Anything else in this column ends up
#: in a `style` attribute on a public television.
RING_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


class AlreadyOwned(Exception):
    """Buying something twice."""


def valid_value(kind: str, value: str) -> str | None:
    """Why this value cannot be used for this kind, or None if it can."""
    if kind == "ring" and not RING_COLOUR.match(value):
        return "A ring needs a colour, written like #f5b301."
    if kind == "title" and not value.strip():
        return "A title needs some words."
    return None


def buy(
    db: DbSession, org: Organization, item: Unlockable, user_id: int
) -> Unlock:
    """Spend points on something and own it.

    **The ownership check happens after the person's row is locked**, and the
    order matters. Checked first, a double-click would pass the check twice,
    spend twice, and then have the second insert refused by the unique index —
    points taken for a second copy nobody gets. Locked first, the second click
    waits, finds the first one's purchase, and stops before spending anything.

    Worn straight away if nothing of its kind is being worn: somebody who has
    just bought a ring wants to see it, not to find a second button.

    Does not commit.
    """
    if not item.enabled:
        raise ValueError("This can no longer be bought.")

    db.execute(
        select(UserAccount.id).where(UserAccount.id == user_id).with_for_update()
    )
    owned = db.scalar(
        select(Unlock.id).where(
            Unlock.unlockable_id == item.id, Unlock.user_id == user_id
        )
    )
    if owned is not None:
        raise AlreadyOwned()

    point_service.spend(
        db,
        org=org,
        user_id=user_id,
        points=item.price,
        what="unlock",
        subject_type="unlockable",
        subject_id=item.id,
        reason=f"Bought {item.name}",
    )

    wearing = db.scalar(
        select(Unlock.id).where(
            Unlock.user_id == user_id,
            Unlock.kind == item.kind,
            Unlock.equipped.is_(True),
        )
    )
    row = Unlock(
        organization_id=org.id,
        unlockable_id=item.id,
        user_id=user_id,
        kind=item.kind,
        equipped=wearing is None,
        paid=item.price,
    )
    db.add(row)
    db.flush()
    return row


def equip(db: DbSession, unlock: Unlock) -> None:
    """Wear this, and take off whatever of its kind was worn before.

    The take-off is flushed before the put-on, or the partial unique index sees
    two worn rings for the instant between them and refuses a perfectly
    ordinary change of mind.
    """
    db.execute(
        update(Unlock)
        .where(
            Unlock.user_id == unlock.user_id,
            Unlock.kind == unlock.kind,
            Unlock.id != unlock.id,
        )
        .values(equipped=False)
    )
    db.flush()
    unlock.equipped = True
    db.flush()


def unequip(db: DbSession, unlock: Unlock) -> None:
    unlock.equipped = False
    db.flush()


@dataclass
class Worn:
    """What one person has on."""

    ring: str | None = None
    title: str | None = None


def worn_by(db: DbSession, user_ids: set[int] | list[int]) -> dict[int, Worn]:
    """What each of these people is wearing, in one query.

    **One query for a whole slide or table**, never one per row. A board of ten
    is ten lookups otherwise, on every poll, on every television — the same
    reason `channels._nicknames` batches.

    A retired cosmetic is still worn. Somebody paid for it; retiring it means it
    can no longer be *bought*, not that it comes off the people who have it.
    """
    ids = set(user_ids)
    if not ids:
        return {}

    rows = db.execute(
        select(Unlock.user_id, Unlockable.kind, Unlockable.value)
        .join(Unlockable, Unlockable.id == Unlock.unlockable_id)
        .where(Unlock.user_id.in_(ids), Unlock.equipped.is_(True))
    ).all()

    out: dict[int, Worn] = {}
    for user_id, kind, value in rows:
        worn = out.setdefault(user_id, Worn())
        if kind == "ring":
            worn.ring = value
        elif kind == "title":
            worn.title = value
    return out
