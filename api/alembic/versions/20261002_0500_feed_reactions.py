"""Reactions and comments on the recognition feed (6.15).

Revision ID: a2c8e4f6b913
Revises: f1b7d3e9a246
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c8e4f6b913"
down_revision: str | None = "f1b7d3e9a246"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feed_reaction",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("feed_key", sa.String(160), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reaction", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE",
                                name=op.f("fk_feed_reaction_organization_id_organization")),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE",
                                name=op.f("fk_feed_reaction_user_id_user_account")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_reaction")),
        sa.UniqueConstraint("organization_id", "feed_key", "user_id", "reaction",
                            name="uq_feed_reaction_one_each"),
        sa.CheckConstraint("reaction IN ('clap', 'fire', 'party', 'muscle', 'heart')",
                           name=op.f("ck_feed_reaction_reaction_valid")),
    )
    op.create_index("ix_feed_reaction_entry", "feed_reaction", ["organization_id", "feed_key"])

    op.create_table(
        "feed_comment",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("feed_key", sa.String(160), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE",
                                name=op.f("fk_feed_comment_organization_id_organization")),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE",
                                name=op.f("fk_feed_comment_user_id_user_account")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feed_comment")),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 300", name=op.f("ck_feed_comment_body_sane")),
    )
    op.create_index("ix_feed_comment_entry", "feed_comment", ["organization_id", "feed_key", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feed_comment_entry", table_name="feed_comment")
    op.drop_table("feed_comment")
    op.drop_index("ix_feed_reaction_entry", table_name="feed_reaction")
    op.drop_table("feed_reaction")
