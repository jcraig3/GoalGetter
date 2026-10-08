"""how the sync signs in

A deployment picks one: acting as the application, which needs a Privileged Role
Administrator to consent once and then never expires; or acting as one account,
which a Cloud Application Administrator can set up alone and which stops if that
account is disabled.

The two permission sets cannot share a registration — consent is all-or-nothing,
and a Cloud Application Administrator can grant every delegated permission and no
app role — so the mode has to be known before provisioning.

Revision ID: a7d4e2b91c60
Revises: f2c93a15e6d8
Create Date: 2026-09-03 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'a7d4e2b91c60'
down_revision: str | None = 'f2c93a15e6d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'oauth_client',
        sa.Column(
            'directory_auth_mode',
            sa.String(length=20),
            nullable=False,
            server_default='application',
        ),
    )
    # Delegated mode keeps a refresh token for the account it acts as. Dropped
    # when that mode was briefly removed; back because the mode is a choice now.
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


def downgrade() -> None:
    op.drop_column('oauth_client', 'tenant_connected_as')
    op.drop_column('oauth_client', 'tenant_refresh_token_encrypted')
    op.drop_column('oauth_client', 'directory_auth_mode')
