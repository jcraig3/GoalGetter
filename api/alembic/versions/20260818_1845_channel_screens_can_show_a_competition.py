"""channel screens can show a competition

Adds `channel_screen.competition_id` and widens the two CHECK constraints that
police what a screen may be.

Constraint names here are the **bare** ones (`kind_valid`), not the stored ones
(`ck_channel_screen_kind_valid`). The metadata naming convention adds the prefix,
so passing the full name asks Postgres to drop
`ck_channel_screen_ck_channel_screen_kind_valid`.

**Autogenerate found the column and the foreign key, and neither constraint.**
Alembic does not diff CHECK constraints, so the generated migration would have
left `kind_valid` refusing the very row this feature exists to write — a
`competition` screen would have failed on insert with a constraint violation,
after the model, the API and the UI all agreed it was allowed. They are dropped
and recreated by hand below.

Revision ID: 0cdc5b353384
Revises: 50b62b1669a1
Create Date: 2026-08-18 18:45:19.428299
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0cdc5b353384'
down_revision: str | None = '50b62b1669a1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The two states of each constraint, so up and down are obviously inverses
#: rather than two hand-written strings that have to be compared by eye.
KIND_BEFORE = (
    "kind IN ('leaderboard', 'goal', 'achievements', 'image', 'video', 'message')"
)
KIND_AFTER = (
    "kind IN ('leaderboard', 'goal', 'competition', 'achievements', "
    "'image', 'video', 'message')"
)

PAYLOAD_BEFORE = (
    "(kind = 'leaderboard' AND leaderboard_id IS NOT NULL) OR "
    "(kind = 'goal' AND goal_id IS NOT NULL) OR "
    "(kind = 'achievements') OR "
    "(kind IN ('image', 'video') AND url IS NOT NULL) OR "
    "(kind = 'message' AND title IS NOT NULL)"
)
PAYLOAD_AFTER = (
    "(kind = 'leaderboard' AND leaderboard_id IS NOT NULL) OR "
    "(kind = 'goal' AND goal_id IS NOT NULL) OR "
    "(kind = 'competition' AND competition_id IS NOT NULL) OR "
    "(kind = 'achievements') OR "
    "(kind IN ('image', 'video') AND url IS NOT NULL) OR "
    "(kind = 'message' AND title IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column(
        'channel_screen', sa.Column('competition_id', sa.BigInteger(), nullable=True)
    )
    # CASCADE, like the board and goal columns beside it: a screen whose
    # competition was deleted cannot render, and the payload constraint would
    # refuse to let it exist with a null id anyway.
    op.create_foreign_key(
        op.f('fk_channel_screen_competition_id_competition'),
        'channel_screen',
        'competition',
        ['competition_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.drop_constraint('kind_valid', 'channel_screen', type_='check')
    op.create_check_constraint('kind_valid', 'channel_screen', KIND_AFTER)

    op.drop_constraint('payload_matches_kind', 'channel_screen', type_='check')
    op.create_check_constraint(
        'payload_matches_kind', 'channel_screen', PAYLOAD_AFTER
    )


def downgrade() -> None:
    # Narrow the constraints first. Dropping the column while `payload_matches_kind`
    # still references it would fail, and any `competition` screens have to go
    # before `kind_valid` refuses them.
    op.execute("DELETE FROM channel_screen WHERE kind = 'competition'")

    op.drop_constraint('payload_matches_kind', 'channel_screen', type_='check')
    op.create_check_constraint(
        'payload_matches_kind', 'channel_screen', PAYLOAD_BEFORE
    )

    op.drop_constraint('kind_valid', 'channel_screen', type_='check')
    op.create_check_constraint('kind_valid', 'channel_screen', KIND_BEFORE)

    op.drop_constraint(
        op.f('fk_channel_screen_competition_id_competition'),
        'channel_screen',
        type_='foreignkey',
    )
    op.drop_column('channel_screen', 'competition_id')
