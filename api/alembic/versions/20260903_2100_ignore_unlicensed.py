"""ignore unlicensed accounts

A tenant is full of accounts nobody signs in with: service principals given a
mailbox, shared boxes, leavers left disabled but not deleted. Most carry no
licence, and a licence is the closest thing Entra has to "this is a person who
works here".

Off by default: it changes who a sync proposes, and a deployment already running
should not silently start ignoring people.

Revision ID: b8e1f5c72d94
Revises: a7d4e2b91c60
Create Date: 2026-09-03 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'b8e1f5c72d94'
down_revision: str | None = 'a7d4e2b91c60'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'oauth_client',
        sa.Column(
            'directory_ignore_unlicensed',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    op.drop_column('oauth_client', 'directory_ignore_unlicensed')
