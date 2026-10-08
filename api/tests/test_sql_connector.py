"""Reading straight from a database.

**Driven against a real one.** The stub-connector tests in `test_sync.py` prove the
engine; this proves the driver, and a pull connector's whole job is the thing a stub
cannot fake — a query, a bound window, a server-side cursor, and a schema discovered
by asking.

The fixture commits its rows on a connection of its own and drops them afterwards,
because that is what a remote database *is*. Putting them in the test's own rolled-
back transaction would make them invisible to the connector, which is the same trap
the webhook connector fell into from the other direction.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.connectors import sql as connector_module
from app.connectors.sql import (
    DIALECTS,
    QueryProblem,
    SqlConfig,
    SqlConnector,
    SqlSecrets,
    _check_query,
    available_dialects,
)

WHEN = datetime(2026, 8, 7, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def external():
    """A table in a real database, on its own committed connection.

    Module-scoped: creating and dropping a table per test is slower than the tests
    themselves, and nothing here writes to it.
    """
    engine = create_engine(get_settings().database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS deals_under_test"))
        conn.execute(
            text(
                """
                CREATE TABLE deals_under_test (
                    deal_id     text PRIMARY KEY,
                    owner_email text,
                    amount      numeric(12, 2),
                    closed_on   date,
                    updated_at  timestamptz,
                    is_won      boolean,
                    notes       text
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO deals_under_test VALUES
                ('d-1', 'alice@acme.example', 1200.50, '2026-08-07',
                 '2026-08-07 12:00+00', true,  'phone'),
                ('d-2', 'bob@acme.example',    900.00, '2026-08-06',
                 '2026-08-06 09:00+00', true,  null),
                ('d-3', 'alice@acme.example',  250.00, '2026-07-01',
                 '2026-08-19 15:00+00', false, 'edited long after it closed'),
                -- Amount and closed_on null, so a column whose first row is
                -- empty has a real kind waiting further down the result.
                ('d-4', 'carol@acme.example',  null,   null,
                 '2026-08-08 08:00+00', null,  null)
                """
            )
        )
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS deals_under_test"))
    engine.dispose()


def config(**overrides) -> SqlConfig:
    settings = get_settings()
    body = {
        "dialect": "postgresql",
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "database": settings.postgres_db,
        "query": (
            "SELECT deal_id, owner_email, amount, closed_on, is_won, notes "
            "FROM deals_under_test WHERE updated_at >= :since ORDER BY deal_id"
        ),
    }
    body.update(overrides)
    return SqlConfig(**body)


def secrets() -> SqlSecrets:
    settings = get_settings()
    return SqlSecrets(username=settings.postgres_user, password=settings.postgres_password)


def rows(since: datetime | None) -> list[dict]:
    return [
        row.values
        for row in SqlConnector().fetch(config(), secrets(), since)
    ]


# ── The query has to be a read, and has to use the window ────────────────────


def test_a_select_is_accepted():
    assert _check_query("SELECT 1 WHERE x >= :since") == "SELECT 1 WHERE x >= :since"


def test_a_cte_is_accepted():
    """`WITH … SELECT` is how anybody writes a real reporting query."""
    query = "WITH w AS (SELECT 1 AS n) SELECT n FROM w WHERE n >= :since"
    assert _check_query(query) == query


def test_a_trailing_semicolon_is_tolerated():
    """It is what you get from pasting out of a SQL client, and refusing it would
    be a rule about punctuation rather than about safety."""
    assert _check_query("SELECT 1 WHERE x >= :since;").endswith(":since")


def test_a_write_is_refused():
    """Caught by the "must start with SELECT" rule rather than the forbidden-word
    scan, and that is the better message of the two: it says what the query has to
    be, not merely which word offended."""
    with pytest.raises(QueryProblem, match="start with SELECT"):
        _check_query("DELETE FROM deals WHERE updated_at >= :since")


def test_a_write_hidden_after_a_select_is_refused():
    """A regex on the first word is not enough — this is why the whole statement
    is scanned and why there is a read-only transaction behind it as well."""
    with pytest.raises(QueryProblem, match="DROP"):
        _check_query("SELECT 1 WHERE x >= :since; DROP TABLE deals")


def test_a_forbidden_word_inside_a_comment_is_not_a_write():
    """`-- delete this view later` is a note, not a statement. Refusing it would
    make somebody delete their own comment to get the form to submit."""
    query = "SELECT 1 -- delete this later\nWHERE x >= :since"
    assert _check_query(query)


def test_a_since_inside_a_comment_does_not_count_as_using_it():
    """The dangerous direction of the same rule: a commented-out window reads as
    present and every sync then re-scans the table."""
    with pytest.raises(QueryProblem, match="must use :since"):
        _check_query("SELECT 1 -- WHERE updated_at >= :since")


def test_a_block_comment_is_stripped_too():
    assert _check_query("SELECT 1 /* delete me */ WHERE x >= :since")


def test_a_query_without_the_window_is_refused_with_an_example():
    """The failure this prevents is silent: it works, and quietly costs a full
    table scan an hour until somebody notices the database load."""
    with pytest.raises(QueryProblem) as raised:
        _check_query("SELECT * FROM deals")

    assert "updated_at >= :since" in str(raised.value)
    # And the trap that cost a day in 3a, said where it will be read.
    assert "last *modified*" in str(raised.value)


def test_an_empty_query_says_so_rather_than_failing_obscurely():
    with pytest.raises(QueryProblem, match="no query yet"):
        _check_query("   ")


# ── Reading ──────────────────────────────────────────────────────────────────


def test_it_reads_rows_from_a_real_database(external):
    found = rows(WHEN - timedelta(days=365))

    assert len(found) == 4
    assert found[0]["deal_id"] == "d-1"
    assert found[0]["owner_email"] == "alice@acme.example"


def test_the_window_is_a_bound_parameter_that_actually_filters(external):
    """Bound, never interpolated: a date formatted into a string is a syntax error
    in one locale and a silently empty result in another."""
    recent = rows(datetime(2026, 8, 7, tzinfo=UTC))

    assert {r["deal_id"] for r in recent} == {"d-1", "d-3", "d-4"}


def test_a_row_edited_after_it_closed_still_arrives(external):
    """**The trap this connector is built around.** `d-3` closed on 1 July and was
    edited on 19 August. A query filtered on the close date would never return it
    again, so the edit would never be imported — which is why `_check_query`
    insists on the window and says to use a modified-at column."""
    late = rows(datetime(2026, 8, 19, tzinfo=UTC))

    assert [r["deal_id"] for r in late] == ["d-3"]
    assert str(late[0]["closed_on"]) == "2026-07-01"


def test_no_external_id_is_invented(external):
    """A SQL row has no id the connector can guess at. The mapping names the
    column; guessing would make re-imports overwrite the wrong fact."""
    found = list(SqlConnector().fetch(config(), secrets(), WHEN - timedelta(days=365)))

    assert all(row.external_id is None for row in found)


def test_the_row_cap_keeps_what_it_read_and_says_it_stopped(external, monkeypatch):
    """**This used to `break`**, on the claim that "the run's counts make the
    truncation visible". They did not: the run reported `ok`, so the watermark moved
    past rows nobody had read and they were lost. It now raises *after* the rows it
    did read, which keeps them and makes the run partial."""
    from app.connectors import Truncated

    monkeypatch.setattr(connector_module, "MAX_ROWS", 2)

    stream = SqlConnector().fetch(config(), secrets(), WHEN - timedelta(days=365))
    found = []
    with pytest.raises(Truncated, match="incomplete"):
        for row in stream:
            found.append(row)

    assert len(found) == 2


def test_a_query_that_fits_under_the_cap_raises_nothing(external, monkeypatch):
    """The cap must not fire on a normal sync, or every source would report itself
    incomplete forever."""
    monkeypatch.setattr(connector_module, "MAX_ROWS", 500)

    assert len(rows(WHEN - timedelta(days=365))) > 0


def test_it_is_a_generator_so_the_first_row_arrives_before_the_last(external):
    """A connector that returned a list would have moved a warehouse-sized memory
    problem into the API process."""
    stream = SqlConnector().fetch(config(), secrets(), WHEN - timedelta(days=365))

    first = next(stream)

    assert first.values["deal_id"] == "d-1"
    stream.close()


def test_it_asks_the_driver_for_a_server_side_cursor(external, monkeypatch):
    """Being a generator is not enough on its own: a generator that reads the whole
    result before its first `yield` streams nothing. This asserts the request, and
    the test below asserts that the request works."""
    from sqlalchemy import Connection

    asked: list[dict] = []
    real = Connection.execution_options

    def recording(self, **options):
        asked.append(options)
        return real(self, **options)

    monkeypatch.setattr(Connection, "execution_options", recording)

    stream = SqlConnector().fetch(config(), secrets(), WHEN - timedelta(days=365))
    next(stream)
    stream.close()

    assert any(o.get("stream_results") for o in asked), asked


def test_asking_for_streaming_really_produces_a_server_side_cursor(external):
    """The other half of the claim, against a real server: `stream_results` gives a
    `ServerCursor` and its absence gives an ordinary one, so the option above is
    doing something rather than being accepted and ignored.

    Each half runs on its own connection because `Connection.execution_options`
    **mutates the connection in place** rather than returning a copy — checking
    both on one connection reports streaming twice and proves nothing. That cost a
    confused minute to find.
    """
    from sqlalchemy import text as sa_text

    from app.connectors.sql import _engine, _read_only

    engine = _engine(config(), secrets())
    seen = {}
    try:
        for label, options in (
            ("streamed", {"stream_results": True, "yield_per": 10}),
            ("materialised", {}),
        ):
            with engine.connect() as conn:
                _read_only(conn, "postgresql")
                result = conn.execution_options(**options).execute(
                    sa_text("SELECT generate_series(1, 5000) AS n")
                )
                seen[label] = type(result.cursor).__name__
                result.close()
    finally:
        engine.dispose()

    assert seen["streamed"] == "ServerCursor"
    assert seen["materialised"] == "Cursor"


# ── The guards that are not the regex ────────────────────────────────────────


def test_the_transaction_is_read_only_so_the_database_refuses_writes(external):
    """**The guard that cannot be talked around.** `_check_query` is a regex and
    regexes lose arguments; a `READ ONLY` transaction is the database's own answer.
    Asserted against a real server because "we sent the statement" and "the server
    honoured it" are different claims."""
    from sqlalchemy import text as sa_text

    from app.connectors.sql import _engine, _read_only

    engine = _engine(config(), secrets())
    try:
        with engine.connect() as conn:
            _read_only(conn, "postgresql")

            assert conn.scalar(sa_text("SHOW transaction_read_only")) == "on"
            with pytest.raises(Exception):
                conn.execute(sa_text("CREATE TABLE should_not_exist (x int)"))
    finally:
        engine.dispose()


def test_a_statement_timeout_is_set_so_a_runaway_query_cannot_hold_a_connection(
    external,
):
    from sqlalchemy import text as sa_text

    from app.connectors.sql import STATEMENT_TIMEOUT_SECONDS, _engine, _read_only

    engine = _engine(config(), secrets())
    try:
        with engine.connect() as conn:
            _read_only(conn, "postgresql")
            reported = conn.scalar(sa_text("SHOW statement_timeout"))
    finally:
        engine.dispose()

    assert reported == f"{STATEMENT_TIMEOUT_SECONDS // 60}min"


def test_connections_are_not_pooled_between_syncs():
    """`poolclass=None` reads like "no pool" and means "the default" — a
    `QueuePool` holding idle connections open against somebody else's database
    between runs. Asserted rather than commented, because the comment was wrong."""
    from sqlalchemy.pool import NullPool

    from app.connectors.sql import _engine

    engine = _engine(config(), secrets())
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()


# ── Discovery ────────────────────────────────────────────────────────────────


def test_it_discovers_the_columns_the_query_returns(external):
    found = SqlConnector().discover(config(), secrets())

    assert [f.name for f in found] == [
        "deal_id",
        "owner_email",
        "amount",
        "closed_on",
        "is_won",
        "notes",
    ]


def test_column_order_is_the_order_the_query_asked_for(external):
    """A SELECT list is written by a person, so their order is more meaningful
    than the alphabet — and the mapping's suggestions break ties by it."""
    found = SqlConnector().discover(
        config(
            query=(
                "SELECT notes, deal_id FROM deals_under_test "
                "WHERE updated_at >= :since"
            )
        ),
        secrets(),
    )

    assert [f.name for f in found] == ["notes", "deal_id"]


def test_the_database_types_come_through_as_kinds(external):
    """Much less of a guess than JSON: the database told us."""
    kinds = {f.name: f.kind for f in SqlConnector().discover(config(), secrets())}

    assert kinds["amount"] == "number"
    assert kinds["closed_on"] == "date"
    assert kinds["owner_email"] == "email"
    assert kinds["notes"] == "string"


def test_a_boolean_is_not_reported_as_a_number(external):
    """`bool` is a subclass of `int` in Python, so an unguarded check reports a
    flag column as a number and the mapper offers to sum it."""
    kinds = {f.name: f.kind for f in SqlConnector().discover(config(), secrets())}

    assert kinds["is_won"] == "boolean"


def test_a_column_whose_first_value_is_null_is_typed_from_a_later_row(external):
    """`d-4` has no amount. Reading only the first row — or refusing to revisit a
    column once seen — types a numeric column as text from whichever row happened
    to sort first, and the mapper then declines to offer it as the value."""
    found = SqlConnector().discover(
        config(
            query=(
                "SELECT amount FROM deals_under_test WHERE updated_at >= :since "
                "ORDER BY (amount IS NOT NULL), deal_id"
            )
        ),
        secrets(),
    )

    assert [f.kind for f in found] == ["number"]
    assert found[0].samples  # and it found a real value to show


def test_a_column_that_is_null_in_every_row_read_stays_a_string(external):
    """There is nothing to type it from, and guessing would be inventing. The
    admin can still map it; the kind only drives the suggestion."""
    found = SqlConnector().discover(
        config(
            query=(
                "SELECT amount FROM deals_under_test WHERE updated_at >= :since "
                "AND deal_id = 'd-4'"
            )
        ),
        secrets(),
    )

    assert [(f.kind, f.samples) for f in found] == [("string", ())]


def test_discovery_answers_empty_when_the_database_refuses_the_query(external):
    """A query that passes validation and then fails at the server — a table that
    was renamed, a column that was dropped. An empty list, because the page needs
    to say "no columns known yet" rather than show an error where a schema goes;
    the Test button is where the reason belongs."""
    found = SqlConnector().discover(
        config(query="SELECT 1 FROM gone_away WHERE updated_at >= :since"), secrets()
    )

    assert found == []


def test_discovery_is_an_empty_list_when_the_query_is_unusable(external):
    """An empty answer, the same as a webhook that has received nothing — the page
    says so rather than showing an error where a schema should be."""
    assert SqlConnector().discover(config(query="SELECT * FROM deals"), secrets()) == []


# ── Testing the connection ───────────────────────────────────────────────────


def test_a_good_connection_reports_the_server_it_reached(external):
    """"Connected" alone does not say whether they reached the replica they meant
    or the primary, and this is the one moment they are looking."""
    result = SqlConnector().test_connection(config(), secrets())

    assert result.ok is True
    assert "PostgreSQL" in result.info["server"]
    assert "deal_id" in result.info["columns"]


def test_a_bad_password_is_reported_not_raised(external):
    result = SqlConnector().test_connection(
        config(), SqlSecrets(username="nobody", password="wrong")
    )

    assert result.ok is False
    assert result.detail  # the driver's own words, which name the problem


def test_an_unreachable_host_is_reported_not_raised():
    result = SqlConnector().test_connection(
        config(host="no-such-host.invalid"), secrets()
    )

    assert result.ok is False


def test_a_query_naming_a_missing_table_is_reported_with_the_name(external):
    """The driver's message names the relation. Rewriting it into "could not read"
    would lose the only detail that identifies the problem."""
    result = SqlConnector().test_connection(
        config(query="SELECT 1 FROM nope WHERE updated_at >= :since"), secrets()
    )

    assert result.ok is False
    assert "nope" in result.detail


def test_a_bad_query_is_caught_before_anything_connects():
    """No host, no credentials, no database — and still a useful answer, because
    the query is wrong on its own terms."""
    result = SqlConnector().test_connection(
        SqlConfig(dialect="postgresql", query="SELECT * FROM deals"), SqlSecrets()
    )

    assert result.ok is False
    assert ":since" in result.detail


# ── Which databases this build can speak to ──────────────────────────────────


def test_postgres_is_available_because_the_app_itself_needs_it():
    assert "postgresql" in available_dialects()


def test_a_dialect_without_a_driver_is_refused_by_name():
    """Rather than a connection attempt that fails with an import error. The form
    should never offer a database this build cannot reach — and if it does, the
    message says what is missing."""
    missing = sorted(set(DIALECTS) - set(available_dialects()))
    assert missing, "this test needs at least one uninstalled dialect"

    result = SqlConnector().test_connection(
        config(dialect=missing[0]), secrets()
    )

    assert result.ok is False
    assert "no driver" in result.detail


def test_an_unknown_dialect_lists_the_known_ones():
    result = SqlConnector().test_connection(config(dialect="oracle"), secrets())

    assert result.ok is False
    assert "postgresql" in result.detail


def test_every_dialect_names_a_driver_package():
    """The table is what makes adding a database a line rather than a rewrite, so
    it has to stay complete: a prefix with no package cannot be checked for."""
    for key, dialect in DIALECTS.items():
        assert dialect.prefix and dialect.package and dialect.module, key


def test_a_dialect_whose_driver_is_installed_is_actually_offered():
    """**The test that was missing while Snowflake was invisible.**

    `available_dialects` probes by importing, and the import name used to be
    guessed from the package name by swapping dashes for underscores. That is right
    for `sqlalchemy-redshift` and wrong for `snowflake-sqlalchemy`, which imports as
    `snowflake.sqlalchemy` — so the dialect never appeared even in a build that had
    installed the driver on purpose, and nothing said so.

    Phrased as a property rather than a list of names: whichever drivers this image
    happens to have, every one of them has to be reachable. It fails on the old
    code and passes on the new, which is the whole point.
    """
    import importlib.metadata as meta

    offered = set(available_dialects())
    for key, dialect in DIALECTS.items():
        try:
            meta.distribution(dialect.package)
        except meta.PackageNotFoundError:
            continue  # Not in this build; nothing to be wrong about.
        assert key in offered, (
            f"{dialect.package!r} is installed but {key!r} is not offered — "
            f"the declared import name {dialect.module!r} is wrong."
        )


def test_snowflake_ships_in_the_default_image():
    """It has its own connector now, not only a line in a dropdown, and a connector
    whose every attempt ends in "no driver installed" is worse than none."""
    assert "snowflake" in available_dialects()


def test_mysql_and_mariadb_are_in_the_default_image():
    """`pymysql` is pure Python and about fifty kilobytes, so it ships rather than
    being an extra — two more databases for no meaningful weight."""
    assert {"mysql", "mariadb"} <= set(available_dialects())


def test_each_dialect_assembles_the_url_its_driver_expects():
    """**What is testable about a database this build has never talked to.** Whether
    the driver holds a real conversation is not; whether the prefix is spelled
    correctly is, and a typo there is a connection attempt against nothing.
    """
    from app.connectors.sql import _build_url

    for key, dialect in DIALECTS.items():
        built = _build_url(
            SqlConfig(dialect=key, host="db.internal", port=1234, database="warehouse"),
            SqlSecrets(username="reader", password="pw"),
        )
        assert built.render_as_string(hide_password=False).startswith(
            f"{dialect.prefix}://reader:pw@db.internal:1234/warehouse"
        ), key


def test_a_password_with_awkward_characters_is_escaped():
    """Assembled with `URL.create` rather than pasted together: a password holding
    `@` or `/` would otherwise produce a URL that parses into a different host, and
    present as an authentication failure against a server nobody meant to reach."""
    from app.connectors.sql import _build_url

    built = _build_url(
        SqlConfig(dialect="postgresql", host="db.internal", database="d"),
        SqlSecrets(username="reader", password="p@ss/word"),
    )

    assert built.host == "db.internal"
    assert built.password == "p@ss/word"
    assert "p%40ss%2Fword" in built.render_as_string(hide_password=False)


def test_driver_options_reach_the_url():
    """Where the per-database awkwardness lives — `sslmode`, `warehouse`, `role`."""
    from app.connectors.sql import _build_url

    built = _build_url(
        SqlConfig(
            dialect="postgresql",
            host="db.internal",
            database="d",
            options={"sslmode": "require"},
        ),
        SqlSecrets(),
    )

    assert "sslmode=require" in built.render_as_string()


def test_only_postgres_claims_to_have_been_verified():
    """A list that quietly grew to include databases nobody had run against would
    be a worse lie than having no list."""
    from app.connectors.sql import VERIFIED

    assert VERIFIED == ("postgresql",)
    assert set(VERIFIED) <= set(available_dialects())


# ── The Snowflake preset ─────────────────────────────────────────────────────


def test_snowflake_asks_for_an_account_and_gets_a_host():
    """The preset exists to ask Snowflake's questions rather than ours. Its whole
    job is this translation, so this is the whole of what there is to test without
    a warehouse to connect to."""
    from app.connectors.sql import SnowflakeConfig, SnowflakeConnector

    built = SnowflakeConnector._as_sql(
        SnowflakeConfig(account="ab12345.us-east-1", database="ANALYTICS")
    )

    assert built.dialect == "snowflake"
    assert built.host == "ab12345.us-east-1"


def test_snowflake_no_longer_asks_for_a_schema():
    """**Dropped rather than kept as an optional extra.** A fully-qualified query
    names its own schema — `ANALYTICS.SALES.CLOSED_DEALS` — and a schema field that
    silently disagrees with the query is a trap rather than a convenience. The
    database stays, optional, for a query that is not qualified."""
    from app.connectors.sql import SnowflakeConfig, SnowflakeConnector

    assert "schema_name" not in SnowflakeConfig.model_fields

    built = SnowflakeConnector._as_sql(
        SnowflakeConfig(account="ab1", database="ANALYTICS")
    )

    assert built.database == "ANALYTICS"


def test_a_snowflake_source_is_a_query_and_a_mode():
    """**Everything else is answered once on the connection.** Asking for the
    account and warehouse again on the second table would be five of six answers
    repeated, and five chances for two sources to disagree about which warehouse
    they mean. The rest are carried on the config but hidden from the form — see
    `oauth.config_for`."""
    from app.connectors.sql import SnowflakeConfig

    schema = SnowflakeConfig.model_json_schema()["properties"]
    shown = [n for n, p in schema.items() if not p.get("hidden")]

    assert shown == ["query", "read_mode"]


def test_snowflake_carries_the_warehouse_and_role_as_driver_options():
    """The two things somebody would otherwise have to know to type into an
    advanced box as `name=value`, which is the reason the preset exists at all."""
    from app.connectors.sql import SnowflakeConfig, SnowflakeConnector

    built = SnowflakeConnector._as_sql(
        SnowflakeConfig(account="ab1", warehouse="COMPUTE_WH", role="ANALYST")
    )

    assert built.options == {"warehouse": "COMPUTE_WH", "role": "ANALYST"}


def test_snowflake_omits_an_option_that_was_left_empty():
    """An empty `role=` in the URL is not the same as no role: it asks the driver
    for a role called nothing, rather than for the login's default."""
    from app.connectors.sql import SnowflakeConfig, SnowflakeConnector

    built = SnowflakeConnector._as_sql(SnowflakeConfig(account="ab1", role=""))

    assert "role" not in built.options


def test_snowflake_builds_a_url_its_own_driver_accepts():
    """End to end through the same `_build_url` every other dialect uses — which is
    the point of subclassing rather than writing a second connector."""
    from app.connectors.sql import SnowflakeConfig, SnowflakeConnector, _build_url

    built = _build_url(
        SnowflakeConnector._as_sql(
            SnowflakeConfig(account="ab1", database="ANALYTICS", warehouse="WH")
        ),
        SqlSecrets(username="reader", password="pw"),
    )

    assert built.render_as_string(hide_password=False) == (
        "snowflake://reader:pw@ab1/ANALYTICS?warehouse=WH"
    )


def test_an_incremental_query_must_use_since():
    """The trap the SQL connector refuses a query for is the same trap on a
    warehouse: without a window, every sync re-reads the whole table at warehouse
    prices. Said plainly rather than charged for silently."""
    from app.connectors.sql import QueryProblem, _check_query

    with pytest.raises(QueryProblem, match=":since"):
        _check_query("SELECT 1 FROM DEALS", require_since=True)


def test_a_full_query_does_not():
    """**The mode that exists for a pre-aggregated view.** `SELECT * FROM …_V` is
    read whole by design, and demanding a window on it would refuse the query a
    BI team actually wrote. The cost is stated on the form instead."""
    from app.connectors.sql import _check_query

    assert _check_query("SELECT * FROM ANALYTICS.SALES.CLOSED_DEALS_V", require_since=False)


def test_reading_everything_is_per_source_not_per_connector():
    """**Which is why Snowflake answers it as a method.** A spreadsheet is always
    whole; a warehouse query is whole only when somebody chose that mode. Getting
    this wrong in the True direction deletes every fact outside the window on
    every pass — see `sync._withdraw_missing`."""
    from app import connectors
    from app.connectors.sql import SnowflakeConfig, SnowflakeConnector

    sf = SnowflakeConnector()
    full = SnowflakeConfig(query="SELECT * FROM V", read_mode="full")
    incremental = SnowflakeConfig(
        query="SELECT * FROM T WHERE u >= :since", read_mode="incremental"
    )

    assert connectors.reads_everything(sf, full) is True
    assert connectors.reads_everything(sf, incremental) is False
    # And with no config at all, the safe answer.
    assert connectors.reads_everything(sf) is False


def test_a_spreadsheet_still_answers_with_a_plain_flag():
    """Both spellings are accepted, because forcing the simple case to write a
    method that ignores its argument is how a rule stops being read."""
    from app import connectors

    assert connectors.reads_everything(connectors.get("microsoft_excel")) is True
    assert connectors.reads_everything(connectors.get("webhook")) is False

# ── Access tokens ────────────────────────────────────────────────────────────


def _snowflake(**secrets):
    from app.connectors.sql import SqlConfig, SqlSecrets, _build_url, _connect_args

    config = SqlConfig(
        dialect="snowflake", host="ab12345", database="ANALYTICS", query="SELECT 1"
    )
    creds = SqlSecrets(username="JC", **secrets)
    return _connect_args(config, creds), _build_url(config, creds)


def test_a_token_travels_under_its_own_authenticator():
    """**A PAT is not a password, and the driver means it.**

    Snowflake's connector routes PROGRAMMATIC_ACCESS_TOKEN to AuthByPAT via the
    `token` parameter. A token handed over in the password field is sent as a
    password and refused — which reads as a bad token rather than the wrong kind
    of credential, and is why this is its own branch.
    """
    args, url = _snowflake(token="pat-abc123")

    assert args == {"authenticator": "PROGRAMMATIC_ACCESS_TOKEN", "token": "pat-abc123"}
    # And nowhere near the URL, where a password would have gone.
    assert "pat-abc123" not in str(url)
    assert url.password is None


def test_a_token_is_trimmed_before_it_is_sent():
    """Pasted tokens arrive with whatever whitespace came with them."""
    args, _ = _snowflake(token="  pat-abc123" + chr(10))

    assert args["token"] == "pat-abc123"


def test_a_key_still_wins_over_a_password():
    """The existing rule, unchanged by the third option."""
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric import rsa

    pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())
        .decode()
    )

    args, url = _snowflake(private_key=pem, password="hunter2")

    assert "private_key" in args
    assert "authenticator" not in args
    assert url.password is None


def test_a_token_keeps_a_password_out_of_the_url():
    """Both present would let the driver choose, and it chooses wrong."""
    _, url = _snowflake(token="pat-abc123", password="hunter2")

    assert url.password is None


def test_a_plain_password_still_reaches_the_url():
    """Nothing above may break the dialects that only have passwords."""
    from app.connectors.sql import SqlConfig, SqlSecrets, _build_url

    config = SqlConfig(
        dialect="postgresql", host="db", database="app", query="SELECT 1"
    )
    url = _build_url(config, SqlSecrets(username="jc", password="hunter2"))

    assert url.password == "hunter2"
