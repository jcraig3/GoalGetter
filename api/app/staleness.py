"""When the numbers have stopped arriving (7.3).

**A source that syncs cleanly can still be stuck.** A spreadsheet nobody has
updated since the 23rd is read every hour without an error, so its card said
"Working" while Home blamed 400 people for recording nothing, the Inbox said
nothing, and a rule check advised lowering a bar (Q2-4, Q2-5). Whether a sync
*succeeded* and whether anything *new* arrived are different questions; this
answers the second, once, for every page that needs it.

**Counted in working days**, like pace, so a source quiet over a weekend is
not flagged on Monday morning: three working days with no new row is stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import periods
from app.models import DataSource, MetricFact, Organization
from app.models.data_source import READ_ONCE
from app.pace import working_days

#: Working days with no new row before a source is said to be quiet.
STALE_WORKING_DAYS = 3


def newest_row(db: DbSession, source_id: int) -> datetime | None:
    """When the newest number this source wrote happened."""
    return db.scalar(
        select(func.max(MetricFact.occurred_at)).where(MetricFact.data_source_id == source_id)
    )


def quiet_days(org: Organization, newest: datetime | None, now: datetime) -> int | None:
    """Working days since the newest row, or None when there is none."""
    if newest is None:
        return None
    tz = periods.tz(org)
    last = newest.astimezone(tz).date()
    today = now.astimezone(tz).date()
    # The day of the newest row does not count against it, nor does today,
    # which still has time to produce one.
    return working_days(last + timedelta(days=1), today)


def is_watched(source: DataSource) -> bool:
    """Sources expected to keep bringing numbers: running, set up, scheduled."""
    return (
        source.enabled
        and source.archived_at is None
        and source.activated_at is not None
        and source.interval_minutes != READ_ONCE
        # A failing source is already said to be failing, with its reason.
        and source.last_status != "failed"
    )


@dataclass
class Quiet:
    source: DataSource
    newest: datetime
    working_days: int


def quiet_sources(db: DbSession, org: Organization, now: datetime) -> list[Quiet]:
    """Every watched source that has brought nothing new for a while."""
    out = []
    for source in db.scalars(
        select(DataSource).where(DataSource.organization_id == org.id).order_by(DataSource.name)
    ).all():
        if not is_watched(source):
            continue
        newest = newest_row(db, source.id)
        days = quiet_days(org, newest, now)
        if days is not None and days >= STALE_WORKING_DAYS:
            out.append(Quiet(source=source, newest=newest, working_days=days))
    return out


def name_of(source: DataSource) -> str:
    """What to call a source in a sentence. One made before the setup flow
    was fixed is still named by its connector's key — "microsoft_excel" — so
    it is called what the Integrations page calls it instead."""
    if source.name != source.connector:
        return source.name
    from app import connectors

    try:
        return connectors.get(source.connector).display_name
    except connectors.UnknownConnector:
        return source.name


def say_date(org: Organization, moment: datetime) -> str:
    """"Wed 23 Sep", in the organization's time."""
    local = moment.astimezone(periods.tz(org))
    return f"{local:%a} {local.day} {local:%b}"
