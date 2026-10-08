"""Hold an image, rather than link to one.

**The first file storage in this product, and it stayed out on purpose.** Media
takes URLs and avatars draw initials; both decisions said uploads could follow if
anybody wanted them. Staff photos are what wanted them — nobody is going to host
four hundred headshots elsewhere and paste four hundred URLs.

In Postgres rather than on a volume, because the compose file backs up the
database nightly and nothing else: an uploads directory would be a second backup
path that existed only in somebody's memory. Four hundred and fifty faces at
forty kilobytes is twenty megabytes.

Revision ID: a2f8c61b94d7
Revises: f7c41d0e3a52
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2f8c61b94d7"
down_revision: str | None = "f7c41d0e3a52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stored_image",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organization.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stored_image"),
        sa.UniqueConstraint(
            "organization_id", "sha256", name="uq_stored_image_content"
        ),
    )
    op.create_index("ix_stored_image_sha256", "stored_image", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_stored_image_sha256", table_name="stored_image")
    op.drop_table("stored_image")
