"""Announcements for the TVs: designed, saved, sent and sent again (Phase 25).

A neutral announcement — about nobody in particular — that takes over the
screens for as long as it says: "Lunch is here", "All-hands at 3". Its words,
its own background (a YouTube video filling the screen included), something to
show beside the words, and a sound effect from the library.

**At `/api/tv-announcements`**, because `/api/announcements` is the Microsoft
Teams posts (`app/announcements.py`). Admins and managers, the people who send
shout-outs; `announcements.send` for a custom role.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit, display_previews
from app import channels as channel_service
from app import media as media_service
from app.appearance import Background
from app.db import get_db
from app.models import Channel, TvAnnouncement, TvAnnouncementSend, UserAccount
from app.sessions import require_role

router = APIRouter(prefix="/tv-announcements", tags=["tv-announcements"])

SENDERS = ("admin", "manager")
LIST_SIZE = 100


class AnnouncementWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    body: str | None = Field(default=None, max_length=500)
    #: How long it holds the screens.
    hold_seconds: int = Field(default=15, ge=5, le=120)
    background: Background | None = None
    #: A YouTube link, a link to a picture, or a library file (`video:`,
    #: `image:`), shown beside the words.
    media_url: str | None = Field(default=None, max_length=500)
    media_start_seconds: int | None = Field(default=None, ge=0, le=86_400)
    #: A sound effect from the library: `asset:<sha256>`.
    sound_url: str | None = Field(default=None, max_length=100)


class AnnouncementRead(BaseModel):
    id: int
    title: str
    body: str | None
    hold_seconds: int
    background: dict | None
    media_url: str | None
    media_kind: str | None
    media_start_seconds: int | None
    sound_url: str | None
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime
    #: How often, and when last, it went out.
    times_sent: int
    last_sent_at: datetime | None


class SendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: The channels to take over; empty or missing: every wall.
    channel_ids: list[int] | None = None


class SendResult(BaseModel):
    channels: int
    #: Every wall in the organization.
    everywhere: bool


class ChannelChoice(BaseModel):
    id: int
    name: str


def _refuse(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _checked_media(db: DbSession, org_id: int, url: str | None) -> str | None:
    """A YouTube link, a picture link, or a library video or picture."""
    url = (url or "").strip()
    if not url:
        return None
    if media_service.asset_digest(url) is not None:
        try:
            return media_service.stored_ref(db, org_id, url, (media_service.KIND_VIDEO, media_service.KIND_IMAGE))
        except media_service.MediaError as problem:
            raise _refuse(str(problem))
    if urlparse(url).scheme not in ("http", "https"):
        raise _refuse("Use a YouTube link, a link to a picture, or a file from the library.")
    if media_service.kind_of(url) not in (media_service.KIND_YOUTUBE, media_service.KIND_IMAGE):
        raise _refuse("Use a YouTube link, or a direct link to a picture (ending in .gif, .png, .jpg or .webp).")
    return url


def _checked_sound(db: DbSession, org_id: int, url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    try:
        return media_service.stored_ref(db, org_id, url, (media_service.KIND_AUDIO,))
    except media_service.MediaError as problem:
        raise _refuse(str(problem))


def _checked_background(db: DbSession, org_id: int, background: Background | None) -> dict | None:
    if background is None or background.kind in (None, "none", "inherit"):
        return None
    shape = background.model_dump(exclude_none=True)
    if background.kind in ("image", "video"):
        if not background.asset:
            raise _refuse("Choose the picture or video for the background.")
        scheme = media_service.IMAGE_SCHEME if background.kind == "image" else media_service.VIDEO_SCHEME
        try:
            media_service.stored_ref(db, org_id, scheme + background.asset, (background.kind,))
        except media_service.MediaError as problem:
            raise _refuse(str(problem))
    if background.kind == "youtube" and not background.asset:
        raise _refuse("Give the YouTube video for the background.")
    return shape


def _fields(db: DbSession, org_id: int, payload: AnnouncementWrite) -> dict:
    return {
        "title": payload.title.strip(),
        "body": (payload.body or "").strip() or None,
        "hold_seconds": payload.hold_seconds,
        "background": _checked_background(db, org_id, payload.background),
        "media_url": _checked_media(db, org_id, payload.media_url),
        "media_start_seconds": payload.media_start_seconds,
        "sound_url": _checked_sound(db, org_id, payload.sound_url),
    }


def _read(db: DbSession, item: TvAnnouncement) -> AnnouncementRead:
    sends = db.execute(
        select(func.count(TvAnnouncementSend.id), func.max(TvAnnouncementSend.created_at)).where(
            TvAnnouncementSend.announcement_id == item.id
        )
    ).one()
    author = db.get(UserAccount, item.created_by_user_id) if item.created_by_user_id else None
    return AnnouncementRead(
        id=item.id,
        title=item.title,
        body=item.body,
        hold_seconds=item.hold_seconds,
        background=item.background,
        media_url=item.media_url,
        media_kind=media_service.kind_of(item.media_url) if item.media_url else None,
        media_start_seconds=item.media_start_seconds,
        sound_url=item.sound_url,
        created_by_name=author.full_name if author else None,
        created_at=item.created_at,
        updated_at=item.updated_at,
        times_sent=sends[0] or 0,
        last_sent_at=sends[1],
    )


def _owned(db: DbSession, actor: UserAccount, announcement_id: int) -> TvAnnouncement:
    item = db.get(TvAnnouncement, announcement_id)
    if item is None or item.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such announcement.")
    return item


@router.get("", response_model=list[AnnouncementRead])
def list_announcements(
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> list[AnnouncementRead]:
    """Saved announcements, the most recently changed first."""
    rows = db.scalars(
        select(TvAnnouncement)
        .where(TvAnnouncement.organization_id == actor.organization_id)
        .order_by(TvAnnouncement.updated_at.desc(), TvAnnouncement.id.desc())
        .limit(LIST_SIZE)
    ).all()
    return [_read(db, row) for row in rows]


@router.get("/channels", response_model=list[ChannelChoice])
def channel_choices(
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> list[ChannelChoice]:
    """Where an announcement can go — names only, for the picker."""
    rows = db.scalars(
        select(Channel).where(Channel.organization_id == actor.organization_id).order_by(Channel.name)
    ).all()
    return [ChannelChoice(id=row.id, name=row.name) for row in rows]


@router.post("", response_model=AnnouncementRead, status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementWrite,
    request: Request,
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> AnnouncementRead:
    item = TvAnnouncement(
        organization_id=actor.organization_id,
        created_by_user_id=actor.id,
        **_fields(db, actor.organization_id, payload),
    )
    db.add(item)
    db.flush()
    audit.record(db, actor=actor, action="announcement.created", request=request, name=item.title)
    db.commit()
    return _read(db, item)


@router.patch("/{announcement_id}", response_model=AnnouncementRead)
def update_announcement(
    announcement_id: int,
    payload: AnnouncementWrite,
    request: Request,
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> AnnouncementRead:
    item = _owned(db, actor, announcement_id)
    for key, value in _fields(db, actor.organization_id, payload).items():
        setattr(item, key, value)
    item.updated_at = datetime.now(UTC)
    audit.record(db, actor=actor, action="announcement.updated", request=request, name=item.title)
    db.commit()
    return _read(db, item)


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_announcement(
    announcement_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> Response:
    item = _owned(db, actor, announcement_id)
    audit.record(db, actor=actor, action="announcement.deleted", request=request, name=item.title)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{announcement_id}/send", response_model=SendResult)
def send_announcement(
    announcement_id: int,
    payload: SendRequest,
    request: Request,
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> SendResult:
    """Put it on the screens now: every wall, or the channels named. Each
    screen on them takes it over in turn with any wins already queued."""
    item = _owned(db, actor, announcement_id)
    now = datetime.now(UTC)
    wanted = sorted(set(payload.channel_ids or []))
    if wanted:
        found = db.scalars(
            select(Channel.id).where(Channel.organization_id == actor.organization_id, Channel.id.in_(wanted))
        ).all()
        if len(found) != len(wanted):
            raise _refuse("One of those channels doesn't exist any more.")
        targets: list[int | None] = list(found)
    else:
        targets = [None]
    for channel_id in targets:
        db.add(
            TvAnnouncementSend(
                organization_id=actor.organization_id,
                announcement_id=item.id,
                channel_id=channel_id,
                sent_by_user_id=actor.id,
                created_at=now,
            )
        )
    audit.record(
        db, actor=actor, action="announcement.sent", request=request,
        name=item.title, channels=len(wanted) or "all",
    )
    db.commit()
    return SendResult(channels=len(wanted), everywhere=not wanted)


def _shown(db: DbSession, actor: UserAccount, payload: AnnouncementWrite) -> dict:
    """What a wall would take over with, without saving anything."""
    fields = _fields(db, actor.organization_id, payload)
    shown = channel_service.announcement_celebration(
        SimpleNamespace(**fields), "preview", datetime.now(UTC).isoformat()
    )
    return {key: value for key, value in vars(shown).items() if key != "due"}


@router.post("/preview")
def preview_announcement(
    payload: AnnouncementWrite,
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> dict:
    """The takeover this would be, for the page to draw — nothing is saved."""
    return _shown(db, actor, payload)


@router.post("/preview/tv/{display_id}", status_code=status.HTTP_202_ACCEPTED)
def preview_announcement_on_tv(
    display_id: int,
    payload: AnnouncementWrite,
    request: Request,
    actor: UserAccount = Depends(require_role(*SENDERS)),
    db: DbSession = Depends(get_db),
) -> dict:
    """On one television, once, marked as a preview — see `display_previews`."""
    display = display_previews.target(db, actor, display_id)
    shown = _shown(db, actor, payload)
    return display_previews.send(db, actor, display, request, celebration=shown, hold_seconds=shown["hold_seconds"])
