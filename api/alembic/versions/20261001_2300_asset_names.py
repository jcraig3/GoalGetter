"""Organization → Assets (6.3): a name, and who uploaded it.

The store has always been content-addressed — a file is its hash — which is
right for serving and useless for browsing: a library of sixty-four-character
names. A name is what the Assets page shows and lets an admin change; the
uploader is who to ask. Both are optional, so every file already stored stays
as it was.

Revision ID: a9e3c7f1d254
Revises: f4c8d2a6b913
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9e3c7f1d254"
down_revision: str | None = "f4c8d2a6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stored_asset", sa.Column("name", sa.String(120), nullable=True))
    op.add_column(
        "stored_asset",
        sa.Column(
            "uploaded_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "user_account.id",
                ondelete="SET NULL",
                name=op.f("fk_stored_asset_uploaded_by_user_id_user_account"),
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("stored_asset", "uploaded_by_user_id")
    op.drop_column("stored_asset", "name")
