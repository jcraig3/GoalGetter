"""The points economy: a ledger, priced per event, inside a season.

Three tables, and the reasoning for each is in the models. The short version:

`season` — the one that cannot be added later. Points that only accumulate
produce a scoreboard where the top cannot be caught and the bottom cannot
catch up, and both stop looking; retrofitting a reset then means either wiping
balances people earned or keeping the lifetime total that caused it. Seasons
never overlap, and that is an EXCLUDE constraint rather than a service check,
because "which season is this award in?" must have exactly one answer.

`point_award` — one row per award. Never a running total on the person: that
is one number incremented from four code paths, wrong the first time two race,
with nothing to compare it against. A balance is a sum, so a corrected row
corrects the balance.

`point_value` — what each event is worth here. A table rather than a column
per event, because the catalogue grows and a migration to make competitions
outweigh birthdays is a migration nobody will write.

Revision ID: d4c7b1e9a802
Revises: c1a8f34b7e25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4c7b1e9a802"
down_revision: str | None = "c1a8f34b7e25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Needed for the EXCLUDE below: GiST cannot index the `organization_id =`
    # part of the constraint without it. Shipped with Postgres as a standard
    # contrib module, so this installs rather than requires anything new.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "season",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_season_org_dates", "season", ["organization_id", "starts_on", "ends_on"]
    )
    # Inclusive at both ends — a season runs *through* its last day, and a
    # half-open range would drop everything earned on the final afternoon.
    op.execute(
        "ALTER TABLE season ADD CONSTRAINT seasons_do_not_overlap "
        "EXCLUDE USING gist ("
        "  organization_id WITH =,"
        "  daterange(starts_on, ends_on, '[]') WITH &&"
        ")"
    )

    op.create_table(
        "point_award",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("season_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("period_anchor", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("awarded_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("points <> 0", name="points_not_zero"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["season.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["awarded_by_user_id"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_point_award_balance", "point_award", ["season_id", "user_id"]
    )
    op.create_index(
        "ix_point_award_statement",
        "point_award",
        ["organization_id", "user_id", "id"],
    )
    # The idempotency guarantee, copied from `notification`. NULLS NOT
    # DISTINCT is load-bearing: without it every award with no period would
    # insert again on every job cycle, forever. Partial, because a
    # hand-written award must be repeatable.
    op.create_index(
        "uq_point_award_once",
        "point_award",
        [
            "organization_id",
            "user_id",
            "event_key",
            "subject_type",
            "subject_id",
            "period_anchor",
        ],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("awarded_by_user_id IS NULL"),
    )

    op.create_table(
        "point_value",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("points >= 0", name="point_value_not_negative"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_point_value_event",
        "point_value",
        ["organization_id", "event_key"],
        unique=True,
    )

    # What an achievement rule pays. On the rule rather than in `point_value`
    # because it is an attribute of that rule, edited where the rule is
    # edited — the same place its message and its media live.
    op.add_column(
        "achievement_rule",
        sa.Column("points", sa.Integer(), nullable=False, server_default="10"),
    )


def downgrade() -> None:
    op.drop_column("achievement_rule", "points")
    op.drop_index("uq_point_value_event", table_name="point_value")
    op.drop_table("point_value")
    op.drop_index("uq_point_award_once", table_name="point_award")
    op.drop_index("ix_point_award_statement", table_name="point_award")
    op.drop_index("ix_point_award_balance", table_name="point_award")
    op.drop_table("point_award")
    op.execute("ALTER TABLE season DROP CONSTRAINT seasons_do_not_overlap")
    op.drop_index("ix_season_org_dates", table_name="season")
    op.drop_table("season")
    # The extension is left installed. Dropping it would fail if anything else
    # in the deployment had started using it, and an unused contrib module
    # costs nothing.
