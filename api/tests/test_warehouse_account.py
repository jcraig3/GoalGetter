"""The warehouse credential, held once for the deployment.

**Connect once, add queries.** The same split as the spreadsheet accounts: an
account identifier, a username, a key, a warehouse and a role are answered when
the warehouse is connected, and each source after that is a name and a query.

What is genuinely Snowflake's own, and therefore what is tested here:

**A private key instead of a password**, because Snowflake blocks password-only
sign-ins for service users — so this is the only credential that works, not a
hardening option.

**The key is parsed before it is stored**, in front of the person who pasted it,
rather than surfacing as an authentication error at three in the morning.

**Reading everything is per source**, not per connector — a pre-aggregated view is
whole every time, an incremental query is a window, and getting that backwards
deletes every fact outside the window on every pass.
"""

import pytest
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric import rsa

from app import oauth, warehouse_account
from app.connectors.sql import KeyProblem
from app.models import DataSource


@pytest.fixture(scope="module")
def keys():
    """One RSA key, in the three shapes somebody might paste."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {
        "plain": key.private_bytes(
            ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()
        ).decode(),
        "encrypted": key.private_bytes(
            ser.Encoding.PEM,
            ser.PrivateFormat.PKCS8,
            ser.BestAvailableEncryption(b"hunter2"),
        ).decode(),
        "public": key.public_key()
        .public_bytes(ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    }


@pytest.fixture
def source(db, org):
    def _make(**config):
        row = DataSource(
            organization_id=org.id,
            name="Sales",
            connector="snowflake",
            config={"query": "SELECT * FROM V", "read_mode": "full", **config},
        )
        db.add(row)
        db.flush()
        return row

    return _make


# ── Connect once ─────────────────────────────────────────────────────────────


def test_a_connection_needs_somewhere_to_go_and_something_to_prove_it(db, org, keys):
    """A row holding only an account name is a half-filled form, not a connection.
    Reporting it as one is how a source claims to be set up and fails on its first
    sync."""
    assert warehouse_account.is_connected(db, org.id) is False

    warehouse_account.save(db, org.id, account="ab1", username="", private_key=None)
    assert warehouse_account.is_connected(db, org.id) is False

    warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=keys["plain"]
    )
    assert warehouse_account.is_connected(db, org.id) is True


def test_the_credential_reaches_the_connector(db, org, keys, source):
    """`ensure_fresh` hands it over as `SqlSecrets` fields. A warehouse credential
    is not a token — it never expires and never refreshes — so it goes straight
    through rather than being dressed up as one."""
    warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=keys["plain"]
    )

    secrets = oauth.ensure_fresh(db, source(), None)

    assert secrets["username"] == "svc"
    assert secrets["private_key"].startswith("-----BEGIN PRIVATE KEY-----")


def test_the_connection_fills_in_where_to_run(db, org, source):
    """**The whole reason a source is two fields.** Account, warehouse, role and
    database are answered once; asking again on the second table would be five of
    six answers repeated, and five chances for two sources to disagree."""
    warehouse_account.save(
        db,
        org.id,
        account="ab12345.us-east-1",
        username="svc",
        warehouse="ANALYTICS_WH",
        role="ANALYST",
        database="ANALYTICS",
        password="pw",
    )

    config = oauth.config_for(db, source())

    assert config["account"] == "ab12345.us-east-1"
    assert config["warehouse"] == "ANALYTICS_WH"
    assert config["role"] == "ANALYST"
    assert config["database"] == "ANALYTICS"
    # And what the source itself owns is untouched.
    assert config["query"] == "SELECT * FROM V"


def test_the_connection_wins_over_a_stale_source_row(db, org, source):
    """It is the one place these are edited, so a source holding an old warehouse
    name must not quietly keep using it."""
    warehouse_account.save(
        db, org.id, account="new", username="svc", warehouse="NEW_WH", password="pw"
    )

    config = oauth.config_for(db, source(account="old", warehouse="OLD_WH"))

    assert config["account"] == "new"
    assert config["warehouse"] == "NEW_WH"


def test_a_snowflake_source_counts_as_credentialled(db, org, keys, source):
    """Same rule as the spreadsheets: `credentials_set` means "can authenticate",
    not "stores its own secret"."""
    row = source()
    assert oauth.has_shared_credential(db, row) is False

    warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=keys["plain"]
    )
    assert oauth.has_shared_credential(db, row) is True


# ── The key ──────────────────────────────────────────────────────────────────


def test_a_key_is_parsed_before_it_is_stored(db, org, keys):
    """In front of the person who pasted it, rather than as an authentication
    failure against a warehouse nobody is watching."""
    with pytest.raises(KeyProblem, match="public key"):
        warehouse_account.save(
            db, org.id, account="ab1", username="svc", private_key=keys["public"]
        )

    assert warehouse_account.get(db, org.id) is None


def test_an_encrypted_key_needs_its_passphrase(db, org, keys):
    with pytest.raises(KeyProblem, match="passphrase"):
        warehouse_account.save(
            db, org.id, account="ab1", username="svc", private_key=keys["encrypted"]
        )

    warehouse_account.save(
        db,
        org.id,
        account="ab1",
        username="svc",
        private_key=keys["encrypted"],
        key_passphrase="hunter2",
    )
    assert warehouse_account.is_connected(db, org.id) is True


def test_a_key_and_a_password_are_never_both_stored(db, org, keys):
    """A driver given both may prefer the password and fail against a Snowflake
    that no longer accepts one — which reads as "the key is wrong" and is not."""
    warehouse_account.save(db, org.id, account="ab1", username="svc", password="pw")
    row = warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=keys["plain"]
    )

    assert row.password_encrypted is None
    assert row.private_key_encrypted is not None


def test_none_leaves_a_secret_alone_and_empty_clears_it(db, org, keys):
    """The same rule `oauth.store_client` uses: an admin fixing a typo in the
    warehouse name must not have to find the private key again."""
    warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=keys["plain"]
    )

    warehouse_account.save(db, org.id, account="ab1", username="svc", warehouse="WH2")
    assert warehouse_account.is_connected(db, org.id) is True

    row = warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=""
    )
    assert row.private_key_encrypted is None


def test_forgetting_keeps_the_queries(db, org, keys, source):
    """Their SQL and their column mappings are still correct and expensive to
    rebuild; what has gone is the ability to run them."""
    warehouse_account.save(
        db, org.id, account="ab1", username="svc", private_key=keys["plain"]
    )
    row = source()

    warehouse_account.forget(db, org.id)

    assert warehouse_account.is_connected(db, org.id) is False
    assert db.get(DataSource, row.id) is not None

# ── Access tokens ────────────────────────────────────────────────────────────


def test_a_token_is_enough_to_count_as_connected(db, org):
    """A PAT is a whole credential, not a half-filled key form."""
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", token="pat-abc123"
    )

    assert warehouse_account.is_connected(db, org.id) is True
    assert warehouse_account.credentials_for(db, org.id)["token"] == "pat-abc123"


def test_a_token_is_encrypted_at_rest(db, org):
    """The same treatment as the key beside it."""
    row = warehouse_account.save(
        db, org.id, account="ab12345", username="JC", token="pat-abc123"
    )

    assert row.token_encrypted
    assert "pat-abc123" not in row.token_encrypted


def test_storing_a_token_clears_the_key(db, org, keys):
    """**One credential per connection.**

    Both present would make which one authenticates the driver's choice rather
    than anybody's decision — and a Snowflake that has stopped accepting the
    other then fails in a way that reads as the wrong secret.
    """
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", private_key=keys["plain"]
    )
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", token="pat-abc123"
    )

    creds = warehouse_account.credentials_for(db, org.id)
    assert creds["token"] == "pat-abc123"
    assert creds["private_key"] == ""
    assert creds["key_passphrase"] == ""


def test_storing_a_key_clears_the_token(db, org, keys):
    """The move a deployment is supposed to make, so it has to be clean."""
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", token="pat-abc123"
    )
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", private_key=keys["plain"]
    )

    creds = warehouse_account.credentials_for(db, org.id)
    assert creds["private_key"] == keys["plain"]
    assert creds["token"] == ""


def test_a_token_survives_an_edit_that_does_not_mention_it(db, org):
    """Fixing a typo in the warehouse name must not cost the credential."""
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", token="pat-abc123"
    )
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", warehouse="ANALYTICS_WH"
    )

    assert warehouse_account.credentials_for(db, org.id)["token"] == "pat-abc123"


def test_an_empty_token_clears_it(db, org):
    """None keeps, empty string clears — the rule every secret here follows."""
    warehouse_account.save(
        db, org.id, account="ab12345", username="JC", token="pat-abc123"
    )
    warehouse_account.save(db, org.id, account="ab12345", username="JC", token="")

    assert warehouse_account.credentials_for(db, org.id)["token"] == ""
    assert warehouse_account.is_connected(db, org.id) is False
