"""Shout-outs, and the feed everybody can see.

An automated achievement is *detected*; a shout-out is *authored*. They are the
same object with one difference — `created_by_user_id` — so a shout-out reaches
the notification centre, the celebration overlay, and (in 2f) the wall screens
through machinery that already exists rather than a second pipeline.

The one behavioural difference is repeatability. Detected events latch, once
per subject per period, enforced by a partial unique index. Authored ones must
repeat: two good weeks are two shout-outs, and a manager praising the same
person twice is the feature working rather than a duplicate to swallow.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import achievements, assets, audio, audit, display_previews, events, feed as feed_service, media as media_service, merge_tags, notifications, periods, points, video
from app import channels as channel_service
from app import photos as photo_service
from app.db import get_db
from app.models import (
    AchievementRule,
    MetricDefinition,
    MetricFact,
    Notification,
    Organization,
    Team,
    UserAccount,
    WalkupMedia,
)
from app.models.achievement_rule import COMPARATORS, SCOPES
from app.models.feed import MAX_COMMENT, REACTIONS
from app.scope import can_see_user
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(tags=["recognition"])

#: How many entries the achievements feed returns. A wall screen shows a
#: handful and the page scrolls; beyond this it is history nobody reads.
FEED_SIZE = 50


class RecognitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Exactly one of these. A team shout-out reaches every member's bell and
    #: shows once on the feed under the team's name — the same shape as a team
    #: goal being hit, so the wall reads consistently.
    user_id: int | None = None
    team_id: int | None = None
    #: What they did. Required, and the whole value of the feature — "great
    #: work" tells the floor nothing, so there is no default and no template.
    message: str = Field(min_length=1, max_length=200)
    #: An override for this occasion. Omitted, the recipient's own walk-up
    #: media plays — which is the usual case and the one worth optimising for.
    media_url: str | None = None
    media_start_seconds: int | None = None


class AchievementRead(BaseModel):
    id: int
    event_key: str
    #: Who it is about. For a team goal this is the team's name and
    #: `about_user_id` is null.
    about_name: str | None
    about_user_id: int | None
    #: The face to draw beside the name, where it is a person and they have one.
    #: Resolved from the id rather than stored on the notification: a photograph
    #: changing must not leave a year of feed entries showing the old one.
    about_photo_digest: str | None = None
    title: str
    body: str | None
    link_url: str | None
    created_at: datetime
    #: Set when a person wrote it. The feed reads very differently with a name
    #: attached — recognition is from somebody, achievement is just true.
    from_name: str | None
    #: What plays on a wall screen. `media_kind` is derived from the URL rather
    #: than stored, so the two can never disagree.
    media_url: str | None
    media_kind: str | None
    media_start_seconds: int | None
    media_end_seconds: int | None
    #: Reactions and comments, from the whole floor (6.15).
    reactions: list["ReactionRead"] = []
    comments: list["CommentRead"] = []


class ReactionRead(BaseModel):
    reaction: str
    count: int
    #: Whether the viewer is one of them, so the button shows as pressed.
    mine: bool
    names: list[str] = []


class CommentRead(BaseModel):
    id: int
    body: str
    created_at: datetime
    author_id: int
    author_name: str
    author_photo_digest: str | None = None


class ThreadRead(BaseModel):
    reactions: list[ReactionRead]
    comments: list[CommentRead]


class ReactionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reaction: str = Field(pattern="^(" + "|".join(REACTIONS) + ")$")


class CommentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_COMMENT)


@router.post(
    "/recognition", response_model=AchievementRead, status_code=status.HTTP_201_CREATED
)
def send_recognition(
    payload: RecognitionCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> AchievementRead:
    """Recognise somebody.

    Scoped to people the sender can already see. A shout-out is a broadcast —
    it reaches the recipient's bell and every screen in their office — so
    without that it would double as a way to discover who works elsewhere.

    Audited, for the same reason: this puts a sentence in front of a whole
    floor, and "who sent that" needs an answer that does not depend on the row
    still existing.
    """
    if (payload.user_id is None) == (payload.team_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Recognise either a person or a team, not both.",
        )

    if payload.team_id is not None:
        (
            recipients, about_name, about_user_id, subject_type, subject_id, where
        ) = _team_target(db, actor, payload.team_id)
    else:
        (
            recipients, about_name, about_user_id, subject_type, subject_id, where
        ) = _person_target(db, actor, payload.user_id)

    if payload.media_url:
        try:
            # A link, or a file from the library (Phase 27).
            clip = media_service.clip_of(
                db, actor.organization_id, payload.media_url, payload.media_start_seconds
            )
        except media_service.MediaError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        clip_fields = {
            "media_url": clip.url,
            "media_start_seconds": clip.start_seconds,
            "media_end_seconds": clip.end_seconds,
        }
    else:
        # Their own walk-up music. The override exists for the occasion that
        # deserves a specific joke; the default is what makes it a walk-up.
        #
        # A team has none: borrowing one member's would credit the wrong person
        # in front of the room.
        clip_fields = notifications.walkup_for(db, about_user_id)

    for user_id in recipients:
        notifications.emit(
            db,
            org_id=actor.organization_id,
            user_id=user_id,
            **clip_fields,
            event=events.RECOGNITION,
            subject_type=subject_type,
            subject_id=subject_id,
            # No period. Recognition is a moment, not a thing that recurs — and
            # the partial unique index does not apply to authored rows anyway,
            # so there is nothing for an anchor to distinguish.
            period_anchor=None,
            title=payload.message,
            about_name=about_name,
            about_user_id=about_user_id,
            created_by_user_id=actor.id,
            **where,
        )
    _pay_the_recognised(db, actor, payload, about_name)
    audit.record(
        db, actor=actor, action="recognition.sent", request=request,
        recipient=about_name, message=payload.message,
    )
    db.commit()

    created = db.scalars(
        select(Notification)
        .where(Notification.event_key == events.RECOGNITION.key)
        .order_by(Notification.id.desc())
        .limit(1)
    ).one()
    return _to_read(created, actor.full_name)


def _pay_the_recognised(
    db: DbSession, actor: UserAccount, payload, about_name: str
) -> None:
    """Award points to whoever was recognised — once per sender, per day.

    **Recognition is the one award another person can hand out freely**, and
    that makes it the one an economy has to defend. Nothing else here can be
    farmed: a goal pays when a target is met, a rule pays when a fact matches,
    a contest pays when it settles. This pays because a colleague typed a
    sentence, and a manager who likes somebody could type fifty.

    The defence is a latch rather than a limit, so the feature is untouched:
    the second shout-out of the day still happens, still lands on the wall,
    still means what it meant. It just does not pay again.

    Expressed through the ledger's existing unique index by keying the award
    on the *sender* and the day — so two people both recognising somebody on
    the same afternoon is two awards, which is right, and one person doing it
    twice is one.

    `awarded_by_user_id` stays null even though a person authored the
    shout-out: the system decided to pay, and that column is what tells a
    hand-written award apart from a detected one. Setting it would switch the
    latch off, which is exactly what this is for.
    """
    org = db.get(Organization, actor.organization_id)
    if org is None:
        return

    if payload.team_id is not None:
        earners = list(
            db.scalars(
                select(UserAccount.id).where(
                    UserAccount.team_id == payload.team_id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.status == "active",
                )
            ).all()
        )
    else:
        earners = [payload.user_id]

    today = datetime.now(periods.tz(org)).date()
    for user_id in earners:
        # Nobody is paid for recognising themselves. It is allowed to write
        # one — the wall is a strange place to do it, and that is its own
        # deterrent — but it is not income.
        if user_id == actor.id:
            continue
        points.award_for(
            db,
            org=org,
            user_id=user_id,
            event_key=events.RECOGNITION.key,
            subject_type="recognition_from",
            subject_id=actor.id,
            period_anchor=today,
            reason=f"Recognised by {actor.full_name}",
        )


def _person_target(db: DbSession, actor: UserAccount, user_id: int):
    recipient = db.get(UserAccount, user_id)
    if (
        recipient is None
        or recipient.organization_id != actor.organization_id
        or recipient.hidden_at is not None
        or not can_see_user(db, actor, recipient.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Person not found."
        )
    return (
        [recipient.id],
        recipient.full_name,
        recipient.id,
        "user",
        recipient.id,
        notifications.where_of(db, recipient.id),
    )


def _team_target(db: DbSession, actor: UserAccount, team_id: int):
    """Everybody on the team hears about it; the feed shows it once.

    Scoped through the members rather than the team row: a manager may
    recognise a team whose people they can already see, which is the same rule
    that governs everything else they can reach.
    """
    team = db.get(Team, team_id)
    if team is None or team.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
        )

    members = db.scalars(
        select(UserAccount.id).where(
            UserAccount.team_id == team.id,
            UserAccount.hidden_at.is_(None),
            UserAccount.status == "active",
        )
    ).all()
    if not members or not all(can_see_user(db, actor, member) for member in members):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
        )

    # `about_user_id` stays None, so the feed renders a team rather than a
    # person — the same shape a team goal produces.
    return list(members), team.name, None, "team", team.id, notifications.where_of(
        db, None, team.id
    )


@router.delete("/recognition/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recognition(
    notification_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    """Take one back.

    Deleted rather than archived, unlike almost everything else here. A goal or
    a display is kept because somebody will ask what it was; a shout-out with a
    typo in front of the whole floor has no such afterlife, and leaving it
    visible-but-flagged would be worse than removing it. The audit log holds
    the record that it happened.

    A manager may remove their own; an admin may remove any. Neither can touch
    a detected achievement — nobody gets to un-hit a target.
    """
    notification = db.get(Notification, notification_id)
    if (
        notification is None
        or notification.organization_id != actor.organization_id
        or notification.event_key != events.RECOGNITION.key
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recognition not found."
        )
    if actor.org_role != "admin" and notification.created_by_user_id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recognition not found."
        )

    audit.record(
        db, actor=actor, action="recognition.deleted", request=request,
        message=notification.title,
    )
    # Every copy — a team shout-out is one row per member, and deleting only
    # the one it was opened from left the rest in their bells (7.5) — with
    # its reactions and comments (6.15).
    from app import cleanup

    cleanup.forget(
        db,
        notification.organization_id,
        Notification.event_key == notification.event_key,
        Notification.subject_type == notification.subject_type,
        Notification.subject_id == notification.subject_id,
        Notification.period_anchor.is_(None)
        if notification.period_anchor is None
        else Notification.period_anchor == notification.period_anchor,
    )
    db.commit()


@router.get("/achievements", response_model=list[AchievementRead])
def list_achievements(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[AchievementRead]:
    """What the organization is celebrating.

    **Org-wide, not scoped to the viewer.** Every other list in this product
    narrows to what somebody may see; this one deliberately does not, because
    these same rows go on a wall screen that anybody walking past can read.
    "Public" has to mean the same thing at a desk and in a corridor, or the
    page and the TV would disagree about what happened.

    What keeps that safe is the event catalogue rather than a filter here: only
    `PUBLIC_EVENT_KEYS` are eligible, and being behind on a goal is not one of
    them.

    **One row per event, not per recipient.** A team goal being hit sends a
    notification to every member — four rows about one achievement — and a feed
    that listed each would repeat the same news four times under four names.
    DISTINCT ON collapses them.
    """
    rows = db.execute(
        select(Notification, UserAccount.full_name)
        .outerjoin(UserAccount, UserAccount.id == Notification.created_by_user_id)
        .where(
            Notification.organization_id == actor.organization_id,
            # Narrowed in SQL to the two shapes that can possibly be public,
            # then decided by `events.is_public` below — which is the only
            # thing that actually says yes or no.
            or_(
                Notification.event_key.in_(events.PUBLIC_EVENT_KEYS),
                Notification.event_key.startswith(events.ACHIEVEMENT_PREFIX),
            ),
        )
        # The DISTINCT ON key must lead the ORDER BY, so the newest of each
        # group survives rather than an arbitrary one.
        .distinct(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
        )
        .order_by(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
            Notification.created_at.desc(),
        )
    ).all()

    # Sorted here rather than in SQL: DISTINCT ON dictates its own ordering,
    # and re-sorting fifty rows in Python is cheaper than the subquery it would
    # take to have both.
    #
    # **Id breaks the tie, and it is not optional.** `created_at` defaults to
    # `now()`, which in Postgres is transaction start — so every notification
    # from one detection pass carries the *same* timestamp, and a whole pass is
    # emitted in one transaction. Ordering on the timestamp alone would leave
    # those in whatever order the DISTINCT ON happened to produce, which is by
    # subject id. A test caught this by sending two shout-outs and getting them
    # back oldest-first.
    # **One query for every face in the feed.** Resolved here rather than per
    # entry, and from the id rather than stored on the notification: a
    # photograph changing must not leave a year of entries showing the old one.
    faces = _faces(db, [n.about_user_id for n, _ in rows if n.about_user_id])

    public = [(n, author) for n, author in rows if events.is_public(n.event_key)]
    public.sort(key=lambda pair: (pair[0].created_at, pair[0].id), reverse=True)
    public = public[:FEED_SIZE]

    # Reactions and comments for the whole page in two queries (6.15).
    keyed = {n.id: feed_service.key_of(n) for n, _ in public}
    threads = feed_service.threads(db, actor.organization_id, list(set(keyed.values())), actor.id)

    feed = []
    for n, author in public:
        # The single source of truth. The SQL above is a prefilter; `is_public`
        # is the decision, so a rule marked private stays off the wall.
        entry = _to_read(n, author, faces)
        thread = threads[keyed[n.id]]
        entry.reactions = [ReactionRead(**vars(r)) for r in thread.reactions]
        entry.comments = [CommentRead(**vars(c)) for c in thread.comments]
        feed.append(entry)
    return feed


def _entry(db: DbSession, actor: UserAccount, entry_id: int) -> Notification:
    """A feed entry this person may react to: public, and their organization's."""
    notification = db.get(Notification, entry_id)
    if (
        notification is None
        or notification.organization_id != actor.organization_id
        or not events.is_public(notification.event_key)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not on the feed.")
    return notification


def _thread(db: DbSession, actor: UserAccount, key: str) -> ThreadRead:
    thread = feed_service.threads(db, actor.organization_id, [key], actor.id)[key]
    return ThreadRead(
        reactions=[ReactionRead(**vars(r)) for r in thread.reactions],
        comments=[CommentRead(**vars(c)) for c in thread.comments],
    )


@router.post("/feed/{entry_id}/reactions", response_model=ThreadRead)
def react(
    entry_id: int,
    payload: ReactionWrite,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ThreadRead:
    """Add a reaction, or take it back — the same button does both (6.15).

    Anybody signed in: the feed is the whole organization's, and so is
    clapping at it."""
    notification = _entry(db, actor, entry_id)
    key = feed_service.key_of(notification)
    feed_service.toggle(db, actor.organization_id, key, actor.id, payload.reaction)
    db.commit()
    return _thread(db, actor, key)


@router.post("/feed/{entry_id}/comments", response_model=ThreadRead, status_code=status.HTTP_201_CREATED)
def comment(
    entry_id: int,
    payload: CommentWrite,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ThreadRead:
    """Say something under an entry (6.15). The person it is about, and
    whoever wrote the shout-out, hear about it — not the commenter."""
    from app.models import FeedComment

    notification = _entry(db, actor, entry_id)
    key = feed_service.key_of(notification)
    body = " ".join(payload.body.split())
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Say something first.")
    row = FeedComment(organization_id=actor.organization_id, feed_key=key, user_id=actor.id, body=body)
    db.add(row)
    db.flush()

    told = {notification.about_user_id, notification.created_by_user_id} - {None, actor.id}
    for user_id in told:
        notifications.emit(
            db,
            org_id=actor.organization_id,
            user_id=user_id,
            event=events.FEED_COMMENT,
            subject_type="feed_comment",
            subject_id=row.id,
            title=f"{actor.full_name} commented: “{body[:80]}{'…' if len(body) > 80 else ''}”",
            body=notification.title,
            link_url="/announcements",
            # Authored, so it never collides with the once-only index for
            # detected events.
            created_by_user_id=actor.id,
        )
    db.commit()
    return _thread(db, actor, key)


@router.delete("/feed/comments/{comment_id}", response_model=ThreadRead)
def delete_comment(
    comment_id: int,
    request: Request,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ThreadRead:
    """Take a comment back — your own, or any, for an admin."""
    from app.models import FeedComment

    row = db.get(FeedComment, comment_id)
    if (
        row is None
        or row.organization_id != actor.organization_id
        or (row.user_id != actor.id and actor.org_role != "admin")
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found.")
    key = row.feed_key
    if row.user_id != actor.id:
        audit.record(db, actor=actor, action="feed.comment_removed", request=request, body=row.body)
    # The "commented:" notification it sent, too (Q2-6).
    from app import cleanup

    cleanup.forget(db, actor.organization_id, *cleanup.about("feed_comment", row.id))
    db.delete(row)
    db.commit()
    return _thread(db, actor, key)


def _faces(db: DbSession, user_ids: list[int]) -> dict[int, str]:
    """The photo hash for each of these people, where they have one."""
    from app.models import StoredAsset, UserAccount

    if not user_ids:
        return {}
    rows = db.execute(
        select(UserAccount.id, StoredAsset.sha256)
        .join(
            StoredAsset,
            StoredAsset.id
            == func.coalesce(
                UserAccount.custom_photo_image_id, UserAccount.tenant_photo_image_id
            ),
        )
        .where(UserAccount.id.in_(set(user_ids)))
    ).all()
    return {user_id: digest for user_id, digest in rows}


def _to_read(
    notification: Notification,
    author: str | None,
    faces: dict[int, str] | None = None,
) -> AchievementRead:
    return AchievementRead(
        about_photo_digest=(
            (faces or {}).get(notification.about_user_id)
            if notification.about_user_id
            else None
        ),
        media_url=notification.media_url,
        media_kind=(
            media_service.kind_of(notification.media_url)
            if notification.media_url
            else None
        ),
        media_start_seconds=notification.media_start_seconds,
        media_end_seconds=notification.media_end_seconds,
        id=notification.id,
        event_key=notification.event_key,
        about_name=notification.about_name,
        about_user_id=notification.about_user_id,
        title=notification.title,
        body=notification.body,
        link_url=notification.link_url,
        created_at=notification.created_at,
        from_name=author,
    )


# ── Your own walk-up media ───────────────────────────────────────────────────


class WalkupRead(BaseModel):
    url: str | None
    kind: str | None
    start_seconds: int | None
    end_seconds: int | None


class WalkupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Empty or null clears it.
    url: str | None = None
    start_seconds: int | None = None


def _walkup_subject(db: DbSession, actor: UserAccount, user_id: int | None) -> int:
    """Whose walk-up media a request may touch.

    Yours always. Somebody else's only if you manage them — which in practice
    is how most of these get set: plenty of people never open their own
    settings, and a wall with no music is the result.

    An earlier version of this was deliberately self-only, on the grounds that
    a walk-up song somebody else picked defeats the point. That was the wrong
    call for a floor where a manager is the one setting the room up, and the
    scope check is what keeps it from becoming a way to edit strangers.
    """
    if user_id is None or user_id == actor.id:
        # **An organization can close the self half**, and a floor that has
        # heard one person's song nine hundred times is why. Binds agents only:
        # a manager can already set anybody's, so locking them out of their own
        # would be a rule with no purpose.
        if actor.org_role == "agent":
            org = db.get(Organization, actor.organization_id)
            if org is not None and not org.self_walkup:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Your organization has turned off choosing your own "
                        "walk-up media. Ask a manager or an administrator."
                    ),
                )
        return actor.id

    if actor.org_role not in ("admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed."
        )

    subject = db.get(UserAccount, user_id)
    if (
        subject is None
        or subject.organization_id != actor.organization_id
        or subject.hidden_at is not None
        or not can_see_user(db, actor, subject.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Person not found."
        )
    return subject.id


class PreviewWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The link as typed, unsaved. Empty means "preview what is saved" — which
    #: is how an uploaded clip is previewed, since an upload saves at once.
    url: str | None = None
    start_seconds: int | None = None


class PreviewRead(BaseModel):
    """An announcement, shaped exactly as a wall receives one.

    The same fields as `display_feed.CelebrationRead`, minus the timetable — a
    preview starts when somebody presses the button, not when a server says.
    """

    title: str
    body: str | None
    about_name: str
    occasion: str
    media_url: str | None
    media_kind: str | None
    media_id: str | None
    media_digest: str | None
    media_start_seconds: int | None
    media_end_seconds: int | None
    hold_seconds: int
    #: Which kind of win, so the screen draws its trophy (6.6).
    event_key: str = ""
    #: The number it was for and their photograph, as a wall gets them (7.9).
    figure: str | None = None
    photo_digest: str | None = None


@router.post("/me/walkup/preview", response_model=PreviewRead)
def preview_walkup(
    payload: PreviewWrite,
    user_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> PreviewRead:
    """What this person's announcement would look like, for the editor.

    **Nothing is sent anywhere.** This writes no notification and reaches no
    wall; it hands back the announcement a wall *would* be given, and the
    editor plays it in the browser of the person who pressed the button. That
    is the difference from the "send a test to the wall" button that was
    removed in 4f — that one interrupted every screen in the building, and
    would not go away.

    The link is checked here, by the same parser saving uses, so a link the
    preview accepts is one Save will accept — and a bad one is refused with
    the same sentence either way.

    Scoped like editing: the button sits in the editor, and previewing
    somebody's walk-up is as much as editing it lets you see.
    """
    subject_id = _walkup_subject(db, actor, user_id)
    person = db.get(UserAccount, subject_id)

    if payload.url and payload.url.strip():
        try:
            clip = media_service.parse(payload.url, payload.start_seconds, None)
        except media_service.MediaError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        url, start, end = clip.url, clip.start_seconds, clip.end_seconds
    else:
        saved = db.get(WalkupMedia, subject_id)
        url = saved.url if saved else None
        start = saved.start_seconds if saved else None
        end = saved.end_seconds if saved else None

    return PreviewRead(
        # A recognition, because that is the announcement anybody can be given
        # and the one a walk-up song is most often heard on.
        occasion="Recognition",
        event_key="recognition",
        about_name=person.full_name,
        title="Great work today!",
        body=None,
        media_url=url,
        media_kind=media_service.kind_of(url) if url else None,
        media_id=media_service.youtube_id(url) if url else None,
        media_digest=media_service.asset_digest(url) if url else None,
        media_start_seconds=start,
        media_end_seconds=end,
        hold_seconds=channel_service.hold_for_clip(url, start, end),
        photo_digest=photo_service.digest_of(db, person),
    )


@router.get("/me/walkup", response_model=WalkupRead)
def read_walkup(
    user_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> WalkupRead:
    """Your walk-up media, or somebody's you manage.

    `?user_id=` is how an admin or manager reads another person's. Without it
    this is always about the caller, so the common case cannot accidentally
    address somebody else.
    """
    return _walkup_read(db.get(WalkupMedia, _walkup_subject(db, actor, user_id)))


@router.put("/me/walkup", response_model=WalkupRead)
def set_walkup(
    payload: WalkupUpdate,
    user_id: int | None = None,
    request: Request = None,  # type: ignore[assignment]
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> WalkupRead:
    subject_id = _walkup_subject(db, actor, user_id)
    existing = db.get(WalkupMedia, subject_id)

    if not payload.url or not payload.url.strip():
        if existing is not None:
            db.delete(existing)
            _audit_walkup(db, actor, subject_id, request, None)
            db.commit()
        return _walkup_read(None)

    try:
        clip = media_service.parse(payload.url, payload.start_seconds, None)
    except media_service.MediaError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error

    if existing is None:
        existing = WalkupMedia(user_id=subject_id)
        db.add(existing)
    existing.url = clip.url
    existing.start_seconds = clip.start_seconds
    existing.end_seconds = clip.end_seconds
    _audit_walkup(db, actor, subject_id, request, clip.url)
    db.commit()

    return _walkup_read(existing)


class WalkupFromAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    digest: str = Field(min_length=64, max_length=64)


@router.put("/me/walkup/asset", response_model=WalkupRead)
def set_walkup_from_asset(
    payload: WalkupFromAsset,
    user_id: int | None = None,
    request: Request = None,  # type: ignore[assignment]
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> WalkupRead:
    """A sound or a video already in Assets, rather than a fresh upload (8.1).

    Only this organization's own files, and only ones that play. Stored under
    the same schemes an upload uses, so nothing downstream can tell the two
    apart — which is the point.
    """
    from app import asset_library
    from app.models import StoredAsset

    subject_id = _walkup_subject(db, actor, user_id)
    row = db.scalars(
        select(StoredAsset).where(
            StoredAsset.organization_id == actor.organization_id,
            StoredAsset.sha256 == payload.digest,
        )
    ).first()
    kind = asset_library.kind_of(row) if row is not None else None
    if kind not in ("audio", "video"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That is not a sound or a video in Assets.",
        )

    existing = db.get(WalkupMedia, subject_id)
    if existing is None:
        existing = WalkupMedia(user_id=subject_id)
        db.add(existing)
    scheme = media_service.VIDEO_SCHEME if kind == "video" else media_service.ASSET_SCHEME
    existing.url = f"{scheme}{row.sha256}"
    existing.start_seconds = 0
    existing.end_seconds = audio.clip_seconds(row.duration_ms)
    _audit_walkup(db, actor, subject_id, request, existing.url)
    db.commit()
    return _walkup_read(existing)


@router.post("/me/walkup/audio", response_model=WalkupRead)
async def upload_walkup_audio(
    request: Request,
    user_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> WalkupRead:
    """Upload a clip rather than paste a link.

    **A link was never an answer for most people.** Pasting a YouTube address
    means finding the song, copying the URL and knowing which second to start
    at — which is most of the reason a floor ends up with three songs between
    forty people. What everybody has is a file.

    The bytes are the body, exactly as a photograph is: a browser sends a
    `File` that way just as happily, and nothing here trusts the declared type.
    """
    subject_id = _walkup_subject(db, actor, user_id)

    # Checked before reading, not after: `await request.body()` pulls the whole
    # thing into memory, so a refusal afterwards has already paid for it.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > audio.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"The largest clip accepted is "
                f"{audio.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )

    raw = await request.body()
    try:
        data, content_type, duration_ms = audio.normalise(raw)
    except audio.AudioProblem as problem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
        ) from None

    stored = assets.keep(
        db,
        actor.organization_id,
        data,
        content_type=content_type,
        duration_ms=duration_ms,
    )

    existing = db.get(WalkupMedia, subject_id)
    if existing is None:
        existing = WalkupMedia(user_id=subject_id)
        db.add(existing)
    # Named with the scheme rather than stored in a second column — see
    # `media.ASSET_SCHEME`. Everything downstream carries one string for "what
    # to play", and a parallel field would be a pair that can disagree about
    # what a wall is doing.
    existing.url = f"{media_service.ASSET_SCHEME}{stored.sha256}"
    existing.start_seconds = 0
    # **Cut to the cap, not refused.** Somebody uploading a whole track has not
    # made a mistake; playing its first fifteen seconds is what they expect,
    # and stopping the rotation for three minutes is not.
    existing.end_seconds = audio.clip_seconds(duration_ms)

    _audit_walkup(db, actor, subject_id, request, existing.url)
    db.commit()
    return _walkup_read(existing)


@router.post("/me/walkup/video", response_model=WalkupRead)
async def upload_walkup_video(
    request: Request,
    user_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> WalkupRead:
    """Upload a video clip as walk-up media.

    **The announcement people actually want, with no adverts.** The music video
    fills the screen and the words sit over it — which a YouTube embed can
    never do, because its uploader decides whether it shows ads, nothing here
    may skip or hide them, and YouTube's embed rules forbid putting anything in
    front of its player. A file served from this deployment has none of those
    limits.

    Checked exactly as a background video is — see `app/video.py` — so an
    iPhone's HEVC is refused here, with how to fix it, rather than uploaded and
    then silent on the wall. Kept as uploaded, and like an audio clip it plays
    from the start for at most fifteen seconds.
    """
    subject_id = _walkup_subject(db, actor, user_id)

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > video.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"The largest video accepted is "
                f"{video.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )

    raw = await request.body()
    try:
        stored = video.store_background(db, actor.organization_id, raw)
    except video.VideoProblem as problem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
        ) from None

    existing = db.get(WalkupMedia, subject_id)
    if existing is None:
        existing = WalkupMedia(user_id=subject_id)
        db.add(existing)
    existing.url = f"{media_service.VIDEO_SCHEME}{stored.sha256}"
    existing.start_seconds = 0
    # Cut to the cap, like an audio clip: a whole music video is not a mistake,
    # and playing its first fifteen seconds is what somebody uploading one
    # expects.
    existing.end_seconds = audio.clip_seconds(stored.duration_ms or 0)

    _audit_walkup(db, actor, subject_id, request, existing.url)
    db.commit()
    return _walkup_read(existing)


def _audit_walkup(
    db: DbSession,
    actor: UserAccount,
    subject_id: int,
    request: Request | None,
    url: str | None,
) -> None:
    """Recorded only when it is somebody else's.

    Changing your own is not worth an audit row. Changing a colleague's is:
    that clip plays in a room in front of them, and "who set that" needs an
    answer.
    """
    if subject_id == actor.id or request is None:
        return
    subject = db.get(UserAccount, subject_id)
    audit.record(
        db, actor=actor, action="walkup.changed", request=request,
        subject=subject.full_name if subject else str(subject_id), url=url,
    )


def _walkup_read(media: WalkupMedia | None) -> WalkupRead:
    if media is None:
        return WalkupRead(url=None, kind=None, start_seconds=None, end_seconds=None)
    return WalkupRead(
        url=media.url,
        kind=media_service.kind_of(media.url),
        start_seconds=media.start_seconds,
        end_seconds=media.end_seconds,
    )


# ── Achievement rules ────────────────────────────────────────────────────────


class RuleRead(BaseModel):
    id: int
    name: str
    metric_id: int
    metric_name: str
    comparator: str
    threshold: Decimal
    scope: str
    scope_team_id: int | None
    scope_team_name: str | None
    #: What the announcement says, one alternative per line. Empty is the
    #: fixed shape. See `app/merge_tags.py`.
    message: str
    media_url: str | None
    media_kind: str | None
    media_start_seconds: int | None
    allow_personal_media: bool
    enabled: bool
    #: What one of these is worth in the points economy. See `app/points.py`.
    points: int


class RuleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120)
    metric_id: int
    comparator: str = "gte"
    threshold: Decimal = Field(gt=0)
    scope: str = "everyone"
    scope_team_id: int | None = None
    message: str = ""
    media_url: str | None = None
    media_start_seconds: int | None = None
    #: Whether somebody's own walk-up music beats this rule's clip. On by
    #: default, which makes the rule's media a fallback rather than an override.
    allow_personal_media: bool = True
    enabled: bool = True
    #: Points per matching piece of work.
    #:
    #: Capped low, and the cap is the interesting part. A rule fires on *every*
    #: record that matches, so it is the one award whose volume nobody can
    #: predict at the moment they write it — "a deal over $5,000" might be
    #: twice a month or twice an hour. An admin who wants a big number here
    #: almost always wants a competition instead, which pays once and has a
    #: winner.
    points: int = Field(default=10, ge=0, le=100)


class MergeTag(BaseModel):
    name: str
    describes: str
    example: str


@router.get("/achievement-rules/tags", response_model=list[MergeTag])
def list_merge_tags(
    actor: UserAccount = Depends(require_role("admin")),
) -> list[MergeTag]:
    """What may be written into a celebration.

    **Served rather than listed in the client**, the same rule as the eligible
    screens: the picker and the validation are then one catalogue, and the
    quiet version of that mistake is a picker offering a tag the server
    refuses.
    """
    return [
        MergeTag(name=tag.name, describes=tag.describes, example=tag.example)
        for tag in merge_tags.TAGS
    ]


@router.get("/achievement-rules", response_model=list[RuleRead])
def list_rules(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[RuleRead]:
    rows = db.scalars(
        select(AchievementRule)
        .where(AchievementRule.organization_id == actor.organization_id)
        .order_by(AchievementRule.name)
    ).all()
    return [_rule_read(db, rule) for rule in rows]


@router.post(
    "/achievement-rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED
)
def create_rule(
    payload: RuleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RuleRead:
    """Admin only, and deliberately.

    A rule puts a celebration on every screen in the building every time it
    matches. Setting the bar too low does not fail loudly — it just makes the
    wall noise, which is the failure mode this whole feature is trying to
    avoid. That is not a delegation worth making cheap.
    """
    rule = AchievementRule(organization_id=actor.organization_id, created_by_user_id=actor.id)
    _apply(db, actor, rule, payload)
    db.add(rule)
    audit.record(
        db, actor=actor, action="achievement_rule.created", request=request,
        name=payload.name,
    )
    db.commit()
    return _rule_read(db, rule)


#: How far back a suggested bar looks: four whole weeks, so a quiet Monday
#: and a busy Friday both count.
SUGGEST_WEEKS = 4


class RuleSuggestion(BaseModel):
    #: The metric it is for: the one asked about, or the busiest of the unit.
    metric_id: int | None
    #: The bar, rounded to two significant figures. Null when the metric has
    #: no recent data to suggest from.
    threshold: Decimal | None
    #: How many pieces of work in the window clear it.
    would_fire: int
    weeks: int


def _two_figures(value: Decimal) -> Decimal:
    """6,237.50 → 6,200: a bar somebody would write, not one read off a row."""
    if value <= 0:
        return value
    places = value.adjusted() - 1
    step = Decimal(10) ** places
    return (value / step).to_integral_value(rounding="ROUND_FLOOR") * step


@router.get("/achievement-rules/suggest", response_model=RuleSuggestion)
def suggest_threshold(
    metric_id: int | None = None,
    unit: str | None = None,
    per_week: int = 7,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RuleSuggestion:
    """A bar that would have fired about `per_week` times a week (6.4).

    For the starter templates: "Big deal" is not a number anybody knows for
    somebody else's business, but "about one a day, over the last four weeks"
    is a question the data can answer. The answer is a starting point — the
    form's Check then shows exactly what it would do.
    """
    per_week = max(1, min(per_week, 70))
    since = datetime.now(UTC) - timedelta(weeks=SUGGEST_WEEKS)

    # **By unit, the busiest one** — for a template, which knows it wants
    # money but not which of the organization's money metrics. The first one
    # alphabetically may have nothing in it this month; the one with the most
    # recent work is the one a floor is watching.
    if metric_id is None and unit is not None:
        metric_id = db.scalar(
            select(MetricDefinition.id)
            .join(MetricFact, MetricFact.metric_definition_id == MetricDefinition.id)
            .where(
                MetricDefinition.organization_id == actor.organization_id,
                MetricDefinition.unit == unit,
                MetricDefinition.aggregation != "ratio",
                MetricDefinition.archived_at.is_(None),
                MetricFact.occurred_at >= since,
            )
            .group_by(MetricDefinition.id)
            .order_by(func.count(MetricFact.id).desc(), MetricDefinition.id)
            .limit(1)
        )
        if metric_id is None:
            return RuleSuggestion(metric_id=None, threshold=None, would_fire=0, weeks=SUGGEST_WEEKS)

    metric = db.get(MetricDefinition, metric_id) if metric_id is not None else None
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")
    where = [
        MetricFact.organization_id == actor.organization_id,
        MetricFact.metric_definition_id == metric.id,
        MetricFact.occurred_at >= since,
        MetricFact.value > 0,
        UserAccount.hidden_at.is_(None),
    ]
    top = db.scalars(
        select(MetricFact.value)
        .join(UserAccount, UserAccount.id == MetricFact.subject_user_id)
        .where(*where)
        .order_by(MetricFact.value.desc())
        .limit(per_week * SUGGEST_WEEKS)
    ).all()
    if not top:
        return RuleSuggestion(
            metric_id=metric.id, threshold=None, would_fire=0, weeks=SUGGEST_WEEKS
        )
    threshold = _two_figures(top[-1])
    would_fire = db.scalar(
        select(func.count(MetricFact.id))
        .join(UserAccount, UserAccount.id == MetricFact.subject_user_id)
        .where(*where, MetricFact.value >= threshold)
    )
    return RuleSuggestion(
        metric_id=metric.id,
        threshold=threshold,
        would_fire=would_fire or 0,
        weeks=SUGGEST_WEEKS,
    )


#: How far back a rule is tried before it is saved.
#: How far back a rule is tried. **The same four weeks as the suggestion**
#: (Q2-4): a template saying "28 times in the last 4 weeks" followed by a
#: check saying "would not have fired in the last 7 days" was one product
#: contradicting itself in one form.
RULE_CHECK_DAYS = SUGGEST_WEEKS * 7


class RulePreview(BaseModel):
    """What a rule would do, before anybody has to find out on a wall.

    The question nobody can answer by reading the form: whether "a deal over
    $5,000" is twice a month or twice an hour. That is the reason the points
    cap above exists, and a bar set too low is the failure this feature most
    needs to prevent: it does not fail loudly, it makes the wall noise.
    """

    #: Pieces of work in the last `RULE_CHECK_DAYS` days that would have fired it.
    fired: int
    #: How many different people those were.
    people: int
    days: int
    #: Numbers of this metric that arrived in the window at all, whatever
    #: their size. Zero means the check had nothing to try — which is not the
    #: bar's fault (Q2-4).
    recorded: int = 0
    #: The announcement a wall would have shown for the most recent of them, or,
    #: when there were none, for the person checking, at exactly the bar.
    celebration: PreviewRead


@router.post("/achievement-rules/preview", response_model=RulePreview)
def preview_rule(
    payload: RuleWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RulePreview:
    """A rule tried against last week, and the celebration it would play.

    **Built as an unsaved rule** and put through `_apply` and
    `achievements.matches`, exactly as saving and firing do, the same approach
    as the competitions dry run. A second way of deciding what a rule matches
    would be a second place for the answer to be right in isolation and wrong
    on the wall.

    Nothing is written: the rule is never added to the session, and no
    notification, point or wall is touched.
    """
    return _try_rule(db, actor, payload)


@router.post(
    "/achievement-rules/preview/tv/{display_id}",
    status_code=status.HTTP_202_ACCEPTED,
)
def preview_rule_on_tv(
    display_id: int,
    payload: RuleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> dict:
    """The celebration this rule would play, on one television, once.

    Nothing is announced: no notification is written and no point is paid. See
    `app/display_previews.py`.
    """
    display = display_previews.target(db, actor, display_id)
    celebration = _try_rule(db, actor, payload).celebration
    return display_previews.send(
        db, actor, display, request,
        celebration=celebration.model_dump(mode="json"),
        hold_seconds=celebration.hold_seconds,
    )


def _try_rule(db: DbSession, actor: UserAccount, payload: RuleWrite) -> RulePreview:
    rule = AchievementRule(
        organization_id=actor.organization_id, created_by_user_id=actor.id
    )
    _apply(db, actor, rule, payload)
    now = datetime.now(UTC)
    # As if it had been made a week ago, which is the whole of "would have".
    rule.created_at = now - timedelta(days=RULE_CHECK_DAYS)
    metric = db.get(MetricDefinition, rule.metric_definition_id)

    # Hidden people are skipped when a rule fires, so they are not counted.
    where = [
        *achievements.matches(rule),
        MetricFact.occurred_at <= now,
        UserAccount.hidden_at.is_(None),
    ]
    on_person = UserAccount.id == MetricFact.subject_user_id
    fired = db.scalar(
        select(func.count(MetricFact.id)).join(UserAccount, on_person).where(*where)
    )
    people = db.scalar(
        select(func.count(func.distinct(MetricFact.subject_user_id)))
        .join(UserAccount, on_person)
        .where(*where)
    )
    latest = db.scalars(
        select(MetricFact)
        .join(UserAccount, on_person)
        .where(*where)
        .order_by(MetricFact.occurred_at.desc(), MetricFact.id.desc())
        .limit(1)
    ).first()

    person = db.get(UserAccount, latest.subject_user_id) if latest else actor
    figure = notifications.format_value(
        latest.value if latest else rule.threshold,
        metric,
        db.get(Organization, actor.organization_id).currency,
    )
    # Rendered and chosen the way the firing pass does it, so the preview says
    # what the wall would have said.
    body = merge_tags.render(
        rule.message,
        seed=latest.id if latest else 0,
        name=person.full_name,
        first_name=person.full_name.split(" ")[0],
        value=figure,
        metric=metric.name,
    ) or f"{person.full_name} — {figure}"
    media = notifications.rule_media(db, rule, person.id)
    url = media.get("media_url")
    start = media.get("media_start_seconds")
    end = media.get("media_end_seconds")

    recorded = db.scalar(
        select(func.count(MetricFact.id)).where(
            MetricFact.organization_id == actor.organization_id,
            MetricFact.metric_definition_id == metric.id,
            MetricFact.occurred_at >= now - timedelta(days=RULE_CHECK_DAYS),
            MetricFact.occurred_at <= now,
        )
    )

    return RulePreview(
        fired=fired or 0,
        people=people or 0,
        days=RULE_CHECK_DAYS,
        recorded=recorded or 0,
        celebration=PreviewRead(
            occasion=rule.name,
            event_key="achievement:preview",
            title=rule.name,
            about_name=person.full_name,
            body=body,
            media_url=url,
            media_kind=media_service.kind_of(url) if url else None,
            media_id=media_service.youtube_id(url) if url else None,
            media_digest=media_service.asset_digest(url) if url else None,
            media_start_seconds=start,
            media_end_seconds=end,
            hold_seconds=channel_service.hold_for_clip(url, start, end),
            figure=figure,
            photo_digest=photo_service.digest_of(db, person),
        ),
    )


@router.patch("/achievement-rules/{rule_id}", response_model=RuleRead)
def update_rule(
    rule_id: int,
    payload: RuleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RuleRead:
    """Editing a rule does not re-announce anything.

    `last_fact_id` is left alone, so raising a threshold stops future
    celebrations without disturbing the ones already sent, and lowering one
    does not reach back for work that has already happened. Same reasoning as
    never being retroactive in the first place.
    """
    rule = _owned_rule(db, actor, rule_id)
    _apply(db, actor, rule, payload)
    audit.record(
        db, actor=actor, action="achievement_rule.updated", request=request,
        name=payload.name,
    )
    db.commit()
    return _rule_read(db, rule)


@router.delete(
    "/achievement-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_rule(
    rule_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Really deleted, with what it announced (7.5, Q2-6).

    This used to set `archived_at` instead, which was `enabled = False` with no
    way back: the list filtered archived rules out and no endpoint could
    restore one. Two mechanisms for the same outcome and one of them a
    trapdoor. **Pausing is the reversible option**, and keeps everything the
    rule announced; delete means delete — its wins leave the bells and the
    feed with it, as the confirmation says. Points it paid stay: the ledger
    is the season's record.
    """
    from app import cleanup

    rule = _owned_rule(db, actor, rule_id)
    name = rule.name
    cleanup.forget(db, actor.organization_id, Notification.event_key == rule.event_key)
    db.delete(rule)
    audit.record(
        db, actor=actor, action="achievement_rule.deleted", request=request,
        name=name,
    )
    db.commit()


def _owned_rule(db: DbSession, actor: UserAccount, rule_id: int) -> AchievementRule:
    rule = db.get(AchievementRule, rule_id)
    if rule is None or rule.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found."
        )
    return rule


def _apply(
    db: DbSession, actor: UserAccount, rule: AchievementRule, payload: RuleWrite
) -> None:
    if payload.comparator not in COMPARATORS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose 'at least' or 'at most'.",
        )
    if payload.scope not in SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown scope."
        )

    metric = db.get(MetricDefinition, payload.metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found."
        )

    team_id = payload.scope_team_id if payload.scope == "team" else None
    if payload.scope == "team":
        team = db.get(Team, team_id) if team_id else None
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )

    # **Before anything is written.** A typo'd tag caught on a wall is caught
    # by whoever is standing in front of it, hours later, with no way to tell
    # what was meant.
    try:
        merge_tags.check(payload.message)
    except merge_tags.MergeTagError as problem:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(problem)
        ) from None

    clip = None
    if payload.media_url:
        # A link, or a sound, video or picture from the library (6.17, 27).
        try:
            clip = media_service.clip_of(
                db, actor.organization_id, payload.media_url, payload.media_start_seconds
            )
        except media_service.MediaError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error

    if metric.aggregation == "ratio":
        # A rule fires on one fact crossing a line, and a derived metric has no
        # facts — a close rate is two metrics divided, not an event.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{metric.name}' is worked out from two other metrics, so no single "
                "record ever crosses a line. Build the rule on one of its parts."
            ),
        )

    rule.name = payload.name
    rule.metric_definition_id = metric.id
    rule.comparator = payload.comparator
    rule.threshold = payload.threshold
    rule.scope = payload.scope
    rule.scope_team_id = team_id
    rule.message = payload.message.strip()
    rule.enabled = payload.enabled
    rule.points = payload.points
    rule.allow_personal_media = payload.allow_personal_media
    rule.media_url = clip.url if clip else None
    rule.media_start_seconds = clip.start_seconds if clip else None
    rule.media_end_seconds = clip.end_seconds if clip else None


def _rule_read(db: DbSession, rule: AchievementRule) -> RuleRead:
    metric = db.get(MetricDefinition, rule.metric_definition_id)
    team = db.get(Team, rule.scope_team_id) if rule.scope_team_id else None
    return RuleRead(
        id=rule.id,
        name=rule.name,
        metric_id=rule.metric_definition_id,
        metric_name=metric.name if metric else "Deleted metric",
        comparator=rule.comparator,
        threshold=rule.threshold,
        scope=rule.scope,
        scope_team_id=rule.scope_team_id,
        scope_team_name=team.name if team else None,
        message=rule.message or "",
        media_url=rule.media_url,
        media_kind=media_service.kind_of(rule.media_url) if rule.media_url else None,
        media_start_seconds=rule.media_start_seconds,
        allow_personal_media=rule.allow_personal_media,
        enabled=rule.enabled,
        points=rule.points,
    )
