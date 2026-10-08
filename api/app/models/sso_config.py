from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SsoConfig(Base):
    """OIDC settings, managed by an admin in the app rather than at deploy time.

    Environment variables would be the obvious home, but an admin of a
    self-hosted deployment should not have to SSH into a server, edit a file,
    and restart containers to connect their identity provider. Keeping it in
    the database also puts SSO in the same place as the data connectors, so
    there is one mental model for external connections instead of two.

    The consequence is that this must be read per request, not cached at boot —
    otherwise saving a change would not take effect, which defeats the point.

    **What is left here is only what is about signing in.** Whether it is on, what
    the button says, whether an unknown but authenticated person gets an account,
    and whether passwords still work. The identity of the provider and the secret
    used to talk to it belong to the connection, not to this feature — see
    `oauth_client`.
    """

    __tablename__ = "sso_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id"), unique=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")

    #: Which provider connection signs people in — `microsoft`, `google`, `oidc`.
    #:
    #: **The credential itself is not here any more.** It lives on `oauth_client`,
    #: which is the one row for everything a deployment does with that provider.
    #: An admin who wants Microsoft SSO and Excel makes one app registration in
    #: Entra and enters it once; before this, the same client id and secret went
    #: into two forms on the same page, and rotating a leaked secret was two jobs.
    #:
    #: NULL means single sign-on is not pointed at anything yet, which is what
    #: every deployment starts as.
    provider: Mapped[str | None] = mapped_column(String(64))

    scopes: Mapped[str] = mapped_column(
        String(500), server_default="openid profile email"
    )
    button_label: Mapped[str] = mapped_column(
        String(100), server_default="Sign in with SSO"
    )

    # Create an account for anyone who authenticates successfully but has none.
    # Off by default: the safer failure is "a legitimate user asks for access",
    # not "everyone in the tenant silently gains access to sales data".
    auto_provision: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Disables password login for everyone except accounts flagged
    # allow_local_login — see the break-glass note in 03-auth-and-users.md.
    require_sso: Mapped[bool] = mapped_column(Boolean, server_default="false")

    #: Roles from groups: on every sign-in, set the role the person's groups
    #: give — `[{"group": "Sales Managers", "role": "manager"}]`. Off by
    #: default. See `app/sso_roles.py`.
    role_sync: Mapped[bool] = mapped_column(Boolean, server_default="false")
    role_rules: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SsoConfig org={self.organization_id} enabled={self.enabled}>"
