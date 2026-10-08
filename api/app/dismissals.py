"""Putting away an Inbox item or a Home banner, until it changes (12.2).

Those items are worked out from the data on every request (`app/inbox.py`,
`dashboard.attention`), which is what lets fixing a thing be how it leaves. It
also meant there was no way to say "I know, not now": a TV in a closed room
sat in the Inbox all weekend, and a feed nobody can fix till Monday kept its
banner on Home.

**A dismissal remembers what the item was about**, not just that it was
dismissed — its fingerprint: the error a source is failing with, the newest
row a quiet source has, when a TV was last seen. It stays away while that is
still true *and* it is still the same day where the organization is. So it
comes back:

- **on the next sync that changes it** — a different error, a new newest row;
- **or the next day**, whichever is first: a dismissal is "not today", never
  "never", because a problem nobody sees is a problem nobody fixes.

An item that is a count — "3 people waiting to be placed" — comes back only
when it grows. Going from three to two is not news.

Per person: one admin putting an item away does not hide it from another.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app import periods
from app.models import Dismissal, Organization, UserAccount

SURFACES = frozenset({"inbox", "home"})


@dataclass(frozen=True)
class Mark:
    """What an item says about itself, for deciding whether a dismissal holds."""

    key: str
    fingerprint: str = ""
    #: Set for an item that is a count; it comes back only above this.
    count: int | None = None


def holds(dismissal: Dismissal | None, mark: Mark, today) -> bool:
    """Whether this dismissal still keeps this item away."""
    if dismissal is None or dismissal.dismissed_on != today:
        return False
    if dismissal.fingerprint != mark.fingerprint:
        return False
    if mark.count is not None and dismissal.count is not None:
        return mark.count <= dismissal.count
    return True


def current(db: DbSession, user: UserAccount, surface: str) -> dict[str, Dismissal]:
    """This person's dismissals on one surface, by item key."""
    return {
        d.key: d
        for d in db.scalars(
            select(Dismissal).where(Dismissal.user_id == user.id, Dismissal.surface == surface)
        )
    }


def split(db: DbSession, org: Organization, user: UserAccount, surface: str, items: list, mark_of):
    """(shown, put away) — the items in their order, by whether a dismissal holds."""
    found = current(db, user, surface)
    today = periods.today(org)
    shown, away = [], []
    for item in items:
        mark = mark_of(item)
        (away if holds(found.get(mark.key), mark, today) else shown).append(item)
    return shown, away


def dismiss(db: DbSession, org: Organization, user: UserAccount, surface: str, mark: Mark) -> None:
    """Put an item away as it is now. Replaces an earlier dismissal of it."""
    today = periods.today(org)
    # Yesterday's and older can never hold again; nothing reads them.
    db.execute(
        delete(Dismissal).where(
            Dismissal.user_id == user.id, Dismissal.dismissed_on < today - timedelta(days=1)
        )
    )
    row = db.scalar(
        select(Dismissal).where(
            Dismissal.user_id == user.id,
            Dismissal.surface == surface,
            Dismissal.key == mark.key,
        )
    )
    if row is None:
        row = Dismissal(user_id=user.id, surface=surface, key=mark.key)
        db.add(row)
    row.fingerprint = mark.fingerprint
    row.count = mark.count
    row.dismissed_on = today


def restore_matching(db: DbSession, user: UserAccount, surface: str, pattern: str) -> None:
    """Bring back every item whose key matches a LIKE pattern: "source_quiet:%"."""
    db.execute(
        delete(Dismissal).where(
            Dismissal.user_id == user.id,
            Dismissal.surface == surface,
            Dismissal.key.like(pattern),
        )
    )


def restore(db: DbSession, user: UserAccount, surface: str, key: str) -> None:
    """Bring an item back now: the Undo, or "Show" on the ones put away."""
    db.execute(
        delete(Dismissal).where(
            Dismissal.user_id == user.id, Dismissal.surface == surface, Dismissal.key == key
        )
    )
