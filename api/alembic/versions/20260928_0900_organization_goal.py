"""A goal the whole company pulls toward.

**The one shape a goal could not express.** A target belonged to one person or
one team, so "half a million this quarter, all of us" had to be faked as a team
goal for a team that did not exist, or drawn by hand on a message screen and
updated by somebody every morning.

The subject columns stay null, which is the honest encoding: an organization
goal is not about a row in another table, it is about everyone. The CHECK is
widened to say so rather than a sentinel id being invented for it.

Revision ID: c4b81f27ea60
Revises: b7e04f5c1a93
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4b81f27ea60"
down_revision: str | None = "b7e04f5c1a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUBJECT_BEFORE = (
    "(subject_type = 'user' AND subject_user_id IS NOT NULL "
    "AND subject_team_id IS NULL) OR "
    "(subject_type = 'team' AND subject_team_id IS NOT NULL "
    "AND subject_user_id IS NULL)"
)
SUBJECT_AFTER = SUBJECT_BEFORE + (
    " OR (subject_type = 'organization' AND subject_user_id IS NULL "
    "AND subject_team_id IS NULL)"
)


def upgrade() -> None:
    # VARCHAR(8) held "user" and "team" with room to spare and rejects
    # "organization" outright. Widened first, or every insert below fails on a
    # length nobody thought to look at.
    op.alter_column(
        "goal",
        "subject_type",
        existing_type=sa.String(8),
        type_=sa.String(16),
        existing_nullable=False,
    )
    op.drop_constraint("subject_matches_type", "goal", type_="check")
    op.create_check_constraint("subject_matches_type", "goal", SUBJECT_AFTER)
    op.drop_constraint("subject_type_valid", "goal", type_="check")
    op.create_check_constraint(
        "subject_type_valid", "goal", "subject_type IN ('user', 'team', 'organization')"
    )


def downgrade() -> None:
    # The rows go first, or narrowing the CHECK fails halfway and leaves it
    # dropped. Their screens go with them by cascade.
    op.execute("DELETE FROM goal WHERE subject_type = 'organization'")
    op.drop_constraint("subject_type_valid", "goal", type_="check")
    op.create_check_constraint(
        "subject_type_valid", "goal", "subject_type IN ('user', 'team')"
    )
    op.drop_constraint("subject_matches_type", "goal", type_="check")
    op.create_check_constraint("subject_matches_type", "goal", SUBJECT_BEFORE)
    op.alter_column(
        "goal",
        "subject_type",
        existing_type=sa.String(16),
        type_=sa.String(8),
        existing_nullable=False,
    )
