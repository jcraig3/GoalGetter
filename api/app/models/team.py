from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Team(Base, TimestampMixin):
    """A team. Flat — teams do not nest.

    An earlier version modelled this as a tree so a company could run
    divisions → regions → teams → pods. That bought recursive queries, cycle
    prevention, depth limits, and a rule about archiving a team with children,
    in exchange for a hierarchy this product does not need: a sales floor has
    teams, and leaderboards compare them directly.

    If divisional rollups are ever wanted, a separate grouping is a smaller and
    clearer change than reinstating a tree.
    """

    __tablename__ = "team"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id"), index=True
    )

    # Optional: a team created before offices exist should not be blocked, and
    # "no office yet" is worth seeing rather than being impossible to express.
    office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id"), index=True
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    color: Mapped[str | None] = mapped_column(String(7))
    #: For where the full name will not fit: a race piece, a podium block, a
    #: head-to-head banner (6.7). Up to twelve characters.
    short_name: Mapped[str | None] = mapped_column(String(12))
    #: A picture from Organization → Assets, by digest — drawn where a person
    #: would have their face.
    logo: Mapped[str | None] = mapped_column(String(64))

    # Archive hides a team from pickers while leaving history intact — a
    # leaderboard for last quarter must still be able to name the team that won
    # it. Deletion is only permitted for teams nothing references yet.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The Microsoft 365 department whose people join this team (Phase 28).
    m365_department: Mapped[str | None] = mapped_column(String(200))


    def __repr__(self) -> str:
        return f"<Team id={self.id} name={self.name!r}>"
