"""the tenant account a connection acts as

Directory sync and outgoing mail used application permissions, which only a
Privileged Role Administrator can consent to. They are delegated now, so the
connection needs somewhere to keep the refresh token for the account it acts as —
and the address of that account, so a screen can say whose it is.

Revision ID: e4b81c0d7a35
Revises: c1f7a4e93b12
Create Date: 2026-09-03 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'e4b81c0d7a35'
down_revision: str | None = 'c1f7a4e93b12'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'oauth_client',
        sa.Column('tenant_refresh_token_encrypted', sa.Text(), nullable=True),
    )
    op.add_column(
        'oauth_client',
        sa.Column(
            'tenant_connected_as',
            sa.String(length=320),
            nullable=False,
            server_default='',
        ),
    )
    # Which mailbox outgoing mail is sent as. Empty means "the connected account
    # itself", which is the only address that needs no extra Exchange rights.
    op.add_column(
        'oauth_client',
        sa.Column(
            'mail_from',
            sa.String(length=320),
            nullable=False,
            server_default='',
        ),
    )
    op.add_column(
        'oauth_client',
        sa.Column(
            'mail_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('oauth_client', 'mail_enabled')
    op.drop_column('oauth_client', 'mail_from')
    op.drop_column('oauth_client', 'tenant_connected_as')
    op.drop_column('oauth_client', 'tenant_refresh_token_encrypted')
