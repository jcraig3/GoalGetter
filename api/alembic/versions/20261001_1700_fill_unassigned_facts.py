"""Facts recorded before their subject had a team take the team they are on.

The same rule `app.attribution` applies from now on, run once over what is
already stored: a blank team snapshot becomes the subject's current team (and
its office), and a blank office snapshot on a team that now has an office
becomes that office. Snapshots that name a team or office are never touched.

Revision ID: a7d3e9c2b461
Revises: e4c9d2a7f158
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7d3e9c2b461"
down_revision: str | None = "e4c9d2a7f158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE metric_fact AS f
        SET subject_team_id = u.team_id,
            subject_office_id = t.office_id
        FROM user_account AS u
        JOIN team AS t ON t.id = u.team_id
        WHERE f.subject_user_id = u.id
          AND f.subject_team_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE metric_fact AS f
        SET subject_office_id = t.office_id
        FROM team AS t
        WHERE f.subject_team_id = t.id
          AND f.subject_office_id IS NULL
          AND t.office_id IS NOT NULL
        """
    )


def downgrade() -> None:
    # Nothing to undo that can be told apart: after the upgrade, a filled-in
    # snapshot looks exactly like one written at the time. And undoing it would
    # only put back the empty team boards this fixed.
    pass
