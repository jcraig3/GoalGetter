"""outgoing mail needs no account

The delegated account those two columns held is gone. Sending uses the same client
credentials the directory sync does, so there is no refresh token to keep and
nobody to name — the mailbox to send as is `mail_from`, which stays.

Revision ID: f2c93a15e6d8
Revises: e4b81c0d7a35
Create Date: 2026-09-03 19:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'f2c93a15e6d8'
down_revision: str | None = 'e4b81c0d7a35'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column('oauth_client', 'tenant_connected_as')
    op.drop_column('oauth_client', 'tenant_refresh_token_encrypted')


def downgrade() -> None:
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
