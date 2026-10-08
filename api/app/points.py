"""The points economy: one row per award, and a balance is a sum.

Three decisions shape everything here.

**A ledger, never a running total.** `user_account.points` would be one number
incremented from four code paths, and the first time two of them race — or a
job restarts mid-pass — it is wrong with nothing to compare it against. A
ledger cannot drift from itself, and "why do I have 4,200?" becomes a query
instead of an apology.

**Awarding is idempotent, by the same index trick `notification` uses.** The
jobs that pay points out are the jobs that announce things: they run on a loop
over state that is a query rather than a column. The row *is* the record that
we awarded it, so the insert is ON CONFLICT DO NOTHING and races stop
mattering.

**Every award belongs to a season, from the first one.** See `app/seasons.py`
for why that is not a refinement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app import events, seasons as season_service
from app.models import Organization, PointAward, PointValue, Season, UserAccount

__all__ = [
    "DEFAULTS",
    "Standing",
    "award",
    "award_for",
    "balance",
    "lifetime",
    "NotEnough",
    "WALLET_PREFIX",
    "credit",
    "spend",
    "wallet",
    "rule_key",
    "standings",
    "statement",
    "value_of",
    "values_for",
]


#: What each thing is worth before anybody tunes it.
#:
#: **The shape of this table is the product's opinion about what matters**, and
#: it is deliberately not flat. Hitting a goal you were set is the backbone of
#: the number; winning a contest you entered against other people is worth
#: more than any single goal; being recognised by a colleague is worth
#: something real but small, because it is the one award another person can
#: hand out freely and an economy where praise is the cheapest way to farm
#: points stops being praise.
#:
#: A birthday is worth nothing. It is celebrated on the wall and it is not an
#: achievement — paying for it would put the person with the earliest birthday
#: ahead of the person who closed the most deals in January, which is the sort
#: of detail that makes a floor stop believing the scoreboard.
#:
#: Absent from a deployment's `point_value` rows means these apply. Zero means
#: an admin turned it off, which is a different statement.
DEFAULTS: dict[str, int] = {
    events.GOAL_ACHIEVED.key: 100,
    #: Each stretch level past the target, on top of the target's own points.
    **{event.key: 50 for event in events.GOAL_STRETCH},
    events.COMPETITION_WON.key: 500,
    #: Not first place, but on the podium. Entering a contest and finishing
    #: third should beat not entering.
    "competition.placed": 150,
    events.RECOGNITION.key: 25,
    events.BIRTHDAY.key: 0,
    events.WORK_ANNIVERSARY.key: 0,
}

#: A hand-written award or correction. Never latches — a manager who gives
#: somebody 50 points twice meant to do it twice.
MANUAL = "manual"

#: The prefix for movements that touch the wallet and never the table:
#: `wallet.unlock` and `wallet.spin` going out, `wallet.win` coming in.
#:
#: **Spending never costs anybody their place on the table**, and this prefix
#: is how the ledger keeps that promise. A system where buying something drops
#: you down the rankings is a system where nobody buys anything — which is
#: exactly how the economy this was measured against died: lifetime points
#: equalled reward points because nothing was ever spent. So there are two
#: numbers, and they are read from the same rows:
#:
#:     earned   every row except spends — what the table ranks on, and it
#:              resets with the season
#:     wallet   every row, spends included — what can be spent, and it
#:              carries across seasons
#:
#: The wallet carries over because the reason for a season does not apply to
#: it. A reset exists to keep the *ranking* catchable, and the wallet ranks
#: nothing; wiping somebody's savings every quarter would read as theft.
#:
#: **Winnings from the prize wheel come in under it too**, and that is the same
#: promise from the other side. If a lucky spin moved somebody up the table,
#: spinning would become a way to climb it — the ranking would start measuring
#: luck and appetite for risk rather than work. So a win lands in the wallet,
#: spendable like anything else, and the table never hears about it.
#:
#: A correction (`manual`, negative) is not a wallet movement. It un-earns
#: points that were paid by mistake, so it moves the table as well — which is
#: its job.
WALLET_PREFIX = "wallet."


def _earned():
    """Rows that count toward what somebody has *earned* — everything but
    wallet movements. Used by every number that ranks, and by nothing that
    spends."""
    return ~PointAward.event_key.startswith(WALLET_PREFIX)


class NotEnough(Exception):
    """A spend the wallet cannot cover."""

    def __init__(self, have: int, need: int) -> None:
        super().__init__(f"This costs {need:,} points and you have {have:,}.")
        self.have = have
        self.need = need

#: What an achievement rule pays, when the rule does not say otherwise.
#:
#: Low on purpose. A rule fires on *every* matching record, so it is the one
#: award whose volume an admin cannot predict when they write it — "a deal over
#: $5,000" might be twice a month or twice an hour, and a default of 100 would
#: let one careless threshold swamp every other source in the economy.
DEFAULT_RULE_POINTS = 10

#: How a rule's award is keyed, so two rules do not share a latch.
def rule_key(rule_id: int) -> str:
    return f"achievement.{rule_id}"


def value_of(db: DbSession, org_id: int, event_key: str) -> int:
    """What this organization pays for one of these."""
    found = db.scalar(
        select(PointValue.points).where(
            PointValue.organization_id == org_id,
            PointValue.event_key == event_key,
        )
    )
    return found if found is not None else DEFAULTS.get(event_key, 0)


def values_for(db: DbSession, org_id: int) -> dict[str, int]:
    """Every catalogue value, defaults filled in. For the settings page."""
    rows = {
        key: points
        for key, points in db.execute(
            select(PointValue.event_key, PointValue.points).where(
                PointValue.organization_id == org_id
            )
        ).all()
    }
    return {key: rows.get(key, default) for key, default in DEFAULTS.items()}


def award(
    db: DbSession,
    *,
    org: Organization,
    user_id: int,
    points: int,
    event_key: str,
    subject_type: str,
    subject_id: int,
    reason: str,
    period_anchor: date | None = None,
    awarded_by_user_id: int | None = None,
    now: datetime | None = None,
) -> PointAward | None:
    """Write one ledger row. Returns it, or None if nothing was written.

    None means one of two innocent things: the award is worth zero points, or
    this exact award already exists. Neither is an error — the second is the
    idempotency guarantee doing its job, and callers run in loops that expect
    to hit it constantly.

    Does not commit. The caller owns the transaction boundary, so one pass over
    many goals is one commit rather than hundreds.
    """
    if points == 0:
        # The CHECK constraint forbids it anyway, and a statement full of
        # "+0 for something" lines is a statement nobody reads.
        return None

    season = season_service.open_for(db, org, now=now)

    statement_ = (
        insert(PointAward)
        .values(
            organization_id=org.id,
            season_id=season.id,
            user_id=user_id,
            points=points,
            event_key=event_key,
            subject_type=subject_type,
            subject_id=subject_id,
            period_anchor=period_anchor,
            reason=reason[:200],
            awarded_by_user_id=awarded_by_user_id,
        )
        # Untargeted, for the same reason `notifications.emit` is: naming the
        # arbiter would mean repeating its partial WHERE clause here, and two
        # copies of a predicate that must agree forever is one copy too many.
        .on_conflict_do_nothing()
        .returning(PointAward.id)
    )
    new_id = db.scalar(statement_)
    return db.get(PointAward, new_id) if new_id is not None else None


def award_for(
    db: DbSession,
    *,
    org: Organization,
    user_id: int,
    event_key: str,
    subject_type: str,
    subject_id: int,
    reason: str,
    period_anchor: date | None = None,
    now: datetime | None = None,
) -> PointAward | None:
    """`award`, with the amount looked up from what this organization pays.

    The form almost every caller wants, so that a detection path never has to
    know the price list — it says what happened and this decides what that is
    worth here.
    """
    return award(
        db,
        org=org,
        user_id=user_id,
        points=value_of(db, org.id, event_key),
        event_key=event_key,
        subject_type=subject_type,
        subject_id=subject_id,
        reason=reason,
        period_anchor=period_anchor,
        now=now,
    )


def balance(db: DbSession, season_id: int, user_id: int) -> int:
    """What somebody has *earned* this season. A sum, every time it is asked.

    Wallet movements are left out — see `WALLET_PREFIX`. This is the number the table
    ranks on, and buying something must never move it.
    """
    total = db.scalar(
        select(func.coalesce(func.sum(PointAward.points), 0)).where(
            PointAward.season_id == season_id,
            PointAward.user_id == user_id,
            _earned(),
        )
    )
    return int(total or 0)


def lifetime(db: DbSession, org_id: int, user_id: int) -> int:
    """Every season added together.

    Exists, and is deliberately not what anything ranks on. It is a fact about
    somebody's history — worth showing on their own profile, the way a career
    total is — but the moment it becomes the scoreboard, the scoreboard is
    unwinnable again for everybody who joined last year.
    """
    total = db.scalar(
        select(func.coalesce(func.sum(PointAward.points), 0)).where(
            PointAward.organization_id == org_id,
            PointAward.user_id == user_id,
            _earned(),
        )
    )
    return int(total or 0)


def wallet(db: DbSession, org_id: int, user_id: int) -> int:
    """What somebody can spend: everything earned, in every season, less what
    they have already spent.

    Deliberately not scoped to a season. See `WALLET_PREFIX` for why the wallet
    carries over when the table does not.
    """
    total = db.scalar(
        select(func.coalesce(func.sum(PointAward.points), 0)).where(
            PointAward.organization_id == org_id,
            PointAward.user_id == user_id,
        )
    )
    return int(total or 0)


def spend(
    db: DbSession,
    *,
    org: Organization,
    user_id: int,
    points: int,
    what: str,
    subject_type: str,
    subject_id: int,
    reason: str,
    now: datetime | None = None,
) -> PointAward:
    """Take `points` out of somebody's wallet. Raises `NotEnough` if it cannot.

    **The person's row is locked first**, and that is what makes the balance
    check mean anything. Without it two spends a few milliseconds apart — a
    double-click, two tabs — both read the same wallet, both see enough, and
    both go through, leaving a negative balance that nothing refused. `FOR
    UPDATE` on the account serializes spends per person, and only per person:
    two different people spending at once never wait on each other.

    `awarded_by_user_id` is the spender. That switches off the ledger's
    idempotency latch, which is right — buying two spins is two spins — and it
    also records who chose to spend, which for a spend is the only person who
    could have.

    Does not commit. The caller owns the transaction, and the thing bought has
    to be written inside the same one: a spend that commits while the unlock it
    paid for fails is points taken for nothing.
    """
    if points <= 0:
        raise ValueError("A spend has to cost something.")

    db.execute(
        select(UserAccount.id).where(UserAccount.id == user_id).with_for_update()
    )
    have = wallet(db, org.id, user_id)
    if have < points:
        raise NotEnough(have, points)

    season = season_service.open_for(db, org, now=now)
    row = PointAward(
        organization_id=org.id,
        season_id=season.id,
        user_id=user_id,
        points=-points,
        event_key=f"{WALLET_PREFIX}{what}",
        subject_type=subject_type,
        subject_id=subject_id,
        reason=reason[:200],
        awarded_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    return row


def credit(
    db: DbSession,
    *,
    org: Organization,
    user_id: int,
    points: int,
    what: str,
    subject_type: str,
    subject_id: int,
    reason: str,
    now: datetime | None = None,
) -> PointAward:
    """Put points in somebody's wallet without putting them on the table.

    For a prize-wheel win, and for nothing earned by work — that goes through
    `award`, which is what the table counts. See `WALLET_PREFIX` for why the
    difference matters.

    Never latches. Each spin is its own event, and the spin row it pays for is
    what records that it happened once.
    """
    if points <= 0:
        raise ValueError("A credit has to be worth something.")

    season = season_service.open_for(db, org, now=now)
    row = PointAward(
        organization_id=org.id,
        season_id=season.id,
        user_id=user_id,
        points=points,
        event_key=f"{WALLET_PREFIX}{what}",
        subject_type=subject_type,
        subject_id=subject_id,
        reason=reason[:200],
        awarded_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    return row


@dataclass
class Standing:
    """One row of the season table."""

    user_id: int
    name: str
    points: int
    rank: int


def standings(
    db: DbSession,
    season: Season,
    *,
    user_ids: list[int] | None = None,
    limit: int | None = None,
) -> list[Standing]:
    """The season table, highest first.

    `user_ids` narrows it to people the viewer may see, and is passed rather
    than resolved here so that this module never has to know about scope. An
    empty list means nobody, which is different from None meaning everybody.
    """
    if user_ids is not None and not user_ids:
        return []

    query = (
        select(
            PointAward.user_id,
            UserAccount.full_name,
            func.sum(PointAward.points).label("points"),
        )
        .join(UserAccount, UserAccount.id == PointAward.user_id)
        # Earned only. Spending must never move anybody on the table — see
        # `WALLET_PREFIX`.
        .where(PointAward.season_id == season.id, _earned())
        .group_by(PointAward.user_id, UserAccount.full_name)
        # **A net of zero is not a score.** Somebody who has never been awarded
        # anything does not appear at all, so somebody whose award was
        # corrected back to nothing must not appear either — otherwise two
        # people with no points are shown differently, and one of them is
        # sitting at rank 1 with a zero beside their name. Negative balances
        # do show: being docked is a thing that happened.
        .having(func.sum(PointAward.points) != 0)
        # Name breaks the tie so the order is stable between loads rather than
        # whatever the planner returns today.
        .order_by(func.sum(PointAward.points).desc(), UserAccount.full_name)
    )
    if user_ids is not None:
        query = query.where(PointAward.user_id.in_(user_ids))

    rows = db.execute(query).all()

    out: list[Standing] = []
    # RANK, giving 1, 2, 2, 4 — two tied for 2nd and nobody 3rd, matching how
    # every other ranked thing in this product behaves.
    previous_points: int | None = None
    previous_rank = 0
    for index, (user_id, name, total) in enumerate(rows, start=1):
        total = int(total)
        rank = previous_rank if total == previous_points else index
        out.append(Standing(user_id=user_id, name=name, points=total, rank=rank))
        previous_points, previous_rank = total, rank

    return out[:limit] if limit else out


def statement(
    db: DbSession, org_id: int, user_id: int, *, season_id: int | None = None, limit: int = 50
) -> list[PointAward]:
    """Where somebody's points came from, newest first.

    **The thing that makes a points total believable.** A number with no
    statement behind it is a number people argue with; one they can open and
    read line by line is one they trust, including the lines they do not like.
    """
    query = (
        select(PointAward)
        .where(
            PointAward.organization_id == org_id,
            PointAward.user_id == user_id,
        )
        .order_by(PointAward.id.desc())
        .limit(limit)
    )
    if season_id is not None:
        query = query.where(PointAward.season_id == season_id)
    return list(db.scalars(query).all())
