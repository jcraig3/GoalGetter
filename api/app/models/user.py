from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.custom_role import CustomRole
    from app.models.stored_asset import StoredAsset

from app.models.base import Base, TimestampMixin

# Three roles, each with a distinct job:
#
#   agent    the people whose performance is measured — the players
#   manager  sets goals, manages agents, moves people between teams
#   admin    controls the deployment itself: settings, integrations, users
#
# A `viewer` role existed for wall-mounted TV displays. It was dropped because
# displays authenticate with a signed URL rather than an account, so the role
# protected nothing and was one more cell in every permission table.
ORG_ROLES = ("admin", "manager", "agent")
#: `deactivated` — the directory reported this account turned off.
#:
#: **Set by the sync, cleared by the sync.** Distinct from `suspended`, which an
#: admin chose: re-enabling the account upstream brings a deactivated person back
#: by itself, and doing that to a suspension would overturn somebody's decision.
USER_STATUSES = ("invited", "active", "suspended", "deactivated")


class UserAccount(Base, TimestampMixin):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(
            f"org_role IN {ORG_ROLES}",
            name="org_role_valid",
        ),
        CheckConstraint(
            f"status IN {USER_STATUSES}",
            name="status_valid",
        ),
        # Both halves or neither. A month with no day is a date nothing can
        # mark, and the sweep would have to decide what to do with it on every
        # pass, for ever.
        CheckConstraint(
            "(birthday_month IS NULL AND birthday_day IS NULL) OR "
            "(birthday_month BETWEEN 1 AND 12 AND birthday_day BETWEEN 1 AND 31)",
            name="birthday_whole",
        ),
        # Email uniqueness is case-insensitive, enforced by the database rather
        # than by remembering to lowercase in application code. Without this,
        # Jayden@x.com and jayden@x.com become two accounts.
        Index(
            "uq_user_account_org_email_lower",
            "organization_id",
            text("lower(email)"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id"), index=True
    )

    # One team per agent. A join table would allow several, but every
    # leaderboard would then have to answer "does this person count twice?" —
    # and a sales floor puts someone on one team. If multi-team is ever needed,
    # adding a join table is a contained change; unpicking one that
    # aggregations already depend on is not.
    #
    # Nullable, because someone invited but not yet placed is a real state —
    # and one worth surfacing, since they are silently missing from every team
    # leaderboard until assigned.
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id"), index=True
    )
    #: Their office while they have no team (Phase 28) — put there from
    #: Microsoft 365 or a Team linked as an office. On a team, the team's
    #: office is theirs and this is ignored.
    office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="SET NULL"), index=True
    )

    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(200))
    # server_default so the schema itself carries the default — see the note
    # in organization.py.
    #: What the directory said this person does, when it said anything.
    #:
    #: **Copied for filtering, not for comparing.** `app/directory/apply.py`
    #: deliberately leaves these out of its difference check: they are not facts
    #: this product owns, so reporting a mismatch would be reporting a change
    #: nobody here can act on. Storing them is a different job — the People list
    #: filters on them, and a filter cannot join to a table that only holds the
    #: people who arrived through a sync.
    #:
    #: Empty for anybody invited by hand, which is also what "any" means to a
    #: filter — so the two cases need no special handling.
    #: What people actually call them, if it is not their name.
    #:
    #: Empty rather than NULL, like `job_title` below: "has not set one" and
    #: "set it to nothing" are the same state, and a nullable column would make
    #: every reader decide which it was holding.
    #:
    #: Short on purpose — a nickname is what a floor shouts across a room, not
    #: a second biography.
    nickname: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=""
    )

    #: A month and a day, and deliberately no year.
    #:
    #: **A wall saying "happy birthday" needs the date; nothing here needs
    #: somebody's age.** A column holding it is a column that leaks it — to
    #: every admin, every export, and every later feature that assumed it was
    #: there to be used. Both halves or neither; the CHECK says so.
    birthday_month: Mapped[int | None] = mapped_column(Integer)
    birthday_day: Mapped[int | None] = mapped_column(Integer)

    #: When they started, year and all.
    #:
    #: **The asymmetry with a birthday is the point.** "Three years today" is
    #: the whole of what a work anniversary says, so the year is the feature —
    #: and when somebody joined is a company fact rather than a personal one.
    started_on: Mapped[date | None] = mapped_column(Date)

    job_title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    department: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    office_location: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default=""
    )

    #: The photograph the directory has, and the one somebody chose instead.
    #:
    #: **Two columns rather than one, and that is what makes "revert" mean
    #: anything.** With a single slot, a directory sync would overwrite the
    #: headshot somebody uploaded, or an upload would vanish at three the next
    #: morning — and there would be nothing to revert *to*. Kept apart, the sync
    #: owns one and the person owns the other.
    #:
    #: The custom one wins where it exists; otherwise the tenant's; otherwise
    #: initials. See `photo_of`.
    tenant_photo_image_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stored_asset.id", ondelete="SET NULL")
    )
    custom_photo_image_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stored_asset.id", ondelete="SET NULL")
    )

    #: Graph's own tag for the tenant photo, so a sync can skip downloading one
    #: it already has. Four hundred and fifty faces is four hundred and fifty
    #: round trips the first time and none after it.
    tenant_photo_etag: Mapped[str | None] = mapped_column(String(120))

    #: Joined eagerly so a roster does not become one query per face. Safe only
    #: because `StoredAsset.data` is deferred — without that this would drag the
    #: whole JPEG into every list of people.
    tenant_photo: Mapped["StoredAsset | None"] = relationship(
        foreign_keys=[tenant_photo_image_id], lazy="joined"
    )
    custom_photo: Mapped["StoredAsset | None"] = relationship(
        foreign_keys=[custom_photo_image_id], lazy="joined"
    )

    @property
    def photo_digest(self) -> str | None:
        """The image to show, or `None` for initials.

        Chosen over tenant: somebody picking a photograph of themselves is more
        recent and more deliberate than whatever was uploaded when they joined.
        """
        chosen = self.custom_photo or self.tenant_photo
        return chosen.sha256 if chosen else None

    org_role: Mapped[str] = mapped_column(String(20), server_default="agent")
    status: Mapped[str] = mapped_column(String(20), server_default="invited")

    # Null for SSO-only accounts. A user may have both, so these coexist rather
    # than being one "credentials" column.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    external_subject_id: Mapped[str | None] = mapped_column(String(255), index=True)

    # Break-glass is role-based rather than a per-account flag: when "require
    # SSO" is on, admins keep password sign-in. See app/sign_in.py.

    #: The password was chosen by an admin, not by them (11.2). Every request
    #: but choosing their own is refused until they do — see `sessions.py`.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Soft delete. Users are never removed — their goals and historical
    # leaderboard positions are part of the company's record.
    #: When an admin hid this person, or NULL.
    #:
    #: **Hidden, not archived**, and the word matters because this schema uses
    #: `archived_at` on nine other tables to mean "the thing itself is retired".
    #: A person is not retired, they are excluded — they keep their history, their
    #: facts keep counting toward their team's totals, and one click brings them
    #: back. See `aggregate._scored` for what excluded actually means.
    #:
    #: **The sync never writes this.** A decision an admin made outranks anything
    #: the directory says, which is the same rule `directory.DECIDED` states for
    #: staged people.
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Two-step sign-in ─────────────────────────────────────────────────────
    #
    # For password sign-in only: SSO gets its second step from the identity
    # provider. See `app/totp.py`.

    #: The authenticator secret, encrypted. Set once a code has confirmed it.
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    #: A secret shown in a QR code and not yet confirmed. Kept apart from the
    #: real one, so starting setup again never breaks a working authenticator.
    mfa_pending_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Hashes of the recovery codes not yet used.
    mfa_recovery_hashes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    #: The last 30-second step a code was accepted for — what stops a replay.
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger)

    #: A built-in role, narrowed — applies while its base is `org_role`. See
    #: `app/roles.py`.
    custom_role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("custom_role.id", ondelete="SET NULL")
    )
    custom_role: Mapped["CustomRole | None"] = relationship(lazy="select")

    def __repr__(self) -> str:
        return f"<UserAccount id={self.id} email={self.email!r} role={self.org_role}>"
