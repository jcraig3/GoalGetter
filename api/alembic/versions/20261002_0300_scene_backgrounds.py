"""Drawn scene backgrounds (6.9): a "scenes" shelf a kept background can go on.

Scenes themselves need no column — a background is stored as JSON, and its
new `scene` key is checked by the same model every screen uses. Only the
library's category list, which the database checks, gains a shelf.

Revision ID: e5a9c1f7b382
Revises: d8f2b4c6e731
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5a9c1f7b382"
down_revision: str | None = "d8f2b4c6e731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_saved_background_saved_background_category_valid"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "saved_background", type_="check")
    op.create_check_constraint(
        op.f(NAME),
        "saved_background",
        "category IN ('calm', 'energy', 'celebration', 'seasonal', 'brand', 'scenes')",
    )


def downgrade() -> None:
    op.execute("UPDATE saved_background SET category = 'calm' WHERE category = 'scenes'")
    op.drop_constraint(op.f(NAME), "saved_background", type_="check")
    op.create_check_constraint(
        op.f(NAME),
        "saved_background",
        "category IN ('calm', 'energy', 'celebration', 'seasonal', 'brand')",
    )
