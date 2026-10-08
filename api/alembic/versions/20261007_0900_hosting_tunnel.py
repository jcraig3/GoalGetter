"""The Cloudflare tunnel set up from the app (Phase 21).

Revision ID: e6a1c8b4f925
Revises: d5f9b7a3e814
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6a1c8b4f925"
down_revision: str | None = "d5f9b7a3e814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosting_config", sa.Column("front_door", sa.String(16), nullable=False, server_default=""))
    op.add_column("hosting_config", sa.Column("tunnel_token_encrypted", sa.Text(), nullable=True))
    op.alter_column("hosting_config", "front_door", server_default=None)


def downgrade() -> None:
    op.drop_column("hosting_config", "tunnel_token_encrypted")
    op.drop_column("hosting_config", "front_door")
