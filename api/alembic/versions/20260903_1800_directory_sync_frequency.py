"""directory sync frequency

How often a directory is read, per connection, instead of a constant in
`app/directory/sync.py`. Daily is what that constant said, so an existing
deployment keeps the behaviour it already had.

Revision ID: c1f7a4e93b12
Revises: 68bb593b349a
Create Date: 2026-09-03 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'c1f7a4e93b12'
down_revision: str | None = '68bb593b349a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'oauth_client',
        sa.Column(
            'directory_sync_hours',
            sa.Integer(),
            nullable=False,
            server_default='24',
        ),
    )


def downgrade() -> None:
    op.drop_column('oauth_client', 'directory_sync_hours')
