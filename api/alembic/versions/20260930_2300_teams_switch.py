"""One switch for Microsoft Teams, on the Microsoft 365 connection.

`organization.announcements_enabled` paused posting only. Microsoft Teams is
now switched on and off as a whole — posting, and the scheduled reads that
keep teams in step with it — from the Microsoft 365 box, the way Excel is, and
configured in its own card. So the column becomes `teams_enabled`.

**Off unless it is already in use.** A new deployment has not asked for Teams;
one that already posts to a channel or links a Team has, so it stays on.

Revision ID: c3e9a7d15b40
Revises: b8d2f41c7a93
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e9a7d15b40"
down_revision: str | None = "b8d2f41c7a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("teams_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        """
        UPDATE organization SET teams_enabled = true
        WHERE announcements_enabled
          AND (
            EXISTS (SELECT 1 FROM announcement_destination d WHERE d.organization_id = organization.id)
            OR EXISTS (SELECT 1 FROM m365_link l WHERE l.organization_id = organization.id)
          )
        """
    )
    op.drop_column("organization", "announcements_enabled")


def downgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("announcements_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.execute(
        """
        UPDATE organization SET announcements_enabled = false
        WHERE NOT teams_enabled
          AND EXISTS (SELECT 1 FROM announcement_destination d WHERE d.organization_id = organization.id)
        """
    )
    op.drop_column("organization", "teams_enabled")
