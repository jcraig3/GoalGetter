"""Let the directory add somebody as hidden.

The panel offered two answers — add them, or never ask again — and the gap
between those is where most of a directory actually sits. A company of four
hundred has contractors, service accounts and a whole department that does not
sell: none of them belong on a leaderboard, and all of them belong in the
roster.

"Don't add" is the wrong tool for that, and it is the only one there was: it
creates no account at all, so those people exist nowhere and cannot be found,
photographed or moved onto a team later.

**A status rather than a flag on approval**, because it records what somebody
decided rather than what to do about it — the same as the three beside it. And
because a sync must not overturn it, which is a property of the status list.

Revision ID: d7b4e1c8a520
Revises: b6c2f0e94a17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7b4e1c8a520"
down_revision: str | None = "b6c2f0e94a17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = "status IN ('pending', 'approved', 'declined', 'archived')"
AFTER = "status IN ('pending', 'approved', 'declined', 'archived', 'hidden')"


def upgrade() -> None:
    op.drop_constraint("directory_status_valid", "directory_person", type_="check")
    op.create_check_constraint("directory_status_valid", "directory_person", AFTER)


def downgrade() -> None:
    # They became accounts, and those accounts stay. Only the record of *how*
    # they were added narrows back to the older vocabulary.
    op.execute("UPDATE directory_person SET status = 'approved' WHERE status = 'hidden'")
    op.drop_constraint("directory_status_valid", "directory_person", type_="check")
    op.create_check_constraint("directory_status_valid", "directory_person", BEFORE)
