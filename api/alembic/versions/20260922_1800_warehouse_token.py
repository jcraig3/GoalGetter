"""Hold a Snowflake programmatic access token beside the private key.

**Its own column rather than the password's.** A PAT is not a password to the
driver: Snowflake's connector routes `PROGRAMMATIC_ACCESS_TOKEN` to `AuthByPAT`
via the `token` parameter, and one handed over as a password is rejected — which
reads as a bad token rather than the wrong kind of credential. Sharing
`password_encrypted` would also leave nothing able to say which of the two a row
holds, so the status endpoint would report "password" for a token.

**Why a deployment wants one at all.** A private key needs `ALTER USER`, which
most people connecting a warehouse for the first time cannot run on themselves.
A PAT they can issue to themselves. It is the credential a connection gets tested
with; a key is the one it should end up on, because a PAT expires and may be tied
to a network-policy bypass that lapses sooner still.

Revision ID: d3b91c5f8e42
Revises: c8f3a2d47b91
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3b91c5f8e42"
down_revision: str | None = "c8f3a2d47b91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "warehouse_connection", sa.Column("token_encrypted", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    # A connection authenticating by token loses its credential, which is the
    # honest outcome: the old schema has nowhere to keep one. The account, the
    # warehouse and the queries survive, so reconnecting is one field.
    op.drop_column("warehouse_connection", "token_encrypted")
