"""Somewhere to spend points: cosmetic unlocks and a prize wheel.

In the economy this product was measured against, lifetime points equalled
reward points because nothing was ever spent. A season reset keeps the ranking
catchable; it does not give the points a use. These do, without building a
store — no stock, no shipping, nobody in finance.

Spending never moves anybody on the table. That is a property of the ledger
rather than of these tables (see `points.WALLET_PREFIX`), and it is the whole
reason anybody will spend: a purchase that cost you your place is one nobody
makes.

Revision ID: a8b4d93f6c27
Revises: f7a3c82e5b16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b4d93f6c27"
down_revision: str | None = "f7a3c82e5b16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "unlockable",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("value", sa.String(length=40), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        *_stamps(),
        sa.CheckConstraint("kind IN ('ring', 'title')", name="unlockable_kind_valid"),
        sa.CheckConstraint("price > 0", name="unlockable_price_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_unlockable_name", "unlockable", ["organization_id", "name"], unique=True
    )

    op.create_table(
        "unlock",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("unlockable_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("equipped", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("paid", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('ring', 'title')", name="unlock_kind_valid"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unlockable_id"], ["unlockable.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_unlock_once", "unlock", ["unlockable_id", "user_id"], unique=True
    )
    # One of each kind worn at a time: two rings is a rendering question with
    # no good answer, and two titles is a sentence.
    op.create_index(
        "uq_unlock_worn",
        "unlock",
        ["user_id", "kind"],
        unique=True,
        postgresql_where=sa.text("equipped"),
    )

    op.create_table(
        "prize_wheel",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("spin_cost", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        *_stamps(),
        sa.CheckConstraint("spin_cost > 0", name="prize_wheel_cost_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_prize_wheel_org", "prize_wheel", ["organization_id"], unique=True
    )

    op.create_table(
        "wheel_prize",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("points", sa.Integer(), server_default="0", nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "kind IN ('points', 'prize', 'nothing')", name="wheel_prize_kind_valid"
        ),
        sa.CheckConstraint(
            "(kind = 'points' AND points > 0) OR (kind <> 'points' AND points = 0)",
            name="wheel_prize_points_match_kind",
        ),
        sa.CheckConstraint("weight > 0", name="wheel_prize_weight_positive"),
        sa.CheckConstraint(
            "stock IS NULL OR (kind = 'prize' AND stock >= 0)",
            name="wheel_prize_stock_only_for_prizes",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wheel_prize_org", "wheel_prize", ["organization_id"])

    op.create_table(
        "wheel_spin",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("prize_id", sa.BigInteger(), nullable=True),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("points_won", sa.Integer(), nullable=False),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("given_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prize_id"], ["wheel_prize.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["given_by_user_id"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wheel_spin_person", "wheel_spin", ["user_id", "id"])
    op.create_index(
        "ix_wheel_spin_waiting",
        "wheel_spin",
        ["organization_id", "id"],
        postgresql_where=sa.text("kind = 'prize' AND given_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_wheel_spin_waiting", table_name="wheel_spin")
    op.drop_index("ix_wheel_spin_person", table_name="wheel_spin")
    op.drop_table("wheel_spin")
    op.drop_index("ix_wheel_prize_org", table_name="wheel_prize")
    op.drop_table("wheel_prize")
    op.drop_index("uq_prize_wheel_org", table_name="prize_wheel")
    op.drop_table("prize_wheel")
    op.drop_index("uq_unlock_worn", table_name="unlock")
    op.drop_index("uq_unlock_once", table_name="unlock")
    op.drop_table("unlock")
    op.drop_index("uq_unlockable_name", table_name="unlockable")
    op.drop_table("unlockable")
