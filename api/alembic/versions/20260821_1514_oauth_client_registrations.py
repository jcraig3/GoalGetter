"""oauth client registrations

The app registration a deployment makes with a provider, once. There is no hosted
relay — GoalGetter runs on somebody else's server, so no central service holds a
Google client secret on their behalf. Each deployment registers its own OAuth
application and pastes the two values in; everything after that is a sign-in
button.

Keyed by `(organization, provider)` rather than by connector, so one Google
registration serves every Google connector and there is one place to rotate a
leaked secret.

**No index on `organization_id` alone.** The unique constraint's index leads with
that column, so a lookup by organization uses it as a prefix; a second index would
only ever be written to. Alembic's autogenerate proposed one because the model
asked for it, and the model was wrong.

Revision ID: 794e677dacd2
Revises: dea8225095f8
Create Date: 2026-08-21 15:14:00.461148
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '794e677dacd2'
down_revision: str | None = 'dea8225095f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'oauth_client',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('provider', sa.String(length=64), nullable=False),
        sa.Column('client_id', sa.String(length=500), nullable=False),
        sa.Column('client_secret_encrypted', sa.String(length=2000), nullable=False),
        sa.Column('created_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['created_by_user_id'],
            ['user_account.id'],
            name=op.f('fk_oauth_client_created_by_user_id_user_account'),
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['organization_id'],
            ['organization.id'],
            name=op.f('fk_oauth_client_organization_id_organization'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_oauth_client')),
        sa.UniqueConstraint(
            'organization_id', 'provider', name='uq_oauth_client_provider'
        ),
    )


def downgrade() -> None:
    # Drops the registrations. Every OAuth source then has tokens it cannot
    # refresh, which surfaces as a failing sync rather than as silence — see
    # `app/oauth.py`, which reports a missing registration by name.
    op.drop_table('oauth_client')
