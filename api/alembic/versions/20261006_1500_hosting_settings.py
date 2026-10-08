"""Hosting settings an admin can change in the app (Phase 17).

Whether a proxy of the organization's own stands in front, and the two
sign-in limits. All nullable: null means the shipped default (`.env` for the
proxy, 5 and 20 for the limits).

Revision ID: c4e8a6f2d793
Revises: b3d7f5e1c682
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a6f2d793"
down_revision: str | None = "b3d7f5e1c682"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("proxy_mode", sa.String(16), nullable=True))
    op.add_column("organization", sa.Column("sign_in_limit_account", sa.SmallInteger(), nullable=True))
    op.add_column("organization", sa.Column("sign_in_limit_device", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("organization", "sign_in_limit_device")
    op.drop_column("organization", "sign_in_limit_account")
    op.drop_column("organization", "proxy_mode")
