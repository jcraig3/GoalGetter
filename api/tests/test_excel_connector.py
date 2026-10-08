"""Excel on Microsoft 365.

The grid transform is tested once in `test_grid.py` and shared, so what is left here
is the two things that are genuinely Microsoft's: how a sharing link becomes a file
id, and how its OAuth differs from Google's in ways that bite.
"""

import base64

import httpx
import pytest

from app import connectors
from app.connectors import excel as excel_module
from app.connectors.excel import (
    ExcelConfig,
    ExcelConnector,
    ExcelCredentials,
    share_token,
)
from app.connectors.rest import RestProblem

LINK = "https://contoso-my.sharepoint.com/:x:/g/personal/sam/abc?e=1"

ITEM = {"id": "01ITEM", "name": "deals.xlsx", "parentReference": {"driveId": "b!DRIVE"}}
GRID = {
    "values": [
        ["Deal id", "Owner", "Amount"],
        ["OPP-1", "alice@acme.example", 1200.5],
    ]
}


class Graph:
    """A fake Microsoft Graph. Answers in the order it is given replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        status, body = self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]
        return httpx.Response(status, json=body)

    def paths(self) -> list[str]:
        return [request.url.path for request in self.asked]


@pytest.fixture
def serve(monkeypatch):
    def _install(*replies):
        graph = Graph(replies)
        real = httpx.Client

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(graph)
            return real(*args, **kwargs)

        monkeypatch.setattr(excel_module.httpx, "Client", client)
        return graph

    return _install


def ok(body):
    return (200, body)


def config(**overrides) -> ExcelConfig:
    body = {"file_url": LINK, "worksheet": "Deals"}
    body.update(overrides)
    return ExcelConfig(**body)


def signed_in() -> ExcelCredentials:
    return ExcelCredentials(access_token="at-1", refresh_token="rt-1")


def read(conf=None, creds=None):
    return list(ExcelConnector().fetch(conf or config(), creds or signed_in()))


# ── Turning a sharing link into a file ───────────────────────────────────────


def test_a_sharing_link_is_encoded_the_way_graph_wants_it():
    """Microsoft's documented encoding: base64url, padding stripped, `u!` prefix.
    Worth its own test because a wrong encoding produces a 400 about a malformed id,
    which says nothing at all about the link somebody pasted."""
    token = share_token(LINK)

    assert token.startswith("u!")
    assert base64.urlsafe_b64decode(token[2:] + "==").decode() == LINK


@pytest.mark.parametrize("link", [LINK + "x", LINK + "xx"])
def test_the_padding_is_stripped_whatever_the_link_length(link):
    """**`LINK` alone could not test this.** Its length happens to be divisible by
    three, so base64 adds no padding and stripping it is a no-op — the first version
    of this test passed with the stripping removed. These two lengths force one and
    two padding characters respectively."""
    assert "=" not in share_token(link)
    assert base64.urlsafe_b64decode(share_token(link)[2:] + "==").decode() == link


def test_surrounding_whitespace_in_a_pasted_link_is_ignored():
    assert share_token(f"  {LINK}  ") == share_token(LINK)


def test_the_link_is_resolved_before_the_cells_are_read(serve):
    """Two requests, not one. Graph identifies a file by an internal id and what an
    admin has is a sharing link — asking them to find the id instead would be asking
    them to use Graph Explorer to import a spreadsheet."""
    graph = serve(ok(ITEM), ok(GRID))

    read()

    assert graph.paths()[0].startswith("/v1.0/shares/u!")
    assert graph.paths()[0].endswith("/driveItem")


def test_the_workbook_is_addressed_through_the_drive_it_lives_in(serve):
    """`/me/drive` would only find a file the signed-in account owns, which is
    exactly not the case for a shared team workbook."""
    graph = serve(ok(ITEM), ok(GRID))

    read()

    assert "/drives/b!DRIVE/items/01ITEM" in graph.paths()[1]


def test_naming_no_workbook_at_all_says_how_to_name_one(serve):
    """Neither picked nor pasted. Both ways out are named, because the picker is
    the normal one and pasting is what a deployment without browsing falls back
    to."""
    graph = serve(ok(ITEM))

    with pytest.raises(RestProblem, match="Pick one from the list, or paste"):
        read(config(file_url=""))

    assert graph.asked == []


def test_a_picked_workbook_needs_no_link_and_resolves_nothing(serve):
    """**The point of the picker, asserted.** Ids address the file directly, so the
    share-resolve request that a pasted link needs is not made at all — one fewer
    round trip and one fewer thing that can fail."""
    graph = serve(ok(GRID))

    read(config(file_url="", drive_id="drive-1", item_id="item-9"))

    assert not any("/shares/" in path for path in graph.paths())
    assert any("/drives/drive-1/items/item-9" in path for path in graph.paths())


def test_a_link_graph_cannot_resolve_says_what_to_check(serve):
    """The likely cause is a link to the containing folder rather than to the file,
    which looks identical when you paste it."""
    serve(ok({"name": "no id here"}))

    with pytest.raises(RestProblem, match="sharing link to the workbook itself"):
        read()


# ── Which worksheet ──────────────────────────────────────────────────────────


def test_the_named_worksheet_is_the_one_read(serve):
    graph = serve(ok(ITEM), ok(GRID))

    read(config(worksheet="Closed deals"))

    assert "/worksheets/Closed deals/usedRange" in graph.asked[1].url.path


def test_no_worksheet_named_uses_the_first_one(serve):
    """Which is what a single-sheet workbook wants, and most of them are."""
    graph = serve(
        ok(ITEM), ok({"value": [{"id": "sheet-a"}, {"id": "sheet-b"}]}), ok(GRID)
    )

    found = read(config(worksheet=""))

    assert "/worksheets/sheet-a/usedRange" in graph.asked[2].url.path
    assert len(found) == 1


def test_a_workbook_with_no_worksheets_says_so(serve):
    serve(ok(ITEM), ok({"value": []}))

    with pytest.raises(RestProblem, match="no worksheets"):
        read(config(worksheet=""))


def test_only_the_used_range_is_asked_for(serve):
    """A workbook's grid is a million rows of nothing. Asking for the used range is
    the difference between reading a table and reading a spreadsheet."""
    graph = serve(ok(ITEM), ok(GRID))

    read()

    assert "usedRange(valuesOnly=true)" in str(graph.asked[1].url)


# ── Reading ──────────────────────────────────────────────────────────────────


def test_rows_come_back_as_records(serve):
    serve(ok(ITEM), ok(GRID))

    found = read()

    assert found[0].values == {
        "Deal id": "OPP-1",
        "Owner": "alice@acme.example",
        "Amount": 1200.5,
    }


def test_no_row_id_is_invented(serve):
    """Same reasoning as Google Sheets: a row's position looks like an identity and
    is not one, so the mapping names a column and `sync` refuses the row if it does
    not."""
    serve(ok(ITEM), ok(GRID))

    assert [row.external_id for row in read()] == [None]


def test_the_whole_sheet_is_read_however_recent_the_window(serve):
    """A workbook has no notion of when a cell changed, so there is nothing to
    filter on."""
    from datetime import UTC, datetime

    serve(ok(ITEM), ok(GRID))

    recent = list(
        ExcelConnector().fetch(config(), signed_in(), datetime(2026, 8, 26, tzinfo=UTC))
    )

    assert len(recent) == 1


def test_a_runaway_workbook_is_bounded(serve, monkeypatch):
    monkeypatch.setattr(excel_module, "MAX_ROWS", 1)
    serve(
        ok(ITEM),
        ok({"values": [["A"], ["1"], ["2"], ["3"]]}),
    )

    assert len(read()) == 1


def test_no_credential_says_to_sign_in(serve):
    graph = serve(ok(ITEM))

    with pytest.raises(RestProblem, match="No Microsoft account is signed in"):
        read(creds=ExcelCredentials())

    assert graph.asked == []


# ── Testing and discovering ──────────────────────────────────────────────────


def test_a_good_test_reports_the_columns(serve):
    serve(ok(ITEM), ok(GRID))

    result = ExcelConnector().test_connection(config(), signed_in())

    assert result.ok is True
    assert result.info["columns"] == "Deal id, Owner, Amount"


def test_an_empty_worksheet_points_at_the_name(serve):
    serve(ok(ITEM), ok({"values": []}))

    result = ExcelConnector().test_connection(config(), signed_in())

    assert result.ok is False
    assert "typo in the name" in result.detail


def test_a_wrong_header_row_names_the_row_it_used(serve):
    serve(ok(ITEM), ok({"values": [["Owner", "Amount"]]}))

    result = ExcelConnector().test_connection(config(), signed_in())

    assert result.ok is False
    assert "Row 1 is being read as the column names" in result.detail


def test_a_refused_token_is_reported_not_raised(serve):
    serve((401, {"error": {"message": "nope"}}))

    result = ExcelConnector().test_connection(config(), signed_in())

    assert result.ok is False
    assert "refused the credential" in result.detail


def test_discovery_names_the_columns(serve):
    serve(ok(ITEM), ok(GRID))

    found = ExcelConnector().discover(config(), signed_in())

    assert [(f.name, f.kind) for f in found] == [
        ("Deal id", "string"),
        ("Owner", "email"),
        ("Amount", "number"),
    ]


def test_discovery_is_empty_rather_than_raising(serve):
    serve((403, {}))

    assert ExcelConnector().discover(config(), signed_in()) == []


# ── How Microsoft's OAuth differs from Google's ──────────────────────────────


def test_offline_access_is_in_the_scopes():
    """**Microsoft has no `access_type=offline`.** `offline_access` has to be one of
    the scopes or no refresh token is issued at all — so the source works for an
    hour and then stops. The same failure Google's parameter guards against, spelled
    completely differently."""
    spec = connectors.oauth_of(connectors.get("microsoft_excel"))

    assert "offline_access" in spec.scopes


def test_the_scope_reaches_files_the_account_does_not_own():
    """A team's workbook usually lives in somebody else's OneDrive or a SharePoint
    site, and the narrower `Files.Read` only reaches files the signed-in account
    owns."""
    spec = connectors.oauth_of(connectors.get("microsoft_excel"))

    assert "Files.Read.All" in spec.scopes


def test_the_endpoints_are_built_from_the_connection_not_hard_coded():
    """**This test used to assert `/common/`, and that was the bug.**

    `/common/` is right for a multi-tenant app registration and returns an error
    for a single-tenant one — which is the kind the setup steps produce and the
    kind most companies make. The endpoints now carry `{tenant}`, filled from the
    connection, so both kinds work without asking an admin which they made.
    """
    from app.oauth import endpoints_for

    spec = connectors.oauth_of(connectors.get("microsoft_excel"))

    class Connection:
        tenant_id = "contoso.onmicrosoft.com"

    authorize, token = endpoints_for(spec, Connection())

    assert authorize.startswith(
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/"
    )
    assert token.startswith("https://login.microsoftonline.com/contoso.onmicrosoft.com/")


def test_a_connection_with_no_tenant_still_reaches_microsoft():
    """`common` remains the fallback, so a multi-tenant registration — and any
    connection saved before the tenant field existed — keeps working rather than
    producing a URL with a literal `{tenant}` in it."""
    from app.oauth import endpoints_for

    spec = connectors.oauth_of(connectors.get("microsoft_excel"))

    class Connection:
        tenant_id = None

    authorize, token = endpoints_for(spec, Connection())

    assert "/common/" in authorize
    assert "/common/" in token
    assert "{tenant}" not in authorize + token


def test_it_shares_a_registration_with_any_other_microsoft_connector():
    """Keyed by provider, not by connector — so a future Teams or Dynamics connector
    needs no second app registration."""
    spec = connectors.oauth_of(connectors.get("microsoft_excel"))

    assert spec.provider == "microsoft"


def test_it_satisfies_the_connector_protocol():
    assert isinstance(connectors.get("microsoft_excel"), connectors.Connector)
