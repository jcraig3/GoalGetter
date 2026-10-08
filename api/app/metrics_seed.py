"""The metrics a fresh deployment starts with.

A new install faces an empty configuration screen otherwise, and "what should I
measure?" is a worse first question than "are these the right eight?". They are
ordinary rows — editable, archivable, deletable — not protected defaults.

Deliberately NOT seeded by a migration. Migrations are structural and must
behave identically forever; business defaults change as the product learns what
teams actually track. Seeding happens when an organization is created, so the
list can evolve without rewriting history.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import MetricDefinition

# (key, name, unit, aggregation, direction, decimal_places)
DEFAULT_METRICS: list[tuple[str, str, str, str, str, int]] = [
    ("calls_made", "Calls Made", "count", "sum", "higher_is_better", 0),
    ("emails_sent", "Emails Sent", "count", "sum", "higher_is_better", 0),
    ("meetings_booked", "Meetings Booked", "count", "sum", "higher_is_better", 0),
    ("meetings_held", "Meetings Held", "count", "sum", "higher_is_better", 0),
    ("demos_completed", "Demos Completed", "count", "sum", "higher_is_better", 0),
    ("deals_created", "Deals Created", "count", "sum", "higher_is_better", 0),
    ("deals_won", "Deals Won", "count", "sum", "higher_is_better", 0),
    # The only one with decimals: money is the metric people check most closely,
    # and a revenue board rounding to whole units invites "that's not my number".
    ("revenue_closed", "Revenue Closed", "currency", "sum", "higher_is_better", 2),
]


def seed_default_metrics(db: DbSession, organization_id: int) -> int:
    """Add any missing default metrics. Returns how many were created.

    Skips by key rather than by count, so an admin who renamed `calls_made` to
    "Dials" keeps the name — running this again finds the key present and leaves
    the row untouched.

    A key that is *absent* is added, including one that was deleted. That is the
    intended behaviour for both callers: at organization creation nothing has
    been deleted yet, and the "restore defaults" endpoint exists precisely to
    bring missing ones back. It is not a way to permanently opt out of a
    default — archiving is, and archived metrics are skipped because their key
    still exists.

    Does not commit — the caller's transaction does, so a failed setup leaves no
    orphaned metrics behind.
    """
    existing = set(
        db.scalars(
            select(MetricDefinition.key).where(
                MetricDefinition.organization_id == organization_id
            )
        ).all()
    )

    # A default whose name an active metric already uses is skipped too: names
    # are unique among metrics in use, and an admin's own "Revenue" is the one
    # to keep.
    names = {
        name.lower()
        for name in db.scalars(
            select(MetricDefinition.name).where(
                MetricDefinition.organization_id == organization_id,
                MetricDefinition.archived_at.is_(None),
            )
        ).all()
    }

    created = 0
    for key, name, unit, aggregation, direction, decimals in DEFAULT_METRICS:
        if key in existing or name.lower() in names:
            continue
        db.add(
            MetricDefinition(
                organization_id=organization_id,
                key=key,
                name=name,
                unit=unit,
                aggregation=aggregation,
                direction=direction,
                decimal_places=decimals,
            )
        )
        created += 1

    return created
