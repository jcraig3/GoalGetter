"""Recurring competitions: the same contest, every day, week or month.

**No template row.** Like a recurring goal, the original competition is itself
the first round, and it repeats: each later round is a real competition with its
own absolute start and end, its own entrants and its own frozen result. A
settled round is exactly as settled as any other contest — which is why this is
a spawner and not a "period type" on the competition. Re-resolving a period
later could give a different window, and for a result somebody was paid on that
would be rewriting history.

**Dates follow the series; everything else follows the last round.** A round's
window is the original's, moved on by whole days, weeks or months in the
organization's own clock — so a 9am Monday start stays 9am across a daylight
saving change, and nothing drifts. Its name, prize, rules and entrants are
copied from the most recent round, so editing next week's scheduled round is how
the series changes from then on.

**One round ahead.** The next round is made as soon as the current one starts,
so it is on the list as *scheduled* and builds anticipation. A series left alone
for a month does not produce four back-dated contests nobody saw: only the round
running now, if one is, and the next.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.models import Competition, CompetitionParticipant, Organization

__all__ = ["REPEATS", "fits", "root_of", "round_window", "rounds_of", "shift", "spawn_due"]

REPEATS = ("daily", "weekly", "monthly")

#: How far a neglected series is walked forward in one pass before giving up —
#: a daily series untouched for a decade is somebody's mistake, not a backlog.
MAX_STEPS = 5000


def _add_months(day: date, months: int) -> date:
    """The same day of a later month, or its last day when it has fewer.

    A monthly contest starting on the 31st runs on the 30th in April rather
    than skipping April.
    """
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def shift(org: Organization, instant: datetime, repeat: str, steps: int) -> datetime:
    """`instant` moved on by `steps` repeats, on the organization's wall clock."""
    zone = ZoneInfo(org.timezone)
    local = instant.astimezone(zone).replace(tzinfo=None)
    if repeat == "daily":
        moved = local + timedelta(days=steps)
    elif repeat == "weekly":
        moved = local + timedelta(weeks=steps)
    elif repeat == "monthly":
        moved = datetime.combine(_add_months(local.date(), steps), local.time())
    else:
        raise ValueError(f"Not a repeat: {repeat}")
    return moved.replace(tzinfo=zone).astimezone(UTC)


def round_window(org: Organization, root: Competition, number: int) -> tuple[datetime, datetime]:
    return (
        shift(org, root.starts_at, root.repeat, number),
        shift(org, root.ends_at, root.repeat, number),
    )


def fits(org: Organization, starts_at: datetime, ends_at: datetime, repeat: str) -> bool:
    """Whether one round ends before the next begins.

    Two rounds of the same contest running at once would split the same
    people's numbers between two tables, so a fortnight's contest cannot
    repeat weekly.
    """
    return ends_at <= shift(org, starts_at, repeat, 1)


def root_of(db: DbSession, competition: Competition) -> Competition:
    if competition.spawned_from_competition_id is None:
        return competition
    return db.get(Competition, competition.spawned_from_competition_id) or competition


def rounds_of(db: DbSession, root: Competition) -> list[Competition]:
    """Every round of a series, first first."""
    later = db.scalars(
        select(Competition)
        .where(Competition.spawned_from_competition_id == root.id)
        .order_by(Competition.round)
    ).all()
    return [root, *later]


def _copy(db: DbSession, root: Competition, source: Competition, number: int,
          starts_at: datetime, ends_at: datetime) -> Competition:
    child = Competition(
        organization_id=root.organization_id,
        name=source.name,
        prize=source.prize,
        metric_definition_id=source.metric_definition_id,
        entity_type=source.entity_type,
        starts_at=starts_at,
        ends_at=ends_at,
        settlement_hours=source.settlement_hours,
        tie_break=source.tie_break,
        min_participation=source.min_participation,
        finish_line=source.finish_line,
        appearance=dict(source.appearance or {}),
        # Published: the series was, and a round nobody publishes would never run.
        state="scheduled",
        created_by_user_id=root.created_by_user_id,
        spawned_from_competition_id=root.id,
        round=number,
    )
    db.add(child)
    db.flush()
    for entrant in db.scalars(
        select(CompetitionParticipant).where(CompetitionParticipant.competition_id == source.id)
    ).all():
        db.add(
            CompetitionParticipant(
                competition_id=child.id, user_id=entrant.user_id, team_id=entrant.team_id
            )
        )
    db.flush()
    return child


def spawn_due(db: DbSession, *, now: datetime | None = None) -> int:
    """Make the rounds every repeating series should have by now. Idempotent:
    a unique index on (series, round) makes a second copy impossible."""
    now = now or datetime.now(UTC)
    made = 0
    roots = db.scalars(
        select(Competition).where(
            Competition.repeat.is_not(None),
            Competition.spawned_from_competition_id.is_(None),
            # An unpublished series has not started, and nobody should
            # discover it went live. A cancelled first round does not end the
            # series; switching repeating off does.
            Competition.state != "draft",
        )
    ).all()

    for root in roots:
        org = db.get(Organization, root.organization_id)
        if org is None:
            continue
        zone = ZoneInfo(org.timezone)
        existing = dict(
            db.execute(
                select(Competition.round, Competition.id).where(
                    Competition.spawned_from_competition_id == root.id
                )
            ).all()
        )
        latest = max(existing, default=0)

        # The round running now: the last one whose start has passed. Walked
        # back first, because the latest round made is usually the *next* one.
        current = latest
        while current > 0 and round_window(org, root, current)[0] > now:
            current -= 1
        for _ in range(MAX_STEPS):
            if round_window(org, root, current + 1)[0] > now:
                break
            current += 1

        if current == 0 and root.starts_at > now:
            # The first round has not started, so there is no "current" round
            # to be one ahead of yet.
            continue

        wanted = [current + 1]
        if current > latest and round_window(org, root, current)[1] > now:
            wanted.insert(0, current)

        for number in wanted:
            if number <= 0 or number in existing:
                continue
            starts_at, ends_at = round_window(org, root, number)
            if root.repeat_until is not None and starts_at.astimezone(zone).date() > root.repeat_until:
                continue
            source_id = existing[max(existing)] if existing else root.id
            source = db.get(Competition, source_id) or root
            try:
                with db.begin_nested():
                    child = _copy(db, root, source, number, starts_at, ends_at)
            except IntegrityError:
                continue
            existing[number] = child.id
            made += 1
    return made

