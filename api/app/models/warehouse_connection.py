"""The warehouse a deployment reads from, held once.

**The same split as the spreadsheet accounts, for the same reason.** A Snowflake
credential is an account identifier, a username, a private key, a warehouse and a
role — six answers nobody wants to give again for the second table they connect.
So the credential is the *connection*, and each query is a `data_source` hanging
off it: connect once, then add queries.

**Its own table rather than a row in `oauth_client`.** That one is a registration
with an OAuth provider — client id, client secret, issuer, tenant — and Snowflake
is none of those. A row there would carry every OAuth column null and a provider
key absent from the catalogue in `providers.py`.

**Three ways to prove who we are, and no setting that says which.** Whichever
credential is stored is the one used, matching `SqlSecrets` and every other such
pair in this codebase — a mode column could disagree with the credential beside
it, and then the row says one thing and the driver does another.

A private key is the durable answer: Snowflake blocks password-only sign-ins for
service users, so it is not a hardening option there but the only thing that
lasts. A programmatic access token is the one a person can mint for themselves
without an admin, which makes it how most connections get tested — but it expires,
and it can be bound to a network-policy bypass that lapses sooner still. The
password column is the legacy half, for a warehouse that still allows one.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: The kinds of warehouse this table can hold a connection for.
#:
#: One today. A column rather than an assumption because Redshift and BigQuery are
#: the same shape of problem and would otherwise each want their own table.
WAREHOUSE_PROVIDERS = ("snowflake",)


class WarehouseConnection(Base):
    """One organization's credential for one kind of warehouse."""

    __tablename__ = "warehouse_connection"
    __table_args__ = (
        # **Connect once, add queries.** Two credentials for one warehouse would
        # make "which is this source reading as?" unanswerable from the row.
        UniqueConstraint(
            "organization_id", "provider", name="uq_warehouse_connection_org_provider"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)

    #: From the Snowflake URL, minus `.snowflakecomputing.com`.
    account: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    username: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")

    #: The PEM private key. Encrypted, and never returned by any endpoint — the
    #: API reports whether one is set, the same way it does for every secret.
    private_key_encrypted: Mapped[str | None] = mapped_column(Text)
    key_passphrase_encrypted: Mapped[str | None] = mapped_column(Text)

    #: A Snowflake programmatic access token. Its own column rather than reusing
    #: `password_encrypted`, because the driver does not treat them alike: a PAT
    #: goes to `AuthByPAT` via the `token` parameter under its own authenticator,
    #: and one handed over as a password is simply rejected. Sharing the column
    #: would leave nothing able to tell which of the two was stored.
    token_encrypted: Mapped[str | None] = mapped_column(Text)

    #: The legacy half. Snowflake blocks password-only sign-ins for service users,
    #: so this exists for a warehouse that still allows one rather than as an
    #: equal option.
    password_encrypted: Mapped[str | None] = mapped_column(Text)

    #: The compute that runs the query. Blank means the user's default, which is
    #: what Snowflake does when a connection names none.
    warehouse: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    role: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")

    #: Optional, because a fully-qualified query does not need it — and a database
    #: that silently disagrees with the query is a trap rather than a convenience.
    database: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<WarehouseConnection {self.provider} {self.account!r}>"
