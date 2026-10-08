"""The app registration a deployment makes with a provider.

**There is no hosted relay, deliberately.** GoalGetter is installed on somebody
else's server, so there is no central service holding a Google client secret on
their behalf — which means each deployment registers its own OAuth application
once, and pastes the two values in here. That is the one manual step in the whole
integration story, and it is unavoidable without becoming a SaaS.

Everything after it is a sign-in button: an admin clicks *Connect Google Sheets*,
approves it, and comes back with a source that works. Registering the app is
per-deployment; connecting a source is per-source and takes seconds.

**Keyed by provider, not by connector.** One Google registration serves Sheets and
whatever Google connector comes next, so a second Google integration costs nothing
and there is one place to rotate a leaked secret.

**And not by feature either, which is what this row became.** Single sign-on used to
keep its own copy of a client id and secret in `sso_config`, so an admin who wanted
Microsoft SSO *and* Excel made one app registration in Entra and pasted the same two
values into two different forms on the same page — with neither knowing the other
existed, and rotating a leaked secret being two jobs.

One app registration can serve both: a registration holds several redirect URIs, and
delegated scopes are asked for per authorization request rather than fixed on the
app. So the credential lives here once, and what it powers — signing in, reading a
spreadsheet, and later syncing people — is a property of the connection rather than
a reason to have another one.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OauthClient(Base, TimestampMixin):
    """One provider's client id and secret, for this organization."""

    __tablename__ = "oauth_client"
    __table_args__ = (
        # One registration per provider. Two would mean the connect flow had to
        # choose, and the choice would be arbitrary.
        #
        # No separate index on `organization_id`: this constraint's index leads
        # with that column, so a lookup by organization alone uses it as a
        # prefix. A second index would only ever be written to, never read.
        UniqueConstraint("organization_id", "provider", name="uq_oauth_client_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )

    #: Which provider, matching a connector's declared `oauth.provider` —
    #: `google`, `microsoft`. Not an enum: providers arrive by shipping a
    #: connector, and a database enum would need a migration to release one.
    provider: Mapped[str] = mapped_column(String(64), nullable=False)

    client_id: Mapped[str] = mapped_column(String(500), nullable=False)

    #: Microsoft's directory (tenant) id, and nothing else's.
    #:
    #: Here rather than in `sso_config` because **both halves of a Microsoft
    #: connection need it and neither had it properly**. Single sign-on needs it to
    #: build the issuer it validates tokens against; the Excel connector had
    #: `/common/` hard-coded in its endpoints, which is right for a multi-tenant app
    #: registration and quietly wrong for a single-tenant one.
    #:
    #: Empty for a provider that has no such concept, which is most of them.
    tenant_id: Mapped[str | None] = mapped_column(String(200))

    #: The OIDC discovery base, for a connection that signs people in.
    #:
    #: Usually derived rather than stored — Microsoft's is a template around
    #: `tenant_id` — so this holds only what cannot be worked out: the issuer of an
    #: identity provider we ship no connector for. Okta, Auth0, Keycloak. See
    #: `app.providers.issuer_for`, which is the one place that decides.
    issuer: Mapped[str | None] = mapped_column(String(500))

    #: Encrypted with the same key as everything else in `connector_credential`.
    #: Reported to the API as a boolean, never read back — see `sso_config`, which
    #: makes the same trade for the same reason.
    client_secret_encrypted: Mapped[str] = mapped_column(String(2000), nullable=False)

    #: Whether this connection syncs people from the directory.
    #:
    #: **The one capability that is stored rather than derived**, and the exception
    #: is worth stating. Signing in is on because `sso_config` says so; reading data
    #: is on because a source uses it. There is nothing equivalent here — a
    #: connection existing says nothing about whether a company wants two hundred
    #: accounts proposed from it, and that has to be somebody's decision rather than
    #: a side effect of connecting Excel.
    directory_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    #: How many hours between reads of this directory.
    #:
    #: **Per connection rather than a constant**, which is what it was. Daily is
    #: still the default and still the right answer for most deployments — people
    #: join and leave on a scale of days, and a tenant is somebody else's API
    #: quota — but the two ends of the range are both real: a company onboarding a
    #: cohort every morning wants hourly, and one that hires twice a year does not
    #: want its directory read three hundred and sixty-five times to notice.
    directory_sync_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="24"
    )

    #: Whether the sync skips accounts holding no licence.
    #:
    #: **A licence is the closest thing a directory has to "this person works
    #: here."** A tenant is full of accounts nobody signs in with — service
    #: accounts given a mailbox, shared boxes, leavers disabled but not deleted —
    #: and most carry no licence. Skipping them keeps the approval queue to
    #: people, which for a company of six hundred is the difference between a
    #: list somebody reads and one they wave through.
    #:
    #: Off by default, because it changes who a sync proposes and a deployment
    #: already running should not silently start ignoring people.
    directory_ignore_unlicensed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    #: How the directory sync and outgoing mail authenticate.
    #:
    #: `application` — acts as itself, needs no account, and needs a Privileged
    #: Role Administrator to consent once. `delegated` — acts as one signed-in
    #: account, which a Cloud Application Administrator can set up start to
    #: finish, and which stops if that account is disabled.
    #:
    #: **Decided before the registration is provisioned, and changing it means
    #: re-provisioning.** The two permission sets cannot share a registration:
    #: consent is all-or-nothing, and an admin who can grant every delegated
    #: permission can grant no app role — so a mixed set greys the consent button
    #: and nothing is granted at all.
    #: Whether each directory sync applies the Microsoft Teams mirror itself, or
    #: leaves it to be previewed and applied by hand. Off by default: a mirror
    #: moves people between teams, and a deployment should see that happen once
    #: before trusting it to happen at three in the morning.
    directory_mirror_teams: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    #: When the Microsoft Teams structure was last read, and what could not be
    #: read — "grant Channel.ReadBasic.All" is worth showing, an empty list is not.
    teams_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    teams_read_note: Mapped[str | None] = mapped_column(String(1000))

    #: The account announcements are posted to Teams channels as, when a
    #: channel is picked rather than reached through a Workflows link. Its own
    #: sign-in, like Excel's: see `app/teams_account.py`.
    teams_post_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    teams_post_connected_as: Mapped[str] = mapped_column(
        String(320), nullable=False, server_default=""
    )

    directory_auth_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="application"
    )

    #: The refresh token for the account this acts as in `delegated` mode.
    #: Null in `application` mode, where nothing signs in.
    tenant_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)

    #: Whose account that is, for the screen to name. Not a credential.
    tenant_connected_as: Mapped[str] = mapped_column(
        String(320), nullable=False, server_default=""
    )

    #: The refresh token for the account Excel reads workbooks as.
    #:
    #: **A second slot rather than a reuse of the one above**, because they answer
    #: different questions. `tenant_*` is the account the directory sync acts as
    #: and exists only in delegated mode; this one exists whenever somebody wants
    #: to read a spreadsheet, in either mode. `Files.Read.All` is granted to the
    #: registration as a *delegated* permission, so a signed-in user is not a
    #: design choice here — it is the only thing that token type works with.
    files_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)

    #: Whose files those are, for the screen to name. Not a credential.
    #:
    #: Worth showing prominently: it decides which workbooks can be browsed and
    #: read, so "why can I not see that sheet?" is answered by reading it.
    files_connected_as: Mapped[str] = mapped_column(
        String(320), nullable=False, server_default=""
    )

    #: The refresh token for the Google account spreadsheets are read as.
    #:
    #: Same move as `files_*` above and for the same reason: one account for the
    #: deployment rather than one per spreadsheet. Google has no delegated/
    #: application split, so there is no mode question here — only whether it is a
    #: person's account or the service account below.
    sheets_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)

    #: A Google service-account key, as the whole JSON file.
    #:
    #: **The better half of the pair for Google**, and the one with no expiry
    #: story: a robot account with its own address, which a spreadsheet is shared
    #: with exactly as it would be with a colleague. It belongs to the
    #: organization rather than to whoever happened to click, and it sidesteps
    #: Google's verification review that an External consent screen runs into.
    #:
    #: Stored as text rather than parsed: it is Google's document, not ours, and a
    #: model listing the keys we know about today would silently drop tomorrow's.
    sheets_service_account_encrypted: Mapped[str | None] = mapped_column(Text)

    #: Whose account, or which service account, for the screen to name.
    sheets_connected_as: Mapped[str] = mapped_column(
        String(320), nullable=False, server_default=""
    )

    #: Which mailbox outgoing mail is sent as.
    #:
    #: **Required when sending is on, never defaulted.** An application has no
    #: mailbox of its own, so there is nothing to fall back to — and guessing
    #: would mean a first invitation failing on an address nobody chose.
    mail_from: Mapped[str] = mapped_column(
        String(320), nullable=False, server_default=""
    )

    #: Whether this connection sends mail. Stored for the same reason directory
    #: sync is: there is nothing else to read it off, and a connection existing
    #: says nothing about whether a company wants its invitations sent this way.
    mail_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    #: Who set it up, for the audit trail. NULL once that account is deleted.
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    #: When a token was last successfully obtained or refreshed with it.
    #:
    #: Not required for anything to work — it is here because "we pasted these in
    #: three months ago and nothing has ever worked" and "these worked until
    #: Tuesday" are different problems, and the settings page cannot tell them
    #: apart without it.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<OauthClient {self.provider!r} org={self.organization_id}>"
