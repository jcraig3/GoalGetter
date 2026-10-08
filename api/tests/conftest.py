"""Test fixtures.

Two decisions shape everything here.

**Tests run against a real Postgres, in a separate database.** The whole reason
for choosing Postgres was window functions, `NUMERIC`, partial indexes, and
`AT TIME ZONE` — SQLite supports none of those the same way, so a green SQLite
suite would prove nothing about production. A separate database rather than the
development one, so a test can never disturb data you are looking at, and so
the 3,000 demo facts don't skew an aggregation assertion.

**The schema is built by running the real migrations**, not
`Base.metadata.create_all()`. `create_all` builds the schema the models
describe, which is exactly the thing a broken migration would fail to produce —
so the suite would pass on a schema no deployment will ever have. Running
Alembic means every test also proves the migration chain applies cleanly.
"""

import os

# Must happen before anything imports app.config: Settings is read once and
# cached, and app.db builds its engine at import time from that URL.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "goalgetter_test")
# **Never the server's own .env, Caddy, or nginx** (Phase 20). The dev container
# the suite runs in has all three mounted; a test pointing at them would
# rewrite your .env and reconfigure your HTTPS. Tests that need them give their
# own temporary paths.
os.environ["GOALGETTER_ENV_FILE"] = "/nonexistent/goalgetter/.env"
os.environ["GOALGETTER_CADDY_SOCKET"] = "/nonexistent/goalgetter/admin.sock"
os.environ["GOALGETTER_NGINX_CONF"] = "/nonexistent/goalgetter/https.conf"
os.environ["GOALGETTER_TUNNEL_DIR"] = "/nonexistent/goalgetter-tunnel"
# A port nothing listens on: refused at once, never a real tunnel.
os.environ["GOALGETTER_TUNNEL_METRICS"] = "http://127.0.0.1:9"
os.environ["GOALGETTER_CERTS_DIR"] = "/tmp/goalgetter-test-certs"
os.environ["GOALGETTER_NO_HOSTING_LOOP"] = "1"

import secrets  # noqa: E402
from contextlib import nullcontext  # noqa: E402
from datetime import UTC, date, datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine, get_db, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    MetricDefinition,
    MetricFact,
    Organization,
    Team,
    UserAccount,
)
from app.sessions import COOKIE_NAME, _hash_token  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the test database if absent, then migrate it to head."""
    settings = get_settings()

    # CREATE DATABASE cannot run inside a transaction, so this connects to the
    # maintenance database with autocommit rather than using the app engine.
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": settings.postgres_db},
        )
        if not exists:
            # Identifier cannot be a bound parameter; the value comes from our
            # own environment, not from a request.
            conn.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))
    admin.dispose()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


@pytest.fixture
def db(database: None) -> Session:
    """A session whose writes are always rolled back.

    The session is bound to a connection with an already-open transaction, and
    `join_transaction_mode="create_savepoint"` turns the `db.commit()` calls
    inside request handlers into savepoint releases. So handlers run exactly as
    they do in production — they really do commit — while the outer transaction
    is discarded at the end of the test.

    The alternative, deleting rows afterwards, leaves debris whenever a test
    fails midway and makes the next run's failure a mystery.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(autouse=True)
def no_certificate_probe(monkeypatch):
    """Tests never knock on a real HTTPS address (Phase 19's status card does,
    with a two-second timeout). A test about the probe replaces this."""
    from app import certificate_probe

    monkeypatch.setattr(certificate_probe, "_knock", lambda host, port, name: None)
    certificate_probe._cache.clear()


@pytest.fixture
def client(db: Session) -> TestClient:
    """A TestClient whose requests share the test's transaction."""
    app.dependency_overrides[get_db] = lambda: db
    # Background work after the response (announcing a correction, say) runs
    # on the same session too, and must not close it: the test still needs it.
    app.dependency_overrides[get_session_factory] = lambda: lambda: nullcontext(db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ── Data builders ────────────────────────────────────────────────────────────
#
# Plain functions rather than a fixture per entity: a test that needs "an agent
# on another team" should be able to say so in one line, without a new fixture
# and without depending on a shared object some other test also mutates.


@pytest.fixture
def org(db: Session) -> Organization:
    organization = Organization(
        name="Acme",
        timezone="America/New_York",
        week_starts_on=1,
        fiscal_year_start_month=1,
        currency="USD",
    )
    db.add(organization)
    db.flush()
    return organization


@pytest.fixture
def make_user(db: Session, org: Organization):
    counter = iter(range(1, 10_000))

    def _make(
        role: str = "agent",
        team: Team | None = None,
        *,
        name: str | None = None,
        status: str = "active",
    ) -> UserAccount:
        n = next(counter)
        user = UserAccount(
            organization_id=org.id,
            email=f"{role}{n}@acme.example",
            full_name=name or f"{role.title()} {n}",
            org_role=role,
            status=status,
            team_id=team.id if team else None,
        )
        db.add(user)
        db.flush()
        return user

    return _make


@pytest.fixture
def make_team(db: Session, org: Organization):
    counter = iter(range(1, 10_000))

    def _make(name: str | None = None) -> Team:
        team = Team(organization_id=org.id, name=name or f"Team {next(counter)}")
        db.add(team)
        db.flush()
        return team

    return _make


@pytest.fixture
def make_metric(db: Session, org: Organization):
    counter = iter(range(1, 10_000))

    def _make(
        key: str | None = None,
        *,
        aggregation: str = "sum",
        direction: str = "higher_is_better",
        unit: str = "count",
        decimal_places: int = 0,
    ) -> MetricDefinition:
        metric = MetricDefinition(
            organization_id=org.id,
            key=key or f"metric_{next(counter)}",
            name=(key or "Metric").replace("_", " ").title(),
            aggregation=aggregation,
            direction=direction,
            unit=unit,
            decimal_places=decimal_places,
        )
        db.add(metric)
        db.flush()
        return metric

    return _make


def _office_for(db: Session, team_id: int | None) -> int | None:
    if team_id is None:
        return None
    team = db.get(Team, team_id)
    return team.office_id if team else None


@pytest.fixture
def make_fact(db: Session, org: Organization):
    def _make(
        metric: MetricDefinition,
        user: UserAccount,
        value: float | Decimal,
        occurred_at: datetime,
        *,
        team: Team | None = None,
        office_id: int | None = None,
    ) -> MetricFact:
        fact = MetricFact(
            organization_id=org.id,
            metric_definition_id=metric.id,
            subject_user_id=user.id,
            # Defaults to the user's current team, mirroring the write paths —
            # but overridable, so a test can build history for someone who has
            # since transferred.
            subject_team_id=team.id if team else user.team_id,
            # Mirrors the write paths: the office of whichever team the fact is
            # attributed to, resolved now and then frozen.
            subject_office_id=office_id if office_id is not None else _office_for(
                db, team.id if team else user.team_id
            ),
            value=Decimal(str(value)),
            occurred_at=occurred_at,
            source_type="manual",
            created_at=datetime.now(UTC),
        )
        db.add(fact)
        db.flush()
        return fact

    return _make


@pytest.fixture
def sign_in(db: Session, client: TestClient):
    """Give the client a real session cookie for `user`.

    A Session row plus the cookie, rather than POSTing to /auth/login: it
    exercises the same `current_user` path a real request takes, without paying
    bcrypt's deliberate ~250ms on every test.
    """

    def _sign_in(user: UserAccount) -> UserAccount:
        from app.models import Session as SessionRow

        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        db.add(
            SessionRow(
                user_id=user.id,
                token_hash=_hash_token(token),
                created_at=now,
                last_used_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
        db.flush()
        client.cookies.set(COOKIE_NAME, token)
        return user

    return _sign_in


@pytest.fixture
def registry_slot():
    """Let a test register a connector, and always put the registry back.

    The connector registry is process-global, so a test that adds one without
    restoring leaks it into every test that runs afterwards — including the ones
    asserting which connectors this build has.
    """
    from app import connectors

    saved = dict(connectors._REGISTRY)
    yield
    connectors._REGISTRY.clear()
    connectors._REGISTRY.update(saved)


#: Where the `org` fixture is, so where its "today" and "this month" are.
ORG_ZONE = ZoneInfo("America/New_York")


def org_now() -> datetime:
    """Now, on the test organization's clock."""
    return datetime.now(ORG_ZONE)


def org_today() -> date:
    """Today where the test organization is — not the server's UTC date, which
    runs four or five hours ahead and is already tomorrow every evening."""
    return org_now().date()


def within_this_month(hour: int = 15) -> datetime:
    """A moment inside the current month, in the past, whatever today is.

    **Thirteen tests failed for three weeks because this was a literal.** They
    were written with `datetime(2026, 8, 12)` and asserted against leaderboards
    whose period is "this month" — correct in August, and silently wrong from the
    first of September, when the fact fell outside the window the board asks for.
    Nothing about the product changed; the calendar moved.

    A fixed date is the right instinct — a test that drifts is a test that fails
    on a Tuesday for no reason — but the thing being fixed has to be the *offset*
    from the period, not the date. This is the first of the month plus a few
    hours, clamped to the past so that running on the first at midnight does not
    file a fact in the future.
    """
    # **In the test organization's zone, not UTC's.** For the first four hours
    # of every month UTC is already in the new month while New York — where
    # the `org` fixture is — is still in the old one, so a moment chosen in
    # UTC's month fell outside the organization's "this month" and sixteen
    # tests failed between midnight and 4am UTC on the 1st.
    now = org_now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    moment = min(start + timedelta(hours=hour), now - timedelta(minutes=1))
    return moment.astimezone(UTC)


@pytest.fixture(autouse=True)
def _no_real_announcements(monkeypatch):
    """No test may post to a real chat channel.

    **Added after one did.** A test replaced the poster after the function had
    already bound the real one as a default argument, and a request went out to
    Microsoft from the test suite. The functions now look the poster up when
    called; this makes any test that forgets to supply a fake fail loudly
    instead of quietly reaching the internet.
    """
    from app import announcements

    def refuse(url, payload):
        raise AssertionError(f"A test tried to post a real announcement to {url}")

    monkeypatch.setattr(announcements, "_post", refuse)


@pytest.fixture(autouse=True)
def _no_real_teams_structure(monkeypatch):
    """No test may read a real Microsoft Teams structure.

    `pytest.fail` rather than an exception: the structure read catches every
    `Exception` so a refusal never costs a sync, and a guard it could swallow
    would be no guard. A test that wants a tenant installs one.
    """
    from app.directory import sync as directory_sync

    def refuse(db, connection, want=None):
        pytest.fail("A test tried to read the Microsoft Teams structure from Graph")

    monkeypatch.setitem(directory_sync.STRUCTURE_READERS, "microsoft", refuse)


@pytest.fixture(autouse=True)
def _no_real_teams_posts(monkeypatch):
    """No test may post to, or sign in to, Microsoft Teams through Graph."""
    from app import announcements, teams_account

    def refuse(*args, **kwargs):
        raise AssertionError("A test tried to reach Microsoft Teams through Graph")

    monkeypatch.setattr(announcements, "_post_graph", refuse)
    monkeypatch.setattr(teams_account, "access_token", refuse)
    monkeypatch.setattr(teams_account, "_get", refuse)


@pytest.fixture(autouse=True)
def _no_real_report_mail(monkeypatch):
    """No test may email a coaching digest. A test that wants to see one
    installs its own sender."""
    from app import report_delivery

    def refuse(*args, **kwargs):
        raise AssertionError("A test tried to email a real coaching digest")

    monkeypatch.setattr(report_delivery, "_send", refuse)


@pytest.fixture(autouse=True)
def _no_real_audit_stream(monkeypatch):
    """No test may send the activity log to a real collector."""
    from app import audit_stream

    def refuse(*args, **kwargs):
        raise AssertionError("A test tried to send the activity log to a real collector")

    monkeypatch.setattr(audit_stream, "_post", refuse)
