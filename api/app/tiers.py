"""The ladder, and where to put its rungs.

Setting a threshold by hand is guessing, and the two ways of guessing wrong
look nothing alike from inside the form:

    too high   nobody reaches it, so nobody aims at it
    too low    everybody passes it, so holding it says nothing

Neither is visible while you are typing round numbers. Both are obvious the
moment you look at what people have actually scored — so this module reads the
season's real distribution and proposes rungs from it.

**Percentiles, not round numbers.** A suggestion of 12,480 looks less tidy than
10,000 and is worth more: it is the number that puts a quarter of the floor
above it, which is a statement about this team rather than about base ten. An
admin is free to round it afterwards, and usually should — what matters is
that they are rounding something real.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import points as point_service
from app.models import PointAward, Season, Tier

__all__ = [
    "SHAPE",
    "Reached",
    "Suggestion",
    "ladder",
    "standing_for",
    "suggest",
    "tier_for",
]


#: The default ladder, as a name and the share of the floor that should hold
#: it or better.
#:
#: **The top rung is deliberately a tenth.** A tier a third of the floor holds
#: is a participation award; the point of the highest one is that seeing
#: somebody wearing it tells you something. The bottom rung is set at the 40th
#: percentile rather than at "anybody who has scored", because a rung
#: everybody who turns up holds is the "says nothing" failure again — it just
#: fails quietly instead of loudly.
SHAPE: tuple[tuple[str, float], ...] = (
    ("Bronze", 0.40),
    ("Silver", 0.65),
    ("Gold", 0.85),
    ("Platinum", 0.95),
)

#: Below this many scoring people, a suggestion is arithmetic rather than
#: information.
#:
#: With four people on the board the 95th percentile is "the highest score",
#: and a ladder built from it has a top rung exactly one person can stand on —
#: which is the failure this module exists to prevent, arrived at by way of
#: the thing meant to prevent it.
MIN_SAMPLE = 8


@dataclass
class Suggestion:
    """One proposed rung, and what it would mean for the people here now."""

    name: str
    threshold: int
    #: How many people currently on the board would hold this or better.
    would_hold: int


@dataclass
class Reached:
    """Where somebody stands on the ladder."""

    #: What they hold now. None means they are below the first rung.
    current: Tier | None
    #: What is next. None means they are on the top rung.
    next: Tier | None
    #: Points from here to the next rung. None on the top rung.
    to_next: int | None


def ladder(db: DbSession, org_id: int) -> list[Tier]:
    """The rungs, lowest first."""
    return list(
        db.scalars(
            select(Tier)
            .where(Tier.organization_id == org_id)
            .order_by(Tier.threshold)
        ).all()
    )


def tier_for(points: int, rungs: list[Tier]) -> Tier | None:
    """The highest rung this many points reaches, or None for below the first.

    Takes the ladder rather than querying for it: this is called once per row
    of a standings table, and a query per row is how a page that reads fine
    with eight people stops loading with four hundred.
    """
    held: Tier | None = None
    for rung in rungs:
        if points >= rung.threshold:
            held = rung
        else:
            break
    return held


def standing_for(points: int, rungs: list[Tier]) -> Reached:
    """What somebody holds, what is next, and how far.

    **"1,200 to Gold" is the only part of a ladder that changes behaviour.**
    The badge is a reward for what already happened; the distance is the
    reason to do something this week.
    """
    current = tier_for(points, rungs)
    upcoming = next((rung for rung in rungs if rung.threshold > points), None)
    return Reached(
        current=current,
        next=upcoming,
        to_next=(upcoming.threshold - points) if upcoming else None,
    )


def suggest(
    db: DbSession, season: Season, *, shape: tuple[tuple[str, float], ...] = SHAPE
) -> list[Suggestion]:
    """Rungs drawn from what people have actually scored this season.

    Empty when too few people have scored to say anything — see `MIN_SAMPLE`.
    The caller is expected to say so rather than presenting an empty ladder as
    a recommendation.

    Balances are summed per person first: the distribution that matters is of
    *people*, not of awards. Somebody who earned 900 in one win and somebody
    who earned it in thirty are the same height on this ladder, and
    percentiles over raw award rows would put the second one much higher.
    """
    balances = (
        select(func.sum(PointAward.points).label("total"))
        # Earned, not wallet: the ladder is drawn over the same number the
        # table ranks on, so spending cannot drag the suggested rungs down.
        .where(
            PointAward.season_id == season.id,
            ~PointAward.event_key.startswith(point_service.WALLET_PREFIX),
        )
        .group_by(PointAward.user_id)
        .having(func.sum(PointAward.points) > 0)
        .subquery()
    )

    total_people = db.scalar(select(func.count()).select_from(balances)) or 0
    if total_people < MIN_SAMPLE:
        return []

    out: list[Suggestion] = []
    seen: set[int] = set()
    for name, share in shape:
        cut = db.scalar(
            select(
                func.percentile_cont(share).within_group(balances.c.total.asc())
            ).select_from(balances)
        )
        threshold = max(1, int(round(float(cut or 0))))

        # A flat distribution can put two percentiles on the same number — half
        # a floor on exactly 100 points puts the 40th and 65th both there. Two
        # rungs at one height is not a ladder, and the table refuses it
        # anyway, so nudge each one clear of the last.
        while threshold in seen:
            threshold += 1
        seen.add(threshold)

        out.append(
            Suggestion(
                name=name,
                threshold=threshold,
                would_hold=db.scalar(
                    select(func.count())
                    .select_from(balances)
                    .where(balances.c.total >= threshold)
                )
                or 0,
            )
        )
    return out
