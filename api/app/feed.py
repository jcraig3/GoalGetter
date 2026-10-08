"""Reactions and comments on the recognition feed (6.15).

A shout-out that nobody can answer is a notice. The floor reacting — a
handful of claps, "nobody deserved it more" — is what makes it recognition,
and it is the part people come back to read.

**Everything hangs off the entry's key, not a notification row.** The feed
collapses a team's notifications into one entry by event, subject and period
(see `routers/recognition.list_achievements`), so that is the key a reaction
and a comment are stored against. Whichever member's row the feed shows, the
reactions are the same.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.models import FeedComment, FeedReaction, Notification, UserAccount
from app.models.feed import REACTIONS


def key_of(notification: Notification) -> str:
    """The entry a notification belongs to on the feed."""
    anchor = notification.period_anchor.isoformat() if notification.period_anchor else ""
    return (
        f"{notification.event_key}|{notification.subject_type}|"
        f"{notification.subject_id}|{anchor}"
    )


@dataclass
class Reaction:
    reaction: str
    count: int
    mine: bool
    #: Who, for a tooltip — first names would be ambiguous on a big floor.
    names: list[str] = field(default_factory=list)


@dataclass
class Comment:
    id: int
    body: str
    created_at: datetime
    author_id: int
    author_name: str
    author_photo_digest: str | None


@dataclass
class Thread:
    reactions: list[Reaction] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)


def threads(
    db: DbSession, organization_id: int, keys: list[str], viewer_id: int
) -> dict[str, Thread]:
    """Reactions and comments for every entry on a page of the feed, in two
    queries rather than two per entry."""
    out: dict[str, Thread] = {key: Thread() for key in keys}
    if not keys:
        return out

    names: dict[tuple[str, str], list[str]] = defaultdict(list)
    mine: set[tuple[str, str]] = set()
    for key, reaction, user_id, name in db.execute(
        select(FeedReaction.feed_key, FeedReaction.reaction, FeedReaction.user_id, UserAccount.full_name)
        .join(UserAccount, UserAccount.id == FeedReaction.user_id)
        .where(FeedReaction.organization_id == organization_id, FeedReaction.feed_key.in_(keys))
        .order_by(FeedReaction.created_at, FeedReaction.id)
    ).all():
        names[(key, reaction)].append(name)
        if user_id == viewer_id:
            mine.add((key, reaction))
    for key in keys:
        # In the catalogue's order, so the same reaction is always in the same
        # place on every entry.
        out[key].reactions = [
            Reaction(r, len(names[(key, r)]), (key, r) in mine, names[(key, r)])
            for r in REACTIONS
            if names.get((key, r))
        ]

    from app.routers.recognition import _faces

    rows = db.execute(
        select(FeedComment, UserAccount.full_name)
        .join(UserAccount, UserAccount.id == FeedComment.user_id)
        .where(FeedComment.organization_id == organization_id, FeedComment.feed_key.in_(keys))
        .order_by(FeedComment.created_at, FeedComment.id)
    ).all()
    faces = _faces(db, [comment.user_id for comment, _ in rows])
    for comment, name in rows:
        out[comment.feed_key].comments.append(
            Comment(
                id=comment.id,
                body=comment.body,
                created_at=comment.created_at,
                author_id=comment.user_id,
                author_name=name,
                author_photo_digest=faces.get(comment.user_id),
            )
        )
    return out


def toggle(db: DbSession, organization_id: int, key: str, user_id: int, reaction: str) -> bool:
    """Add the reaction, or take it back if it is already there. Returns
    whether it is on now."""
    existing = db.scalar(
        select(FeedReaction).where(
            FeedReaction.organization_id == organization_id,
            FeedReaction.feed_key == key,
            FeedReaction.user_id == user_id,
            FeedReaction.reaction == reaction,
        )
    )
    if existing is not None:
        db.delete(existing)
        return False
    db.add(
        FeedReaction(organization_id=organization_id, feed_key=key, user_id=user_id, reaction=reaction)
    )
    return True


def forget(db: DbSession, organization_id: int, key: str) -> None:
    """An entry taken off the feed takes its reactions and comments with it."""
    for model in (FeedReaction, FeedComment):
        db.execute(
            delete(model).where(model.organization_id == organization_id, model.feed_key == key)
        )
