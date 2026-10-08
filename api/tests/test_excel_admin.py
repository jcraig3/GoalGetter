"""One account for the deployment, and the workbooks it reads.

The connector itself is tested in `test_excel_connector.py`; what is left here is
the part an admin touches — whose files these are, what is currently being read,
and the two promises that are easy to break by accident:

**Signing out keeps the workbooks.** Their column mappings are the expensive part
and a mis-click must not cost them.

**Nothing here writes to Microsoft.** Asserted structurally rather than by
inspection, because "we would never do that" is not a test.
"""

import pytest

from app.crypto import encrypt
from app.models import DataSource, OauthClient
from app.routers.excel import _hit


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
    def _connect(*, files_token="rt-files", who="svc@contoso.com"):
        row = OauthClient(
            organization_id=org.id,
            provider="microsoft",
            client_id="client",
            client_secret_encrypted=encrypt("shhh"),
            tenant_id="contoso.onmicrosoft.com",
            files_refresh_token_encrypted=encrypt(files_token) if files_token else None,
            files_connected_as=who if files_token else "",
        )
        db.add(row)
        db.flush()
        return row

    return _connect


@pytest.fixture
def workbook(db, org):
    def _make(name="Closed deals", worksheet="Deals", **extra):
        row = DataSource(
            organization_id=org.id,
            name=name,
            connector="microsoft_excel",
            config={"drive_id": "d1", "item_id": "i1", "worksheet": worksheet},
            **extra,
        )
        db.add(row)
        db.flush()
        return row

    return _make


# ── What the panel is told ───────────────────────────────────────────────────


def test_an_unregistered_provider_offers_nothing(signed_in, db):
    """No registration means every other field is moot. The panel hides itself
    rather than offering a sign-in that would 409."""
    db.commit()

    body = signed_in.get("/api/admin/excel/status").json()

    assert body["registered"] is False
    assert body["connected"] is False
    assert body["workbooks"] == []


def test_a_registered_provider_with_nobody_signed_in(signed_in, db, connection):
    connection(files_token=None)
    db.commit()

    body = signed_in.get("/api/admin/excel/status").json()

    assert body["registered"] is True
    assert body["connected"] is False
    assert body["connected_as"] == ""


def test_the_panel_names_the_account_and_its_workbooks(
    signed_in, db, connection, workbook
):
    """**Named, not counted.** A stale workbook is spotted by recognising it, not
    by noticing a total went up."""
    connection(who="svc@contoso.com")
    workbook(name="Closed deals", worksheet="Deals")
    workbook(name="Pipeline", worksheet="Q3")
    db.commit()

    body = signed_in.get("/api/admin/excel/status").json()

    assert body["connected"] is True
    assert body["connected_as"] == "svc@contoso.com"
    assert [(w["name"], w["worksheet"]) for w in body["workbooks"]] == [
        ("Closed deals", "Deals"),
        ("Pipeline", "Q3"),
    ]


def test_an_archived_workbook_is_not_listed(signed_in, db, connection, workbook):
    """Archiving is how a source is removed while its facts are kept — see
    `data_sources.archive_source`. A removed workbook still appearing here would
    make the list disagree with the source list."""
    from datetime import UTC, datetime

    connection()
    workbook(name="Still read")
    workbook(name="Removed", archived_at=datetime.now(UTC))
    db.commit()

    body = signed_in.get("/api/admin/excel/status").json()

    assert [w["name"] for w in body["workbooks"]] == ["Still read"]


# ── Signing out ──────────────────────────────────────────────────────────────


def test_signing_out_keeps_every_workbook(signed_in, db, connection, workbook):
    """**The promise this makes in its own docstring.** The mappings are the
    expensive part; losing them to a mis-click would make signing out a decision
    nobody dares take."""
    row = connection()
    workbook(name="Closed deals")
    db.commit()

    assert signed_in.delete("/api/admin/excel/account").status_code == 204

    db.refresh(row)
    assert row.files_refresh_token_encrypted is None
    assert row.files_connected_as == ""

    body = signed_in.get("/api/admin/excel/status").json()
    assert body["connected"] is False
    assert [w["name"] for w in body["workbooks"]] == ["Closed deals"]


def test_browsing_without_an_account_says_which_step_is_missing(
    signed_in, db, connection
):
    """A 409 naming the sign-in, not a 500 or an empty list. An empty list would
    read as "you have no spreadsheets", which is a different and wrong problem."""
    connection(files_token=None)
    db.commit()

    reply = signed_in.get("/api/admin/excel/files")

    assert reply.status_code == 409
    assert "signed in" in reply.json()["detail"]


# ── Which files are offered ──────────────────────────────────────────────────


def _item(name, *, drive="d1", item="i1", path="/drive/root:/Sales/Reports"):
    return {
        "id": item,
        "name": name,
        "webUrl": "https://contoso.sharepoint.com/x.xlsx",
        "lastModifiedDateTime": "2026-09-01T10:00:00Z",
        "parentReference": {"driveId": drive, "path": path},
    }


@pytest.mark.parametrize(
    "name, offered",
    [
        ("Closed deals.xlsx", True),
        ("Macros.xlsm", True),
        ("Notes.docx", False),
        ("Old figures.csv", False),
        ("Sales", False),
    ],
)
def test_only_workbooks_are_offered(name, offered):
    """Filtered by extension rather than by mime type: Graph reports several types
    for `.xlsx` depending on where the file came from, and the extension is what
    the person choosing is looking at anyway."""
    assert (_hit(_item(name)) is not None) is offered


def test_a_file_with_no_drive_is_skipped_rather_than_half_offered():
    """Both ids are needed to address it. One without the other is an entry that
    looks choosable and fails on the first read."""
    assert _hit(_item("Deals.xlsx", drive="")) is None


def test_the_folder_is_shown_in_words():
    """Graph's path is `/drive/root:/Folder/Sub`; only the half after the colon
    means anything to somebody scanning a list."""
    assert _hit(_item("Deals.xlsx")).location == "Sales/Reports"


def test_a_file_at_the_root_says_so_rather_than_nothing():
    """An empty location column reads as a rendering fault."""
    assert _hit(_item("Deals.xlsx", path="/drive/root:")).location == "My files"


# ── The promise that matters most ────────────────────────────────────────────


def test_nothing_in_this_module_writes_to_microsoft():
    """**Structural, not a matter of care.** Every Graph call made with the files
    token is a GET, and the scope the account holds — `Files.Read.All` — could not
    write even if one were not. This asserts the first half; Microsoft enforces
    the second.
    """
    import inspect

    from app.routers import excel as module

    source = inspect.getsource(module)
    for verb in ("client.post", "client.put", "client.patch", "client.delete"):
        assert verb not in source, f"{verb} would be a write to Microsoft"

    assert "Files.Read.All" in " ".join(
        __import__("app.excel_account", fromlist=["SCOPES"]).SCOPES
    )


# ── The credential lives on the organization, not the source ─────────────────


def test_a_source_using_the_shared_account_counts_as_credentialled(
    signed_in, db, connection, workbook
):
    """**The regression this exists to stop.** `credentials_set` used to mean
    "this source stores a secret", which was the same question as "this source
    can authenticate" right up until the Excel account moved to the organization.
    Leaving it asserting the old one made every working Excel source report
    *Setup unfinished* on its own page and offer to resume a wizard it had
    already completed — with a hundred and ninety-four facts imported.
    """
    from app import oauth

    connection()
    source = workbook(name="Closed deals")
    db.commit()

    assert oauth.has_shared_credential(db, source) is True

    # The detail endpoint, because that is what `/integrations/sources/{id}`
    # reads and where the false "not finished" banner was rendered.
    body = signed_in.get(f"/api/data-sources/{source.id}").json()
    assert body["credentials_set"] is True


def test_without_an_account_signed_in_it_does_not(signed_in, db, connection, workbook):
    """The other half: an Excel source with nobody signed in genuinely cannot
    authenticate, and saying so is the point of the field."""
    from app import oauth

    connection(files_token=None)
    source = workbook(name="Closed deals")
    db.commit()

    assert oauth.has_shared_credential(db, source) is False


def test_the_shared_account_covers_only_the_connectors_that_use_it(
    db, org, connection, make_metric
):
    """A webhook does not borrow the Excel account's credential just because one
    is signed in."""
    from app import oauth
    from app.models import DataSource

    connection()
    other = DataSource(
        organization_id=org.id, name="Hook", connector="webhook", backfill_days=0
    )
    db.add(other)
    db.flush()

    assert oauth.has_shared_credential(db, other) is False


# ── One sheet, one source ────────────────────────────────────────────────────


def _connect(client, org_id, db, *, drive="d1", item="i1", worksheet="Deals"):
    """Create a source and point it at a sheet, the way the wizard does."""
    made = client.post(
        "/api/data-sources", json={"connector": "microsoft_excel", "name": "Sheet"}
    ).json()
    return made, client.patch(
        f"/api/data-sources/{made['id']}",
        json={
            "config": {
                "drive_id": drive,
                "item_id": item,
                "worksheet": worksheet,
                "header_row": 1,
            }
        },
    )


def test_the_same_workbook_and_tab_is_refused_twice(signed_in, db, org, connection):
    """**Because five of them is what happens otherwise.** Every trip through the
    wizard makes a new source, so re-running it to fix a mapping leaves the
    previous attempt behind — enabled, on its own schedule, importing the same
    rows from the same file, and nothing on screen saying they are the same
    sheet."""
    connection()
    db.commit()

    first, ok = _connect(signed_in, org.id, db)
    assert ok.status_code == 200

    _, clash = _connect(signed_in, org.id, db)

    assert clash.status_code == 409
    detail = clash.json()["detail"]
    assert "already reads that spreadsheet" in detail
    # Names the one in the way, because "that is a duplicate" without saying of
    # what leaves somebody hunting through a list.
    assert first["name"] in detail


def test_another_tab_in_the_same_workbook_is_fine(signed_in, db, org, connection):
    """A workbook with a tab per team is the normal shape, so the file alone is
    not the identity — the tab is part of it."""
    connection()
    db.commit()

    _connect(signed_in, org.id, db, worksheet="West")
    _, second = _connect(signed_in, org.id, db, worksheet="East")

    assert second.status_code == 200


def test_a_different_workbook_is_fine(signed_in, db, org, connection):
    connection()
    db.commit()

    _connect(signed_in, org.id, db, item="i1")
    _, second = _connect(signed_in, org.id, db, item="i2")

    assert second.status_code == 200


def test_re_saving_the_same_source_is_not_a_clash_with_itself(
    signed_in, db, org, connection
):
    """Changing the header row on a finished source must not report the source as
    a duplicate of itself."""
    connection()
    db.commit()

    made, _ = _connect(signed_in, org.id, db)
    again = signed_in.patch(
        f"/api/data-sources/{made['id']}",
        json={
            "config": {
                "drive_id": "d1",
                "item_id": "i1",
                "worksheet": "Deals",
                "header_row": 3,
            }
        },
    )

    assert again.status_code == 200


def test_a_removed_source_is_not_in_the_way(signed_in, db, org, connection):
    """Archiving is how a spreadsheet is taken off. Treating a removed one as a
    clash would make removing-and-re-adding impossible."""
    connection()
    db.commit()

    made, _ = _connect(signed_in, org.id, db)
    assert signed_in.post(f"/api/data-sources/{made['id']}/archive").status_code == 200

    _, again = _connect(signed_in, org.id, db)

    assert again.status_code == 200


def test_two_half_built_sources_with_no_ids_are_not_duplicates(
    signed_in, db, org, connection
):
    """"Both have nothing set" is not sameness — otherwise the second connect
    flow anybody opens would be refused before they had chosen a file."""
    connection()
    db.commit()

    for _ in range(2):
        made = signed_in.post(
            "/api/data-sources",
            json={"connector": "microsoft_excel", "name": "Draft"},
        ).json()
        reply = signed_in.patch(
            f"/api/data-sources/{made['id']}",
            json={"config": {"drive_id": "", "item_id": "", "worksheet": ""}},
        )
        assert reply.status_code == 200
