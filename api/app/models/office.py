from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Office(Base, TimestampMixin):
    """A physical location. Offices contain teams; teams contain agents.

    Two fixed levels across separate tables, not a self-referencing tree — so
    there is no recursion, no cycle to prevent, and no depth to track. An
    office cannot contain an office.

    An agent's office is derived from their team rather than stored again.
    Storing it twice invites the state where someone is in the Phoenix office
    on a Dallas team, and every report then has to decide which one wins.
    """

    __tablename__ = "office"
    __table_args__ = (
        # **One office per name, ignoring case**, among those in use. Two
        # "Gotham"s made every office picker a coin toss (QA-7). An archived
        # office keeps its name out of the way of a new one.
        Index(
            "uq_office_org_name_lower",
            "organization_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id"), index=True
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The Microsoft 365 office location whose people come here (Phase 28).
    m365_office: Mapped[str | None] = mapped_column(String(200))

    def __repr__(self) -> str:
        return f"<Office id={self.id} name={self.name!r}>"
