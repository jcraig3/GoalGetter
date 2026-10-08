from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationPreference(Base):
    """One event a person has asked not to hear about.

    **Presence means muted.** Storing only the deviations rather than a row per
    person per event means a new event in the catalogue is on for everybody
    without a backfill, and somebody who has never opened the settings has no
    rows at all. The alternative — materialising every combination — needs a
    migration each time the catalogue grows, and gets it wrong for anybody
    created between the migration and the deploy.

    **Preferences filter at read, never at creation.** The tempting version
    suppresses the row when the recipient has muted the event, which saves
    writes and is wrong: the same rows feed the Achievements page and the wall
    screens, so muting your own achievements would quietly remove you from what
    the *organization* celebrates. A preference is about your bell, not about
    whether the thing happened.

    That also makes unmuting show what you missed, which is the behaviour
    somebody re-enabling a setting expects.
    """

    __tablename__ = "notification_preference"

    #: Composite primary key. A person can mute an event once; there is no
    #: second state to record, so the pair *is* the row and no surrogate id or
    #: `enabled` boolean is needed.
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_key: Mapped[str] = mapped_column(String(64), primary_key=True)

    def __repr__(self) -> str:
        return f"<NotificationPreference user={self.user_id} muted={self.event_key}>"
