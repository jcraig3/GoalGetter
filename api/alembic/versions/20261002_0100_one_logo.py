"""One logo: the separate "logo for dark backgrounds" is gone.

A dark-background logo is moved into the one logo where no other was set, so
nobody's mark disappears; everywhere else it is simply removed. Every stored
appearance is cleaned — the organization's and each item's — so no screen
keeps drawing a logo that nothing can change any more.

Revision ID: c3a7e9d2f560
Revises: b6d1f8e2a407
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a7e9d2f560"
down_revision: str | None = "b6d1f8e2a407"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("organization", "leaderboard", "goal", "competition", "channel", "channel_screen")


def upgrade() -> None:
    for table in TABLES:
        # Kept where it was the only logo: that mark was somebody's choice.
        op.execute(
            f"""
            UPDATE {table}
            SET appearance = jsonb_set(appearance, '{{logo}}', appearance->'logo_dark')
            WHERE appearance ? 'logo_dark'
              AND jsonb_typeof(appearance->'logo_dark') = 'string'
              AND (NOT appearance ? 'logo' OR jsonb_typeof(appearance->'logo') <> 'string')
            """
        )
        op.execute(
            f"UPDATE {table} SET appearance = appearance - 'logo_dark' "
            f"WHERE appearance ? 'logo_dark'"
        )


def downgrade() -> None:
    # Nothing to put back: the field is optional, and an absent one is how
    # every organization that never set it already looked.
    pass
