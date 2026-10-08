"""Two-step sign-in with an authenticator app, and the switch to require it.

Revision ID: c7f2a9e4b183
Revises: b1e6f3a8d247
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7f2a9e4b183"
down_revision: str | None = "b1e6f3a8d247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_account", sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("user_account", sa.Column("mfa_pending_secret_encrypted", sa.Text(), nullable=True))
    op.add_column("user_account", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "user_account",
        sa.Column("mfa_recovery_hashes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column("user_account", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    op.add_column("organization", sa.Column("require_mfa", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("organization", "require_mfa")
    op.drop_column("user_account", "mfa_last_step")
    op.drop_column("user_account", "mfa_recovery_hashes")
    op.drop_column("user_account", "mfa_enabled_at")
    op.drop_column("user_account", "mfa_pending_secret_encrypted")
    op.drop_column("user_account", "mfa_secret_encrypted")
