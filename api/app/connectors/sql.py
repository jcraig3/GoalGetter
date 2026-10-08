"""The SQL connector: read straight from a database.

**The first connector that goes and fetches**, and the one that works when nothing
else can. A self-hosted deployment sits on an internal server, so a SaaS provider
on the public internet cannot post a webhook to it — but an outbound connection to
a reporting replica two racks away needs no inbound access at all. For a lot of
companies this is the only integration that is possible without opening a port.

It is also the honest test of the pull half of the framework: a window that has to
become a query parameter, a result set too big to hold in memory, credentials that
are somebody else's database password, and a schema we discover by asking.

**The admin writes the query.** Not a table name and a column picker — a query.
Somebody who can reach the database already knows what a closed deal looks like in
it, and any abstraction over that is a worse version of SQL that has to be learned
anyway. What the connector insists on is the one thing that is easy to get wrong
and silent when you do: the query must use `:since`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from dataclasses import replace
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from app.connectors.grid import SCAN_ROWS
from app.connectors import (
    ConnectionResult,
    LocalContext,
    SourceField,
    SourceRow,
    Truncated,
    register,
)

#: The databases this connector can speak to, and what each needs installed.
#:
#: A table rather than a hard-coded string because adding one is then a line here
#: plus a dependency, not a rewrite — and because the UI can say *which* are
#: available in this build instead of offering a choice that fails on connect.
#: The same honesty the connector registry itself provides.
class Dialect(NamedTuple):
    """One database this connector can speak to.

    **Three names, because they are three different things**, and conflating two
    of them is what made Snowflake invisible for the whole of 3b: the pip package
    is `snowflake-sqlalchemy`, but what you import is `snowflake.sqlalchemy`.
    `available_dialects` had been deriving the import name from the package name by
    swapping dashes for underscores, which is right for most packages, wrong for
    this one, and wrong *silently* — the dialect simply never appeared, including
    in a build that had installed the driver on purpose.
    """

    #: The SQLAlchemy URL prefix — what goes before `://`.
    prefix: str
    #: What to install. Named in the message when it is missing, so an admin has
    #: something to act on.
    package: str
    #: What to import to find out whether it is there. Not derivable from the
    #: package name, as above.
    module: str


DIALECTS: dict[str, Dialect] = {
    # The first four ship in the default image. The last two are optional extras in
    # `pyproject.toml` — needing system libraries, or rarely wanted — and a build
    # that wants one passes `--build-arg API_EXTRAS="[redshift]"`. Nothing here is
    # offered unless its driver imports, so an absent one is invisible rather than
    # broken.
    "postgresql": Dialect("postgresql+psycopg", "psycopg", "psycopg"),
    "mysql": Dialect("mysql+pymysql", "pymysql", "pymysql"),
    "mariadb": Dialect("mysql+pymysql", "pymysql", "pymysql"),
    "snowflake": Dialect("snowflake", "snowflake-sqlalchemy", "snowflake.sqlalchemy"),
    "redshift": Dialect(
        "redshift+redshift_connector", "sqlalchemy-redshift", "sqlalchemy_redshift"
    ),
    "sqlserver": Dialect("mssql+pyodbc", "pyodbc", "pyodbc"),
}

#: Which dialects this build has actually been run against.
#:
#: **Only PostgreSQL, and saying so is the point.** The dialect table is a URL
#: prefix and a driver name; getting those right is testable without a server and
#: is tested. Whether a driver then holds a real conversation with a real Snowflake
#: is not, and claiming otherwise would be the kind of confidence this project has
#: been bitten by six times. The Test button reports the driver's own words, which
#: is the honest place for that to be found out.
VERIFIED = ("postgresql",)


def available_dialects() -> list[str]:
    """Which dialects this build can actually connect with.

    Checked by import rather than by a list of what we think we shipped, because
    the two drift and the failure mode of the list being wrong is an admin
    filling in a form for a database that was never reachable.
    """
    import importlib.util

    found = []
    for key, dialect in DIALECTS.items():
        try:
            spec = importlib.util.find_spec(dialect.module)
        except (ImportError, ValueError):
            # A submodule whose parent package is absent raises rather than
            # returning None, which would otherwise take the whole registry down
            # at import time on a build without the extra.
            continue
        if spec is not None:
            found.append(key)
    return found


#: How long a query may run before it is cut off.
#:
#: A sync must not be able to hold a connection to somebody's production database
#: open indefinitely. Generous enough for a warehouse scan, short enough that a
#: query with a missing join condition fails rather than becoming an incident.
STATEMENT_TIMEOUT_SECONDS = 120

#: The most rows one sync will read.
#:
#: A query with no useful `WHERE` clause returns the whole table, and without a
#: cap the first sync of a large source becomes an out-of-memory restart. Hitting it
#: raises `Truncated` after the rows that did arrive, which keeps them and stops the
#: watermark advancing past the ones that did not. The fix is a narrower query.
MAX_ROWS = 100_000

#: How many rows to pull from the server at a time.
#:
#: The point of a server-side cursor: `fetch` yields an iterator precisely so a
#: million-row result never exists in this process at once.
CHUNK = 1_000

#: The placeholder the query must use for the window.
#:
#: Bound, never interpolated. The query itself is admin-written and therefore
#: trusted, but the *value* comes from our own scheduling state and formatting it
#: into a string is how a date turns into a syntax error in one locale and a
#: silently empty result in another.
SINCE = "since"

#: Anything that is not a read.
#:
#: The admin supplies both the query and the credentials, so this stops mistakes
#: rather than attackers — a `DELETE` typed into a box labelled "query" should not
#: reach a production database. The real guard is the read-only transaction below;
#: this one exists to fail at configuration time with a sentence somebody can act
#: on rather than at three in the morning with a rollback.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|call|"
    r"merge|replace|vacuum|copy)\b",
    re.IGNORECASE,
)


class SqlConfig(BaseModel):
    """Where the database is and what to ask it.

    Non-secret on purpose: a host somebody typo'd should be visible on the page,
    not encrypted into something only a decrypt call can inspect.

    **The wording lives here, not in the wizard.** Every label, hint and
    placeholder below is carried into the setup form through this model's JSON
    schema, so a connector arrives with its own form rather than needing one
    written for it — which is what the protocol means by generated rather than
    hand-built. It also means the person who knows what `sslmode` is for is the
    person writing the sentence about it.
    """

    dialect: str = Field(
        default="postgresql",
        title="Database type",
        # Only what this build can actually reach. Offering a choice that fails on
        # connect is worse than not offering it, and the list is computed at import
        # because a driver cannot appear while the process is running.
        json_schema_extra={"enum": available_dialects()},
    )
    host: str = Field(default="", title="Host", examples=["db.internal"])
    port: int | None = Field(
        default=None,
        title="Port",
        description="Leave empty for the default.",
        json_schema_extra={"advanced": True},
    )
    database: str = Field(default="", title="Database name")


    query: str = Field(
        default="",
        title="Query",
        description=(
            "Must use :since so each sync only reads what changed. Filter on the "
            "column that says when a row was last modified — not when the event "
            "happened, or an edit to an older row never comes back."
        ),
        examples=[
            "SELECT deal_id, owner_email, amount, closed_on FROM crm.closed_deals WHERE updated_at >= :since"
        ],
        json_schema_extra={"multiline": True},
    )

    #: Whether every run reads the whole result, or only what changed.
    #:
    #: **Carried here so it survives the translation.** A Snowflake source sets it
    #: on its own config, and `_as_sql` copies it across — without that the base
    #: class, which only ever sees this model, could not tell an incremental
    #: source from a full one and would demand `:since` from both.
    #:
    #: `incremental` for a plain database, always: without a window every sync
    #: re-reads the whole table, and there is no form field offering otherwise.
    read_mode: str = Field(
        default="incremental", title="Read mode", json_schema_extra={"hidden": True}
    )

    options: dict[str, str] = Field(
        default_factory=dict,
        title="Driver options",
        description=(
            "One per line, as name=value. For the things every database spells "
            "differently — sslmode, warehouse, role."
        ),
        json_schema_extra={"advanced": True},
    )


class SqlSecrets(BaseModel):
    """Somebody else's database credential. Encrypted at rest, never returned.

    **Three ways to prove who we are, and whichever is present is the one used.**
    A password is what most databases want. A private key is what Snowflake wants —
    it blocks password-only sign-ins for service users outright, so a key is not a
    hardening option there but the only thing that works. A token is Snowflake's
    programmatic access token, which a person can issue to themselves without an
    admin and which therefore tends to be what a first connection is tested with.

    No mode setting, matching every other set of credentials in this codebase: a
    stored key means key-pair, a stored token means PAT, a stored password means
    password, and a setting that could disagree with the credential beside it is
    one more thing to get wrong.
    """

    username: str = Field(
        default="",
        title="Username",
        description="A read-only account. This connector never writes.",
    )
    password: str = Field(
        default="",
        title="Password",
        description="Stored encrypted and never shown again.",
        repr=False,
    )
    private_key: str = Field(
        default="",
        title="Private key",
        description=(
            "The contents of the .p8 file, including the BEGIN and END lines. "
            "Used instead of a password where the database supports it."
        ),
        json_schema_extra={"multiline": True},
        repr=False,
    )
    key_passphrase: str = Field(
        default="",
        title="Key passphrase",
        description="Only for a private key that was encrypted with one.",
        repr=False,
    )
    token: str = Field(
        default="",
        title="Access token",
        description=(
            "A Snowflake programmatic access token. Sent under its own "
            "authenticator, not as a password — the driver will not accept it "
            "as one."
        ),
        repr=False,
    )


class QueryProblem(ValueError):
    """The query cannot be used, and why — in a sentence for an admin."""


def _check_query(query: str, *, require_since: bool = True) -> str:
    """The query, or a refusal that says what to change.

    Two rules, and both exist because their failure is silent:

    **It must be a read.** A write typed into a box labelled "query" runs against
    a production database with the credentials the admin supplied.

    **It must use `:since` — unless the source reads everything on purpose.**
    A pre-aggregated view is read whole every time by design, and demanding a
    window on it would refuse the query its BI team actually wrote. Passing
    `require_since=False` is what a `full` source does, and the cost is stated on
    the form rather than hidden behind a refusal.

    With a window, though: without it every sync re-reads the entire table
    forever — which works, looks fine, and quietly costs a full scan an hour until
    somebody notices the database load. The window is the whole reason `fetch`
    takes one.
    """
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        raise QueryProblem("There is no query yet.")

    # Comments stripped before checking, so `-- delete this later` is not a write
    # and `-- :since` does not count as using the window.
    bare = re.sub(r"--[^\n]*", " ", stripped)
    bare = re.sub(r"/\*.*?\*/", " ", bare, flags=re.DOTALL)

    if not re.match(r"^\s*(select|with)\b", bare, re.IGNORECASE):
        raise QueryProblem(
            "The query has to start with SELECT (or WITH). This connector only "
            "reads."
        )

    found = FORBIDDEN.search(bare)
    if found:
        raise QueryProblem(
            f"The query contains {found.group(0).upper()}, which this connector "
            "will not run. It only reads."
        )

    if require_since and f":{SINCE}" not in bare:
        raise QueryProblem(
            "The query must use :since so each sync only reads what changed — "
            "for example `WHERE updated_at >= :since`. Without it every sync "
            "re-reads everything.\n\n"
            "Use the column that says when a row was last *modified*, not when "
            "the event happened: a deal edited today but closed last week has to "
            "come back, and a query filtered on the close date never returns it."
        )

    return stripped


def _build_url(config: SqlConfig, secrets: SqlSecrets) -> URL:
    """The connection URL, assembled rather than pasted.

    Built with `URL.create` so a password containing `@` or `/` is escaped by
    SQLAlchemy instead of quietly producing a URL that parses into the wrong host
    — which presents as an authentication failure against a server nobody meant to
    contact.

    **Separate from the availability check on purpose.** Most dialects in the table
    have no driver in this image, so a combined function refuses them before
    assembling anything — and then the one part that *is* testable for a database
    this build has never talked to, whether its URL prefix is spelled correctly,
    could not be tested at all. A typo there is a connection attempt against
    nothing.
    """
    prefix = DIALECTS[config.dialect].prefix
    return URL.create(
        prefix,
        username=secrets.username or None,
        # Omitted entirely when a key or a token is in play. A driver given both
        # may prefer the password and fail against a Snowflake that no longer
        # accepts one, which reads as "the key is wrong" and is not.
        password=(
            (secrets.password or None)
            if not (secrets.private_key.strip() or secrets.token.strip())
            else None
        ),
        host=config.host or None,
        port=config.port,
        database=config.database or None,
        query=config.options or {},
    )


def _url(config: SqlConfig, secrets: SqlSecrets) -> URL:
    """The URL, once this build is known to be able to use it."""
    if config.dialect not in DIALECTS:
        raise QueryProblem(
            f"Unknown database type {config.dialect!r}. "
            f"This build knows: {', '.join(sorted(DIALECTS))}."
        )
    if config.dialect not in available_dialects():
        raise QueryProblem(
            f"This build has no driver for {config.dialect} — it needs "
            f"{DIALECTS[config.dialect].package!r} installed in the API image."
        )
    return _build_url(config, secrets)


def _engine(config: SqlConfig, secrets: SqlSecrets):
    """A short-lived engine for one operation.

    `NullPool`, explicitly. A sync runs at most once every few minutes, and a pool
    would hold idle connections open against somebody else's database between runs
    — which shows up in their monitoring rather than ours, and is the sort of thing
    that gets an integration switched off at their end.

    **Not `poolclass=None`**, which reads like "no pool" and means "the default",
    i.e. `QueuePool`. That was here first and the comment above it was wrong;
    checked by asserting the class rather than by re-reading the line.

    No `pool_pre_ping` either: every connection out of a `NullPool` is brand new,
    so pinging it is a round trip to ask whether something a millisecond old is
    still alive.
    """
    return create_engine(
        _url(config, secrets),
        poolclass=NullPool,
        connect_args=_connect_args(config, secrets),
    )


class KeyProblem(ValueError):
    """The private key cannot be used, and why — in a sentence for an admin."""


def load_private_key(pem: str, passphrase: str = "") -> bytes:
    """A PEM private key as the DER bytes Snowflake's driver wants.

    **Parsed here so a bad key fails at save time**, in front of the person who
    pasted it, rather than as an authentication error at three in the morning
    against a warehouse nobody is watching. The same trade the Google service
    account key makes.

    Raised as `KeyProblem` with wording an admin can act on: the three ways this
    goes wrong are a public key pasted instead of a private one, a passphrase
    missing for an encrypted key, and a wrong passphrase — and they are
    indistinguishable from the exception types alone.
    """
    from cryptography.hazmat.primitives import serialization

    text_key = (pem or "").strip()
    if not text_key:
        raise KeyProblem("No private key was given.")
    if "PUBLIC KEY" in text_key:
        raise KeyProblem(
            "That is a public key. Snowflake keeps the public half; GoalGetter "
            "needs the private one — the .p8 file, not the .pub."
        )

    secret = passphrase.encode() if passphrase else None
    try:
        key = serialization.load_pem_private_key(text_key.encode(), password=secret)
    except TypeError:
        # cryptography raises TypeError for "encrypted but no password given"
        # and for "password given but the key is not encrypted".
        raise KeyProblem(
            "That key is encrypted, so it needs its passphrase — or a passphrase "
            "was given for a key that has none."
        ) from None
    except ValueError:
        raise KeyProblem(
            "That key could not be read. Check the whole file was pasted, "
            "including the BEGIN and END lines, and that the passphrase is right."
        ) from None

    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


#: What Snowflake calls the authenticator for a programmatic access token.
#:
#: Spelled out rather than imported from `snowflake.connector.network`, which is
#: an optional dependency this module is careful not to require — the value is
#: part of the driver's public connection contract and does not move.
PAT_AUTHENTICATOR = "PROGRAMMATIC_ACCESS_TOKEN"


def _connect_args(config: SqlConfig, secrets: SqlSecrets | None = None) -> dict:
    """Per-driver connection arguments we set rather than ask for.

    The timeout, where the driver spells it in a way we know — and the two
    Snowflake credentials that cannot travel in the URL: a private key, which is a
    blob of DER bytes rather than a string, and an access token, which needs its
    own authenticator named alongside it.

    **A token is not a password, and the driver means it.** Snowflake's connector
    routes `PROGRAMMATIC_ACCESS_TOKEN` to `AuthByPAT(self._token)` — a PAT put in
    the password field is sent as a password and refused, which reads as a bad
    token rather than the wrong kind of credential. That is the whole reason this
    is a third branch instead of reusing the password.
    """
    if config.dialect == "postgresql":
        return {"connect_timeout": 10}

    if config.dialect == "snowflake" and secrets and secrets.token.strip():
        return {"authenticator": PAT_AUTHENTICATOR, "token": secrets.token.strip()}

    if config.dialect == "snowflake" and secrets and secrets.private_key.strip():
        return {
            "private_key": load_private_key(
                secrets.private_key, secrets.key_passphrase
            )
        }

    return {}


def _read_only(conn, dialect: str) -> None:
    """Make the connection refuse writes, where the database can be told to.

    Belt and braces over `_check_query`: a regex can be talked around, a
    `READ ONLY` transaction cannot. Also sets a statement timeout so a query with
    a missing join condition cannot hold the connection forever.

    Silently skipped on a dialect that has no equivalent — the check above and the
    row cap still apply, and refusing to run at all would be worse than running
    with one fewer guard.
    """
    if dialect == "postgresql":
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(
            text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_SECONDS}s'")
        )
    elif dialect in ("mysql", "mariadb"):
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        conn.execute(
            text(f"SET SESSION MAX_EXECUTION_TIME = {STATEMENT_TIMEOUT_SECONDS * 1000}")
        )
    elif dialect == "snowflake":
        # **The one dialect where a runaway query costs money by the second.** A
        # warehouse bills while it runs, so a missing join condition is not just a
        # slow sync — it is a bill. Snowflake has no read-only transaction, so the
        # SELECT-only check and the forbidden-verb regex are the guards there; this
        # is the one that bounds the damage.
        conn.execute(
            text(
                "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = "
                f"{STATEMENT_TIMEOUT_SECONDS}"
            )
        )


class SqlConnector:
    """Runs one admin-written query and hands back its rows."""

    setup_steps = (
        "Ask whoever runs the database for a read-only account. This "
        "connector only ever reads, and refuses a query that would write.",
        "Point it at a replica rather than the primary if you have one.",
        "Write a query returning one row per thing you want counted, with a "
        "column saying when each row was last modified.",
        "Filter on that column with :since. This connector will not accept a "
        "query without it — re-reading everything every few minutes is how "
        "an integration gets switched off at the far end.",
    )

    key = "sql"
    display_name = "SQL database"
    config_schema = SqlConfig
    credential_schema = SqlSecrets

    @staticmethod
    def _requires_since(config) -> bool:
        """Whether this source's query must carry a `:since` window.

        **Always, for a plain database**, because nothing offers otherwise:
        without a window every sync re-reads the whole table, and re-reading
        without a stable row id appends duplicates — the failure `_identify`
        exists to refuse.

        A Snowflake source can be set to read everything on purpose. A
        pre-aggregated view is whole by design, and demanding a window on it would
        refuse the query a BI team actually wrote; the cost of that choice is
        stated on the form instead of being enforced here.
        """
        return getattr(config, "read_mode", "incremental") != "full"

    def test_connection(
        self, config: SqlConfig, credentials: SqlSecrets
    ) -> ConnectionResult:
        """Connect, check the query is a read, and say what was reached.

        Reports the server version on success. "Connected" on its own does not
        tell an admin whether they reached the replica they meant or the primary,
        and this is the one moment they are looking.
        """
        try:
            query = _check_query(config.query, require_since=self._requires_since(config))
        except QueryProblem as problem:
            return ConnectionResult(ok=False, detail=str(problem))

        try:
            engine = _engine(config, credentials)
        except QueryProblem as problem:
            return ConnectionResult(ok=False, detail=str(problem))

        try:
            with engine.connect() as conn:
                _read_only(conn, config.dialect)
                version = str(conn.scalar(text("SELECT version()")) or "")
                # Run their query too, bounded, so "it connects" and "the query
                # works" are answered by one button rather than two visits.
                rows = _peek(conn, query, limit=1)
        except Exception as error:  # noqa: BLE001 — reported, not raised
            return ConnectionResult(ok=False, detail=_explain(error))
        finally:
            engine.dispose()

        return ConnectionResult(
            ok=True,
            detail=(
                f"Connected, and the query returned {len(rows)} row"
                f"{'' if len(rows) == 1 else 's'} for a recent window."
            ),
            info={"server": version[:120], "columns": ", ".join(rows[0]) if rows else ""},
        )

    def discover(
        self,
        config: SqlConfig,
        credentials: SqlSecrets,
        *,
        local: LocalContext | None = None,
    ) -> list[SourceField]:
        """The columns the query returns, by running it for a few rows.

        **The query is never rewritten to add a LIMIT.** Wrapping admin SQL in a
        subquery breaks on a trailing semicolon, on some CTEs, and on anything
        with its own `ORDER BY … LIMIT` — and a connector that mangles the query
        an admin tested by hand is a connector they cannot trust. Reading the
        first few rows off a server-side cursor and closing it achieves the same
        thing without touching their SQL.
        """
        try:
            query = _check_query(config.query, require_since=self._requires_since(config))
            engine = _engine(config, credentials)
        except QueryProblem:
            return []

        try:
            with engine.connect() as conn:
                _read_only(conn, config.dialect)
                # More rows than a sample needs: whether a column is a choice
                # or a name cannot be told from five. Bounded well below the row
                # cap, and the cursor is closed straight after.
                rows = _peek(conn, query, limit=SCAN_ROWS)
        except Exception:  # noqa: BLE001 — an empty answer, same as a webhook
            return []
        finally:
            engine.dispose()

        return _fields_of(rows)

    def fetch(
        self,
        config: SqlConfig,
        credentials: SqlSecrets,
        since: datetime | None = None,
        *,
        local: LocalContext | None = None,
    ) -> Iterator[SourceRow]:
        """Every row the query returns for this window.

        Streamed. `stream_results` asks the driver for a server-side cursor, so a
        million-row result is consumed a thousand at a time and never exists in
        this process at once — which is the whole reason the protocol returns an
        iterator rather than a list.

        No `external_id`: a SQL row has no id the connector can guess at. The
        mapping names the column, and `sync` falls back to inserting when there is
        none — see the note there on what that costs.
        """
        query = _check_query(config.query, require_since=self._requires_since(config))
        engine = _engine(config, credentials)

        try:
            with engine.connect() as conn:
                _read_only(conn, config.dialect)
                result = conn.execution_options(
                    stream_results=True, yield_per=CHUNK
                ).execute(text(query), {SINCE: since})

                seen = 0
                for row in result:
                    if seen >= MAX_ROWS:
                        # The rows already yielded are real and worth keeping, so
                        # this is raised *after* them rather than instead of them.
                        # It used to `break`, on the claim that "the run's counts
                        # make the truncation visible" — they did not: the run
                        # reported `ok` and the watermark moved past rows nobody
                        # had read.
                        raise Truncated(
                            f"Stopped at {MAX_ROWS:,} rows, so this run is "
                            "incomplete. Narrow the query, or shorten how much "
                            "history this source starts with."
                        )
                    seen += 1
                    yield SourceRow(external_id=None, values=dict(row._mapping))
        finally:
            engine.dispose()


def _peek(conn, query: str, *, limit: int) -> list[dict]:
    """The first few rows, without reading the rest.

    A server-side cursor closed early: the database stops producing rows when we
    stop asking, so this costs a few rows rather than the whole result even on a
    query that would return millions.

    `:since` is bound to a value far enough back to be representative — the point
    is to see the shape of the data, and a window that returned nothing would
    describe an empty result as an empty schema.
    """
    from datetime import UTC, timedelta

    result = conn.execution_options(stream_results=True, yield_per=limit).execute(
        text(query), {SINCE: datetime.now(UTC) - timedelta(days=3650)}
    )
    try:
        return [dict(row._mapping) for _, row in zip(range(limit), result)]
    finally:
        result.close()


def _explain(error: Exception) -> str:
    """A database error an admin can act on.

    The driver's own message, trimmed. Rewriting it into something friendlier
    loses the detail that identifies the problem — "relation does not exist" names
    the table, and a generic "could not connect" does not.
    """
    message = str(error).strip().splitlines()
    first = message[0] if message else type(error).__name__
    return f"{type(error).__name__}: {first}"[:500]


#: Past this many distinct values, a column is data rather than a choice.
#:
#: The same number `grid.MAX_CHOICES` uses, and for the same reason: the things
#: worth filtering on — a pipeline stage, a region, a disposition code — are all
#: small by nature, and a dropdown longer than this is a search box.
MAX_CHOICES = 12


def _fields_of(rows: list[dict]) -> list[SourceField]:
    """Each column's kind, and — where there are few enough — its distinct values.

    Column *order* is kept rather than sorted alphabetically, unlike the webhook
    connector: a SELECT list is written by a person, so the order they chose is
    more meaningful than the alphabet — and the mapping's suggestions rank ties by
    it.

    **Distinct values are what make a filter offerable.** A query of closed deals
    has a `stage` column holding three words, and a metric counting every row
    counts the lost ones too. Nobody reaches for a filter they were never offered,
    so discovery has to say which columns could be filtered on. Spreadsheets have
    done this since `grid.fields_of`; a warehouse query is the same shape of
    problem and was the same shape of silent wrongness.
    """
    fields: dict[str, SourceField] = {}
    # Insertion-ordered, so a dropdown lists values the way the query returned
    # them. One over the cap is kept deliberately: it is how "too many" is
    # detected without holding the whole column.
    choices: dict[str, dict[str, None]] = {}

    for row in rows:
        for name, value in row.items():
            if not isinstance(name, str):
                continue

            text_value = "" if value is None else str(value).strip()
            seen = choices.setdefault(name, {})
            if text_value and len(seen) <= MAX_CHOICES:
                seen[text_value] = None

            existing = fields.get(name)
            if existing is not None and (existing.kind != "string" or value is None):
                continue
            fields[name] = SourceField(
                name=name,
                kind=_kind_of(value),
                samples=(str(value)[:60],) if value is not None else (),
            )

    return [
        replace(
            field,
            values=(
                tuple(choices[name])
                if 0 < len(choices.get(name, {})) <= MAX_CHOICES
                else ()
            ),
        )
        for name, field in fields.items()
    ]


def _kind_of(value: object) -> str:
    """A database tells us the type, so this is much less of a guess than JSON.

    Checked before `int`, because `bool` is a subclass of it in Python and a
    boolean column reported as a number would be suggested as a value to sum.
    """
    from datetime import date
    from decimal import Decimal

    if value is None:
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, str) and "@" in value:
        return "email"
    return "string"


# ── Snowflake ────────────────────────────────────────────────────────────────


class SnowflakeConfig(BaseModel):
    """One query against the connected warehouse.

    **Two fields, because the connection carries the rest.** Account, username,
    key, warehouse, role and database are answered once when the warehouse is
    connected — asking them again for the second table would be five of the six
    answers repeated, and five chances for two sources to disagree about which
    warehouse they mean.

    See `app/warehouse_account.py`. What is left here is the only thing that
    genuinely differs between one source and the next: what to ask for.
    """

    # **Answered once on the connection, carried here for the driver.** Hidden
    # from the form: asking for the account and warehouse again on the second
    # table would be five of six answers repeated, and five chances for two
    # sources to disagree about which warehouse they mean. Filled by
    # `oauth.config_for` at call time — see `app/warehouse_account.py`.
    account: str = Field(
        default="", title="Account", json_schema_extra={"hidden": True}
    )
    warehouse: str = Field(
        default="", title="Warehouse", json_schema_extra={"hidden": True}
    )
    role: str = Field(default="", title="Role", json_schema_extra={"hidden": True})
    database: str = Field(
        default="", title="Database", json_schema_extra={"hidden": True}
    )

    query: str = Field(
        default="",
        title="Query",
        description=(
            "One row per thing you want measured, with a column for who it "
            "belongs to and a column for when it happened. Every period is worked "
            "out from that date — this month, last quarter, a competition over any "
            "range — so a query without one cannot be mapped. Reading from a "
            "pre-aggregated view with no date, add one: SELECT …, CURRENT_DATE() "
            "AS as_of FROM …"
        ),
        # The default mode is "everything, every time", so the example is that
        # shape rather than the incremental one — an example that needs a setting
        # changed before it works is an example that teaches the wrong thing.
        examples=["SELECT * FROM ANALYTICS.SALES.CLOSED_DEALS__V"],
        json_schema_extra={"multiline": True},
    )

    #: Whether every run reads the whole result, or only what changed.
    #:
    #: **One question instead of two and a hidden rule.** It used to be implied by
    #: whether somebody remembered to type `:since`, with `backfill_days` as a
    #: separate setting that only sometimes mattered.
    #:
    #: `full` is the default because it is what a view-shaped query is —
    #: `SELECT * FROM …_V` — and because it is the only mode that notices a row
    #: being deleted. `incremental` is cheaper on warehouse credits and needs
    #: `:since` in the query, which is checked rather than assumed.
    read_mode: Literal["full", "incremental"] = Field(
        default="full",
        title="How much to read each time",
        description=(
            "Everything: your query is the truth, so deleted rows stop counting — "
            "and it costs more credits. Only what changed: cheaper, needs :since "
            "in the query, and deletions are not noticed."
        ),
        json_schema_extra={"enum_labels": {"full": "Everything, every time",
                                           "incremental": "Only what changed"}},
    )


#: What the probe asks Snowflake about the session it just opened.
#:
#: Metadata only, so it costs nothing and runs without a warehouse — which is the
#: whole point: it can report the absence of one rather than failing on it.
SESSION_QUERY = (
    "SELECT CURRENT_WAREHOUSE() AS WAREHOUSE, CURRENT_ROLE() AS ROLE, "
    "CURRENT_DATABASE() AS DATABASE"
)


def describe_session(session: dict) -> ConnectionResult:
    """A verdict on the session Snowflake handed back.

    **Reaching Snowflake is not the same as being able to query it.** Storage and
    compute are separate there: a session with no warehouse authenticates
    perfectly and then cannot run a single query against a table. Every field that
    would supply one is optional — a blank warehouse falls back to the user's
    DEFAULT_WAREHOUSE, and a user may simply not have one — so the likeliest
    misconfiguration is exactly the one a green tick used to hide.

    Kept apart from the connecting so the judgement can be tested without a
    warehouse to connect to.
    """
    warehouse = (session.get("warehouse") or "").strip()
    role = (session.get("role") or "").strip()
    database = (session.get("database") or "").strip()

    info = {"warehouse": warehouse, "role": role, "database": database}

    if not warehouse:
        return ConnectionResult(
            ok=False,
            detail=(
                "Signed in"
                + (f" as {role}" if role else "")
                + ", but no warehouse is selected, so no query can run. Put one in "
                "the Warehouse field above, or give this Snowflake user a "
                "DEFAULT_WAREHOUSE."
            ),
            info=info,
        )

    return ConnectionResult(
        ok=True,
        detail=(
            f"Connected. Queries will run on {warehouse}"
            + (f" as {role}" if role else "")
            + (f", in {database}" if database else "")
            + "."
        ),
        info=info,
    )


def probe_snowflake(config: SqlConfig, secrets: SqlSecrets) -> ConnectionResult:
    """Connect, and report the session rather than the fact of connecting.

    Replaces a `SELECT 1` probe. Snowflake constant-folds that one without any
    compute, so it returned a green tick for a session that could not read a
    table — the false pass the button exists to prevent.
    """
    try:
        engine = _engine(config, secrets)
    except QueryProblem as problem:
        return ConnectionResult(ok=False, detail=str(problem))

    try:
        with engine.connect() as conn:
            _read_only(conn, config.dialect)
            row = conn.execute(text(SESSION_QUERY)).mappings().first()
    except Exception as error:  # noqa: BLE001 - reported, not raised
        return ConnectionResult(ok=False, detail=_explain(error))
    finally:
        engine.dispose()

    # Snowflake answers in upper case; the reader should not have to know that.
    return describe_session({str(k).lower(): v for k, v in dict(row or {}).items()})


class SnowflakeConnector(SqlConnector):
    """Snowflake, on the SQL engine, with its own form.

    Subclassed rather than copied: read-only transactions, the statement timeout,
    the row cap, the server-side cursor and the `:since` refusal are all the
    generic connector's, and a second copy of them would be a second thing to fix.
    Only the questions differ.
    """

    key = "snowflake"
    display_name = "Snowflake"
    config_schema = SnowflakeConfig

    #: **About the query, because the connection is already made.**
    #:
    #: These show on the step where a query is written, above which the connected
    #: warehouse is displayed as a single line. Telling somebody there how to find
    #: their account identifier is answering a question they settled two screens
    #: ago, and it made the step read as though nothing had been saved.
    setup_steps = (
        "Point the query at one table or view — whichever already holds the "
        "numbers you want on a leaderboard.",
        "Return one row per thing being counted, with a column naming who it "
        "belongs to. That column is what ties a row to a person here.",
        "Include a date column if you have one. Every period comes from it — "
        "this month, last quarter, a competition over any range.",
        "Leave the read set to once until the numbers look right. Warehouses "
        "bill per second while they run, so pick a repeat interval only when "
        "you know the query is the one you meant.",
    )

    @staticmethod
    def _as_sql(config: SnowflakeConfig) -> SqlConfig:
        """Snowflake's vocabulary, translated into the generic one.

        `database` carries the schema after a slash, which is how the Snowflake
        SQLAlchemy dialect spells it — `snowflake://user@account/DB/SCHEMA`. The
        alternative is a separate `schema` driver option, which works but leaves
        the URL looking wrong to anybody debugging it.
        """
        # No schema field any more: a fully-qualified query names its own, and a
        # schema setting that silently disagrees with the query is a trap rather
        # than a convenience.
        database = config.database

        options = {}
        if config.warehouse:
            options["warehouse"] = config.warehouse
        if config.role:
            options["role"] = config.role

        return SqlConfig(
            dialect="snowflake",
            # Carried across, so the base class can tell a full source from an
            # incremental one — it never sees the Snowflake config.
            read_mode=config.read_mode,
            # Snowflake's account identifier goes where a host goes; the driver
            # appends `.snowflakecomputing.com` itself.
            host=config.account,
            database=database,
            query=config.query,
            options=options,
        )

    # **These three exist only to translate the config.** They took a positional
    # `context` where the base class takes a keyword-only `local`, which meant
    # every call from `sync` raised TypeError — `discover()` got an unexpected
    # keyword argument. Snowflake was in the picker, with a logo, and had never
    # once imported a row: `test_connection` matched, so the Test button went
    # green and the next step returned nothing.
    #
    # Signatures are repeated rather than `*args, **kwargs` forwarded, so the next
    # change to the protocol breaks this loudly here instead of at a call site.
    @staticmethod
    def _full(config) -> bool:
        """Whether this source reads the whole result every time."""
        return getattr(config, "read_mode", "full") != "incremental"

    def reads_everything(self, config=None) -> bool:  # type: ignore[override]
        """Whether absence in the result means a row was deleted.

        **Per source, not per connector**, which is why this is a method where a
        spreadsheet has a flag. A `full` query is the whole truth every time, so a
        row that stops coming back is gone and its fact can be withdrawn — the
        machinery in `sync._withdraw_missing`, reached for the first time by
        something other than a spreadsheet. An `incremental` query returns a
        window, where absence only ever means "outside it", and withdrawing on
        that basis would delete every fact older than the window on every pass.
        """
        return config is not None and self._full(config)

    def test_connection(self, config, credentials):  # type: ignore[override]
        return super().test_connection(self._as_sql(config), credentials)

    def discover(self, config, credentials, *, local=None):  # type: ignore[override]
        return super().discover(self._as_sql(config), credentials, local=local)

    def fetch(self, config, credentials, since=None, *, local=None):  # type: ignore[override]
        return super().fetch(self._as_sql(config), credentials, since, local=local)


register(SqlConnector())

# Only when this build can actually reach it. The driver is an optional extra —
# `--build-arg API_EXTRAS="[snowflake]"` — and offering a connector whose every
# attempt ends in "no driver installed" is the failure the dialect list exists to
# avoid. The generic SQL connector stays either way, and says the same thing in
# its Database type list.
if "snowflake" in available_dialects():
    register(SnowflakeConnector())
