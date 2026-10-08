"""Badges: something you are, rather than something you have.

The distinction from a tier is the whole design. A tier is a current state read
from this season's balance, and you can lose it by having a quiet month — that
is what makes the top one worth wearing. A badge is a thing that happened and
stays happened: ten big deals in March is still true in December, because March
does not change. So a tier is derived and a badge is stored, and each is stored
the way it is for the opposite reason.

Revision ID: f7a3c82e5b16
Revises: e6f2a91d7c34
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a3c82e5b16"
down_revision: str | None = "e6f2a91d7c34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "badge",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=200), server_default="", nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("achievement_rule_id", sa.BigInteger(), nullable=True),
        sa.Column("threshold", sa.Integer(), nullable=True),
        # Not `window`, which is reserved in Postgres and would need quoting in
        # every CHECK that mentions it.
        sa.Column("counted_over", sa.String(length=16), nullable=True),
        sa.Column("icon", sa.String(length=32), server_default="medal", nullable=False),
        sa.Column("points", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('manual', 'count')", name="badge_kind_valid"),
        sa.CheckConstraint(
            "counted_over IS NULL OR counted_over IN ('week', 'month', 'season')",
            name="badge_counted_over_valid",
        ),
        # A counted badge needs something to count and a number to reach; a
        # manual one must have neither, or the columns silently mean nothing.
        sa.CheckConstraint(
            "(kind = 'count' AND achievement_rule_id IS NOT NULL "
            "AND threshold IS NOT NULL AND counted_over IS NOT NULL) OR "
            "(kind = 'manual' AND achievement_rule_id IS NULL "
            "AND threshold IS NULL AND counted_over IS NULL)",
            name="badge_kind_matches_fields",
        ),
        sa.CheckConstraint(
            "threshold IS NULL OR threshold > 0", name="badge_threshold_positive"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["achievement_rule_id"], ["achievement_rule.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_badge_name", "badge", ["organization_id", "name"], unique=True)

    op.create_table(
        "badge_award",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("badge_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("period_anchor", sa.Date(), nullable=True),
        sa.Column("reason", sa.String(length=200), server_default="", nullable=False),
        sa.Column("awarded_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["badge_id"], ["badge.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["awarded_by_user_id"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    # The same latch as `notification` and `point_award`. Keyed on the window's
    # anchor, so "ten in March" and "ten in April" are two badges and a re-run
    # of either is none. Partial, because a manager pinning one on somebody
    # twice meant to.
    op.create_index(
        "uq_badge_award_once",
        "badge_award",
        ["badge_id", "user_id", "period_anchor"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("awarded_by_user_id IS NULL"),
    )
    op.create_index("ix_badge_award_person", "badge_award", ["user_id", "id"])
    op.create_index("ix_badge_award_org", "badge_award", ["organization_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_badge_award_org", table_name="badge_award")
    op.drop_index("ix_badge_award_person", table_name="badge_award")
    op.drop_index("uq_badge_award_once", table_name="badge_award")
    op.drop_table("badge_award")
    op.drop_index("uq_badge_name", table_name="badge")
    op.drop_table("badge")
