"""Posting to a picked Teams channel, as a signed-in account.

A destination is now reached either through its own Workflows link, as before,
or by Team and channel id through Microsoft Graph as the account signed in for
it on the Microsoft 365 connection. Existing destinations are all Workflows
links.

Revision ID: b8d2f41c7a93
Revises: a1c7e39f5d26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d2f41c7a93"
down_revision: str | None = "a1c7e39f5d26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oauth_client",
        sa.Column("teams_post_refresh_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "oauth_client",
        sa.Column("teams_post_connected_as", sa.String(length=320), server_default="", nullable=False),
    )
    op.add_column(
        "announcement_destination",
        sa.Column("via", sa.String(length=16), server_default="workflow", nullable=False),
    )
    op.add_column(
        "announcement_destination", sa.Column("team_external_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "announcement_destination", sa.Column("channel_external_id", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "announcement_destination", sa.Column("channel_label", sa.String(length=300), nullable=True)
    )
    op.alter_column("announcement_destination", "webhook_url", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "announcement_how_reached",
        "announcement_destination",
        "(via = 'workflow' AND webhook_url IS NOT NULL) OR "
        "(via = 'graph' AND team_external_id IS NOT NULL AND channel_external_id IS NOT NULL)",
    )


def downgrade() -> None:
    # A picked channel has no link to fall back to, so it cannot survive a
    # downgrade; it is removed rather than left breaking the NOT NULL.
    op.execute("DELETE FROM announcement_destination WHERE via = 'graph'")
    op.drop_constraint("announcement_how_reached", "announcement_destination", type_="check")
    op.alter_column("announcement_destination", "webhook_url", existing_type=sa.Text(), nullable=False)
    op.drop_column("announcement_destination", "channel_label")
    op.drop_column("announcement_destination", "channel_external_id")
    op.drop_column("announcement_destination", "team_external_id")
    op.drop_column("announcement_destination", "via")
    op.drop_column("oauth_client", "teams_post_connected_as")
    op.drop_column("oauth_client", "teams_post_refresh_token_encrypted")
