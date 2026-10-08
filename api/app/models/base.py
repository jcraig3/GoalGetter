from datetime import datetime

from sqlalchemy import BigInteger, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Postgres invents its own names for constraints and indexes unless told
# otherwise. Fixing the pattern here means Alembic generates stable, predictable
# names, so a later migration can reliably reference one to drop or alter it.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Every primary key is BIGINT.
    #
    # Overkill for organizations and users, but metric_fact will hold millions
    # of rows, and mixing INTEGER and BIGINT keys means foreign keys of
    # mismatched types — which is awkward to join and painful to widen later.
    # One rule for the whole schema is cheaper than remembering per table.
    type_annotation_map = {int: BigInteger}


class TimestampMixin:
    """created_at / updated_at maintained by the database.

    Uses database functions rather than Python values so rows written by a
    migration or a raw SQL statement get correct timestamps too — not just rows
    written through the ORM.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
