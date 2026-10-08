"""A file this deployment holds, rather than links to.

**The first file storage in this product, and it stayed out for a long time on
purpose.** `media.py` takes URLs because a YouTube link and a hosted GIF cover
walk-up songs and celebration art completely, and `Avatar` draws initials because
an internal tool where everyone knows each other gains little from photos. Both
decisions were right and both said uploads could follow if anybody wanted them.
Staff photos are what wanted them: nobody is going to host four hundred
headshots somewhere else and paste four hundred URLs. Logos, wall backgrounds
and walk-up audio followed, which is why this is an *asset* store rather than
an image one — the reasoning below was never about pictures.

**In Postgres, not on a volume.** The compose file backs up the database nightly
and nothing else, so an uploads directory would be a second backup path that
existed only in somebody's memory — silently missing until the day it mattered.
Four hundred and fifty faces at forty kilobytes each is twenty megabytes, which
is not a number worth building object storage for. It is also transactional: a
row and its bytes commit together, so an orphaned file is not a thing that can
happen here.

**Content-addressed.** The primary key people quote is the SHA-256 of the bytes,
which makes two people with the same photo one row, makes caching safe to mark
immutable, and means a re-upload of the same file changes nothing rather than
growing the table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StoredAsset(Base):
    """One file, normalised, with the hash of its bytes as its name."""

    __tablename__ = "stored_asset"
    __table_args__ = (
        # **Per organization, not globally.** Two tenants uploading the same
        # stock photo is a coincidence, not a reason to share a row across a
        # boundary everything else in this schema respects.
        UniqueConstraint("organization_id", "sha256", name="uq_stored_asset_content"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )

    #: Hex SHA-256 of the stored bytes — the name this is served under.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Null for anything that is not a picture.
    #:
    #: **Null rather than zero.** A zero would be a lie every reader has to know
    #: about; null says "this kind does not have one", which is the truth.
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    #: Null for anything that does not play.
    #:
    #: Milliseconds, because a fifteen-second cap on a clip wants to be exact at
    #: the boundary and seconds would round a 15.4-second file into range.
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    #: **Deferred, because almost nothing that reads this row wants the bytes.**
    #: A roster of four hundred and fifty people renders four hundred and fifty
    #: avatars, and each one needs a hash to build a URL from — not forty
    #: kilobytes of JPEG. Loaded on first access, which is the one endpoint that
    #: actually serves the image.
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)

    #: What the Assets page calls it (6.3) — the uploaded file's name, which an
    #: admin can change. Null for files stored before there was a library.
    name: Mapped[str | None] = mapped_column(String(120))
    #: Who uploaded it through the library. Null for the rest.
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<StoredAsset {self.sha256[:12]} {self.content_type}>"
