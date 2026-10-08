"""Preview on a TV: an unsaved slide or celebration, on one screen, briefly.

**One television, not a channel**, and gone after its hold. The "send a test
to the wall" button removed in 4f interrupted every screen in the building and
would not go away.

Revision ID: d7a2e5c94f18
Revises: c5e1a8f3d720
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d7a2e5c94f18"
down_revision: str | None = "c5e1a8f3d720"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "display_preview",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger(),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "display_id",
            sa.BigInteger(),
            sa.ForeignKey("display.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hold_seconds", sa.Integer(), nullable=False),
        # Stored already built, by the code the wall uses. Exactly one.
        sa.Column("slide", JSONB(), nullable=True),
        sa.Column("celebration", JSONB(), nullable=True),
        sa.CheckConstraint(
            "(slide IS NULL) <> (celebration IS NULL)",
            name=op.f("ck_display_preview_one_thing"),
        ),
    )
    # Every read is "what should this screen show now".
    op.create_index(
        "ix_display_preview_display", "display_preview", ["display_id", "starts_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_display_preview_display", table_name="display_preview")
    op.drop_table("display_preview")
