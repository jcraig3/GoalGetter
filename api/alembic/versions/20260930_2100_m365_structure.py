"""The Microsoft Teams structure, by id — Teams, channels, and who is in them.

Replaces the name-based `team.mirrors_group` from the step before. Kept by name
it broke on a rename and could not see channels at all; kept by Microsoft's own
ids it survives a rename and can map a private channel as well as a Team — to a
GoalGetter team or to an office.

`mirror_placement` is where the mirror last put each person, which is how it
tells its own work from a hand move and leaves the hand move alone.

Any Teams linked by name in the step before need linking again, once.

Revision ID: a1c7e39f5d26
Revises: f4a0c57e8b12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7e39f5d26"
down_revision: str | None = "f4a0c57e8b12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "m365_source",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("membership", sa.String(length=16), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gone_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('team', 'channel')", name="m365_source_kind_valid"),
        sa.CheckConstraint(
            "membership IS NULL OR membership IN ('standard', 'private', 'shared')",
            name="m365_source_membership_valid",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["m365_source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_m365_source", "m365_source", ["organization_id", "kind", "external_id"], unique=True)
    op.create_index("ix_m365_source_parent", "m365_source", ["parent_id"])

    op.create_table(
        "m365_member",
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("person_external_id", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["m365_source.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "person_external_id"),
    )

    op.create_table(
        "m365_link",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("office_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("target IN ('team', 'office')", name="m365_link_target_valid"),
        sa.CheckConstraint(
            "(target = 'team' AND team_id IS NOT NULL AND office_id IS NULL) OR "
            "(target = 'office' AND office_id IS NOT NULL AND team_id IS NULL)",
            name="m365_link_one_target",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["m365_source.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["office_id"], ["office.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_m365_link_source", "m365_link", ["source_id"], unique=True)
    op.create_index("uq_m365_link_team", "m365_link", ["team_id"], unique=True,
                    postgresql_where=sa.text("team_id IS NOT NULL"))
    op.create_index("uq_m365_link_office", "m365_link", ["office_id"], unique=True,
                    postgresql_where=sa.text("office_id IS NOT NULL"))

    op.create_table(
        "mirror_placement",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # When the structure was last read, and what could not be — so the panel
    # can say "grant Channel.ReadBasic.All" rather than show an empty list.
    op.add_column("oauth_client", sa.Column("teams_read_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_client", sa.Column("teams_read_note", sa.String(length=1000), nullable=True))

    # The name-based link it replaces.
    op.drop_index("uq_team_mirrors_group", table_name="team")
    op.drop_column("team", "mirrors_group")


def downgrade() -> None:
    op.add_column("team", sa.Column("mirrors_group", sa.String(length=200), nullable=True))
    op.create_index(
        "uq_team_mirrors_group", "team", ["organization_id", sa.text("lower(mirrors_group)")],
        unique=True, postgresql_where=sa.text("mirrors_group IS NOT NULL"),
    )
    op.drop_column("oauth_client", "teams_read_note")
    op.drop_column("oauth_client", "teams_read_at")
    op.drop_table("mirror_placement")
    op.drop_index("uq_m365_link_office", table_name="m365_link")
    op.drop_index("uq_m365_link_team", table_name="m365_link")
    op.drop_index("uq_m365_link_source", table_name="m365_link")
    op.drop_table("m365_link")
    op.drop_table("m365_member")
    op.drop_index("ix_m365_source_parent", table_name="m365_source")
    op.drop_index("uq_m365_source", table_name="m365_source")
    op.drop_table("m365_source")
