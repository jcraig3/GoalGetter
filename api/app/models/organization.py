from sqlalchemy import Boolean, CheckConstraint, SmallInteger, String, false, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    """The company using this deployment. Normally exactly one row.

    It is a real table rather than configuration because its period settings
    are load-bearing: timezone, week_starts_on, and fiscal_year_start_month
    decide what "this week" and "this quarter" mean. Every leaderboard and goal
    calculation reads them, so they belong beside the data rather than in an
    environment variable that could drift from what historical rows assumed.
    """

    __tablename__ = "organization"
    __table_args__ = (
        CheckConstraint("week_starts_on BETWEEN 0 AND 6", name="week_starts_on_range"),
        CheckConstraint(
            "fiscal_year_start_month BETWEEN 1 AND 12",
            name="fiscal_year_start_month_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))

    #: Overrides for how this looks. Empty means inherit; see
    #: `app/appearance.py`, which owns the shape and the merge.
    appearance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    #: **What plays for a win when the person has no walk-up music** (6.17),
    #: by kind of win — `goal`, `competition`, `recognition`, `occasion` — as
    #: `asset:<sha256>` of a sound in the organization's store. Absent is
    #: silence, as before. See `app/sounds.py`.
    celebration_sounds: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )


    # server_default, not default. `default=` is applied by the ORM in Python
    # and never appears in the schema, so any insert that doesn't go through
    # SQLAlchemy — a seed script, a data migration, a manual fix in psql —
    # hits NOT NULL with nothing to fill it. server_default puts a real
    # DEFAULT on the column.
    timezone: Mapped[str] = mapped_column(String(64), server_default="UTC")
    week_starts_on: Mapped[int] = mapped_column(  # 0=Sunday, 1=Monday
        SmallInteger, server_default="1"
    )
    fiscal_year_start_month: Mapped[int] = mapped_column(
        SmallInteger, server_default="1"
    )
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")

    # ── What an agent may set about themselves ───────────────────────────────
    #
    # **Columns rather than one JSON blob**, unlike `appearance` above.
    # Appearance earned JSON at nineteen fields and growing; this is the
    # complete set of things about a person that are not roster facts, and it
    # is three.
    #
    # **Agents only.** A manager and an admin can already set these for
    # anybody, and a switch that locked an admin out of their own photograph
    # would be a support call rather than a policy.
    #
    # All true by default, because most deployments want what the product did
    # before there was a switch.

    #: Their own photograph. Off suits a company with HR headshots it would
    #: rather keep uniform.
    self_photo: Mapped[bool] = mapped_column(Boolean, server_default=true())
    #: Their nickname and their birthday — the two optional facts about them.
    self_details: Mapped[bool] = mapped_column(Boolean, server_default=true())
    #: The clip that plays when they win. Off suits a floor that has heard one
    #: person's song nine hundred times.
    self_walkup: Mapped[bool] = mapped_column(Boolean, server_default=true())
    #: Whether colleagues can open each other's profiles (9.5) — badges, wins,
    #: points. Off, a profile is seen only by the person and those who manage
    #: them. See `app/people.py`.
    profiles_public: Mapped[bool] = mapped_column(Boolean, server_default=true())

    #: Where this deployment is — "https://goals.acme.com" — set in Settings
    #: (11.7). NULL means `APP_URL` from the environment. See `app/public_url.py`.
    public_url: Mapped[str | None] = mapped_column(String(300))

    #: Is a proxy of the organization's own in front of GoalGetter (Phase
    #: 17)? `direct` or `proxy`; null means `TRUSTED_PROXY_HOPS` from `.env`.
    #: See `net.proxy_hops`.
    proxy_mode: Mapped[str | None] = mapped_column(String(16))
    #: Wrong passwords allowed in five minutes, per account and per device
    #: (Phase 17). Null means the shipped 5 and 20. See `rate_limit.limits`.
    sign_in_limit_account: Mapped[int | None] = mapped_column(SmallInteger)
    sign_in_limit_device: Mapped[int | None] = mapped_column(SmallInteger)

    #: Microsoft Teams, switched on or off as a whole — from the Microsoft 365
    #: box, the way Excel is. Off, nothing is posted to any channel and the
    #: scheduled Teams reads stop; what is configured in the Microsoft Teams
    #: card is kept, ready for when it is back on. Each channel has its own
    #: switch as well.
    #:
    #: **Off by default.** A deployment that has not asked for Teams should not
    #: find it reading its tenant.
    teams_enabled: Mapped[bool] = mapped_column(Boolean, server_default=false())

    #: Password sign-in needs an authenticator code as well. Somebody without
    #: one set up is taken through setup straight after their password. SSO
    #: sign-in is untouched — its second step is the identity provider's.
    require_mfa: Mapped[bool] = mapped_column(Boolean, server_default=false())
    #: Only admins and managers may sign in, by any method (Phase 28). Agents'
    #: sessions stop working the moment it is switched on.
    sign_in_leaders_only: Mapped[bool] = mapped_column(Boolean, server_default=false())

    def __repr__(self) -> str:
        return f"<Organization id={self.id} name={self.name!r}>"
