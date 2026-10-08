"""drop viewer role

Revision ID: dbca172c95c7
Revises: 7c2b73532560
Create Date: 2026-08-13 19:30:10.139610
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'dbca172c95c7'
down_revision: str | None = '7c2b73532560'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Written by hand: Alembic's autogenerate does not compare CHECK
    # constraints, so it produced an empty migration for this change.

    # Any existing viewers become agents. Must run BEFORE the new constraint is
    # added, or the ALTER fails on rows the constraint would reject — and a
    # migration that works on an empty database but fails on a real one is the
    # worst kind.
    op.execute("UPDATE user_account SET org_role = 'agent' WHERE org_role = 'viewer'")

    op.drop_constraint(op.f("ck_user_account_org_role_valid"), "user_account", type_="check")
    op.create_check_constraint(
        "org_role_valid",
        "user_account",
        "org_role IN ('admin', 'manager', 'agent')",
    )


def downgrade() -> None:
    # Widening the constraint is safe — every existing value still satisfies
    # it. The viewers converted above are not recoverable, which is why this
    # direction is documented as "restore from backup" rather than trusted.
    op.drop_constraint(op.f("ck_user_account_org_role_valid"), "user_account", type_="check")
    op.create_check_constraint(
        "org_role_valid",
        "user_account",
        "org_role IN ('admin', 'manager', 'agent', 'viewer')",
    )
