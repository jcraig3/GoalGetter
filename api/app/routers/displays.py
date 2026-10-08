"""Wall displays: issuing, listing, revoking — and pairing a television.

Pairing is the interesting half. See `app/pairing.py` for why a code is four
characters, and the endpoints at the foot of this file for the three-step
flow: a screen asks, an admin claims, the screen collects.
"""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app import audit, pairing, public_url
from app.db import get_db
from app.models import Channel, Display, DisplayPairing, UserAccount
from app.sessions import require_role
from app.validation import Name

router = APIRouter(prefix="/displays", tags=["displays"])

DISPLAY_PATH = "/display"

# 32 bytes of randomness, like a session token. Long enough that guessing is
# not a threat, so the value needs no signing or expiry encoded in it — the
# database row is the source of truth and revocation is immediate.
TOKEN_BYTES = 32


class DisplayRead(BaseModel):
    id: int
    name: str
    channel_id: int
    channel_name: str
    last_seen_at: datetime | None
    #: Its browser holds sound back (Phase 24): celebrations play muted there
    #: until sound is allowed for GoalGetter on that TV.
    sound_blocked: bool = False
    revoked: bool
    created_at: datetime
    #: The full URL to open on the screen. Returned every time it is listed,
    #: not just at creation — the whole point of keeping the token readable is
    #: that setting a TV up weeks later does not need a new link.
    url: str


class DisplayCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120)
    #: Which authored playlist it plays. Required now: through Phase 1 a
    #: display derived its content from an office, and NULL meant "everything".
    #: A channel is a thing somebody built, so there is no sensible default.
    channel_id: int


def _to_read(db: DbSession, display: Display) -> DisplayRead:
    channel = db.get(Channel, display.channel_id)
    app_url = public_url.get(db)
    return DisplayRead(
        id=display.id,
        name=display.name,
        channel_id=display.channel_id,
        channel_name=channel.name if channel else "Deleted channel",
        last_seen_at=display.last_seen_at,
        sound_blocked=display.sound_blocked_at is not None,
        revoked=display.revoked_at is not None,
        created_at=display.created_at,
        url=f"{app_url}{DISPLAY_PATH}/{display.token}",
    )


@router.get("", response_model=list[DisplayRead])
def list_displays(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[DisplayRead]:
    rows = db.scalars(
        select(Display)
        .where(Display.organization_id == actor.organization_id)
        .order_by(Display.name)
    ).all()
    return [_to_read(db, display) for display in rows]


@router.post("", response_model=DisplayRead, status_code=status.HTTP_201_CREATED)
def create_display(
    payload: DisplayCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DisplayRead:
    """Issue a URL for a screen.

    Admin only. A display URL is a standing credential that anyone in the room
    can read off the screen, so handing them out is not a delegation worth
    making cheap.
    """
    channel = db.get(Channel, payload.channel_id)
    if channel is None or channel.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found."
        )

    display = Display(
        organization_id=actor.organization_id,
        name=payload.name,
        channel_id=channel.id,
        token=secrets.token_urlsafe(TOKEN_BYTES),
        created_by_user_id=actor.id,
    )
    db.add(display)
    audit.record(
        db, actor=actor, action="display.created", request=request,
        name=payload.name, channel=channel.name,
    )
    db.commit()
    return _to_read(db, display)


class DisplayUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120) | None = None
    #: Point it at a different channel. The screen picks the change up on its
    #: next poll without anybody touching it.
    channel_id: int | None = None


@router.patch("/{display_id}", response_model=DisplayRead)
def update_display(
    display_id: int,
    payload: DisplayUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DisplayRead:
    """Rename a screen, or point it somewhere else.

    **Reassigning beats revoking and re-pairing.** A television showing the
    wrong channel is a five-minute job with a ladder under the old way: revoke,
    make a new display, walk to the screen, type a new URL. The token is not
    the thing that was wrong, so it does not need replacing — and the screen
    picks the new channel up on its next poll, with nobody in the room.
    """
    display = _owned(db, actor, display_id)
    fields = payload.model_fields_set

    if "channel_id" in fields and payload.channel_id is not None:
        channel = db.get(Channel, payload.channel_id)
        if channel is None or channel.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found."
            )
        if channel.id != display.channel_id:
            audit.record(
                db,
                actor=actor,
                action="display.reassigned",
                request=request,
                name=display.name,
                channel=channel.name,
            )
        display.channel_id = channel.id

    if "name" in fields and payload.name is not None:
        display.name = payload.name

    db.commit()
    return _to_read(db, display)


@router.post("/{display_id}/reload", response_model=DisplayRead)
def reload_display(
    display_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DisplayRead:
    """Ask a screen to reload itself the next time it polls.

    **For the browser that has been open since a deploy three weeks ago**, and
    for the one that has wedged. Both look identical from a desk and both are
    on a wall somebody would otherwise need a ladder to reach.

    Not immediate, and says so: the screen finds out when it next asks, which
    is within its refresh interval.
    """
    display = _owned(db, actor, display_id)
    display.reload_at = datetime.now(UTC)
    audit.record(
        db,
        actor=actor,
        action="display.reload_requested",
        request=request,
        name=display.name,
    )
    db.commit()
    return _to_read(db, display)


@router.post("/{display_id}/revoke", response_model=DisplayRead)
def revoke_display(
    display_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DisplayRead:
    """Stop a URL working, immediately.

    The row survives as the record that it was issued and by whom — the
    question after a screen goes missing is "what did it have access to", and
    a deleted row cannot answer it.
    """
    display = _owned(db, actor, display_id)
    display.revoked_at = datetime.now(UTC)
    audit.record(
        db, actor=actor, action="display.revoked", request=request, name=display.name
    )
    db.commit()
    return _to_read(db, display)


@router.delete("/{display_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_display(
    display_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """For one created by mistake. Revoke is the normal path."""
    display = _owned(db, actor, display_id)
    audit.record(
        db, actor=actor, action="display.deleted", request=request, name=display.name
    )
    db.delete(display)
    db.commit()


def _owned(db: DbSession, actor: UserAccount, display_id: int) -> Display:
    display = db.get(Display, display_id)
    if display is None or display.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Display not found."
        )
    return display


# ── Pairing a television ─────────────────────────────────────────────────────


class PairingStart(BaseModel):
    """What the screen is told when it asks."""

    code: str
    #: The screen keeps this and polls with it. Never shown to anybody.
    secret: str
    #: How long the code is good for, so the screen can count down rather than
    #: guess — and ask for a fresh one when it lapses instead of showing a code
    #: that no longer works.
    expires_in_seconds: int


class PairingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=16)
    name: Name(120)
    channel_id: int


class PairingAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The link a disconnected screen used to have (6.2), so its code can be
    #: tied to the display it was. Optional: a new screen has none.
    previous_token: str | None = Field(default=None, max_length=200)


@router.post(
    "/pair/start",
    response_model=PairingStart,
    status_code=status.HTTP_201_CREATED,
)
def start_pairing(
    payload: PairingAsk | None = None, db: DbSession = Depends(get_db)
) -> PairingStart:
    """A screen asks for a code. **No account, because a television has none.**

    This is the one open endpoint in the product, and what keeps it safe is
    that it grants nothing: the row it creates points at no organization and no
    channel, and the only way it becomes a display is an admin signing in and
    claiming it. Until then it is four characters and a secret that unlock an
    empty seat.
    """
    now = datetime.now(UTC)
    cutoff = pairing.expired_before(now)

    # Swept here rather than by a job: this is the one moment somebody is
    # already writing to the table, and the sweep is what keeps the cap below
    # from being reached by abandoned screens from yesterday.
    db.execute(delete(DisplayPairing).where(DisplayPairing.created_at < cutoff))

    waiting = db.scalar(
        select(func.count())
        .select_from(DisplayPairing)
        .where(
            DisplayPairing.display_id.is_(None),
            DisplayPairing.created_at >= cutoff,
        )
    )
    if (waiting or 0) >= pairing.MAX_WAITING:
        # **A bound, not a rate limit.** The failure worth preventing is
        # somebody filling the code space so the four characters an admin reads
        # belong to a screen they do not own — and a cap makes that impossible
        # rather than merely slow.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many screens are waiting to be paired. Try again shortly.",
        )

    # **Only a revoked display is linked.** The old token says which screen
    # this was, so the inbox can name it; it grants nothing — the link stays
    # dead, and only an admin can reconnect it. A working token never asks,
    # and a deleted display's token finds nothing, which is just a new screen.
    previous = None
    if payload and payload.previous_token:
        previous = db.scalar(
            select(Display).where(
                Display.token == payload.previous_token,
                Display.revoked_at.is_not(None),
            )
        )

    row = DisplayPairing(
        code=_free_code(db, cutoff),
        secret=pairing.new_secret(),
        created_at=now,
        previous_display_id=previous.id if previous else None,
    )
    db.add(row)
    db.commit()
    return PairingStart(
        code=row.code,
        secret=row.secret,
        expires_in_seconds=int(pairing.LIFETIME.total_seconds()),
    )


@router.get("/pair/{secret}")
def poll_pairing(secret: str, db: DbSession = Depends(get_db)) -> dict[str, str]:
    """The screen asks whether anybody has claimed it yet.

    **By secret, not by code.** Four characters are guessable by design — they
    have to be typeable with a remote — so they never authenticate anything.
    Somebody guessing a code can claim a pairing; they cannot read the token it
    produces.

    204 while waiting, so the screen can poll without parsing anything.
    """
    row = db.scalar(select(DisplayPairing).where(DisplayPairing.secret == secret))
    if row is None or row.created_at < pairing.expired_before(datetime.now(UTC)):
        # Gone or never existed. The screen asks for a new code rather than
        # waiting for one that will never come.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That code has expired."
        )

    if row.display_id is None:
        raise HTTPException(status_code=status.HTTP_204_NO_CONTENT)

    display = db.get(Display, row.display_id)
    if display is None or display.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="That screen was removed."
        )

    return {"url": f"{DISPLAY_PATH}/{display.token}"}


@router.post("/pair", response_model=DisplayRead, status_code=status.HTTP_201_CREATED)
def claim_pairing(
    payload: PairingClaim,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DisplayRead:
    """An admin types the four characters and chooses what the screen plays.

    The display this creates is an ordinary one — same token, same revocation,
    same everything. Pairing is a way of *delivering* the URL to a television
    that cannot be typed into, not a second kind of display.
    """
    channel = db.get(Channel, payload.channel_id)
    if channel is None or channel.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found."
        )

    row = db.scalar(
        select(DisplayPairing).where(
            DisplayPairing.code == pairing.normalise(payload.code),
            DisplayPairing.display_id.is_(None),
            DisplayPairing.created_at >= pairing.expired_before(datetime.now(UTC)),
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No screen is waiting with that code. Codes last ten minutes — "
                "check the screen for a fresh one."
            ),
        )

    display = Display(
        organization_id=actor.organization_id,
        name=payload.name,
        channel_id=channel.id,
        token=secrets.token_urlsafe(TOKEN_BYTES),
        created_by_user_id=actor.id,
    )
    db.add(display)
    db.flush()
    row.display_id = display.id

    audit.record(
        db,
        actor=actor,
        action="display.paired",
        request=request,
        name=payload.name,
        channel=channel.name,
    )
    db.commit()
    return _to_read(db, display)


@router.post(
    "/{display_id}/reconnect",
    response_model=DisplayRead,
    status_code=status.HTTP_201_CREATED,
)
def reconnect_display(
    display_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DisplayRead:
    """Put a disconnected screen back, from the inbox, in one press (6.2).

    The screen is showing a pairing code it asked for with its old link, so
    the server already knows which one it is: this claims that code for a new
    display with the old one's name and channel — what an admin would have
    typed under Connect a TV. The revoked row is then removed, since the new
    one replaces it; the activity log keeps the record.
    """
    old = _owned(db, actor, display_id)
    if old.revoked_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That TV is still connected.",
        )
    waiting = db.scalar(
        select(DisplayPairing)
        .where(
            DisplayPairing.previous_display_id == old.id,
            DisplayPairing.display_id.is_(None),
            DisplayPairing.created_at >= pairing.expired_before(datetime.now(UTC)),
        )
        .order_by(DisplayPairing.created_at.desc())
        .limit(1)
    )
    if waiting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "That TV is not showing a code right now — it may be switched off. "
                "Once it is on, it shows one within a few seconds."
            ),
        )
    channel = db.get(Channel, old.channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Its channel was deleted. Connect it with its code and choose another.",
        )

    display = Display(
        organization_id=actor.organization_id,
        name=old.name,
        channel_id=channel.id,
        token=secrets.token_urlsafe(TOKEN_BYTES),
        created_by_user_id=actor.id,
    )
    db.add(display)
    db.flush()
    waiting.display_id = display.id
    audit.record(
        db,
        actor=actor,
        action="display.reconnected",
        request=request,
        name=old.name,
        channel=channel.name,
    )
    db.delete(old)
    db.commit()
    return _to_read(db, display)


def _free_code(db: DbSession, cutoff: datetime) -> str:
    """A code no screen is currently showing.

    Retried rather than trusted to chance: the unique index would refuse a
    collision anyway, and a 500 on the first television of the morning is a
    worse answer than asking the random number generator again.
    """
    taken = set(
        db.scalars(
            select(DisplayPairing.code).where(
                DisplayPairing.display_id.is_(None),
                DisplayPairing.created_at >= cutoff,
            )
        ).all()
    )
    for _ in range(20):
        code = pairing.new_code()
        if code not in taken:
            return code
    # Twenty collisions against fewer than fifty waiting codes is not chance.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not allocate a pairing code. Try again.",
    )
