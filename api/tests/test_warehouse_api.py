"""The warehouse connection endpoints.

The module underneath is tested in `test_warehouse_account.py`; what is left here
is what an admin can do through the API, and the two promises that are easy to
break by accident:

**A secret goes in and never comes back.** The status endpoint reports whether a
key is stored, never what it is.

**Omitted means keep.** Fixing a typo in the warehouse name must not cost somebody
their private key.
"""

import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import rsa

from app import warehouse_account
from app.connectors.sql import describe_session
from app.models import DataSource


@pytest.fixture(scope="module")
def pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()
    ).decode()


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


def save(client, **overrides):
    body = {"account": "ab12345.us-east-1", "username": "svc"}
    body.update(overrides)
    return client.put("/api/admin/warehouse/snowflake", json=body)


# ── Reading ──────────────────────────────────────────────────────────────────


def test_nothing_connected_reports_so_without_failing(signed_in, db):
    db.commit()

    body = signed_in.get("/api/admin/warehouse/snowflake").json()

    assert body["connected"] is False
    assert body["private_key_set"] is False
    assert body["queries"] == 0


def test_the_key_never_comes_back(signed_in, db, pem):
    """**The one thing this endpoint must never do.** There is no legitimate
    reason for a browser to receive a private key, and every mechanism that
    offers to show one is a mechanism that can be made to."""
    db.commit()
    save(signed_in, private_key=pem)

    body = signed_in.get("/api/admin/warehouse/snowflake").json()

    assert body["private_key_set"] is True
    assert pem not in str(body)
    assert "BEGIN PRIVATE KEY" not in str(body)


# ── Writing ──────────────────────────────────────────────────────────────────


def test_saving_a_key_connects_it(signed_in, db, pem):
    db.commit()

    body = save(signed_in, private_key=pem).json()

    assert body["connected"] is True
    assert body["account"] == "ab12345.us-east-1"


def test_a_bad_key_is_refused_with_a_reason(signed_in, db, pem):
    """In front of the person who pasted it, rather than as an authentication
    error at three in the morning against a warehouse nobody is watching."""
    db.commit()

    reply = save(signed_in, private_key="not a key at all")

    assert reply.status_code == 400
    assert "could not be read" in reply.json()["detail"]
    assert signed_in.get("/api/admin/warehouse/snowflake").json()["connected"] is False


def test_a_public_key_says_which_half_is_wanted(signed_in, db, pem):
    db.commit()
    public = (
        "-----BEGIN PUBLIC KEY-----\nMIIBIjANBg\n-----END PUBLIC KEY-----\n"
    )

    reply = save(signed_in, private_key=public)

    assert reply.status_code == 400
    assert "public key" in reply.json()["detail"]


def test_omitting_the_key_keeps_it(signed_in, db, pem):
    """The rule `oauth.store_client` uses. Without it, correcting a warehouse name
    means finding the .p8 file again."""
    db.commit()
    save(signed_in, private_key=pem)

    body = save(signed_in, warehouse="ANALYTICS_WH").json()

    assert body["private_key_set"] is True
    assert body["warehouse"] == "ANALYTICS_WH"


def test_an_account_and_a_username_are_both_required(signed_in, db, pem):
    db.commit()

    assert save(signed_in, account="", private_key=pem).status_code == 400
    assert save(signed_in, username="", private_key=pem).status_code == 400


# ── Removing ─────────────────────────────────────────────────────────────────


def test_forgetting_keeps_the_queries(signed_in, db, org, pem):
    """Their SQL and their column mappings are still correct and expensive to
    rebuild; what has gone is the ability to run them."""
    db.add(
        DataSource(
            organization_id=org.id,
            name="Sales",
            connector="snowflake",
            config={"query": "SELECT * FROM V", "read_mode": "full"},
        )
    )
    db.commit()
    save(signed_in, private_key=pem)

    assert signed_in.delete("/api/admin/warehouse/snowflake").status_code == 204

    body = signed_in.get("/api/admin/warehouse/snowflake").json()
    assert body["connected"] is False
    # The query is still there, and still counted.
    assert body["queries"] == 1


# ── Probing ──────────────────────────────────────────────────────────────────


def test_testing_before_connecting_says_what_is_missing(signed_in, db):
    """A 409 naming the step, rather than a driver error nobody can act on."""
    db.commit()

    reply = signed_in.post("/api/admin/warehouse/snowflake/test")

    assert reply.status_code == 409
    assert "save it before testing" in reply.json()["detail"]


def test_a_session_without_a_warehouse_is_not_a_pass():
    """The failure a green tick used to hide.

    Snowflake separates storage from compute, so these credentials are correct and
    can still run nothing. Every field that would supply a warehouse is optional,
    which makes this the likeliest way a connection is wrong.
    """
    verdict = describe_session({"warehouse": None, "role": "ANALYST", "database": "ANALYTICS"})

    assert verdict.ok is False
    assert "no warehouse is selected" in verdict.detail
    # Names both fixes, because which one applies depends on who owns the user.
    assert "Warehouse field" in verdict.detail
    assert "DEFAULT_WAREHOUSE" in verdict.detail
    assert "ANALYST" in verdict.detail


def test_a_blank_warehouse_reads_the_same_as_a_missing_one():
    """Snowflake returns an empty string in some drivers and NULL in others."""
    assert describe_session({"warehouse": "   ", "role": "", "database": ""}).ok is False


def test_a_working_session_says_what_it_resolved_to():
    """Where a query will run is the answer, not that something ran.

    It is the only moment an admin who left the warehouse blank finds out which
    default they inherited.
    """
    verdict = describe_session(
        {"warehouse": "ANALYTICS_WH", "role": "ANALYST", "database": "ANALYTICS"}
    )

    assert verdict.ok is True
    assert "ANALYTICS_WH" in verdict.detail
    assert "ANALYST" in verdict.detail
    assert "ANALYTICS" in verdict.detail
    assert verdict.info["warehouse"] == "ANALYTICS_WH"


def test_a_working_session_needs_only_the_warehouse():
    """Role and database are optional everywhere else, so not here either."""
    verdict = describe_session({"warehouse": "ANALYTICS_WH"})

    assert verdict.ok is True
    assert "ANALYTICS_WH" in verdict.detail
    # No trailing "as , in ." from fields nobody filled in.
    assert verdict.detail == "Connected. Queries will run on ANALYTICS_WH."


def test_only_an_admin_may_touch_any_of_it(client, db, make_user, sign_in):
    """A warehouse credential reads somebody else's database. That is not a
    manager-level decision."""
    sign_in(make_user("manager"))
    db.commit()

    assert client.get("/api/admin/warehouse/snowflake").status_code == 403
    assert save(client).status_code == 403
    assert client.delete("/api/admin/warehouse/snowflake").status_code == 403
    assert client.post("/api/admin/warehouse/snowflake/test").status_code == 403


def test_the_probe_names_a_query_left_in_a_name_field(signed_in, db, org):
    """A row saved before the check still has to fail legibly.

    Left to the driver, a query in the database field returns a connection error
    naming a host — which sends somebody looking at networking for a mistake that
    is on screen in front of them.
    """
    warehouse_account.save(
        db, org.id, account="ab1", username="JC", token="pat-1"
    )
    # Straight onto the row, the way an older save would have left it.
    warehouse_account.get(db, org.id).database = "SELECT * FROM ANALYTICS.S.C__V;"
    db.commit()

    reply = signed_in.post("/api/admin/warehouse/snowflake/test")

    assert reply.status_code == 200
    body = reply.json()
    assert body["ok"] is False
    assert "database field takes a name" in body["detail"]
    assert "step 2" in body["detail"]


def test_the_probe_survives_a_connection_with_nothing_optional_filled_in(
    signed_in, db, org, monkeypatch
):
    """**The normal case, and it returned a 500.**

    Warehouse, role and database are all optional and all default to the user's
    own. A fully-qualified query names its own database, so leaving it blank is
    what most connections look like — and `database=row.database or None` turned
    that into a validation error before any connection was attempted.
    """
    warehouse_account.save(db, org.id, account="ab1", username="JC", token="pat-1")
    db.commit()

    # Stop at the driver: what is being tested is that we get that far.
    def reached(config, secrets):
        from app.connectors import ConnectionResult

        assert config.database == ""
        assert config.options == {}
        return ConnectionResult(ok=True, detail="reached the driver")

    monkeypatch.setattr("app.routers.warehouse.probe_snowflake", reached)

    reply = signed_in.post("/api/admin/warehouse/snowflake/test")

    assert reply.status_code == 200
    assert reply.json() == {"ok": True, "detail": "reached the driver"}
