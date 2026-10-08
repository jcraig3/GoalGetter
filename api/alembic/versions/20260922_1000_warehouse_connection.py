"""The warehouse a deployment reads from, held once.

**The same split as the spreadsheet accounts, for the same reason.** A Snowflake
credential is an account identifier, a username, a private key, a warehouse and a
role — six answers nobody wants to give again for the second table they connect.
So the credential is the *connection*, and each query is a source hanging off it:
connect once, add queries.

**Its own table rather than a row in `oauth_client`.** That table is a
registration with an OAuth provider — client id, client secret, issuer, tenant —
and Snowflake is none of those things. A row there would have every OAuth column
null and a provider key absent from the catalogue in `providers.py`, which is the
kind of shortcut that reads fine today and confuses everybody in a year.

Revision ID: b2e8f4a71c53
Revises: a9d47c31e8b6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2e8f4a71c53"
down_revision: str | None = "a9d47c31e8b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "warehouse_connection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger(),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        #: Which kind of warehouse. One today; a column rather than an assumption
        #: because Redshift and BigQuery are the same shape of problem.
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("account", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("username", sa.String(length=200), nullable=False, server_default=""),
        #: The PEM private key, encrypted. Never returned by any endpoint.
        sa.Column("private_key_encrypted", sa.Text(), nullable=True),
        sa.Column("key_passphrase_encrypted", sa.Text(), nullable=True),
        #: Kept for a warehouse that still allows one. Snowflake blocks
        #: password-only sign-ins for service users, so this is the legacy half.
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("warehouse", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("role", sa.String(length=200), nullable=False, server_default=""),
        #: Optional, because a fully-qualified query does not need it — and a
        #: database that silently disagrees with the query is a trap.
        sa.Column("database", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One per organization per kind. "Connect once, add queries" is the whole
        # shape; two credentials for one warehouse would make "which is this
        # reading as?" unanswerable from a source row.
        sa.UniqueConstraint(
            "organization_id", "provider", name="uq_warehouse_connection_org_provider"
        ),
    )


def downgrade() -> None:
    op.drop_table("warehouse_connection")
