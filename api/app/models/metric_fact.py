from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Where a fact came from. Not an ordering — `manual` is visibly marked in the UI
# wherever it appears, because a hand-entered number in a leaderboard has to be
# distinguishable from a synced one.
#
# **`import` no longer has a feature behind it.** CSV/Excel upload was dropped
# during Phase 3 — a spreadsheet somebody maintains by hand is a second source of
# truth that quietly disagrees with the first — and a live Sheets or Excel connector
# replaced it, writing `connector` like everything else.
#
# The value is kept rather than removed for two reasons: a Phase 1 deployment may
# hold real CSV-imported rows, and dropping it from the check constraint would make
# those rows unwritable and the table un-migratable. The **demo seeder** also still
# writes it, which is the one active caller and is arguably mislabelling itself — see
# `seed_demo.py`. Renaming that to `seed` is a small migration nobody has needed yet.
SOURCE_TYPES = ("manual", "import", "connector")

#: The shape of a stored measurement. Named because two things need it: the column
#: below, and the sync preview.
#:
#: A preview promising "this is what you will get" while showing more decimal
#: places than the column can hold is a preview that quietly lies — and the whole
#: reason it exists is to be believed.
VALUE_PRECISION = 18
VALUE_SCALE = 4


class MetricFact(Base):
    """One measurable event.

    `metric_fact` is the only truth. There is no `current_total` column
    anywhere — every score, rank, and goal progress figure is a query over this
    table. See documentation/06-metrics-engine.md for why:

        late-arriving data   a connector syncing yesterday's deals today would
                             make a stored total wrong the moment it landed
        corrections          deleting a mistaken row has to reduce the total
        arbitrary windows    "since the competition started" is not a column
    """

    __tablename__ = "metric_fact"
    __table_args__ = (
        # The leaderboard query, in index order: one organization, one metric,
        # a time window, grouped by person.
        #
        # `value` is INCLUDEd rather than indexed. It is not something anyone
        # filters or sorts by, but the aggregation needs it — and without it
        # every matching row costs a random heap fetch. Measured at 4M rows:
        # **7,423ms without it, 12ms with it**, a 600x difference on the query
        # this product is judged by.
        #
        # An earlier version of this comment claimed the index already covered
        # everything the query touched. It did not; `value` was missing, and
        # the claim went unchallenged until somebody measured.
        #
        # The Index Only Scan also depends on the visibility map being current,
        # which autovacuum maintains. On a freshly bulk-loaded table it is not,
        # and the same query took 2,115ms until VACUUM ran.
        Index(
            "ix_metric_fact_leaderboard",
            "organization_id",
            "metric_definition_id",
            "occurred_at",
            "subject_user_id",
            postgresql_include=["value"],
        ),
        # The other access pattern: ONE subject, across a window — a sparkline
        # rather than a board. The leaderboard index above leads with time, so
        # a year-long chart for one person would scan every fact in the year
        # for that metric and discard all but theirs.
        #
        # These three are deliberately plain rather than covering. A covering
        # team index measured 18ms against this one's 31ms on a year-long
        # chart, for nearly double the size — not a trade worth making on the
        # busiest table here, for the rarest chart in the product.
        #
        # "My history" and an agent's own dashboard: one person, over time.
        Index("ix_metric_fact_subject_time", "subject_user_id", "occurred_at"),
        # Office boards, which filter or group on this.
        Index("ix_metric_fact_office_time", "subject_office_id", "occurred_at"),
        # Team goals and team-board sparklines. Added last, because nothing
        # asked for a single team's line until sparklines did: measured at 4M
        # facts, a year-long team chart went from 1,677ms to 31ms.
        Index("ix_metric_fact_team_time", "subject_team_id", "occurred_at"),
        # Makes re-syncing idempotent: a connector replaying the same rows
        # updates instead of duplicating. PARTIAL, because manual entries have
        # no external id and several of them being NULL must not collide —
        # in Postgres NULLs don't collide in a unique index anyway, but the
        # partial index is also much smaller.
        # What makes a sync idempotent: re-reading yesterday's deals writes
        # nothing new, because the source's own row ids are already here.
        #
        # `data_source_id` is in the key, and has to be. Two connectors can
        # legitimately issue the same id — a Salesforce opportunity and a
        # spreadsheet row are both plausibly "1042" — and without the source in
        # the key the second connector's rows would silently collide with the
        # first's, updating them instead of adding their own.
        #
        # `metric_definition_id` stays in it because one source row can feed
        # several metrics: a closed deal is both a "deals won" count and a
        # "revenue" amount, which are two facts sharing one external id.
        Index(
            "uq_metric_fact_external",
            "organization_id",
            "data_source_id",
            "metric_definition_id",
            "external_id",
            unique=True,
            postgresql_where=(
                # Text form because the column object isn't bound yet here.
                "external_id IS NOT NULL"
            ),
            # Manual and corrected rows carry no source, and NULLs do not
            # collide by default — which would let one hand-entered row per
            # metric escape the constraint. Here it is moot (they have no
            # external id either, so the partial index excludes them) but the
            # flag states the intent rather than relying on that coincidence.
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "source_type IN ('manual', 'import', 'connector')",
            name="source_type_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    metric_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id")
    )

    subject_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id")
    )

    # The team the person was on WHEN THE EVENT HAPPENED, copied at write time.
    #
    # Joining to user_account.team_id at read time instead would rewrite
    # history: move someone from SMB to Enterprise and last quarter's team
    # leaderboard silently changes, because their past deals follow them. The
    # snapshot is what makes "who won Q1" answerable a year later.
    #
    # Nullable, because a fact can legitimately be recorded for someone not yet
    # on a team.
    subject_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id")
    )

    # The office that team belonged to at the time, for exactly the same reason
    # — and it is a second snapshot rather than a join through `team.office_id`
    # because that column is *current* state.
    #
    # Teams move between offices during a restructure. Deriving office at query
    # time would hand every historical fact to the new office the moment one
    # did, so "which office won Q1" would answer differently after a
    # reorganisation that happened in Q3. Measured on the dev data: one office
    # holds 2,649 facts through two teams, all of which would have moved.
    #
    # Nullable, because a team need not belong to an office and a person need
    # not belong to a team.
    subject_office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id")
    )

    # NUMERIC, never a float. Binary floating point cannot represent 0.1
    # exactly, so summing a column of currency drifts — and a revenue
    # leaderboard that is off by cents is a leaderboard nobody trusts.
    # 18,4 holds trillions with four decimal places, enough for currency,
    # percentages, and durations in seconds.
    value: Mapped[Decimal] = mapped_column(Numeric(VALUE_PRECISION, VALUE_SCALE))

    # When it happened in the real world, NOT when it was imported. All time
    # bucketing uses this. Using the import time instead would drop a
    # backfilled month of history into today.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    source_type: Mapped[str] = mapped_column(String(16))

    #: Which connected source wrote this, for a `connector` row.
    #:
    #: NULL for anything a person typed. RESTRICT rather than CASCADE or SET
    #: NULL: deleting a source must not delete the numbers it collected — those
    #: are real measurements that leaderboards and settled competitions were
    #: computed from — and nulling the column would break the idempotency key, so
    #: re-connecting the same source would import everything a second time.
    #: A source that has written facts is disabled, not deleted, the same as a
    #: metric that has been measured.
    data_source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("data_source.id", ondelete="RESTRICT")
    )
    # The source system's own identifier. Present for imports and connectors,
    # absent for manual entry.
    external_id: Mapped[str | None] = mapped_column(String(255))

    # Who typed it, for manual entries. SET NULL so removing an account never
    # deletes the numbers they corrected.
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )
    # server_default, so a bulk insert, a seed script, or a fix in psql all get
    # a timestamp without going through the ORM.
    #
    # No `updated_at`, unlike every other table: this one holds millions of
    # rows, facts are corrected rarely, and the audit log already records who
    # changed what. A second timestamp per row is 8 bytes × millions to answer
    # a question something else answers better.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Set when a person edits a row by hand. NULL means untouched.
    #
    # A column rather than something derived from the audit log, for one
    # reason: the connector sync (phase 3) has to ask "did a human change this
    # row?" for every row it is about to overwrite, and answering that by
    # scanning JSONB details in `audit_log` would be both slow and fragile.
    #
    # It also cannot be added retroactively. A correction made before this
    # column existed is indistinguishable afterwards, so the flag has to be in
    # place from the first correction — which is why it lands with the
    # correction tool rather than with the connectors that will read it.
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corrected_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return (
            f"<MetricFact metric={self.metric_definition_id} "
            f"user={self.subject_user_id} value={self.value}>"
        )
