"""Custom roles: a built-in role with capabilities taken away.

Revision ID: d8a3b6f1e592
Revises: c7f2a9e4b183
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8a3b6f1e592"
down_revision: str | None = "c7f2a9e4b183"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_role",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("base_role", sa.String(length=20), nullable=False),
        sa.Column("removed", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("base_role IN ('agent', 'manager', 'admin')", name="base_role_valid"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_custom_role_org_name", "custom_role", ["organization_id", "name"], unique=True)
    op.add_column("user_account", sa.Column("custom_role_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "user_account_custom_role_fkey", "user_account", "custom_role",
        ["custom_role_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("user_account_custom_role_fkey", "user_account", type_="foreignkey")
    op.drop_column("user_account", "custom_role_id")
    op.drop_index("uq_custom_role_org_name", table_name="custom_role")
    op.drop_table("custom_role")
