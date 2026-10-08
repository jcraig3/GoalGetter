"""Earning badges, and counting what earns them.

**A badge is the part of the economy that survives a season reset.** Points go
to zero every quarter — deliberately, because a total that only grows cannot be
caught up with — and something has to be left over, or the reset takes
everything anybody built with it. A tier is not that thing either: a tier is
read from the current balance, so it resets too.

So badges are stored rather than derived, which is the opposite of nearly
everything else here, and it is the right way round. A leaderboard is derived
because a corrected fact should correct it. "Ten big deals in March" is not a
claim about the present at all — March is over — and recomputing it later would
be rewriting history rather than correcting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app import achievements, periods, points as point_service, seasons
from app.models import (
    AchievementRule,
    Badge,
    BadgeAward,
    MetricFact,
    Organization,
    UserAccount,
)

__all__ = ["Report", "detect", "earn", "held_by", "progress_for", "window_start"]


@dataclass
class Report:
    """What one pass over the badges did."""

    badges: int = 0
    awarded: int = 0
    #: Badges skipped because their window could not be resolved — a season
    #: badge in an organization with no season running. Counted rather than
    #: logged away, so a deployment where nothing is ever earned has somewhere
    #: to look.
    skipped: int = 0

    def __str__(self) -> str:
        return (
            f"badges {self.badges} considered, {self.awarded} awarded, "
            f"{self.skipped} with no window"
        )


def window_start(
    db: DbSession, org: Organization, counted_over: str, today: date
) -> date | None:
    """The first day of the window a count is taken over, or None.

    None only for a season badge in an organization with no season running.
    **Awarding one must not open a season** — that is the ledger's job, and a
    background pass quietly starting the economy's clock because somebody
    defined a badge would be a surprising thing for it to do.
    """
    if counted_over in ("week", "month"):
        # **Through `periods`, not recomputed here.** That module already
        # converts the organization's Sunday-is-0 setting to Python's
        # Monday-is-0 and calls the mix-up "the classic off-by-one that puts
        # Sunday's numbers in the wrong week". A second copy of that
        # conversion is how a badge counts a different week from the
        # leaderboard beside it.
        period = periods.resolve(org, counted_over, today)
        return period.start.astimezone(periods.tz(org)).date()

    season = seasons.for_date(db, org.id, today)
    return season.starts_on if season else None


def _count_since(
    db: DbSession, rule: AchievementRule, since: date, org: Organization
) -> list[tuple[int, int]]:
    """How many times this rule has fired for each person since `since`.

    Counted from `metric_fact` rather than from notifications or ledger rows,
    and both alternatives are tempting and wrong. Notifications are pruned at
    ninety days, so a season-long badge would quietly undercount near the end
    of a quarter. Ledger rows only exist when the rule pays points, so a rule
    set to zero — "celebrate it, do not pay for it" — would never earn its
    badge at all.

    The facts are the ground truth, and `achievements.matches` is the single
    definition of which of them this rule celebrates.
    """
    start = datetime.combine(since, datetime.min.time(), tzinfo=periods.tz(org))
    rows = db.execute(
        select(MetricFact.subject_user_id, func.count())
        .where(*achievements.matches(rule), MetricFact.occurred_at >= start)
        .group_by(MetricFact.subject_user_id)
    ).all()
    return [(user_id, count) for user_id, count in rows if user_id is not None]


def detect(db: DbSession, *, now: datetime | None = None) -> Report:
    """One pass over every counted badge, awarding what has become true.

    Idempotent by the unique index, like every other detection pass here, so
    running it twice in a row is indistinguishable from running it once.
    """
    report = Report()
    now = now or datetime.now(UTC)

    orgs = {org.id: org for org in db.scalars(select(Organization)).all()}

    for badge in db.scalars(select(Badge).where(Badge.kind == "count")).all():
        org = orgs.get(badge.organization_id)
        rule = db.get(AchievementRule, badge.achievement_rule_id)
        if org is None or rule is None:
            continue

        report.badges += 1
        today = now.astimezone(periods.tz(org)).date()
        since = window_start(db, org, badge.counted_over, today)
        if since is None:
            report.skipped += 1
            continue

        for user_id, count in _count_since(db, rule, since, org):
            if count < badge.threshold:
                continue
            person = db.get(UserAccount, user_id)
            if person is None or person.hidden_at is not None:
                continue
            if earn(db, org, badge, user_id, period_anchor=since, now=now):
                report.awarded += 1

    return report


def earn(
    db: DbSession,
    org: Organization,
    badge: Badge,
    user_id: int,
    *,
    period_anchor: date | None,
    reason: str | None = None,
    awarded_by_user_id: int | None = None,
    now: datetime | None = None,
) -> BadgeAward | None:
    """Give somebody a badge. None when they already had this one.

    Pays the badge's points through the ordinary ledger, and only when the
    award was new — so a re-run of the detection pass cannot pay twice even
    though the ledger would have latched it anyway. Two guards on one thing,
    which is right for the one write that hands out money.
    """
    statement = (
        insert(BadgeAward)
        .values(
            organization_id=org.id,
            badge_id=badge.id,
            user_id=user_id,
            period_anchor=period_anchor,
            reason=(reason or badge.name)[:200],
            awarded_by_user_id=awarded_by_user_id,
        )
        .on_conflict_do_nothing()
        .returning(BadgeAward.id)
    )
    new_id = db.scalar(statement)
    if new_id is None:
        return None

    if badge.points:
        point_service.award(
            db,
            org=org,
            user_id=user_id,
            points=badge.points,
            event_key=f"badge.{badge.id}",
            subject_type="badge",
            subject_id=badge.id,
            period_anchor=period_anchor,
            reason=badge.name,
            # Null even for a hand-pinned badge: the *system* decided to pay,
            # from a number set on the badge. Setting it would turn off the
            # ledger's latch, and then a manager pinning one twice would pay
            # twice for a badge somebody holds once.
            now=now,
        )

    return db.get(BadgeAward, new_id)


@dataclass
class Held:
    """One badge somebody holds, with everything a page needs to draw it."""

    badge_id: int
    name: str
    description: str
    icon: str
    reason: str
    earned_at: datetime
    times: int = 1


def held_by(db: DbSession, org_id: int, user_id: int) -> list[Held]:
    """Every badge somebody has, most recent first.

    **Collapsed by badge, with a count.** Somebody who has earned "Ten big
    deals" in four different months holds one badge four times over, and a
    profile listing it four times reads as a bug. The number is the
    interesting part anyway — it is the difference between a good month and a
    habit.
    """
    rows = db.execute(
        select(
            Badge.id,
            Badge.name,
            Badge.description,
            Badge.icon,
            func.count(BadgeAward.id),
            func.max(BadgeAward.created_at),
            func.min(BadgeAward.reason),
        )
        .join(BadgeAward, BadgeAward.badge_id == Badge.id)
        .where(
            BadgeAward.organization_id == org_id,
            BadgeAward.user_id == user_id,
        )
        .group_by(Badge.id, Badge.name, Badge.description, Badge.icon)
        .order_by(func.max(BadgeAward.created_at).desc())
    ).all()

    return [
        Held(
            badge_id=badge_id,
            name=name,
            description=description or "",
            icon=icon,
            reason=reason or name,
            earned_at=earned_at,
            times=times,
        )
        for badge_id, name, description, icon, times, earned_at, reason in rows
    ]


@dataclass
class Progress:
    """How close somebody is to a counted badge this window."""

    badge_id: int
    name: str
    description: str
    icon: str
    have: int
    need: int
    counted_over: str

    @property
    def remaining(self) -> int:
        return max(self.need - self.have, 0)


def progress_for(
    db: DbSession, org: Organization, user_id: int, *, now: datetime | None = None
) -> list[Progress]:
    """Counted badges this person is partway to, closest first.

    **The half of a badge that changes behaviour**, and the same argument the
    tier ladder makes: the badge rewards what already happened, "two more this
    month" is the reason to do something today. Badges they have not started
    on are left out — a list of everything they could theoretically earn is a
    catalogue, and nobody reads a catalogue.
    """
    now = now or datetime.now(UTC)
    today = now.astimezone(periods.tz(org)).date()

    out: list[Progress] = []
    for badge in db.scalars(
        select(Badge).where(
            Badge.organization_id == org.id, Badge.kind == "count"
        )
    ).all():
        rule = db.get(AchievementRule, badge.achievement_rule_id)
        since = window_start(db, org, badge.counted_over, today)
        if rule is None or since is None:
            continue

        have = next(
            (
                count
                for found, count in _count_since(db, rule, since, org)
                if found == user_id
            ),
            0,
        )
        if have == 0 or have >= badge.threshold:
            continue

        out.append(
            Progress(
                badge_id=badge.id,
                name=badge.name,
                description=badge.description or "",
                icon=badge.icon,
                have=have,
                need=badge.threshold,
                counted_over=badge.counted_over,
            )
        )

    out.sort(key=lambda row: row.remaining)
    return out
