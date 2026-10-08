"""Spending points: cosmetics and the prize wheel.

Under `/points` with the rest of the economy, in its own file because the
points router had become the whole economy in one module.

Everybody can buy and spin — agents most of all, since they are the people
doing the earning. Setting the prices and stocking the wheel is an admin's.
Handing over a real prize is anybody who may see the winner, because that is
usually their manager, standing near their desk.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import audit, points as point_service, unlocks as unlock_service
from app import wheel as wheel_service
from app.db import get_db
from app.models import (
    Organization,
    Unlock,
    Unlockable,
    UserAccount,
    WheelPrize,
    WheelSpin,
)
from app.models.unlock import KINDS as UNLOCK_KINDS
from app.models.wheel import PRIZE_KINDS
from app.scope import EVERYONE, can_see_user, visible_user_ids
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/points", tags=["economy"])


def _org(db: DbSession, actor: UserAccount) -> Organization:
    return db.get(Organization, actor.organization_id)


# -- Cosmetics ---------------------------------------------------------------


class UnlockableRead(BaseModel):
    id: int
    name: str
    kind: str
    value: str
    price: int
    enabled: bool
    #: Whether the person asking owns it, and whether they have it on.
    owned: bool = False
    equipped: bool = False
    #: How many people own it. Shown to an admin because it decides whether
    #: the thing can be deleted, or only retired.
    owners: int = 0


class ShopRead(BaseModel):
    #: What the person asking can spend. Sent alongside the list so a price
    #: can be shown as affordable or not without a second request.
    wallet: int
    items: list[UnlockableRead]


def _shop(db: DbSession, actor: UserAccount) -> ShopRead:
    items = db.scalars(
        select(Unlockable)
        .where(Unlockable.organization_id == actor.organization_id)
        .order_by(Unlockable.kind, Unlockable.price, Unlockable.name)
    ).all()
    mine = {
        row.unlockable_id: row
        for row in db.scalars(select(Unlock).where(Unlock.user_id == actor.id)).all()
    }
    owners = dict(
        db.execute(
            select(Unlock.unlockable_id, func.count())
            .where(Unlock.organization_id == actor.organization_id)
            .group_by(Unlock.unlockable_id)
        ).all()
    )
    return ShopRead(
        wallet=point_service.wallet(db, actor.organization_id, actor.id),
        items=[
            UnlockableRead(
                id=item.id,
                name=item.name,
                kind=item.kind,
                value=item.value,
                price=item.price,
                enabled=item.enabled,
                owned=item.id in mine,
                equipped=bool(mine.get(item.id) and mine[item.id].equipped),
                owners=owners.get(item.id, 0),
            )
            for item in items
            # A retired cosmetic is still listed for the people who own it —
            # they need to be able to take it off — and for an admin. Nobody
            # else can do anything with it, so nobody else sees it.
            if item.enabled or item.id in mine or actor.org_role == "admin"
        ],
    )


@router.get("/unlockables", response_model=ShopRead)
def list_unlockables(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ShopRead:
    return _shop(db, actor)


class UnlockableWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(60)
    kind: str
    value: str = Field(min_length=1, max_length=40)
    price: int = Field(gt=0, le=1_000_000)
    enabled: bool = True


def _check_unlockable(payload: UnlockableWrite) -> None:
    if payload.kind not in UNLOCK_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A cosmetic is either a ring or a title.",
        )
    problem = unlock_service.valid_value(payload.kind, payload.value)
    if problem:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem
        )


def _owned_item(db: DbSession, actor: UserAccount, item_id: int) -> Unlockable:
    item = db.get(Unlockable, item_id)
    if item is None or item.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found."
        )
    return item


@router.post(
    "/unlockables", response_model=UnlockableRead, status_code=status.HTTP_201_CREATED
)
def create_unlockable(
    payload: UnlockableWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> UnlockableRead:
    _check_unlockable(payload)
    item = Unlockable(
        organization_id=actor.organization_id,
        name=payload.name.strip(),
        kind=payload.kind,
        value=payload.value.strip(),
        price=payload.price,
        enabled=payload.enabled,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Something with that name already exists.",
        ) from None
    audit.record(
        db, actor=actor, action="unlockable.created", request=request, name=item.name
    )
    db.commit()
    return UnlockableRead(
        id=item.id, name=item.name, kind=item.kind, value=item.value,
        price=item.price, enabled=item.enabled,
    )


@router.patch("/unlockables/{item_id}", response_model=UnlockableRead)
def update_unlockable(
    item_id: int,
    payload: UnlockableWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> UnlockableRead:
    """Edit a cosmetic.

    **Its kind cannot change once somebody owns it.** A ring somebody bought
    turning into a title would be selling them something different after the
    money changed hands — and it would break the "one worn of each kind" rule
    for everybody wearing it. Price changes are fine: what each owner paid is
    recorded on their own row.
    """
    item = _owned_item(db, actor, item_id)
    _check_unlockable(payload)

    owners = db.scalar(
        select(func.count()).select_from(Unlock).where(Unlock.unlockable_id == item.id)
    ) or 0
    if payload.kind != item.kind and owners:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "People already own this, so it cannot change from a "
                f"{item.kind} to a {payload.kind}. Make a new one instead."
            ),
        )

    item.name = payload.name.strip()
    item.kind = payload.kind
    item.value = payload.value.strip()
    item.price = payload.price
    item.enabled = payload.enabled
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Something with that name already exists.",
        ) from None
    audit.record(
        db, actor=actor, action="unlockable.updated", request=request, name=item.name
    )
    db.commit()
    return UnlockableRead(
        id=item.id, name=item.name, kind=item.kind, value=item.value,
        price=item.price, enabled=item.enabled, owners=owners,
    )


@router.delete("/unlockables/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unlockable(
    item_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Delete a cosmetic nobody owns.

    **Refused once anybody has bought it.** Deleting it then would take it off
    people who paid for it — their points back without saying so. Retire it
    instead: it stops being sold and stays on everybody who has it.
    """
    item = _owned_item(db, actor, item_id)
    owners = db.scalar(
        select(func.count()).select_from(Unlock).where(Unlock.unlockable_id == item.id)
    ) or 0
    if owners:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{owners} {'person has' if owners == 1 else 'people have'} "
                "bought this. Retire it instead — it stops being sold and "
                "stays on the people who paid for it."
            ),
        )
    audit.record(
        db, actor=actor, action="unlockable.deleted", request=request, name=item.name
    )
    db.delete(item)
    db.commit()


@router.post("/unlockables/{item_id}/buy", response_model=ShopRead)
def buy(
    item_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ShopRead:
    """Spend points on a cosmetic. Worn straight away if nothing of its kind is."""
    item = _owned_item(db, actor, item_id)
    try:
        unlock_service.buy(db, _org(db, actor), item, actor.id)
    except unlock_service.AlreadyOwned:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You already have this."
        ) from None
    except point_service.NotEnough as short:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(short)
        ) from None
    except ValueError as refused:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(refused)
        ) from None
    db.commit()
    return _shop(db, actor)


def _mine(db: DbSession, actor: UserAccount, item_id: int) -> Unlock:
    row = db.scalar(
        select(Unlock).where(
            Unlock.unlockable_id == item_id, Unlock.user_id == actor.id
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="You do not own this."
        )
    return row


@router.post("/unlockables/{item_id}/wear", response_model=ShopRead)
def wear(
    item_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ShopRead:
    unlock_service.equip(db, _mine(db, actor, item_id))
    db.commit()
    return _shop(db, actor)


@router.post("/unlockables/{item_id}/take-off", response_model=ShopRead)
def take_off(
    item_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ShopRead:
    unlock_service.unequip(db, _mine(db, actor, item_id))
    db.commit()
    return _shop(db, actor)


# -- The wheel ---------------------------------------------------------------


class SegmentRead(BaseModel):
    id: int
    label: str
    kind: str
    points: int
    #: 0–1, from the weights actually used in the draw. Shown to the person
    #: about to spin, because a wheel whose odds are hidden is a slot machine.
    chance: float
    stock: int | None


class SpinRead(BaseModel):
    id: int
    label: str
    kind: str
    cost: int
    points_won: int
    given_at: datetime | None
    created_at: datetime
    #: Which segment it landed on, so the animation can stop there. Null once
    #: the segment has been deleted.
    prize_id: int | None
    #: Who won it, for the list of prizes waiting to be handed over.
    winner_name: str | None = None


def _spin_read(row: WheelSpin, winner_name: str | None = None) -> SpinRead:
    return SpinRead(
        id=row.id, label=row.label, kind=row.kind, cost=row.cost,
        points_won=row.points_won, given_at=row.given_at,
        created_at=row.created_at, prize_id=row.prize_id, winner_name=winner_name,
    )


class WheelRead(BaseModel):
    enabled: bool
    spin_cost: int
    segments: list[SegmentRead]
    wallet: int
    recent: list[SpinRead]


def _wheel(db: DbSession, actor: UserAccount) -> WheelRead:
    settings = wheel_service.settings_for(db, actor.organization_id)
    recent = db.scalars(
        select(WheelSpin)
        .where(WheelSpin.user_id == actor.id)
        .order_by(WheelSpin.id.desc())
        .limit(10)
    ).all()
    return WheelRead(
        enabled=settings.enabled,
        spin_cost=settings.spin_cost,
        segments=[
            SegmentRead(
                id=c.prize.id, label=c.prize.label, kind=c.prize.kind,
                points=c.prize.points, chance=round(c.chance, 4),
                stock=c.prize.stock,
            )
            for c in wheel_service.chances(db, actor.organization_id)
        ],
        wallet=point_service.wallet(db, actor.organization_id, actor.id),
        recent=[_spin_read(row) for row in recent],
    )


@router.get("/wheel", response_model=WheelRead)
def read_wheel(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> WheelRead:
    result = _wheel(db, actor)
    # `settings_for` may have just created the row; keep it rather than
    # creating it again on every read.
    db.commit()
    return result


class WheelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spin_cost: int = Field(gt=0, le=1_000_000)
    enabled: bool


def _unfair(problem: wheel_service.Unfair) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(problem)
    )


@router.put("/wheel", response_model=WheelRead)
def write_wheel(
    payload: WheelWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> WheelRead:
    """Set the price and switch it on or off.

    Switching on an empty wheel is refused — a wheel with nothing on it is a
    way to lose points to an animation — and so is a price that would make it
    print points. See `app/wheel.py`.
    """
    settings = wheel_service.settings_for(db, actor.organization_id)
    settings.spin_cost = payload.spin_cost
    settings.enabled = payload.enabled
    db.flush()

    if payload.enabled and not wheel_service.chances(db, actor.organization_id):
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Put something on the wheel before switching it on.",
        )
    try:
        wheel_service.check_fair(db, actor.organization_id)
    except wheel_service.Unfair as problem:
        db.rollback()
        raise _unfair(problem) from None

    audit.record(
        db, actor=actor, action="wheel.updated", request=request,
        spin_cost=str(payload.spin_cost), enabled=str(payload.enabled),
    )
    db.commit()
    return _wheel(db, actor)


class PrizeRead(BaseModel):
    id: int
    label: str
    kind: str
    points: int
    weight: int
    stock: int | None
    enabled: bool


class PrizeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=60)
    kind: str
    points: int = Field(default=0, ge=0, le=1_000_000)
    weight: int = Field(default=1, gt=0, le=10_000)
    stock: int | None = Field(default=None, ge=0)
    enabled: bool = True


def _prize_read(row: WheelPrize) -> PrizeRead:
    return PrizeRead(
        id=row.id, label=row.label, kind=row.kind, points=row.points,
        weight=row.weight, stock=row.stock, enabled=row.enabled,
    )


def _apply_prize(row: WheelPrize, payload: PrizeWrite) -> None:
    if payload.kind not in PRIZE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A segment pays points, gives a prize, or misses.",
        )
    if payload.kind == "points" and payload.points <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Say how many points it pays.",
        )
    row.label = payload.label.strip()
    row.kind = payload.kind
    # Zeroed and cleared rather than refused for the other kinds: a form that
    # switched a segment from points to a miss should not have to remember to
    # empty the points box as well.
    row.points = payload.points if payload.kind == "points" else 0
    row.stock = payload.stock if payload.kind == "prize" else None
    row.weight = payload.weight
    row.enabled = payload.enabled


@router.get("/wheel/prizes", response_model=list[PrizeRead])
def list_prizes(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[PrizeRead]:
    """Every segment, including switched-off and sold-out ones."""
    rows = db.scalars(
        select(WheelPrize)
        .where(WheelPrize.organization_id == actor.organization_id)
        .order_by(WheelPrize.id)
    ).all()
    return [_prize_read(row) for row in rows]


def _save_prize(
    db: DbSession, actor: UserAccount, row: WheelPrize, request: Request, action: str
) -> PrizeRead:
    db.flush()
    try:
        wheel_service.check_fair(db, actor.organization_id)
    except wheel_service.Unfair as problem:
        db.rollback()
        raise _unfair(problem) from None
    audit.record(db, actor=actor, action=action, request=request, label=row.label)
    db.commit()
    return _prize_read(row)


@router.post(
    "/wheel/prizes", response_model=PrizeRead, status_code=status.HTTP_201_CREATED
)
def create_prize(
    payload: PrizeWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> PrizeRead:
    row = WheelPrize(organization_id=actor.organization_id)
    _apply_prize(row, payload)
    db.add(row)
    return _save_prize(db, actor, row, request, "wheel.prize_created")


def _prize(db: DbSession, actor: UserAccount, prize_id: int) -> WheelPrize:
    row = db.get(WheelPrize, prize_id)
    if row is None or row.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found."
        )
    return row


@router.patch("/wheel/prizes/{prize_id}", response_model=PrizeRead)
def update_prize(
    prize_id: int,
    payload: PrizeWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> PrizeRead:
    row = _prize(db, actor, prize_id)
    _apply_prize(row, payload)
    return _save_prize(db, actor, row, request, "wheel.prize_updated")


@router.delete("/wheel/prizes/{prize_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prize(
    prize_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Delete a segment.

    Spins that landed on it keep what they won — the label is copied onto each
    spin — so this rewrites nothing. It can still leave the wheel unfair, since
    removing a miss raises every other segment's share, so it is checked like
    any other change.
    """
    row = _prize(db, actor, prize_id)
    label = row.label
    db.delete(row)
    db.flush()
    try:
        wheel_service.check_fair(db, actor.organization_id)
    except wheel_service.Unfair as problem:
        db.rollback()
        raise _unfair(problem) from None
    audit.record(
        db, actor=actor, action="wheel.prize_deleted", request=request, label=label
    )
    db.commit()


@router.post("/wheel/spin", response_model=SpinRead, status_code=status.HTTP_201_CREATED)
def spin(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> SpinRead:
    """Spin. The server draws; the animation lands where this says."""
    try:
        row = wheel_service.spin(db, _org(db, actor), actor.id)
    except wheel_service.NothingToWin as closed:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(closed)
        ) from None
    except point_service.NotEnough as short:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(short)
        ) from None
    db.commit()
    return _spin_read(row)


@router.get("/wheel/waiting", response_model=list[SpinRead])
def waiting(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[SpinRead]:
    """Real prizes won and not yet handed over, for whoever can see the winner.

    Usually their manager, standing near their desk. Scoped the ordinary way,
    so a manager's list is their own people's prizes.
    """
    visible = visible_user_ids(db, actor)
    rows = wheel_service.waiting(
        db, actor.organization_id, None if visible is EVERYONE else list(visible)
    )
    return [_spin_read(row, wheel_service.name_of(db, row.user_id)) for row in rows]


@router.post("/wheel/spins/{spin_id}/given", response_model=SpinRead)
def mark_given(
    spin_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> SpinRead:
    """Record that a real prize has been handed over."""
    row = db.get(WheelSpin, spin_id)
    if (
        row is None
        or row.organization_id != actor.organization_id
        or not can_see_user(db, actor, row.user_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Spin not found."
        )
    if row.kind != "prize":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a real prize is handed over.",
        )
    if row.given_at is None:
        row.given_at = datetime.now(UTC)
        row.given_by_user_id = actor.id
        audit.record(
            db, actor=actor, action="wheel.prize_given", request=request,
            label=row.label, winner=wheel_service.name_of(db, row.user_id),
        )
        db.commit()
    return _spin_read(row, wheel_service.name_of(db, row.user_id))
