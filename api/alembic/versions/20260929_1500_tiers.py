"""The ladder: reach this many points in a season and you are Gold.

Measured against the season balance, never the lifetime total — which is why
this table could not exist until seasons did. A top tier at 100,000 points in
front of a floor whose leaders sit at 178,000 is not a ladder, it is a label
everybody already has.

Two rungs at one height is not a ladder either, so the threshold is unique per
organization; and a rung at zero is held by everybody who has never scored, so
it is a CHECK.

Revision ID: e6f2a91d7c34
Revises: d4c7b1e9a802
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f2a91d7c34"
down_revision: str | None = "d4c7b1e9a802"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tier",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("threshold > 0", name="tier_threshold_positive"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_tier_threshold", "tier", ["organization_id", "threshold"], unique=True
    )
    op.create_index("uq_tier_name", "tier", ["organization_id", "name"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_tier_name", table_name="tier")
    op.drop_index("uq_tier_threshold", table_name="tier")
    op.drop_table("tier")
