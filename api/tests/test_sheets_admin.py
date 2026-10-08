"""One Google account for the deployment, and the spreadsheets it reads.

The Sheets twin of `test_excel_admin.py`, covering what differs rather than
repeating what does not. Three things are genuinely Google's own:

**Two credentials, one slot.** A signed-in account and a service account are both
honest answers, and whichever is present is the one used — so storing one must
clear the other, or "which is this reading as?" becomes unanswerable from the data.

**A key alone reads nothing.** Google grants a service account exactly the files
shared with its address, so the address is the second half of the setup and the
API has to hand it back.

**The identity of a sheet is one id and a tab**, where Excel needs two ids — so
the duplicate rule is shaped per connector.
"""

import json

import pytest

from app import oauth, sheets_account
from app.crypto import decrypt, encrypt
from app.models import DataSource, OauthClient

KEY = json.dumps(
    {
        "type": "service_account",
        "client_email": "robot@acme.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
    }
)


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


@pytest.fixture
def connection(db, org):
    def _connect(*, token=None, key=None, who=""):
        row = OauthClient(
            organization_id=org.id,
            provider="google",
            client_id="client",
            client_secret_encrypted=encrypt("shhh"),
            sheets_refresh_token_encrypted=encrypt(token) if token else None,
            sheets_service_account_encrypted=encrypt(key) if key else None,
            sheets_connected_as=who,
        )
        db.add(row)
        db.flush()
        return row

    return _connect


@pytest.fixture
def sheet(db, org):
    def _make(name="Deals", **config):
        row = DataSource(
            organization_id=org.id,
            name=name,
            connector="google_sheets",
            config={"spreadsheet_id": "s1", "tab": "Closed", **config},
        )
        db.add(row)
        db.flush()
        return row

    return _make


# ── What the panel is told ───────────────────────────────────────────────────


def test_an_unregistered_provider_offers_nothing(signed_in, db):
    db.commit()

    body = signed_in.get("/api/admin/sheets/status").json()

    assert body["registered"] is False
    assert body["connected"] is False


def test_a_signed_in_account_is_not_a_service_account(signed_in, db, connection):
    connection(token="rt", who="sam@acme.example")
    db.commit()

    body = signed_in.get("/api/admin/sheets/status").json()

    assert body["connected"] is True
    assert body["connected_as"] == "sam@acme.example"
    assert body["service_account"] is False


def test_a_service_account_says_so(signed_in, db, connection):
    """**Because it changes the next step.** A service account reads nothing until
    the spreadsheet has been shared with its address, and nobody guesses that — so
    the screen has to know which kind it is holding."""
    connection(key=KEY, who="robot@acme.iam.gserviceaccount.com")
    db.commit()

    body = signed_in.get("/api/admin/sheets/status").json()

    assert body["connected"] is True
    assert body["service_account"] is True


# ── Two credentials, one slot ────────────────────────────────────────────────


def test_a_key_replaces_a_signed_in_account(signed_in, db, connection):
    """Both stored at once would make "which is this reading as?" a question the
    screen could not answer from the data."""
    row = connection(token="rt", who="sam@acme.example")
    db.commit()

    reply = signed_in.post("/api/admin/sheets/service-account", json={"key": KEY})

    assert reply.status_code == 200
    db.refresh(row)
    assert row.sheets_refresh_token_encrypted is None
    assert decrypt(row.sheets_service_account_encrypted) == KEY


def test_the_address_to_share_with_comes_back(signed_in, db, connection):
    """**The second half of the setup.** A key alone reads nothing, so a screen
    that took it and said "connected" would be lying until a human pressed Share."""
    connection()
    db.commit()

    body = signed_in.post(
        "/api/admin/sheets/service-account", json={"key": KEY}
    ).json()

    assert body["share_with"] == "robot@acme.iam.gserviceaccount.com"


def test_something_that_is_not_a_key_is_refused_with_a_reason(
    signed_in, db, connection
):
    connection()
    db.commit()

    reply = signed_in.post("/api/admin/sheets/service-account", json={"key": "nope"})

    assert reply.status_code == 400
    assert "whole JSON file" in reply.json()["detail"]


def test_an_oauth_client_secret_pasted_by_mistake_says_what_is_wrong(
    signed_in, db, connection
):
    """The likeliest wrong paste: also JSON, also from the same console page, and
    with no `client_email` in it."""
    connection()
    db.commit()

    reply = signed_in.post(
        "/api/admin/sheets/service-account",
        json={"key": json.dumps({"installed": {"client_id": "x"}})},
    )

    assert reply.status_code == 400
    assert "client_email" in reply.json()["detail"]


def test_disconnecting_drops_both_and_keeps_the_sheets(
    signed_in, db, connection, sheet
):
    row = connection(key=KEY, who="robot@acme.iam.gserviceaccount.com")
    sheet(name="Closed deals")
    db.commit()

    assert signed_in.delete("/api/admin/sheets/account").status_code == 204

    db.refresh(row)
    assert row.sheets_service_account_encrypted is None
    assert row.sheets_refresh_token_encrypted is None
    body = signed_in.get("/api/admin/sheets/status").json()
    assert [s["name"] for s in body["spreadsheets"]] == ["Closed deals"]


# ── The shared credential reaches the connector ──────────────────────────────


def test_a_sheets_source_counts_as_credentialled(db, org, connection, sheet):
    """Same regression as Excel's: `credentials_set` means "can authenticate", not
    "stores a secret". Without this a working Sheets source reports *Setup
    unfinished* and offers to resume a wizard it finished."""
    connection(token="rt")
    source = sheet()

    assert oauth.has_shared_credential(db, source) is True


def test_without_a_connected_account_it_does_not(db, org, connection, sheet):
    connection()
    source = sheet()

    assert oauth.has_shared_credential(db, source) is False


def test_each_connector_reaches_its_own_account(db, org, connection, sheet):
    """A Google account signed in must not make an Excel source look connected,
    and the table in `oauth` is what keeps them apart."""
    connection(token="rt")
    excel_source = DataSource(
        organization_id=org.id,
        name="Book",
        connector="microsoft_excel",
        config={"drive_id": "d", "item_id": "i"},
    )
    db.add(excel_source)
    db.flush()

    assert oauth.has_shared_credential(db, sheet()) is True
    assert oauth.has_shared_credential(db, excel_source) is False


# ── One sheet, one source ────────────────────────────────────────────────────


def _connect(client, *, sheet_id="s1", tab="Closed"):
    made = client.post(
        "/api/data-sources", json={"connector": "google_sheets", "name": "Sheet"}
    ).json()
    return made, client.patch(
        f"/api/data-sources/{made['id']}",
        json={"config": {"spreadsheet_id": sheet_id, "tab": tab, "header_row": 1}},
    )


def test_the_same_spreadsheet_and_tab_is_refused_twice(signed_in, db, connection):
    connection(token="rt")
    db.commit()

    first, ok = _connect(signed_in)
    assert ok.status_code == 200

    _, clash = _connect(signed_in)

    assert clash.status_code == 409
    assert "already reads that spreadsheet" in clash.json()["detail"]
    assert first["name"] in clash.json()["detail"]


def test_another_tab_in_the_same_spreadsheet_is_fine(signed_in, db, connection):
    """A sheet with a tab per month is the normal shape, so the file alone is not
    the identity."""
    connection(token="rt")
    db.commit()

    _connect(signed_in, tab="January")
    _, second = _connect(signed_in, tab="February")

    assert second.status_code == 200


def test_a_google_sheet_does_not_clash_with_an_excel_workbook(
    signed_in, db, org, connection
):
    """The identity keys differ per connector, so an empty `drive_id` on a Google
    source must not match an Excel source that also has none."""
    connection(token="rt")
    db.commit()

    _connect(signed_in)
    made = signed_in.post(
        "/api/data-sources", json={"connector": "microsoft_excel", "name": "Book"}
    ).json()
    reply = signed_in.patch(
        f"/api/data-sources/{made['id']}",
        json={"config": {"drive_id": "d1", "item_id": "i1", "worksheet": "Closed"}},
    )

    assert reply.status_code == 200


def test_a_half_built_google_source_is_not_a_duplicate(signed_in, db, connection):
    """Two drafts with no spreadsheet chosen are not the same spreadsheet."""
    connection(token="rt")
    db.commit()

    for _ in range(2):
        made = signed_in.post(
            "/api/data-sources", json={"connector": "google_sheets", "name": "Draft"}
        ).json()
        reply = signed_in.patch(
            f"/api/data-sources/{made['id']}",
            json={"config": {"spreadsheet_id": "", "tab": ""}},
        )
        assert reply.status_code == 200


# ── The promise that matters most ────────────────────────────────────────────


def test_nothing_in_the_sheets_router_writes_to_google():
    """**Structural, not a matter of care.** Both scopes are `readonly` by name,
    and every Google call here is a GET. The two POSTs on this router store and
    drop GoalGetter's own credential; neither touches anything in Google.
    """
    import inspect

    from app.routers import sheets as module

    source = inspect.getsource(module)
    for verb in ("client.post", "client.put", "client.patch", "client.delete"):
        assert verb not in source, f"{verb} would be a write to Google"

    assert all("readonly" in scope for scope in sheets_account.SCOPES)
