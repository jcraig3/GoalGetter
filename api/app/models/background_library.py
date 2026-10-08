from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: How the library is sorted. Fixed rather than free text, because the bundled
#: backgrounds use the same set and a filter that offered "Calm", "calm" and
#: "Relaxing" would be three shelves for one thing.
CATEGORIES = ("calm", "energy", "celebration", "seasonal", "brand", "scenes")


class SavedBackground(Base, TimestampMixin):
    """A background somebody here kept, so it can be used again.

    **Before this, reusing a background meant uploading it again.** Each upload
    returned a digest and went straight onto one screen; nothing remembered it,
    so the second channel that wanted the same photograph got a second trip
    through the uploader and nobody could see what had been used before.

    **A starting point, not a reference.** Choosing one copies it onto the
    screen, the same way a bundled background does. Editing or deleting a
    library entry therefore changes no wall that already uses it — nothing on a
    television should move because somebody tidied a list.
    """

    __tablename__ = "saved_background"
    __table_args__ = (
        CheckConstraint(
            "category IN ('calm', 'energy', 'celebration', 'seasonal', 'brand', 'scenes')",
            name="saved_background_category_valid",
        ),
        Index("uq_saved_background_name", "organization_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(16))

    #: The background itself, in the same shape a screen stores — validated
    #: through `appearance.Background` on the way in, so a library entry is
    #: never something a screen would refuse.
    background: Mapped[dict] = mapped_column(JSONB)

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<SavedBackground {self.name!r} {self.category}>"
