"""Mirror Microsoft Teams as GoalGetter teams.

`team.mirrors_group` names the Microsoft 365 group — every Microsoft Team is
one — whose members belong in the team. Kept by name, because that is what
directory sync already stores for each person; one GoalGetter team per group.

`oauth_client.directory_mirror_teams` is whether each directory sync applies
the mirror by itself, or leaves it for an admin to preview and apply.

Revision ID: e2f9b36d4a71
Revises: d8e1a27c6f50
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f9b36d4a71"
down_revision: str | None = "d8e1a27c6f50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("team", sa.Column("mirrors_group", sa.String(length=200), nullable=True))
    op.create_index(
        "uq_team_mirrors_group",
        "team",
        ["organization_id", sa.text("lower(mirrors_group)")],
        unique=True,
        postgresql_where=sa.text("mirrors_group IS NOT NULL"),
    )
    op.add_column(
        "oauth_client",
        sa.Column("directory_mirror_teams", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("oauth_client", "directory_mirror_teams")
    op.drop_index("uq_team_mirrors_group", table_name="team")
    op.drop_column("team", "mirrors_group")
