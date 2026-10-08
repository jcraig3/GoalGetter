"""What a deleted thing takes with it (7.5, Q2-6).

Deleting a contest left "QA2 sprint has started" in two people's bells,
linking to a page that no longer existed; deleting a rule, a correction or a
comment left the win or the comment notification behind. A notification about
something that is gone is a link that 404s and a sentence about nothing.

So every delete that can have notifications about it calls `forget` with the
rows it names — and their feed entries' reactions and comments go too, since
they were about the same thing (as 6.15 already did for a shout-out).

**Points already paid stay** (decided in Phase 7): the ledger is the season's
record, and reversing it would rewrite standings people have already seen.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import feed as feed_service
from app.models import Notification


def forget(db: DbSession, organization_id: int, *conditions) -> int:
    """Delete this organization's notifications matching `conditions`, with
    their feed threads. Returns how many went."""
    rows = db.scalars(
        select(Notification).where(Notification.organization_id == organization_id, *conditions)
    ).all()
    for key in {feed_service.key_of(row) for row in rows}:
        feed_service.forget(db, organization_id, key)
    for row in rows:
        db.delete(row)
    return len(rows)


def about(subject_type: str, subject_id: int):
    """The notifications whose subject is this thing."""
    return (Notification.subject_type == subject_type, Notification.subject_id == subject_id)
