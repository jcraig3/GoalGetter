"""What an agent may set about themselves.

Three things about somebody are theirs rather than the roster's — their
photograph, their details, and the clip that plays when they win. Until now the
answer to "may they set it" was decided in code and the same for every
deployment.

It is not the same for every deployment. A company with HR headshots wants one
uniform set of photographs. A floor that has heard one person's walk-up song
nine hundred times wants a manager to choose them. And most places want none of
that and are happy as they are — which is why every column defaults to true.

**Agents only.** A manager and an admin can already set these for anybody, and
a switch that locked an admin out of their own photograph would be a support
call rather than a policy.

Revision ID: a3f7d21c6b09
Revises: c05e93b7f142
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7d21c6b09"
down_revision: str | None = "c05e93b7f142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Columns rather than one JSON blob, unlike `appearance` beside them.
#:
#: Appearance earned JSON at nineteen fields and growing; this is the complete
#: set of things about a person that are not roster facts, and it is three. A
#: column each is queryable, has an obvious default, and cannot hold a key
#: nobody validates.
COLUMNS = ("self_photo", "self_details", "self_walkup")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column(
            "organization",
            sa.Column(
                name, sa.Boolean(), nullable=False, server_default=sa.true()
            ),
        )


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("organization", name)
