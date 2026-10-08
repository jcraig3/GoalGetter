"""job title, department and office on an account

Kept only on `directory_person` until now, deliberately — they exist to drive the
placement rules and nothing read them afterwards. The People list needs to filter
by them, which is a different job from diffing, and a filter cannot join to a
table that only holds directory-synced people.

Nullable and empty by default: a person invited by hand has none of this, and an
empty filter value is what "any" means anyway.

Revision ID: d3f6a80b4e17
Revises: b8e1f5c72d94
Create Date: 2026-09-03 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = 'd3f6a80b4e17'
down_revision: str | None = 'b8e1f5c72d94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ('job_title', 'department', 'office_location'):
        op.add_column(
            'user_account',
            sa.Column(column, sa.String(length=200), nullable=False, server_default=''),
        )


def downgrade() -> None:
    for column in ('office_location', 'department', 'job_title'):
        op.drop_column('user_account', column)
