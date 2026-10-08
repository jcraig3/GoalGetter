"""How many days in a row somebody has put a number on the board.

**A streak is the one statistic on a spotlight that is about the person rather
than about the period.** "Fourteenth on the board" changes when the month
rolls over and says nothing about effort; "nine days running" survives the
reset and is the thing people actually chase.

Counted in the organization's timezone, like every other boundary in this
product — a call logged at 6pm in Phoenix belongs to that Phoenix day, whatever
the server thinks the date is. See `app/periods.py`, which owns that rule.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import periods
from app.models import MetricFact, Organization

#: How far back a streak is counted from.
#:
#: A year, which is past the point where the number stops meaning anything
#: different — and it bounds the scan, so one spotlight on a wall refreshing
#: every thirty seconds cannot turn into a table sweep.
LOOKBACK_DAYS = 370


def current(
    db: DbSession,
    org: Organization,
    *,
    metric_id: int,
    user_id: int,
    today: date | None = None,
) -> int:
    """Consecutive days with at least one fact, ending today or yesterday.

    **Yesterday counts as current, and it has to.** Numbers arrive during the
    day — at nine in the morning nobody has today's yet — so requiring today
    would reset every streak in the building overnight and restore it by lunch.
    A wall that says "0 days" for a person who worked yesterday is wrong in the
    way people notice.

    Returns 0 when the last activity is older than that, which is the honest
    answer: the streak is over, not merely paused.
    """
    zone = periods.tz(org)
    today = today or periods.today(org)
    floor = today - timedelta(days=LOOKBACK_DAYS)

    rows = db.scalars(
        select(MetricFact.occurred_at).where(
            MetricFact.organization_id == org.id,
            MetricFact.metric_definition_id == metric_id,
            MetricFact.subject_user_id == user_id,
            # A generous window on both sides of the local dates we want. The
            # conversion happens in Python, so the filter is deliberately loose
            # rather than trying to express the timezone in SQL.
            MetricFact.occurred_at >= _utc_floor(floor, zone),
        )
    ).all()

    if not rows:
        return 0

    active = {moment.astimezone(zone).date() for moment in rows}

    # Anchor on today or yesterday, whichever the person actually has. Starting
    # unconditionally at today would count a streak ending yesterday as zero.
    day = today if today in active else today - timedelta(days=1)
    if day not in active:
        return 0

    length = 0
    while day in active:
        length += 1
        day -= timedelta(days=1)
    return length


def _utc_floor(local_day: date, zone: ZoneInfo) -> datetime:
    """Midnight on that local day, as an instant, for the SQL filter."""
    return datetime.combine(local_day, time.min, tzinfo=zone)
