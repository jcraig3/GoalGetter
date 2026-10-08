"""The Google account spreadsheets are read as.

**The same move as `files_*`, for the same reason.** Every Sheets source used to
hold its own credential, so connecting three spreadsheets meant three sign-ins
and three tokens expiring independently. One account for the deployment, and the
sheets are just sheets.

Two columns rather than one, because Google offers two honest ways to be a robot
and the connector already supports both:

**A signed-in account** — two clicks, and right for a Workspace company whose
consent screen is Internal. Its weakness is that it belongs to a person.

**A service account** — a key, and the spreadsheet shared with its address, which
is how a colleague gets access too. It belongs to the organization rather than to
anybody, and it sidesteps Google's verification review for a plain Gmail account.

Neither is a mode to choose: whichever is present is the one used, matching what
`SheetsConnector._token` has always done per source.

Revision ID: a9d47c31e8b6
Revises: f4c82e6b1d95
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d47c31e8b6"
down_revision: str | None = "f4c82e6b1d95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "oauth_client",
        sa.Column("sheets_refresh_token_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "oauth_client",
        sa.Column("sheets_service_account_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "oauth_client",
        sa.Column(
            "sheets_connected_as",
            sa.String(length=320),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("oauth_client", "sheets_connected_as")
    op.drop_column("oauth_client", "sheets_service_account_encrypted")
    op.drop_column("oauth_client", "sheets_refresh_token_encrypted")
