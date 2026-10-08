"""one connection per provider

Moves the single sign-on credential onto `oauth_client`, so a deployment holds one
client id and secret per provider instead of one per feature.

**What was wrong.** An admin wanting Microsoft SSO *and* Excel made one app
registration in Entra and pasted the same client id and the same client secret into
two different forms on the same page — one writing `sso_config`, the other
`oauth_client`. Neither knew the other existed. Rotating a leaked secret was two
jobs, and nothing on the page said the two rows were the same registration, because
nothing in the code knew they were.

**The backfill is a judgement about existing data, so it asks the data.** Two
columns are new and one credential is moving, and the move has three cases:

* **No SSO credential** — the overwhelmingly common one, since SSO is off by default.
  Nothing moves. `sso_config.provider` stays NULL, meaning "not pointed at anything".

* **An SSO credential and no conflicting connection** — it moves, and the provider is
  inferred from the issuer. A `login.microsoftonline.com` issuer becomes a
  `microsoft` connection with its tenant id pulled out of the URL, so the connection
  is immediately the one Excel would use too. Anything else becomes an `oidc`
  connection carrying its issuer verbatim, which is what keeps Okta, Auth0 and
  Keycloak working exactly as before.

* **An SSO credential and a connection for the same provider already present** — the
  interesting one. They *ought* to be the same registration, and if they are, either
  value is correct. If they are not, one of them is wrong and this migration cannot
  tell which. It keeps the **connection's** credential and does not overwrite it,
  because that one has live refresh tokens hanging off it: replacing its client id
  would invalidate every one of them and break working data sources, while the worst
  case on the other side is that SSO — which is off unless somebody enabled it —
  needs its secret re-entered once. It still fills in `tenant_id`/`issuer` on that
  row if they are empty, since those are new columns and cannot conflict.

An incomplete SSO credential — a secret with no client id, which is what a
half-finished setup leaves behind — is treated as nothing to move, because it is.

**Reversible.** The downgrade puts the columns back and copies the credential of
whichever connection `sso_config.provider` names back into `sso_config`, so a
deployment that upgrades and rolls back keeps working sign-on.
"""

from urllib.parse import urlparse

import sqlalchemy as sa
from alembic import op

revision = "a1c4f7b90e32"
down_revision = "dae5ed662199"
branch_labels = None
depends_on = None


MICROSOFT_HOSTS = ("login.microsoftonline.com", "sts.windows.net")


def _tenant_from_issuer(issuer: str) -> str:
    """The tenant id sitting in the middle of a Microsoft issuer URL.

    `https://login.microsoftonline.com/<tenant>/v2.0` — the first path segment.
    Returns empty for anything that does not look like one, and the caller then
    treats the connection as a generic OIDC provider rather than guessing.
    """
    parts = [p for p in urlparse(issuer).path.split("/") if p]
    return parts[0] if parts else ""


def _provider_for(issuer: str) -> str:
    host = (urlparse(issuer).hostname or "").lower()
    return "microsoft" if host in MICROSOFT_HOSTS else "oidc"


def upgrade() -> None:
    op.add_column("oauth_client", sa.Column("tenant_id", sa.String(200), nullable=True))
    op.add_column("oauth_client", sa.Column("issuer", sa.String(500), nullable=True))
    op.add_column("sso_config", sa.Column("provider", sa.String(64), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT organization_id, issuer, client_id, client_secret_encrypted "
            "FROM sso_config"
        )
    ).mappings().all()

    for row in rows:
        secret = row["client_secret_encrypted"]
        client_id = row["client_id"]
        issuer = (row["issuer"] or "").rstrip("/")
        org_id = row["organization_id"]

        # A secret with no client id is a setup somebody abandoned half-way. There
        # is nothing usable to move and pretending otherwise would create a
        # connection that can never authenticate.
        if not secret or not client_id:
            continue

        provider = _provider_for(issuer)
        tenant = _tenant_from_issuer(issuer) if provider == "microsoft" else ""
        # Only a generic provider needs its issuer kept: Microsoft's is rebuilt
        # from the tenant id, and storing both would be two places to disagree.
        stored_issuer = "" if provider == "microsoft" else issuer

        existing = connection.execute(
            sa.text(
                "SELECT id, tenant_id, issuer FROM oauth_client "
                "WHERE organization_id = :org AND provider = :provider"
            ),
            {"org": org_id, "provider": provider},
        ).mappings().first()

        if existing is None:
            connection.execute(
                sa.text(
                    "INSERT INTO oauth_client "
                    "(organization_id, provider, client_id, client_secret_encrypted, "
                    " tenant_id, issuer, created_at, updated_at) "
                    "VALUES (:org, :provider, :client_id, :secret, :tenant, :issuer, "
                    " now(), now())"
                ),
                {
                    "org": org_id,
                    "provider": provider,
                    "client_id": client_id,
                    "secret": secret,
                    "tenant": tenant or None,
                    "issuer": stored_issuer or None,
                },
            )
        else:
            # Keep the connection's own credential — see the module docstring. Only
            # fill the columns that did not exist a moment ago and so cannot clash.
            connection.execute(
                sa.text(
                    "UPDATE oauth_client SET "
                    "  tenant_id = COALESCE(NULLIF(tenant_id, ''), :tenant), "
                    "  issuer = COALESCE(NULLIF(issuer, ''), :issuer) "
                    "WHERE id = :id"
                ),
                {
                    "id": existing["id"],
                    "tenant": tenant or None,
                    "issuer": stored_issuer or None,
                },
            )

        connection.execute(
            sa.text("UPDATE sso_config SET provider = :provider WHERE organization_id = :org"),
            {"provider": provider, "org": org_id},
        )

    op.drop_column("sso_config", "issuer")
    op.drop_column("sso_config", "client_id")
    op.drop_column("sso_config", "client_secret_encrypted")


def downgrade() -> None:
    op.add_column("sso_config", sa.Column("issuer", sa.String(500), nullable=True))
    op.add_column("sso_config", sa.Column("client_id", sa.String(500), nullable=True))
    op.add_column(
        "sso_config", sa.Column("client_secret_encrypted", sa.String(2000), nullable=True)
    )

    # Copy back from whichever connection was signing people in, so a rollback
    # leaves working sign-on rather than a config that validates and cannot
    # authenticate. Microsoft's issuer is rebuilt from the tenant id, which is
    # where it went on the way up.
    op.get_bind().execute(
        sa.text(
            "UPDATE sso_config s SET "
            "  client_id = c.client_id, "
            "  client_secret_encrypted = c.client_secret_encrypted, "
            "  issuer = COALESCE( "
            "    NULLIF(c.issuer, ''), "
            "    CASE WHEN c.tenant_id IS NOT NULL AND c.tenant_id <> '' "
            "         THEN 'https://login.microsoftonline.com/' || c.tenant_id || '/v2.0' "
            "    END) "
            "FROM oauth_client c "
            "WHERE c.organization_id = s.organization_id AND c.provider = s.provider"
        )
    )

    op.drop_column("sso_config", "provider")
    op.drop_column("oauth_client", "issuer")
    op.drop_column("oauth_client", "tenant_id")
