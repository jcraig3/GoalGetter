"""The warehouse connection: set it up once, then add queries.

The Snowflake half of what `routers/excel.py` does for spreadsheets. Same shape,
different credential — an account identifier and a private key rather than a
sign-in, because Snowflake blocks password-only logins for service users.

**The key arrives as text either way.** A `.p8` is a PEM file, so the browser
reads an uploaded one and posts its contents exactly as it would a pasted one.
One endpoint rather than a multipart upload beside a JSON body, and the two input
paths cannot drift apart.

**It never comes back.** The status endpoint reports whether a key is set, the
same way every other secret in this codebase is reported.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app import audit, warehouse_account
from app.connectors.sql import (
    SESSION_QUERY,
    KeyProblem,
    SqlConfig,
    SqlSecrets,
    available_dialects,
    probe_snowflake,
)
from app.db import get_db
from app.models import UserAccount
from app.sessions import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/warehouse", tags=["warehouse"])

PROVIDER = "snowflake"


class WarehouseStatus(BaseModel):
    """Everything the Snowflake panel draws itself from."""

    #: Whether this build can reach Snowflake at all. False means the driver is
    #: absent, and the panel says so rather than offering a form that cannot work.
    available: bool
    connected: bool

    account: str = ""
    username: str = ""
    warehouse: str = ""
    role: str = ""
    database: str = ""

    #: Whether a credential is stored, never what it is.
    private_key_set: bool = False
    token_set: bool = False
    password_set: bool = False

    #: How many queries hang off this connection.
    queries: int = 0


class WarehouseWrite(BaseModel):
    account: str = Field(default="", max_length=200)
    username: str = Field(default="", max_length=200)
    warehouse: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    database: str = Field(default="", max_length=200)

    #: **Omitted means "leave it alone", empty string means "clear it".** The same
    #: rule `oauth.store_client` uses: an admin fixing a typo in the warehouse
    #: name must not have to find the private key again.
    private_key: str | None = Field(default=None, max_length=20000)
    key_passphrase: str | None = Field(default=None, max_length=500)
    token: str | None = Field(default=None, max_length=4000)
    password: str | None = Field(default=None, max_length=500)


def _status(db: DbSession, org_id: int) -> WarehouseStatus:
    from sqlalchemy import func, select

    from app.models import DataSource

    row = warehouse_account.get(db, org_id, PROVIDER)
    queries = (
        db.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(
                DataSource.organization_id == org_id,
                DataSource.connector == PROVIDER,
                DataSource.archived_at.is_(None),
            )
        )
        or 0
    )
    if row is None:
        return WarehouseStatus(
            available=PROVIDER in available_dialects(), connected=False, queries=queries
        )
    return WarehouseStatus(
        available=PROVIDER in available_dialects(),
        connected=warehouse_account.is_connected(db, org_id, PROVIDER),
        account=row.account,
        username=row.username,
        warehouse=row.warehouse,
        role=row.role,
        database=row.database,
        private_key_set=bool(row.private_key_encrypted),
        token_set=bool(row.token_encrypted),
        password_set=bool(row.password_encrypted),
        queries=queries,
    )


@router.get("/snowflake", response_model=WarehouseStatus)
def read_connection(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> WarehouseStatus:
    return _status(db, actor.organization_id)


@router.put("/snowflake", response_model=WarehouseStatus)
def save_connection(
    payload: WarehouseWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> WarehouseStatus:
    """Create or update the connection.

    The key is parsed before anything is stored, so a bad one fails here — in
    front of the person who pasted it — rather than as an authentication error at
    three in the morning against a warehouse nobody is watching.
    """
    if not payload.account.strip() or not payload.username.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account identifier and a username are both needed.",
        )

    try:
        warehouse_account.save(
            db,
            actor.organization_id,
            provider=PROVIDER,
            account=payload.account,
            username=payload.username,
            warehouse=payload.warehouse,
            role=payload.role,
            database=payload.database,
            private_key=payload.private_key,
            key_passphrase=payload.key_passphrase,
            token=payload.token,
            password=payload.password,
        )
    except (KeyProblem, warehouse_account.FieldProblem) as problem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
        ) from None

    audit.record(
        db,
        actor=actor,
        action="warehouse.saved",
        request=request,
        provider=PROVIDER,
        account=payload.account,
    )
    db.commit()
    return _status(db, actor.organization_id)


@router.delete("/snowflake", status_code=status.HTTP_204_NO_CONTENT)
def forget_connection(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Response:
    """Drop the credential. **The queries stay.**

    Their SQL and their column mappings are still correct and expensive to
    rebuild; what has gone is the ability to run them, and the next sync says so.
    """
    warehouse_account.forget(db, actor.organization_id, PROVIDER)
    audit.record(
        db, actor=actor, action="warehouse.forgotten", request=request, provider=PROVIDER
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ProbeResult(BaseModel):
    ok: bool
    detail: str


@router.post("/snowflake/test", response_model=ProbeResult)
def test_connection(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ProbeResult:
    """Can we reach it at all, before anybody writes a query?

    **Worth its own button.** Otherwise the first thing that ever tests the
    credential is a query somebody just wrote, and a failure could be the account,
    the key, the role, the warehouse or the SQL — five things at once. This
    narrows it to the four that are not the SQL.

    **It asks what session it got, rather than whether a statement ran.** Snowflake
    separates storage from compute, so a session with no warehouse authenticates
    perfectly and can still run nothing. `SELECT 1` is constant-folded without any
    compute, so it passed in exactly that case — a green tick in front of the one
    misconfiguration this button most needs to catch, and a first query that then
    fails for a reason the tick had just ruled out.
    """
    row = warehouse_account.get(db, actor.organization_id, PROVIDER)
    if row is None or not warehouse_account.is_connected(db, actor.organization_id, PROVIDER):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Fill in the connection and save it before testing.",
        )

    # **Checked here as well as on save, because a row can predate the check.**
    # Left to the driver, a query sitting in the database field comes back as a
    # connection error naming a host, which sends somebody looking at networking
    # for a mistake that is on screen in front of them.
    for field in ("warehouse", "role", "database"):
        try:
            warehouse_account._check_identifier(field, getattr(row, field).strip())
        except warehouse_account.FieldProblem as problem:
            return ProbeResult(ok=False, detail=str(problem))

    config = SqlConfig(
        dialect=PROVIDER,
        host=row.account,
        # **Empty string, not None.** `SqlConfig.database` is a plain `str`, so
        # `or None` turned "no database set" into a validation error and a 500 —
        # and a blank database is the *normal* case, because a fully-qualified
        # query names its own. `_build_url` is what turns "" into an omitted
        # path segment; this layer has no business pre-empting it.
        database=row.database,
        # Supplied by the probe itself; no admin has written a query at this point.
        query=SESSION_QUERY,
        read_mode="full",
        options={
            key: value
            for key, value in (("warehouse", row.warehouse), ("role", row.role))
            if value
        },
    )
    secrets = SqlSecrets(
        **warehouse_account.credentials_for(db, actor.organization_id, PROVIDER)
    )

    result = probe_snowflake(config, secrets)
    return ProbeResult(ok=result.ok, detail=result.detail)
