"""A photograph from the directory, and one somebody chose instead.

**Two columns rather than one, and that is what makes "revert" mean anything.**
With a single slot a directory sync would overwrite the headshot somebody
uploaded, or the upload would vanish at three the next morning — and there would
be nothing to revert *to*. Kept apart, the sync owns one and the person owns the
other; the custom one wins where it exists, and clearing it falls back rather
than falling blank.

`tenant_photo_etag` is Graph's own tag for the photo, so a sync skips downloading
one it already has: four hundred and fifty faces is four hundred and fifty round
trips the first time and none after it.

`ON DELETE SET NULL` rather than CASCADE — losing an image should cost a face,
not a person.

Revision ID: b6d92e4f70c3
Revises: a2f8c61b94d7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d92e4f70c3"
down_revision: str | None = "a2f8c61b94d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_account", sa.Column("tenant_photo_image_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "user_account", sa.Column("custom_photo_image_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "user_account", sa.Column("tenant_photo_etag", sa.String(length=120), nullable=True)
    )
    op.create_foreign_key(
        "fk_user_account_tenant_photo",
        "user_account",
        "stored_image",
        ["tenant_photo_image_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_user_account_custom_photo",
        "user_account",
        "stored_image",
        ["custom_photo_image_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_account_custom_photo", "user_account", type_="foreignkey")
    op.drop_constraint("fk_user_account_tenant_photo", "user_account", type_="foreignkey")
    op.drop_column("user_account", "tenant_photo_etag")
    op.drop_column("user_account", "custom_photo_image_id")
    op.drop_column("user_account", "tenant_photo_image_id")
