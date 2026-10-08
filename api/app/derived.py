"""Derived metrics: one metric worked out from two others.

"Close rate = deals won ÷ deals created." A derived metric has **no facts of
its own** — every number it shows is computed from its two component metrics,
over the same window, the same people and the same scope, inside the one
aggregation query everything else uses (`app/aggregate.py`). So a close-rate
leaderboard, goal or competition is ranked, scoped and snapshotted exactly the
way a calls leaderboard is, with nothing stored to go stale.

**A ratio of totals, never an average of ratios.** A team's close rate is the
team's wins over the team's deals, not the average of each person's rate — the
second lets somebody with one deal and one win count as much as somebody with
forty. That falls out of dividing the two aggregates rather than aggregating a
division.

**Shown as a percent when its unit is percent**, which is what "close rate"
means to anybody reading it: 0.35 becomes 35%.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app.models import MetricDefinition

__all__ = ["RATIO", "components", "fact_metric_ids", "is_derived", "scale", "used_by"]

RATIO = "ratio"


def is_derived(metric: MetricDefinition | None) -> bool:
    return metric is not None and metric.aggregation == RATIO


def scale(metric: MetricDefinition) -> int:
    """100 for a percent — 7 won of 20 is 35% — and 1 otherwise, so revenue
    per call reads as dollars."""
    return 100 if metric.unit == "percent" else 1


def components(
    db: DbSession, metric: MetricDefinition
) -> tuple[MetricDefinition, MetricDefinition]:
    """(numerator, denominator). Raises ValueError for a derived metric whose
    parts no longer exist, rather than quietly scoring zero."""
    numerator = db.get(MetricDefinition, metric.numerator_metric_id)
    denominator = db.get(MetricDefinition, metric.denominator_metric_id)
    if numerator is None or denominator is None:
        raise ValueError(f"{metric.name} is missing one of the metrics it is worked out from.")
    return numerator, denominator


def fact_metric_ids(db: DbSession, metric: MetricDefinition) -> list[int]:
    """The metrics whose facts stand behind this one — itself, or its parts.

    For the few places that ask about facts directly rather than scores: when
    somebody last added to their total, whether data is arriving at all.
    """
    if not is_derived(metric):
        return [metric.id]
    return [i for i in (metric.numerator_metric_id, metric.denominator_metric_id) if i]


def used_by(db: DbSession, metric: MetricDefinition) -> list[MetricDefinition]:
    """Derived metrics worked out from this one."""
    return list(
        db.scalars(
            select(MetricDefinition).where(
                MetricDefinition.organization_id == metric.organization_id,
                MetricDefinition.aggregation == RATIO,
                or_(
                    MetricDefinition.numerator_metric_id == metric.id,
                    MetricDefinition.denominator_metric_id == metric.id,
                ),
            )
        ).all()
    )
