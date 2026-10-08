"""Generalise the blob store from images to assets.

The table has held photographs, logos and wall backgrounds since 4a, and the
reasoning in `models/stored_asset.py` for putting bytes in Postgres rather than
on a volume was never about images — it is about there being one backup path,
and about a row and its bytes committing together.

Walk-up audio is the first thing in it that is not a picture, so the name stops
being true and the two picture-shaped columns stop applying.

**Renamed rather than joined by a second table.** Two content-addressed blob
stores would be two sets of the same de-duplication, the same cache headers and
the same per-organization scoping, and the third asset kind would make three.

`user_account.tenant_photo_image_id` and `custom_photo_image_id` keep their
names: they point at an asset which is a photograph, which is what they say.

Revision ID: b6c2f0e94a17
Revises: f19a4e6b2d80
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c2f0e94a17"
down_revision: str | None = "f19a4e6b2d80"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("stored_image", "stored_asset")
    # The unique constraint and index carry the old name inside their own, which
    # is how a schema ends up explaining a rename that happened years ago.
    op.execute(
        "ALTER TABLE stored_asset "
        "RENAME CONSTRAINT uq_stored_image_content TO uq_stored_asset_content"
    )
    op.execute("ALTER INDEX ix_stored_image_sha256 RENAME TO ix_stored_asset_sha256")

    # Audio has no dimensions. NOT NULL with a zero would be a lie that every
    # reader has to know about; null says "this kind does not have one".
    op.alter_column("stored_asset", "width", existing_type=sa.Integer(), nullable=True)
    op.alter_column("stored_asset", "height", existing_type=sa.Integer(), nullable=True)

    # Milliseconds, because a fifteen-second cap on a clip wants to be exact at
    # the boundary and seconds would round a 15.4-second file down into range.
    op.add_column(
        "stored_asset", sa.Column("duration_ms", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stored_asset", "duration_ms")
    # Anything with no dimensions cannot exist in the old shape.
    op.execute("DELETE FROM stored_asset WHERE width IS NULL OR height IS NULL")
    op.alter_column("stored_asset", "width", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "stored_asset", "height", existing_type=sa.Integer(), nullable=False
    )
    op.execute("ALTER INDEX ix_stored_asset_sha256 RENAME TO ix_stored_image_sha256")
    op.execute(
        "ALTER TABLE stored_asset "
        "RENAME CONSTRAINT uq_stored_asset_content TO uq_stored_image_content"
    )
    op.rename_table("stored_asset", "stored_image")
