"""The Microsoft account Excel reads workbooks as.

**A second account slot, not a rename of the first.** `tenant_*` is the account the
directory sync acts as, and it exists only in delegated mode; most deployments run
the sync as the application and have nothing in it. Reading a workbook is the
opposite: `Files.Read.All` is granted to the registration as a *delegated*
permission, so it works only with a signed-in user — there is no app-only token
that carries it.

Two slots rather than one because they are genuinely two decisions. A deployment
can run the sync as the application and still sign one person in for spreadsheets,
and the person whose files GoalGetter reads is not necessarily the service account
the sync acts as.

Revision ID: c5a91e7f2b38
Revises: d3f6a80b4e17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5a91e7f2b38"
down_revision: str | None = "d3f6a80b4e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oauth_client",
        sa.Column("files_refresh_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "oauth_client",
        sa.Column(
            "files_connected_as",
            sa.String(length=320),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("oauth_client", "files_connected_as")
    op.drop_column("oauth_client", "files_refresh_token_encrypted")
