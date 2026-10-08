"""The six things a new deployment needs before its first wall, and which are done.

**Why a checklist.** A new admin landed on Home to "300 people have recorded
nothing in 7 days" and "350 agents are on no team" — alarms, with no path from
them to a working wall (review §3, #4). Every step here is a question about the
data rather than a box somebody ticks, so it can never say done when it is not,
and finishes itself when the work is done anywhere in the app.

In the order somebody would do them: numbers before the people they belong to,
people before teams, teams before a board worth showing, a board before a
channel to show it on, and a channel before a television to show the channel.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session as DbSession

from app.directory import non_people
from app.models import (
    Channel,
    ChannelScreen,
    DataSource,
    Display,
    Leaderboard,
    Organization,
    Team,
    UserAccount,
)


@dataclass
class Step:
    key: str
    label: str
    done: bool
    link: str
    #: One line on where it stands — what is left, or what was done.
    detail: str


def steps(db: DbSession, org: Organization) -> list[Step]:
    sources = int(
        db.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(
                DataSource.organization_id == org.id,
                DataSource.archived_at.is_(None),
                DataSource.activated_at.is_not(None),
            )
        )
        or 0
    )

    suggested = len(non_people.candidates(db, org.id))

    teams_with_people = int(
        db.scalar(
            select(func.count())
            .select_from(Team)
            .where(
                Team.organization_id == org.id,
                Team.archived_at.is_(None),
                exists().where(
                    UserAccount.team_id == Team.id, UserAccount.hidden_at.is_(None)
                ),
            )
        )
        or 0
    )

    boards = int(
        db.scalar(
            select(func.count())
            .select_from(Leaderboard)
            .where(Leaderboard.organization_id == org.id, Leaderboard.archived_at.is_(None))
        )
        or 0
    )

    channels = int(
        db.scalar(
            select(func.count())
            .select_from(Channel)
            .where(
                Channel.organization_id == org.id,
                exists().where(ChannelScreen.channel_id == Channel.id),
            )
        )
        or 0
    )

    # Connected means it has actually shown up, not merely that a link exists:
    # a link nobody opened is not a television on a wall.
    tvs = int(
        db.scalar(
            select(func.count())
            .select_from(Display)
            .where(
                Display.organization_id == org.id,
                Display.revoked_at.is_(None),
                Display.last_seen_at.is_not(None),
            )
        )
        or 0
    )

    def plural(n: int, one: str, many: str) -> str:
        return f"{n} {one if n == 1 else many}"

    return [
        Step(
            "data", "Connect your data", sources > 0, "/integrations",
            f"{plural(sources, 'source', 'sources')} connected" if sources
            else "A spreadsheet, a CRM or a warehouse — where the numbers come from.",
        ),
        Step(
            "people", "Hide accounts that are not people", suggested == 0, "/users",
            f"{plural(suggested, 'account looks', 'accounts look')} like a device or a mailbox"
            if suggested else "Nothing left that looks like a printer or a mailbox.",
        ),
        Step(
            "teams", "Put people on teams", teams_with_people > 0, "/teams",
            f"{plural(teams_with_people, 'team has', 'teams have')} people on"
            if teams_with_people else "Team boards and team goals need somebody on a team.",
        ),
        Step(
            "board", "Make a leaderboard", boards > 0, "/leaderboards",
            plural(boards, "board", "boards") if boards else "Who is ahead, on one metric.",
        ),
        Step(
            "channel", "Build a channel", channels > 0, "/channels",
            plural(channels, "channel", "channels") if channels
            else "The playlist of slides a TV plays.",
        ),
        Step(
            "tv", "Connect a TV", tvs > 0, "/channels",
            f"{plural(tvs, 'TV has', 'TVs have')} connected" if tvs
            else "Open /pair on the television and type its code here.",
        ),
    ]
