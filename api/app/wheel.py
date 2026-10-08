"""The prize wheel.

Spend points, spin, win something. Three decisions keep it from being either a
slot machine or a leak in the economy.

**The odds are shown, and they are the real ones.** Each segment carries a
weight, and the chance shown beside it is computed from the weights actually
used in the draw — never typed in separately, so it cannot be wrong. A wheel
whose odds are hidden is a slot machine, and a workplace should not be running
one.

**The server draws, never the browser.** The animation lands wherever the
server already decided. A draw made in the client is a draw anybody with the
developer tools open can make come out their way.

**It cannot pay out more points than it costs.** A wheel whose expected points
return reaches the price of a spin is a points printer: spin forever, and the
wallet only grows. That configuration is refused when it is saved, not
discovered in a month by the one person who did the sums. Real prizes carry no
points value and do not count toward it — a long lunch is not a withdrawal.
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import events, points as point_service
from app.models import Organization, PrizeWheel, UserAccount, WheelPrize, WheelSpin

__all__ = [
    "Chance",
    "NothingToWin",
    "Unfair",
    "chances",
    "check_fair",
    "expected_return",
    "settings_for",
    "spin",
]


class NothingToWin(Exception):
    """A spin with no segment in the draw."""


class Unfair(Exception):
    """A wheel that would print points."""


#: The system's own randomness, not Python's seeded default. Python's
#: `random` is predictable from enough of its output, and a draw that pays out
#: points is exactly the thing somebody would sit and study.
_SYSTEM = secrets.SystemRandom()


def settings_for(db: DbSession, org_id: int) -> PrizeWheel:
    """This organization's wheel, created — switched off — the first time it
    is asked for, so there is always one row to read and write."""
    wheel = db.scalar(select(PrizeWheel).where(PrizeWheel.organization_id == org_id))
    if wheel is None:
        wheel = PrizeWheel(organization_id=org_id, spin_cost=100, enabled=False)
        db.add(wheel)
        db.flush()
    return wheel


def _in_draw(db: DbSession, org_id: int, *, lock: bool = False) -> list[WheelPrize]:
    """Segments that can currently be landed on: enabled, and not sold out."""
    query = select(WheelPrize).where(
        WheelPrize.organization_id == org_id,
        WheelPrize.enabled.is_(True),
        (WheelPrize.stock.is_(None)) | (WheelPrize.stock > 0),
    ).order_by(WheelPrize.id)
    if lock:
        query = query.with_for_update()
    return list(db.scalars(query).all())


@dataclass
class Chance:
    prize: WheelPrize
    #: 0–1, from the weights actually used in the draw.
    chance: float


def chances(db: DbSession, org_id: int) -> list[Chance]:
    """Every segment in the draw, with its true chance of coming up."""
    prizes = _in_draw(db, org_id)
    total = sum(prize.weight for prize in prizes)
    if total == 0:
        return []
    return [Chance(prize=prize, chance=prize.weight / total) for prize in prizes]


def expected_return(prizes: list[WheelPrize]) -> float:
    """The points a spin pays back on average, over the segments given."""
    total = sum(prize.weight for prize in prizes)
    if total == 0:
        return 0.0
    return sum(prize.points * prize.weight for prize in prizes) / total


def check_fair(db: DbSession, org_id: int) -> None:
    """Refuse a wheel that pays out as many points as it costs, or more.

    Called after every change that could move the balance — the price, and any
    segment added, edited or restocked — and before the change is committed,
    so an unfair wheel is never saved rather than saved and then noticed.

    Checked over the segments *in the draw now*. A sold-out gift card leaving
    the draw raises the share of every other segment, and that can tip a wheel
    that was fair yesterday over the line; `spin` checks again for exactly
    that reason.
    """
    wheel = settings_for(db, org_id)
    back = expected_return(_in_draw(db, org_id))
    if back >= wheel.spin_cost:
        raise Unfair(
            f"On average a spin would pay back {back:,.0f} points and it costs "
            f"{wheel.spin_cost:,}. Spinning it forever would make points out of "
            f"nothing — lower the points segments, make them rarer, or raise "
            f"the price."
        )


def spin(
    db: DbSession,
    org: Organization,
    user_id: int,
    *,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> WheelSpin:
    """Take the cost, draw a segment, pay out, and record it.

    **Everything here is one transaction**, in the order that cannot leave a
    half-finished spin: the segments are locked, the cost is taken, the draw is
    made, stock is counted down, winnings are paid, the spin is written. A
    failure anywhere and none of it happened.

    The segments are locked for the length of the spin, which serializes spins
    across the organization. That is the price of a sold-out prize staying
    sold out — two people landing on the last gift card at the same instant is
    otherwise two gift cards — and spins are a person pressing a button, not
    traffic.

    `rng` is injectable so a test can decide the outcome.
    """
    wheel = settings_for(db, org.id)
    if not wheel.enabled:
        raise NothingToWin("The prize wheel is switched off.")

    prizes = _in_draw(db, org.id, lock=True)
    if not prizes:
        raise NothingToWin("There is nothing on the wheel to win right now.")

    # Again, now, over what is actually in the draw — see `check_fair`.
    if expected_return(prizes) >= wheel.spin_cost:
        raise NothingToWin(
            "The wheel is closed while its prizes are rebalanced."
        )

    point_service.spend(
        db,
        org=org,
        user_id=user_id,
        points=wheel.spin_cost,
        what="spin",
        subject_type="prize_wheel",
        subject_id=wheel.id,
        reason="Spun the prize wheel",
        now=now,
    )

    chosen = (rng or _SYSTEM).choices(prizes, weights=[p.weight for p in prizes])[0]

    if chosen.stock is not None:
        chosen.stock -= 1

    row = WheelSpin(
        organization_id=org.id,
        user_id=user_id,
        prize_id=chosen.id,
        label=chosen.label,
        kind=chosen.kind,
        cost=wheel.spin_cost,
        points_won=chosen.points,
        # A miss and a points win are finished the moment the wheel stops.
        # Only a real prize waits for somebody to hand it over.
        given_at=None if chosen.kind == "prize" else (now or datetime.now(UTC)),
    )
    db.add(row)
    db.flush()

    if chosen.kind in ("points", "prize"):
        _announce(db, org, user_id, row)

    if chosen.kind == "points":
        point_service.credit(
            db,
            org=org,
            user_id=user_id,
            points=chosen.points,
            what="win",
            subject_type="wheel_spin",
            subject_id=row.id,
            reason=f"Won {chosen.label} on the prize wheel",
            now=now,
        )

    return row


def _announce(db: DbSession, org: Organization, user_id: int, spin: WheelSpin) -> None:
    """Put a win on the walls — the wheel spinning, and landing on it.

    Addressed to the winner, so it lands in their bell as well as on the wall,
    and placed by where they sit, so it reaches their office's screens rather
    than every screen in the company.

    **No walk-up music.** Spins can come thick and fast, and fifteen seconds of
    somebody's song for every one of them would wear a floor out. The wheel is
    the moment.
    """
    from app import notifications

    person = db.get(UserAccount, user_id)
    if person is None or person.hidden_at is not None:
        return
    won = (
        f"{spin.points_won:,} points" if spin.kind == "points" else spin.label
    )
    notifications.emit(
        db,
        org_id=org.id,
        user_id=user_id,
        event=events.WHEEL_WON,
        subject_type="wheel_spin",
        subject_id=spin.id,
        title=f"Won {won}",
        about_name=person.full_name,
        about_user_id=person.id,
        **notifications.where_of(db, person.id),
    )


def waiting(db: DbSession, org_id: int, user_ids: list[int] | None) -> list[WheelSpin]:
    """Real prizes won and not yet handed over, oldest first.

    Oldest first because this is a queue, and the person who has been waiting
    since Tuesday is the one to go and find.
    """
    query = (
        select(WheelSpin)
        .where(
            WheelSpin.organization_id == org_id,
            WheelSpin.kind == "prize",
            WheelSpin.given_at.is_(None),
        )
        .order_by(WheelSpin.id)
    )
    if user_ids is not None:
        query = query.where(WheelSpin.user_id.in_(user_ids or [-1]))
    return list(db.scalars(query).all())


def name_of(db: DbSession, user_id: int) -> str:
    person = db.get(UserAccount, user_id)
    return person.full_name if person else "Deleted user"
