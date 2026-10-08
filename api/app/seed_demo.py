"""Generate months of realistic metric facts for development.

    docker compose exec api python -m app.seed_demo --days 120
    docker compose exec api python -m app.seed_demo --clear

Phase 1 builds goals, leaderboards, and dashboards *before* any connector
exists. Without generated data there is nothing to build them against, nothing
to demo, and no way to find out whether the aggregation queries are fast at
realistic row counts.

Development and evaluation only. Two things keep it out of production:

  * It is a module, not an endpoint — nothing reachable over HTTP triggers it.
  * Every row it writes carries source_type='import' and an external_id
    — `import` because that value predates this seeder and is the only one that
    is neither hand-entered nor from a connector. It is a slightly dishonest
    label for demo data; see the note on `SOURCE_TYPES`.
    prefixed `demo:`, so `--clear` can remove exactly what it created and
    nothing else.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from app.db import SessionLocal
from app.models import MetricDefinition, MetricFact, Organization, Team, UserAccount

# Everything this script writes is tagged with it, so --clear is exact.
DEMO_PREFIX = "demo:"

# Roughly how much of each metric one agent does on an average working day.
# Deliberately not round numbers — data that is obviously synthetic makes charts
# look wrong in ways that hide real bugs.
DAILY_SHAPE: dict[str, tuple[float, float]] = {
    # key: (mean per working day, spread)
    "calls_made": (42, 14),
    "emails_sent": (31, 11),
    "meetings_booked": (3.1, 1.6),
    "meetings_held": (2.4, 1.3),
    "demos_completed": (1.5, 1.0),
    "deals_created": (1.8, 1.1),
    "deals_won": (0.6, 0.7),
}

# Revenue is derived from deals won rather than drawn independently: a
# leaderboard where the top closer has the lowest revenue looks broken, and
# every real correlation the demo data lacks is a bug the UI can't reveal.
DEAL_SIZE = (4200, 2600)  # mean, spread


def working_day(day: datetime) -> bool:
    return day.weekday() < 5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="seed_demo", description=__doc__)
    parser.add_argument("--days", type=int, default=120, help="how far back to go")
    parser.add_argument(
        "--seed",
        type=int,
        default=20260101,
        help="RNG seed — the same seed regenerates identical data",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="remove previously generated demo facts and exit",
    )
    return parser.parse_args(argv)


def clear_demo_facts(db, organization_id: int) -> int:
    """Remove only rows this script wrote.

    Matches on the external_id prefix rather than truncating the table, so a
    manual correction entered by hand while testing survives. A seed script that
    deletes data it did not create is a seed script nobody runs twice.
    """
    result = db.execute(
        delete(MetricFact).where(
            MetricFact.organization_id == organization_id,
            MetricFact.external_id.startswith(DEMO_PREFIX),
        )
    )
    return result.rowcount or 0


def generate(db, organization_id: int, days: int, seed: int) -> int:
    rng = random.Random(seed)

    org = db.get(Organization, organization_id)
    tz = ZoneInfo(org.timezone)

    metrics = {
        m.key: m
        for m in db.scalars(
            select(MetricDefinition).where(
                MetricDefinition.organization_id == organization_id,
                MetricDefinition.archived_at.is_(None),
            )
        ).all()
    }

    agents = db.scalars(
        select(UserAccount).where(
            UserAccount.organization_id == organization_id,
            UserAccount.hidden_at.is_(None),
            UserAccount.status == "active",
        )
    ).all()
    if not agents:
        raise SystemExit("No active users to generate data for.")

    # A fixed multiplier per person, so the same people are consistently ahead
    # across every metric and every month. Random noise per day alone produces a
    # leaderboard that reshuffles completely on every refresh, which looks like
    # a bug in the ranking rather than a demo.
    talent = {agent.id: rng.uniform(0.55, 1.45) for agent in agents}

    # Resolved once rather than per fact: a team's office does not change
    # mid-run, and this loop writes tens of thousands of rows.
    office_of = {
        team.id: team.office_id
        for team in db.scalars(
            select(Team).where(Team.organization_id == organization_id)
        ).all()
    }

    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    rows: list[dict] = []

    for offset in range(days):
        day = today - timedelta(days=offset)
        if not working_day(day):
            continue

        for agent in agents:
            skill = talent[agent.id]

            # An occasional day off. Without them every agent has a perfect
            # attendance record, and "zero rows for this period" — a real state
            # the UI must handle — never gets exercised.
            if rng.random() < 0.06:
                continue

            deals_won_today = 0

            for key, (mean, spread) in DAILY_SHAPE.items():
                metric = metrics.get(key)
                if metric is None:
                    continue

                amount = max(0, round(rng.gauss(mean * skill, spread)))
                if amount == 0:
                    continue
                if key == "deals_won":
                    deals_won_today = amount

                rows.append(
                    _fact(
                        organization_id,
                        metric,
                        agent,
                        amount,
                        # Spread through the working day in the ORGANIZATION's
                        # timezone, then stored as UTC. Writing midnight UTC
                        # instead would push events into the wrong local day for
                        # anyone west of Greenwich — the single most common
                        # source of "the numbers are wrong".
                        day.replace(hour=rng.randint(8, 17), minute=rng.randint(0, 59)),
                        offset,
                        office_of.get(agent.team_id),
                    )
                )

            revenue = metrics.get("revenue_closed")
            if revenue is not None and deals_won_today:
                total = sum(
                    max(500, rng.gauss(*DEAL_SIZE)) for _ in range(deals_won_today)
                )
                rows.append(
                    _fact(
                        organization_id,
                        revenue,
                        agent,
                        round(total, 2),
                        day.replace(hour=rng.randint(9, 18), minute=rng.randint(0, 59)),
                        offset,
                        office_of.get(agent.team_id),
                    )
                )

    # One bulk insert rather than thousands of ORM objects: this writes tens of
    # thousands of rows, and building a mapped instance for each is where the
    # time would go.
    if rows:
        db.execute(MetricFact.__table__.insert(), rows)
    return len(rows)


def _fact(
    organization_id: int,
    metric: MetricDefinition,
    agent: UserAccount,
    value: float,
    occurred_at: datetime,
    offset: int,
    office_id: int | None,
) -> dict:
    return {
        "organization_id": organization_id,
        "metric_definition_id": metric.id,
        "subject_user_id": agent.id,
        # The snapshot. Today's team is correct for data generated as history
        # because nobody has moved during a seed run — but reading it here, once
        # per row, is the same shape the real write paths use.
        "subject_team_id": agent.team_id,
        "subject_office_id": office_id,
        "value": Decimal(str(value)),
        "occurred_at": occurred_at.astimezone(UTC),
        "source_type": "import",
        # Deterministic and unique: re-running with the same seed collides on
        # the partial unique index instead of silently doubling every number.
        "external_id": f"{DEMO_PREFIX}{metric.key}:{agent.id}:{offset}",
        "created_by_user_id": None,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).order_by(Organization.id))
        if org is None:
            print("No organization — run setup first.", file=sys.stderr)
            return 1

        removed = clear_demo_facts(db, org.id)
        if args.clear:
            db.commit()
            print(f"Removed {removed:,} demo facts.")
            return 0

        written = generate(db, org.id, args.days, args.seed)
        db.commit()

        total = db.scalar(
            select(func.count())
            .select_from(MetricFact)
            .where(MetricFact.organization_id == org.id)
        )
        if removed:
            print(f"Replaced {removed:,} previous demo facts.")
        print(f"Wrote {written:,} facts over {args.days} days. Table now holds {total:,}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
