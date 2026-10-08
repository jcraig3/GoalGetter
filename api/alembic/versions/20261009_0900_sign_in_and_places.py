"""Sign-in for admins and managers only; offices and teams from Microsoft 365
(Phase 28).

`organization.sign_in_leaders_only`; a person's own office while they have no
team (`user_account.office_id`); the Microsoft 365 office or department an
office or a team takes its people from.

Revision ID: e4a7c1d9b250
Revises: d2f6b3a9e470
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c1d9b250"
down_revision: str | None = "d2f6b3a9e470"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("sign_in_leaders_only", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("user_account", sa.Column("office_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_user_account_office_id_office", "user_account", "office", ["office_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_user_account_office_id", "user_account", ["office_id"])
    op.add_column("office", sa.Column("m365_office", sa.String(200), nullable=True))
    op.add_column("team", sa.Column("m365_department", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("team", "m365_department")
    op.drop_column("office", "m365_office")
    op.drop_index("ix_user_account_office_id", table_name="user_account")
    op.drop_constraint("fk_user_account_office_id_office", "user_account", type_="foreignkey")
    op.drop_column("user_account", "office_id")
    op.drop_column("organization", "sign_in_leaders_only")
