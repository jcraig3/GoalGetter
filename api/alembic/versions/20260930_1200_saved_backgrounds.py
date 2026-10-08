"""The background library: backgrounds kept to be used again.

Before this, reusing a background meant uploading it again — each upload went
straight onto one screen and nothing remembered it. A library entry is a
starting point rather than a reference: choosing one copies it onto a screen,
so editing or deleting an entry changes no wall already using it.

Revision ID: b9c5e04a7d38
Revises: a8b4d93f6c27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9c5e04a7d38"
down_revision: str | None = "a8b4d93f6c27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_background",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("background", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category IN ('calm', 'energy', 'celebration', 'seasonal', 'brand')",
            name="saved_background_category_valid",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_saved_background_name",
        "saved_background",
        ["organization_id", "name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_saved_background_name", table_name="saved_background")
    op.drop_table("saved_background")
