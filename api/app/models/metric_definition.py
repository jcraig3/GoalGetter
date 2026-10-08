from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Kept here rather than in the router so the API and the database CHECK
# constraints can never disagree about what a valid value is.

UNITS = ("count", "currency", "percent", "duration")

#: `ratio` is a derived metric: one metric divided by another, with no facts
#: of its own. See `app/derived.py`.
AGGREGATIONS = ("sum", "count", "avg", "max", "min", "last", "ratio")

DIRECTIONS = ("higher_is_better", "lower_is_better")


class MetricDefinition(Base, TimestampMixin):
    """What a company decided to measure.

    A definition is configuration; a `metric_fact` is one measurable event; a
    score is facts aggregated over a scope and a window. Nothing stores a
    running total — see documentation/06-metrics-engine.md.
    """

    __tablename__ = "metric_definition"
    __table_args__ = (
        # Connectors and imports address metrics by key, so it has to be
        # unique within an organization — otherwise "calls_made" is ambiguous
        # at exactly the moment data arrives.
        # Spelled out in full, unlike the CHECKs below. Base's naming
        # convention for "uq" is `uq_%(table_name)s_%(column_0_name)s` — it
        # never interpolates the given name, so an explicit one is used
        # verbatim. A bare "org_key" would become a schema-global index by that
        # name, and index names must be unique across the whole database.
        UniqueConstraint("organization_id", "key", name="uq_metric_definition_org_key"),
        # **One name per metric in use, ignoring case.** The key was unique and
        # the name — what every picker shows — was not, so two "Closed Deals"
        # made goals, rules and boards ambiguous (QA-9).
        Index(
            "uq_metric_definition_org_name_lower",
            "organization_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint(
            "unit IN ('count', 'currency', 'percent', 'duration')",
            name="unit_valid",
        ),
        CheckConstraint(
            "aggregation IN ('sum', 'count', 'avg', 'max', 'min', 'last', 'ratio')",
            name="aggregation_valid",
        ),
        # A ratio names both its parts, and nothing else names any.
        CheckConstraint(
            "(aggregation = 'ratio') = "
            "(numerator_metric_id IS NOT NULL AND denominator_metric_id IS NOT NULL)",
            name="ratio_parts",
        ),
        CheckConstraint(
            "direction IN ('higher_is_better', 'lower_is_better')",
            name="direction_valid",
        ),
        CheckConstraint(
            "decimal_places BETWEEN 0 AND 4",
            name="decimal_places_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )

    # Stable machine identifier. Immutable after creation: connectors, saved
    # import mappings, and goals all reference it, and renaming it would break
    # every one of them silently. `name` is the editable label.
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(String(500))

    unit: Mapped[str] = mapped_column(String(16), default="count")
    #: What a count is a count of, as the plural: "deals". Optional, and read
    #: only for counts. See `app/units.py`.
    unit_label: Mapped[str | None] = mapped_column(String(32))
    aggregation: Mapped[str] = mapped_column(String(16), default="sum")

    # Not cosmetic. "Calls Made" ranks descending; "Average Response Time" ranks
    # ascending. Every ranking and goal-progress calculation reads this, and
    # assuming bigger-is-better anywhere produces a leaderboard that celebrates
    # the worst performer.
    direction: Mapped[str] = mapped_column(String(20), default="higher_is_better")

    decimal_places: Mapped[int] = mapped_column(Integer, default=0)

    #: For a `ratio`: what is divided, and by what. No cascade — a metric a
    #: derived one is built from cannot be deleted out from under it.
    numerator_metric_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id")
    )
    denominator_metric_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id")
    )

    # Archive, not delete: facts reference the definition, and a leaderboard for
    # last quarter must still be able to name the metric it ranked.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<MetricDefinition {self.key} agg={self.aggregation}>"
