from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CustomRole(Base, TimestampMixin):
    """A built-in role with some of what it may do taken away.

    "Team lead" is a manager who cannot publish competitions or correct data;
    "Reporting admin" is an admin who cannot touch integrations or settings.

    **Narrower, never wider.** A custom role keeps its base role's scope — which
    people's numbers it can see — and every check that asks for that role, and
    removes capabilities on top. Widening would mean an agent-based role passing
    checks written for managers, which is a different and much riskier feature.
    So a person's `org_role` stays the base, and this only ever subtracts. See
    `app/roles.py`.
    """

    __tablename__ = "custom_role"
    __table_args__ = (
        CheckConstraint("base_role IN ('agent', 'manager', 'admin')", name="base_role_valid"),
        Index("uq_custom_role_org_name", "organization_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(String(300))
    base_role: Mapped[str] = mapped_column(String(20))
    #: Capability keys taken away from the base. See `roles.REMOVABLE`.
    removed: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
