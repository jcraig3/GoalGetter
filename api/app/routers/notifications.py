"""The notification centre: your own events, and marking them seen.

Every endpoint here is scoped to the signed-in user by the WHERE clause, not by
a permission check. There is no capability for "read notifications" because
there is no version of this where you read somebody else's — the recipient is
a column, so scope is the query rather than a rule layered over it.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from app import events
from app.db import get_db
from app.models import Notification, NotificationPreference, UserAccount
from app.sessions import current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])

#: How many the panel asks for. Enough to scroll through a busy fortnight
#: without paging, small enough that the response stays one screenful of JSON.
PAGE_SIZE = 50


class PreferenceRead(BaseModel):
    event_key: str
    #: What the settings page calls it. Sent from here rather than mapped in
    #: the client, so a new event appears in the list the moment the API knows
    #: about it instead of when somebody remembers to add a label.
    label: str
    description: str
    enabled: bool


class PreferenceUpdate(BaseModel):
    #: The events this person wants to hear about. Sent whole rather than as a
    #: diff: a toggle list has no meaningful partial state, and replacing the
    #: set makes the request idempotent and removes any ordering question
    #: between two toggles clicked quickly.
    enabled: list[str]


class NotificationRead(BaseModel):
    id: int
    event_key: str
    title: str
    body: str | None
    link_url: str | None
    created_at: datetime
    read_at: datetime | None
    celebrated_at: datetime | None
    #: Whether this one is worth interrupting for, rather than waiting to be
    #: found. Resolved from the catalogue rather than stored per row, so
    #: changing what celebrates does not need a backfill.
    celebrate: bool
    #: Set when a person wrote it rather than the system detecting it.
    from_name: str | None


class Feed(BaseModel):
    notifications: list[NotificationRead]
    #: Counted separately rather than derived from the page above, which would
    #: undercount the moment somebody has more unread than fits in one request.
    unread: int


def _to_read(notification: Notification, author: str | None) -> NotificationRead:
    # One lookup for fixed and runtime keys alike — see `events.type_for`.
    event = events.type_for(notification.event_key)
    return NotificationRead(
        id=notification.id,
        event_key=notification.event_key,
        title=notification.title,
        body=notification.body,
        link_url=notification.link_url,
        created_at=notification.created_at,
        read_at=notification.read_at,
        celebrated_at=notification.celebrated_at,
        # An unknown key renders as an ordinary row rather than crashing the
        # panel: a notification written by a newer version of the API must not
        # be able to break an older client's bell.
        celebrate=event.celebrate if event else False,
        from_name=author,
    )


def _muted(db: DbSession, user_id: int) -> set[str]:
    """Events this person has switched off. Presence in the table means muted."""
    return set(
        db.scalars(
            select(NotificationPreference.event_key).where(
                NotificationPreference.user_id == user_id
            )
        ).all()
    )


@router.get("/preferences", response_model=list[PreferenceRead])
def list_preferences(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[PreferenceRead]:
    """Every event, with whether this person hears about it.

    Built from the catalogue rather than from the table, so the list is
    complete for somebody who has never opened the settings — they have no rows
    at all, and every event is on.
    """
    muted = _muted(db, actor.id)
    return [
        PreferenceRead(
            event_key=key,
            label=LABELS[key][0],
            description=LABELS[key][1],
            enabled=key not in muted,
        )
        for key in events.CATALOGUE
        if key in LABELS
    ]


@router.put("/preferences", response_model=list[PreferenceRead])
def set_preferences(
    payload: PreferenceUpdate,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[PreferenceRead]:
    """Replace the whole set.

    Unknown keys need no filtering: subtracting from the catalogue ignores
    anything that is not in it. An earlier version guarded with
    `if key in events.CATALOGUE` and a mutation proved the line did nothing —
    it could be deleted without changing a single result. The tolerance is a
    property of the subtraction, not of a check, which is the better place for
    it: a client one deploy behind can send a renamed key and get a 200.
    """
    muted = set(events.CATALOGUE) - set(payload.enabled)

    db.query(NotificationPreference).filter(
        NotificationPreference.user_id == actor.id
    ).delete()
    for key in muted:
        db.add(NotificationPreference(user_id=actor.id, event_key=key))
    db.commit()

    return list_preferences(actor=actor, db=db)


@router.get("", response_model=Feed)
def list_notifications(
    unread_only: bool = Query(default=False),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> Feed:
    query = (
        select(Notification, UserAccount.full_name)
        .outerjoin(UserAccount, UserAccount.id == Notification.created_by_user_id)
        .where(Notification.user_id == actor.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(PAGE_SIZE)
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    # Cleared from the bell (12.1) — still the win everywhere else.
    query = query.where(Notification.dismissed_at.is_(None))

    # Filtered here rather than suppressed at creation. The same rows feed the
    # Achievements page and the wall screens, so muting your own achievements
    # must not remove you from what the organization celebrates — a preference
    # is about your bell, not about whether the thing happened.
    muted = _muted(db, actor.id)
    if muted:
        query = query.where(Notification.event_key.not_in(muted))

    rows = db.execute(query).all()

    return Feed(
        notifications=[_to_read(n, author) for n, author in rows],
        unread=_unread_count(db, actor.id, muted),
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> NotificationRead:
    notification = db.get(Notification, notification_id)
    # 404 rather than 403 for somebody else's, like every other scope refusal
    # here — a 403 would confirm it exists.
    if notification is None or notification.user_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
        )

    # Only the first time. Re-reading something must not move it back to the
    # top of "recently read" or change when it was seen.
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()

    author = (
        db.get(UserAccount, notification.created_by_user_id)
        if notification.created_by_user_id
        else None
    )
    return _to_read(notification, author.full_name if author else None)


@router.post("/{notification_id}/celebrated", status_code=status.HTTP_204_NO_CONTENT)
def mark_celebrated(
    notification_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """Record that the overlay has shown this one.

    Separate from marking it read, and deliberately: a celebration somebody
    walked away from should not clear the badge, and opening the bell should
    not cancel a celebration they never saw.

    Recorded on the server rather than in the browser so that refreshing the
    page, or opening a second tab, does not replay it.
    """
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
        )

    # First time only, like `read_at`. Re-recording would move the timestamp
    # and, worse, would make a repeated call look like a second celebration.
    if notification.celebrated_at is None:
        notification.celebrated_at = datetime.now(UTC)
        db.commit()


class Ids(BaseModel):
    ids: list[int]


@router.post("/{notification_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    notification_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """Clear one from the bell (12.1). Read as well: a badge counting
    something no longer in the list is a badge nothing explains."""
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
        )
    now = datetime.now(UTC)
    notification.dismissed_at = notification.dismissed_at or now
    notification.read_at = notification.read_at or now
    db.commit()


@router.post("/dismiss-all", response_model=Ids)
def dismiss_all(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> Ids:
    """Clear the bell (12.1). Returns what it cleared, for the Undo — not
    "everything dismissed today", which would bring back last hour's too."""
    now = datetime.now(UTC)
    cleared = db.scalars(
        update(Notification)
        .where(Notification.user_id == actor.id, Notification.dismissed_at.is_(None))
        .values(dismissed_at=now, read_at=func.coalesce(Notification.read_at, now))
        .returning(Notification.id)
    ).all()
    db.commit()
    return Ids(ids=list(cleared))


@router.post("/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore(
    payload: Ids,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """The Undo: back in the bell, as read — they had seen them."""
    db.execute(
        update(Notification)
        .where(Notification.user_id == actor.id, Notification.id.in_(payload.ids))
        .values(dismissed_at=None)
    )
    db.commit()


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """One statement, not a loop.

    Somebody returning from leave can have hundreds. Loading them to set a
    field on each would be hundreds of round trips to express one UPDATE.
    """
    db.execute(
        update(Notification)
        .where(Notification.user_id == actor.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()


def _unread_count(db: DbSession, user_id: int, muted: set[str]) -> int:
    """Unread, excluding muted events.

    Counted separately from the page above rather than derived from it, which
    would undercount the moment somebody has more unread than fits in one
    request. Muting has to apply here too, or switching an event off would
    leave a badge that nothing in the panel explains.
    """
    query = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
        )
    )
    if muted:
        query = query.where(Notification.event_key.not_in(muted))
    return int(db.scalar(query) or 0)


#: What each event is called in the settings, and what it means.
#:
#: Here rather than in the client so a new event shows up in the list as soon
#: as the API knows about it, instead of when somebody remembers to add a
#: label. An event missing from this map is simply not offered as a toggle —
#: the right default for anything not yet meant to be user-facing.
LABELS: dict[str, tuple[str, str]] = {
    events.GOAL_ACHIEVED.key: (
        "Goals achieved",
        "When you or your team hit a target.",
    ),
    events.GOAL_ASSIGNED.key: (
        "New goals",
        "When a target is set for you or your team.",
    ),
    events.GOAL_PERIOD_ENDING.key: (
        "Goals running out of time",
        "Once a period is three quarters gone and the target is not met.",
    ),
    events.RECOGNITION.key: (
        "Recognition",
        "When somebody recognises your work.",
    ),
    events.FEED_COMMENT.key: (
        "Comments",
        "When somebody comments on recognition about you, or that you gave.",
    ),
    # Competitions were sent and could not be turned off (QA-38).
    events.COMPETITION_STARTED.key: (
        "Competitions starting",
        "When a contest you are in begins.",
    ),
    events.COMPETITION_FINISHED.key: (
        "Where you finished",
        "When a contest you were in is settled, and your place in it.",
    ),
    events.COMPETITION_WON.key: (
        "Competition winners",
        "When somebody wins a contest you were in.",
    ),
}
