"""Hiding a person, and noticing when the directory turns them off.

**Two states that were one word and one missing word.**

`archived_at` becomes `hidden_at`. Renamed rather than added: it already meant
"an admin took this person off the roster, reversibly, keeping their history",
which is what hiding is. Calling it archiving borrowed a word this schema uses
for *nine other tables* to mean "the thing itself is retired" — a leaderboard, a
goal, a data source. A person is not retired, they are excluded, and the two
deserve different words. A rename keeps every existing decision intact; adding a
column beside it would have left two places to ask the same question.

`deactivated` joins the statuses, and it is the genuinely new one. Until now,
disabling somebody in Entra did nothing here: they kept their account, kept
their access, and kept their place on the leaderboard. The directory already
knew — `directory_person.enabled` is stored on every pass — and nothing read it.

**The two are deliberately not the same state.** Hiding is a decision somebody
made and the sync must never overturn it; deactivation is the directory
reporting a fact, and it reverses itself when the fact does. Collapsing them
would mean re-enabling an account in Entra silently un-hiding a person an admin
had chosen to hide.

Revision ID: e7b3d5a91f42
Revises: c5a91e7f2b38
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7b3d5a91f42"
down_revision: str | None = "c5a91e7f2b38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept verbatim so the downgrade restores exactly what was there.
OLD_STATUSES = "('invited', 'active', 'suspended')"
NEW_STATUSES = "('invited', 'active', 'suspended', 'deactivated')"


def upgrade() -> None:
    op.alter_column("user_account", "archived_at", new_column_name="hidden_at")

    # Widened rather than replaced: the constraint is what stops a typo'd status
    # sitting in the table being neither one thing nor the other.
    op.drop_constraint("status_valid", "user_account", type_="check")
    op.create_check_constraint(
        "status_valid", "user_account", f"status IN {NEW_STATUSES}"
    )


def downgrade() -> None:
    # Anybody the directory had turned off comes back as suspended, which is the
    # nearest surviving word for "here but not allowed in". Silently making them
    # active would hand access back to leavers on a rollback.
    op.execute(
        "UPDATE user_account SET status = 'suspended' WHERE status = 'deactivated'"
    )
    op.drop_constraint("status_valid", "user_account", type_="check")
    op.create_check_constraint(
        "status_valid", "user_account", f"status IN {OLD_STATUSES}"
    )
    op.alter_column("user_account", "hidden_at", new_column_name="archived_at")
