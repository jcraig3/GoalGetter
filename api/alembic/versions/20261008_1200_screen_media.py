"""Picture and video screens that fill the TV (Phase 26).

A video screen's start, a picture screen's fit, and up to an hour on screen.

Revision ID: d2f6b3a9e470
Revises: c1e5a2f8d369
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f6b3a9e470"
down_revision: str | None = "c1e5a2f8d369"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("channel_screen", sa.Column("media_start_seconds", sa.Integer(), nullable=True))
    op.add_column("channel_screen", sa.Column("fit", sa.String(8), nullable=True))
    op.drop_constraint("dwell_sane", "channel_screen", type_="check")
    op.create_check_constraint("dwell_sane", "channel_screen", "dwell_seconds BETWEEN 5 AND 3600")


def downgrade() -> None:
    op.execute("UPDATE channel_screen SET dwell_seconds = 300 WHERE dwell_seconds > 300")
    op.drop_constraint("dwell_sane", "channel_screen", type_="check")
    op.create_check_constraint("dwell_sane", "channel_screen", "dwell_seconds BETWEEN 5 AND 300")
    op.drop_column("channel_screen", "fit")
    op.drop_column("channel_screen", "media_start_seconds")
