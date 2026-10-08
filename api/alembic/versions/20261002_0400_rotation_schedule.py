"""Rotation scheduling and night mode (6.10).

A slide gains the days and hours it plays and how often it comes round; a
channel gains a night mode — a drifting clock or a dark screen out of hours.

Revision ID: f1b7d3e9a246
Revises: e5a9c1f7b382
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "f1b7d3e9a246"
down_revision: str | None = "e5a9c1f7b382"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("channel_screen", sa.Column("days", ARRAY(sa.Integer()), nullable=True))
    op.add_column("channel_screen", sa.Column("play_from", sa.Time(), nullable=True))
    op.add_column("channel_screen", sa.Column("play_until", sa.Time(), nullable=True))
    op.add_column(
        "channel_screen",
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        op.f("ck_channel_screen_weight_sane"), "channel_screen", "weight BETWEEN 1 AND 4"
    )

    op.add_column(
        "channel",
        sa.Column("quiet_mode", sa.String(8), nullable=False, server_default="off"),
    )
    op.add_column("channel", sa.Column("quiet_from", sa.Time(), nullable=True))
    op.add_column("channel", sa.Column("quiet_until", sa.Time(), nullable=True))
    op.add_column(
        "channel",
        sa.Column("quiet_weekends", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_check_constraint(
        op.f("ck_channel_quiet_mode_valid"),
        "channel",
        "quiet_mode IN ('off', 'clock', 'dark')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_channel_quiet_mode_valid"), "channel", type_="check")
    for column in ("quiet_weekends", "quiet_until", "quiet_from", "quiet_mode"):
        op.drop_column("channel", column)
    op.drop_constraint(op.f("ck_channel_screen_weight_sane"), "channel_screen", type_="check")
    for column in ("weight", "play_until", "play_from", "days"):
        op.drop_column("channel_screen", column)
