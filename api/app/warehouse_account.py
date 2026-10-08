"""The warehouse credential, held once for the deployment.

**Connect once, add queries.** The Snowflake analogue of `excel_account.py`: an
account identifier, a username, a key, a warehouse and a role are six answers
nobody wants to give again for the second table they connect — so they live on the
connection, and each source is a name and a query.

**Read-only is enforced three ways and none of them is trust.** The query must
start with SELECT or WITH, a regex refuses every writing verb, and the connection
runs inside a read-only transaction with a statement timeout. See `connectors/sql.py`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.connectors.sql import KeyProblem, SqlSecrets, load_private_key
from app.crypto import decrypt, encrypt
from app.models import WarehouseConnection

logger = logging.getLogger(__name__)

__all__ = [
    "FieldProblem",
    "NotConnected",
    "credentials_for",
    "forget",
    "get",
    "is_connected",
    "save",
]


class NotConnected(Exception):
    """No warehouse is connected yet, phrased for the admin who has to."""


class FieldProblem(Exception):
    """A connection field holding something that is not what it asks for."""


#: Fields on the connection that name a Snowflake object, not a statement.
#:
#: **A query pasted into one of these is the mistake this form invites.** Step 2,
#: where a query belongs, only appears once the connection is green — so somebody
#: arriving with SQL in hand meets three boxes, none of them the right one, and
#: "Database" is the one that sounds closest. It then fails as a connection error
#: naming a host, which is nowhere near the truth.
_IDENTIFIER_FIELDS = ("warehouse", "role", "database")


def _check_identifier(field: str, value: str) -> None:
    """Refuse a value that is plainly a statement rather than a name.

    Deliberately narrow: whitespace and semicolons. A Snowflake identifier has
    neither, and anything cleverer would start rejecting the legitimately odd
    names that quoted identifiers allow.
    """
    if not value:
        return
    if ";" in value or any(c.isspace() for c in value):
        raise FieldProblem(
            f"The {field} field takes a name, not a query — it looks like SQL "
            f"was pasted here. Connect first, then write the query in step 2."
        )


def get(db: DbSession, org_id: int, provider: str = "snowflake") -> WarehouseConnection | None:
    return db.scalar(
        select(WarehouseConnection).where(
            WarehouseConnection.organization_id == org_id,
            WarehouseConnection.provider == provider,
        )
    )


def is_connected(db: DbSession, org_id: int, provider: str = "snowflake") -> bool:
    """Whether there is a credential good enough to attempt a connection.

    An account and a username and *something* to authenticate with. A row holding
    only an account name is a half-filled form, not a connection, and reporting it
    as one is how a source claims to be set up and fails on its first sync.
    """
    row = get(db, org_id, provider)
    return bool(
        row
        and row.account.strip()
        and row.username.strip()
        and (row.private_key_encrypted or row.token_encrypted or row.password_encrypted)
    )


def save(
    db: DbSession,
    org_id: int,
    *,
    provider: str = "snowflake",
    account: str,
    username: str,
    warehouse: str = "",
    role: str = "",
    database: str = "",
    private_key: str | None = None,
    key_passphrase: str | None = None,
    token: str | None = None,
    password: str | None = None,
) -> WarehouseConnection:
    """Create or update the connection.

    **`None` means "leave it alone", empty string means "clear it".** The same
    rule `oauth.store_client` uses, and for the same reason: an admin fixing a
    typo in the warehouse name must not have to find the private key again.

    **The key is parsed before it is stored.** A bad one fails here, in front of
    the person who pasted it, rather than as an authentication error at three in
    the morning against a warehouse nobody is watching.

    **Storing one credential clears the others.** Three could be present at once
    otherwise, and which one authenticates would be the driver's choice rather
    than anybody's decision — a Snowflake that has stopped accepting passwords
    then fails in a way that reads as "the key is wrong". Whichever was set last
    is the one meant.
    """
    for field, value in (
        ("warehouse", warehouse),
        ("role", role),
        ("database", database),
    ):
        _check_identifier(field, value.strip())

    if private_key:
        # Raises KeyProblem, which the router turns into a 400 naming the fix.
        load_private_key(private_key, key_passphrase or "")

    now = datetime.now(UTC)
    row = get(db, org_id, provider)
    if row is None:
        row = WarehouseConnection(
            organization_id=org_id, provider=provider, created_at=now, updated_at=now
        )
        db.add(row)

    row.account = account.strip()
    row.username = username.strip()
    row.warehouse = warehouse.strip()
    row.role = role.strip()
    row.database = database.strip()
    row.updated_at = now

    if private_key is not None:
        row.private_key_encrypted = encrypt(private_key) if private_key else None
        if private_key:
            row.token_encrypted = None
            row.password_encrypted = None
    if key_passphrase is not None:
        row.key_passphrase_encrypted = encrypt(key_passphrase) if key_passphrase else None
    if token is not None:
        row.token_encrypted = encrypt(token) if token else None
        if token:
            row.private_key_encrypted = None
            row.key_passphrase_encrypted = None
            row.password_encrypted = None
    if password is not None:
        row.password_encrypted = encrypt(password) if password else None
        if password:
            row.private_key_encrypted = None
            row.key_passphrase_encrypted = None
            row.token_encrypted = None

    db.flush()
    return row


def forget(db: DbSession, org_id: int, provider: str = "snowflake") -> None:
    """Drop the connection.

    **The queries stay**, matching what forgetting a spreadsheet account does.
    Their SQL and their column mappings are still correct and still expensive to
    rebuild; what has gone is the ability to run them, and the next sync says so.
    """
    row = get(db, org_id, provider)
    if row is not None:
        db.delete(row)
        db.flush()


def credentials_for(db: DbSession, org_id: int, provider: str = "snowflake") -> dict:
    """What the connector needs to authenticate, as `SqlSecrets` fields.

    Returned as a plain dict because that is what `oauth.ensure_fresh` hands back
    for every other connector, and `sync` builds the credential model from it.
    """
    row = get(db, org_id, provider)
    if row is None:
        raise NotConnected(
            "No Snowflake connection is set up yet. Add one under "
            "Integrations → Snowflake, then come back."
        )
    return {
        "username": row.username,
        "password": decrypt(row.password_encrypted) if row.password_encrypted else "",
        "private_key": decrypt(row.private_key_encrypted)
        if row.private_key_encrypted
        else "",
        "key_passphrase": decrypt(row.key_passphrase_encrypted)
        if row.key_passphrase_encrypted
        else "",
        "token": decrypt(row.token_encrypted) if row.token_encrypted else "",
    }


def secrets_for(db: DbSession, org_id: int, provider: str = "snowflake") -> SqlSecrets:
    """The same, as the model — for code that wants it typed."""
    return SqlSecrets(**credentials_for(db, org_id, provider))


def config_defaults(row: WarehouseConnection) -> dict:
    """The connection's half of a source's config.

    A source carries a name and a query; everything else about *where* to run it
    comes from here. Kept as one function so the router, the connector and the
    test screen cannot disagree about which fields the connection owns.
    """
    return {
        "account": row.account,
        "warehouse": row.warehouse,
        "role": row.role,
        "database": row.database,
    }
