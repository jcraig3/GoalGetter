"""Google Sheets: a grid of cells as a data source.

Two things here are unlike every other connector, and they get most of the tests.

**A spreadsheet's header row is its field names**, so this is the one connector that
reshapes what it reads. Getting that wrong is not a crash — it is a mapping offered
`column 3` instead of `Amount`, or a row silently dropped for having a blank cell at
the end.

**A spreadsheet has no idea when a cell changed**, so every sync reads the whole tab.
That makes row identity load-bearing rather than a nicety, and one of the two options
is genuinely dangerous. The tests say so out loud.
"""

import json
from datetime import UTC, datetime

import httpx
import pytest

from app import connectors
from app.connectors import sheets as sheets_module
from app.connectors.rest import RestProblem
from app.connectors.grid import rows_from
from app.connectors.sheets import (
    SheetsConfig,
    SheetsConnector,
    SheetsCredentials,
    rows_from,
    spreadsheet_id_of,
)

WHEN = datetime(2026, 8, 21, 12, tzinfo=UTC)

GRID = [
    ["Deal id", "Owner", "Amount", "Closed"],
    ["OPP-1", "alice@acme.example", 1200.5, "2026-08-20"],
    ["OPP-2", "bob@acme.example", 900, "2026-08-19"],
]


class Google:
    """A fake Sheets API. Records what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        status, body = self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]
        return httpx.Response(status, json=body)


@pytest.fixture
def serve(monkeypatch):
    def _install(*replies):
        google = Google(replies)
        real = httpx.Client

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(google)
            return real(*args, **kwargs)

        monkeypatch.setattr(sheets_module.httpx, "Client", client)
        return google

    return _install


def cells(values):
    return (200, {"majorDimension": "ROWS", "values": values})


def config(**overrides) -> SheetsConfig:
    body = {"spreadsheet_id": "sheet-1", "tab": "Deals"}
    body.update(overrides)
    return SheetsConfig(**body)


def signed_in() -> SheetsCredentials:
    return SheetsCredentials(access_token="at-1", refresh_token="rt-1")


def read(conf=None, creds=None):
    return list(
        SheetsConnector().fetch(conf or config(), creds or signed_in(), WHEN)
    )


# ── Finding the spreadsheet ──────────────────────────────────────────────────


def test_a_pasted_web_address_is_accepted():
    """Everybody pastes the address. Asking for "just the bit between /d/ and
    /edit" and then failing on the address is a form being pedantic about
    something it could work out."""
    assert (
        spreadsheet_id_of("https://docs.google.com/spreadsheets/d/1AbC_x9/edit#gid=0")
        == "1AbC_x9"
    )


def test_a_bare_id_is_accepted_too():
    assert spreadsheet_id_of("  1AbC_x9  ") == "1AbC_x9"


def test_no_spreadsheet_says_so_before_any_request(serve):
    google = serve(cells(GRID))

    with pytest.raises(RestProblem, match="not filled in"):
        read(config(spreadsheet_id=""))

    assert google.asked == []


def test_the_named_tab_is_the_one_read(serve):
    google = serve(cells(GRID))

    read(config(tab="Closed deals"))

    assert "Closed%20deals" in str(google.asked[0].url)


def test_no_tab_reads_the_whole_first_sheet(serve):
    """Which is what a spreadsheet with one tab wants, and that is most of them."""
    google = serve(cells(GRID))

    read(config(tab=""))

    assert "A%3AZZ" in str(google.asked[0].url) or "A:ZZ" in str(google.asked[0].url)


def test_cells_are_asked_for_unformatted(serve):
    """So a currency cell arrives as 1250.5 rather than "$1,250.50". The mapping can
    parse either, but a raw number cannot be got wrong by a locale."""
    google = serve(cells(GRID))

    read()

    assert dict(google.asked[0].url.params)["valueRenderOption"] == "UNFORMATTED_VALUE"


# ── Recognising a row next time ──────────────────────────────────────────────


def test_the_connector_offers_no_row_id(serve):
    """**A spreadsheet has nothing stable to offer.** A row's position looks like an
    id and is not one: insert a row and every row below shifts, each claiming its
    neighbour's identity and overwriting that neighbour's figure.

    So the mapping names a column and `sync` refuses the row if it does not — a
    message somebody can act on, rather than a leaderboard that is quietly wrong.
    An earlier version made this a setting with position as an option, which was
    offering a choice between correct and silently wrong."""
    serve(cells(GRID))

    found = read()

    assert [row.external_id for row in found] == [None, None]


def test_there_is_no_setting_that_could_turn_that_off():
    """The safety comes from there being no option, not from a default."""
    assert "row_identity" not in SheetsConfig.model_fields


# ── Which credential is used ─────────────────────────────────────────────────


def test_a_signed_in_account_sends_its_token(serve):
    google = serve(cells(GRID))

    read()

    assert google.asked[0].headers["authorization"] == "Bearer at-1"


def test_a_service_account_key_is_used_in_preference(monkeypatch, serve):
    """**Inferred rather than configured.** A stored key means service account; a
    separate "which mode" setting would be one more question and one more way for
    the answer and the credential to disagree."""
    minted: list[str] = []

    def fake_mint(raw):
        minted.append(raw)
        return "minted-token"

    monkeypatch.setattr(sheets_module, "_service_token", fake_mint)
    google = serve(cells(GRID))

    read(creds=SheetsCredentials(access_token="at-1", service_account_json='{"a": 1}'))

    assert minted == ['{"a": 1}']
    assert google.asked[0].headers["authorization"] == "Bearer minted-token"


def test_no_credential_at_all_names_both_ways_in(serve):
    google = serve(cells(GRID))

    with pytest.raises(RestProblem) as raised:
        read(creds=SheetsCredentials())

    assert "sign in with Google" in str(raised.value)
    assert "service account key" in str(raised.value)
    assert google.asked == []


def test_a_key_that_is_not_json_says_what_to_paste():
    with pytest.raises(RestProblem, match="not valid JSON"):
        sheets_module._service_token("-----BEGIN PRIVATE KEY-----")


def test_a_key_missing_its_email_is_named(monkeypatch):
    """The commonest wrong paste is the private key alone rather than the file."""
    with pytest.raises(RestProblem, match="client_email"):
        sheets_module._service_token(json.dumps({"private_key": "x"}))


def test_a_key_missing_its_private_key_is_named():
    with pytest.raises(RestProblem, match="private_key"):
        sheets_module._service_token(json.dumps({"client_email": "a@b.iam"}))


def test_a_rejected_key_does_not_echo_the_assertion(monkeypatch):
    """Google's error body can quote the assertion back, and the assertion is signed
    with the customer's private key."""
    import jwt

    monkeypatch.setattr(jwt, "encode", lambda *a, **k: "signed-assertion")
    monkeypatch.setattr(
        sheets_module.httpx,
        "post",
        lambda *a, **k: httpx.Response(
            400, json={"error": "invalid_grant", "assertion": "signed-assertion"}
        ),
    )

    with pytest.raises(RestProblem) as raised:
        sheets_module._service_token(
            json.dumps({"client_email": "a@b.iam", "private_key": "k"})
        )

    assert "signed-assertion" not in str(raised.value)
    assert "400" in str(raised.value)
    assert "Sheets API is enabled" in str(raised.value)


def test_a_minted_token_is_asked_for_with_a_jwt_grant(monkeypatch):
    import jwt

    sent: list[dict] = []
    monkeypatch.setattr(jwt, "encode", lambda *a, **k: "signed-assertion")

    def capture(url, data=None, **kwargs):
        sent.append({"url": url, **(data or {})})
        return httpx.Response(200, json={"access_token": "minted"})

    monkeypatch.setattr(sheets_module.httpx, "post", capture)

    token = sheets_module._service_token(
        json.dumps({"client_email": "a@b.iam", "private_key": "k"})
    )

    assert token == "minted"
    assert sent[0]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    assert sent[0]["assertion"] == "signed-assertion"


def test_a_token_response_with_no_token_is_not_treated_as_success(monkeypatch):
    """Google answering 200 with a body that has no token in it. Passing `None`
    through would send `Bearer None` and fail at the Sheets API instead, one step
    further from the cause."""
    import jwt

    monkeypatch.setattr(jwt, "encode", lambda *a, **k: "signed")
    monkeypatch.setattr(
        sheets_module.httpx,
        "post",
        lambda *a, **k: httpx.Response(200, json={"expires_in": 3600}),
    )

    with pytest.raises(RestProblem, match="no access token"):
        sheets_module._service_token(
            json.dumps({"client_email": "a@b.iam", "private_key": "k"})
        )


def test_the_scope_asked_for_is_read_only():
    """A key with write access to somebody's Drive would be a much bigger thing to
    be holding, and nothing here needs it."""
    assert sheets_module.SCOPES == (
        "https://www.googleapis.com/auth/spreadsheets.readonly",
    )


# ── The window, which does not exist ─────────────────────────────────────────


def test_the_whole_tab_is_read_however_recent_the_window(serve):
    """**A spreadsheet has no idea when a cell changed**, so there is nothing to
    filter on. This is why row identity is load-bearing rather than a nicety."""
    google = serve(cells(GRID))

    recent = list(SheetsConnector().fetch(config(), signed_in(), WHEN))
    everything = list(SheetsConnector().fetch(config(), signed_in(), None))

    assert len(recent) == len(everything) == 2
    for request in google.asked:
        assert "since" not in str(request.url).lower()


def test_a_runaway_sheet_is_bounded(serve, monkeypatch):
    monkeypatch.setattr(sheets_module, "MAX_ROWS", 1)
    serve(cells(GRID))

    assert len(read()) == 1


# ── Testing and discovering ──────────────────────────────────────────────────


def test_a_good_test_reports_the_columns_it_found(serve):
    """"Connected" does not say whether they reached the tab they meant, and
    picking the wrong tab is the easiest mistake here."""
    serve(cells(GRID))

    result = SheetsConnector().test_connection(config(), signed_in())

    assert result.ok is True
    assert "2 rows" in result.detail
    assert result.info["columns"] == "Deal id, Owner, Amount, Closed"


def test_an_empty_tab_points_at_the_tab_name(serve):
    """An empty one usually means a typo rather than an empty sheet."""
    serve(cells([]))

    result = SheetsConnector().test_connection(config(), signed_in())

    assert result.ok is False
    assert "tab name" in result.detail


def test_a_header_row_pointed_at_the_wrong_line_says_which_row_it_used(serve):
    """The other easy mistake, and the message has to name the number it read so
    somebody can see it is wrong."""
    serve(cells([["Owner", "Amount"]]))

    result = SheetsConnector().test_connection(config(header_row=1), signed_in())

    assert result.ok is False
    assert "Row 1 is being read as the column names" in result.detail


def test_a_refused_credential_is_reported_not_raised(serve):
    serve((401, {"error": {"message": "nope"}}))

    result = SheetsConnector().test_connection(config(), signed_in())

    assert result.ok is False
    assert "refused the credential" in result.detail


def test_discovery_names_the_columns_and_guesses_their_kinds(serve):
    serve(cells(GRID))

    found = SheetsConnector().discover(config(), signed_in())

    assert [(f.name, f.kind) for f in found] == [
        ("Deal id", "string"),
        ("Owner", "email"),
        ("Amount", "number"),
        ("Closed", "date"),
    ]


def test_discovery_keeps_the_order_of_the_sheet(serve):
    """Left to right, as somebody laid the sheet out — the alphabet would open the
    mapping on whichever column happens to start with A."""
    serve(cells([["Zebra", "Apple"], [1, 2]]))

    assert [f.name for f in SheetsConnector().discover(config(), signed_in())] == [
        "Zebra",
        "Apple",
    ]


def test_a_column_blank_in_the_first_row_is_typed_from_a_later_one(serve):
    """The first version of this test used a sheet with one column, so the blank row
    was dropped as an empty row and the record never existed to be retyped. It
    needs a second column to keep the row alive."""
    serve(cells([["Deal", "Amount"], ["A", ""], ["B", 1250]]))

    found = SheetsConnector().discover(config(), signed_in())

    assert [(f.name, f.kind) for f in found] == [("Deal", "string"), ("Amount", "number")]


def test_a_boolean_cell_is_not_reported_as_a_number(serve):
    """`bool` is a subclass of `int` in Python, so an unguarded check calls a
    tick-box column a number and the mapper offers to sum it."""
    serve(cells([["Won"], [True]]))

    found = SheetsConnector().discover(config(), signed_in())

    assert [(f.name, f.kind) for f in found] == [("Won", "boolean")]


def test_discovery_is_empty_rather_than_raising_when_the_sheet_cannot_be_read(serve):
    serve((403, {}))

    assert SheetsConnector().discover(config(), signed_in()) == []


# ── How it fits the rest of the system ───────────────────────────────────────


def test_it_signs_in_to_google_so_the_wizard_offers_a_button():
    spec = connectors.oauth_of(connectors.get("google_sheets"))

    assert spec is not None
    assert spec.provider == "google"


def test_it_asks_google_for_a_refresh_token_and_a_fresh_consent():
    """Without `access_type=offline` Google issues no refresh token, so the source
    works for an hour. Without `prompt=consent` it issues none on a *re-connect*,
    which is the more confusing failure because the first connection worked."""
    spec = connectors.oauth_of(connectors.get("google_sheets"))

    assert ("access_type", "offline") in spec.extra_authorize_params
    assert ("prompt", "consent") in spec.extra_authorize_params


def test_it_satisfies_the_connector_protocol():
    assert isinstance(connectors.get("google_sheets"), connectors.Connector)


def test_it_supplies_no_endpoint_because_it_fetches():
    assert connectors.endpoint_credential_of(connectors.get("google_sheets")) is None
