"""When the scoreboard resets.

**The failure this module exists to prevent is not a bug, it is a two-year
decay.** Points that only ever accumulate produce a leaderboard where the
people at the top cannot be caught and the people below cannot catch them, so
both stop looking. The number keeps going up and has stopped meaning anything.

So a season is not an optional feature layered over a points total. Every
award belongs to one, from the very first, and a balance is always "this
season" unless something explicitly asks for the lifetime figure.

The awkward part of that decision is the empty deployment: nobody has
configured a season, somebody closes a big deal, and the economy either
silently swallows the award or refuses to start. Neither is acceptable, so
**the first award opens the first season** — aligned to the organization's
fiscal quarter, because that is a boundary the business already has and
already plans against.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import periods
from app.models import Organization, Season

__all__ = ["current", "open_for", "for_date", "upcoming", "previous", "close"]


def for_date(db: DbSession, org_id: int, day: date) -> Season | None:
    """The season containing `day`, if there is one.

    At most one can match: the exclusion constraint on the table makes
    overlapping seasons unstorable, which is what lets this return a single
    row rather than a list the caller has to disambiguate.
    """
    return db.scalar(
        select(Season).where(
            Season.organization_id == org_id,
            Season.starts_on <= day,
            Season.ends_on >= day,
        )
    )


def current(db: DbSession, org: Organization, *, now: datetime | None = None) -> Season | None:
    """The season running right now, in the organization's own timezone.

    Read-only — see `open_for` for the path that will create one. A page
    showing "no season is running" must not start one as a side effect of
    being looked at.
    """
    return for_date(db, org.id, _today(org, now))


#: The shortest first season worth opening. Fewer days than this left in the
#: quarter and the first season runs to the end of the next one instead.
FIRST_SEASON_MIN_DAYS = 14


def open_for(
    db: DbSession, org: Organization, *, now: datetime | None = None
) -> Season:
    """The season for right now, starting one if none exists.

    **Called from the award path, and only from there.** An economy that
    refuses to pay out until an admin has visited a settings page is an
    economy nobody switches on; one that pays into a lifetime total and gets
    seasons bolted on later has to choose between wiping balances and keeping
    the thing seasons exist to prevent.

    The new season is the organization's current fiscal quarter, so the first
    reset lands on a boundary the business already plans against rather than
    ninety days after whenever somebody happened to close a deal. An admin can
    rename it or reshape the ones after it; what they cannot do is end up
    without one.

    Does not commit. The caller owns the transaction, like `notifications.emit`.
    """
    today = _today(org, now)
    found = for_date(db, org.id, today)
    if found is not None:
        return found

    period = periods.resolve(org, "quarter", today)
    tz = periods.tz(org)
    starts_on = period.start.astimezone(tz).date()
    # `Period.end` is exclusive — the instant the next quarter begins — and a
    # season's `ends_on` is inclusive, so the last day is the one before it.
    ends_on = period.end.astimezone(tz).date() - timedelta(days=1)
    name = period.label

    # **Not a season that is over before anybody notices it.** The first award
    # on 30 September opened "Q3 2026", ending that same day, and reset the
    # points it had just paid (QA-19). Close to a quarter's end, the first
    # season is the *next* quarter, started a few days early.
    if (ends_on - today).days < FIRST_SEASON_MIN_DAYS:
        following = periods.resolve(org, "quarter", ends_on + timedelta(days=1))
        ends_on = following.end.astimezone(tz).date() - timedelta(days=1)
        starts_on = today
        name = following.label

    season = Season(
        organization_id=org.id,
        name=name,
        starts_on=starts_on,
        ends_on=ends_on,
    )
    db.add(season)
    db.flush()
    return season


def previous(db: DbSession, org: Organization, season: Season) -> Season | None:
    """The season before this one, for a "last season" comparison."""
    return db.scalar(
        select(Season)
        .where(
            Season.organization_id == org.id,
            Season.ends_on < season.starts_on,
        )
        .order_by(Season.ends_on.desc())
    )


def upcoming(db: DbSession, org: Organization, *, now: datetime | None = None) -> Season | None:
    """The next season that has been set up, if somebody has set one up."""
    return db.scalar(
        select(Season)
        .where(
            Season.organization_id == org.id,
            Season.starts_on > _today(org, now),
        )
        .order_by(Season.starts_on)
    )


def close(db: DbSession, season: Season, *, now: datetime | None = None) -> bool:
    """Mark a season finished. Returns whether this call did it.

    Separate from the last day for the same reason a competition separates
    `ended` from `closed`: a deal that lands on the final afternoon and syncs
    that evening belongs to the season it happened in.
    """
    if season.closed_at is not None:
        return False
    season.closed_at = now or datetime.now(UTC)
    return True


def _today(org: Organization, now: datetime | None) -> date:
    return (now or datetime.now(UTC)).astimezone(periods.tz(org)).date()
