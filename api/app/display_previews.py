"""Preview on a TV: something unsaved, on one screen, for a moment (5j).

An admin building a slide or a celebration rule can see it in the editor, but
a wall is a different thing to look at — across a room, at that television's
size, with its sound. This sends what they are building to **one** screen
they choose, where it takes over for a slide's thirty seconds or a
celebration's length, and then the screen goes back to its rotation.

It rides the celebrations poll rather than the channel feed: that is asked
every three seconds, so a preview arrives while the person who sent it is
still looking at the screen, where the feed is asked once a minute.

**What makes it safe to offer.** It reaches one screen, not a channel; it
ends on its own; it is marked "Preview" on the screen; and it is built by the
same code a real slide or win is, from a form that has passed every check
saving makes — so it can show nothing a saved one could not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.models import Display, DisplayPreview, UserAccount

#: How long a slide preview holds the screen.
SLIDE_SECONDS = 30

#: How long after it is sent a preview begins. Longer than the screen's
#: three-second poll, so it is heard of before it starts and plays from the top.
LEAD_SECONDS = 4

#: Rows older than this are swept the next time anybody sends one. A preview
#: lasts at most a slide's thirty seconds or a fifteen-second clip.
KEEP_SECONDS = 600


def target(db: DbSession, actor: UserAccount, display_id: int) -> Display:
    """The screen to send to: this organization's, and not revoked."""
    display = db.get(Display, display_id)
    if (
        display is None
        or display.organization_id != actor.organization_id
        or display.revoked_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="TV not found."
        )
    return display


def send(
    db: DbSession,
    actor: UserAccount,
    display: Display,
    request: Request | None,
    *,
    slide: dict | None = None,
    celebration: dict | None = None,
    hold_seconds: int,
) -> dict:
    """Queue it for the screen, and say honestly what was done.

    **"Sent", not "shown".** A television that is switched off misses it, and
    the screen's own last-seen time is the best this can say about whether it
    will be.
    """
    now = datetime.now(UTC)
    db.execute(
        delete(DisplayPreview).where(
            DisplayPreview.organization_id == actor.organization_id,
            DisplayPreview.created_at < now - timedelta(seconds=KEEP_SECONDS),
        )
    )
    db.add(
        DisplayPreview(
            organization_id=actor.organization_id,
            display_id=display.id,
            requested_by_user_id=actor.id,
            created_at=now,
            starts_at=now + timedelta(seconds=LEAD_SECONDS),
            hold_seconds=hold_seconds,
            slide=slide,
            celebration=celebration,
        )
    )
    audit.record(
        db,
        actor=actor,
        action="display.previewed",
        request=request,
        name=display.name,
    )
    db.commit()
    return {
        "status": "sent",
        "display_name": display.name,
        "starts_in_seconds": LEAD_SECONDS,
        "hold_seconds": hold_seconds,
        "last_seen_at": display.last_seen_at.isoformat() if display.last_seen_at else None,
    }


def pending(db: DbSession, display: Display, now: datetime) -> list[dict]:
    """What this screen has been sent and has not finished showing, shaped
    as the celebrations timetable carries an announcement."""
    rows = db.scalars(
        select(DisplayPreview)
        .where(
            DisplayPreview.display_id == display.id,
            # Generous on the lower bound; the end is checked below, per row.
            DisplayPreview.starts_at >= now - timedelta(seconds=KEEP_SECONDS),
        )
        .order_by(DisplayPreview.starts_at, DisplayPreview.id)
    ).all()

    out: list[dict] = []
    for row in rows:
        starts = int(row.starts_at.timestamp() * 1000)
        ends = starts + row.hold_seconds * 1000
        if ends <= int(now.timestamp() * 1000):
            continue
        shape = dict(row.celebration or {})
        if row.slide is not None:
            shape = {
                "title": row.slide.get("title") or "Preview",
                "hold_seconds": row.hold_seconds,
                "slide": row.slide,
            }
        out.append(
            {
                **shape,
                "id": f"preview:{row.id}",
                "created_at": row.created_at.isoformat(),
                "starts_at": starts,
                "ends_at": ends,
                "preview": True,
            }
        )
    return out
