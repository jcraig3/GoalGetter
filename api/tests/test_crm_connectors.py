"""HubSpot, Salesforce and Pipedrive.

The engine is tested in `test_rest_connector.py`. What is left per provider is the
handful of things that are genuinely theirs, and for these three that is almost
entirely **how each one answers "what changed since"** — which is the difference
between an integration that keeps up and one that silently misses every edit.

**None of this is verification against a live account.** These prove the specs are
read the way they are written; only a trial login proves the endpoints are right.
That distinction has caught real bugs six times in this phase and is worth keeping in
front of anybody reading these.
"""

import httpx
import pytest

from app import connectors
from app.connectors import rest as rest_module
from app.connectors.crm import (
    HubspotConfig,
    HubspotConnector,
    HubspotToken,
    PipedriveConfig,
    PipedriveConnector,
    PipedriveToken,
    SalesforceConfig,
    SalesforceConnector,
    SalesforceCredentials,
)
from app.connectors.rest import ApiKey

from datetime import UTC, datetime

WHEN = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)


class Server:
    def __init__(self, replies):
        self.replies = list(replies)
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        status, body = self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]
        return httpx.Response(status, json=body)

    def params(self, index=0) -> dict[str, str]:
        return dict(self.asked[index].url.params)


@pytest.fixture
def serve(monkeypatch):
    def _install(*replies):
        server = Server(replies)
        real = httpx.Client

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(server)
            return real(*args, **kwargs)

        monkeypatch.setattr(rest_module.httpx, "Client", client)
        return server

    return _install


def ok(body):
    return (200, body)


# ── HubSpot ──────────────────────────────────────────────────────────────────


def hubspot_read(server_config=None, since=None):
    conn = HubspotConnector()
    return list(
        conn.fetch(
            server_config or HubspotConfig(),
            HubspotToken(api_key="pat-1"),
            since,
        )
    )


def test_hubspot_reads_the_object_that_was_chosen(serve):
    server = serve(ok({"results": [{"id": "1"}]}))

    hubspot_read(HubspotConfig(records="tickets"))

    assert server.asked[0].url.path == "/crm/v3/objects/tickets"


def test_hubspot_sends_the_token_as_a_bearer(serve):
    server = serve(ok({"results": []}))

    hubspot_read()

    assert server.asked[0].headers["authorization"] == "Bearer pat-1"


def test_hubspot_pages_by_the_cursor_it_hands_back(serve):
    server = serve(
        ok({"results": [{"id": "1"}], "paging": {"next": {"after": "c-2"}}}),
        ok({"results": [{"id": "2"}]}),
    )

    found = hubspot_read()

    assert [row.values["id"] for row in found] == ["1", "2"]
    assert server.params(1)["after"] == "c-2"


def test_hubspot_stops_when_there_is_no_next_cursor(serve):
    """The whole point of a cursor: the provider decides, and a full last page is
    perfectly normal."""
    server = serve(ok({"results": [{"id": str(n)} for n in range(100)]}))

    hubspot_read()

    assert len(server.asked) == 1


def test_hubspot_asks_for_the_properties_that_were_named(serve):
    """**HubSpot returns almost nothing by default.** A deal comes back with an id
    and a couple of system fields unless the request lists what it wants — so a
    source configured without this discovers three columns and none of them are the
    amount."""
    server = serve(ok({"results": []}))

    hubspot_read(HubspotConfig(properties="amount,closedate"))

    assert server.params()["properties"] == "amount,closedate"


def test_hubspot_omits_the_properties_parameter_when_none_were_named(serve):
    server = serve(ok({"results": []}))

    hubspot_read()

    assert "properties" not in server.params()


def test_hubspot_reads_everything_every_sync(serve):
    """**Its list endpoints cannot filter**, and filtering needs a POST to a search
    endpoint this engine does not do. So the window is ignored — which is expensive
    and right, where a wrong filter would be cheap and silently miss edited records.
    `external_id` is what makes the re-reading harmless."""
    server = serve(ok({"results": []}))

    hubspot_read(since=WHEN)

    assert not [key for key in server.params() if "since" in key or "updated" in key]



# ── Salesforce ───────────────────────────────────────────────────────────────


def salesforce_spec(**overrides):
    body = {"instance": "acme.my.salesforce.com"}
    body.update(overrides)
    return SalesforceConnector()._spec_for(SalesforceConfig(**body))


def test_salesforce_puts_the_window_inside_the_query(serve):
    """**What `since_template` exists for.** Salesforce takes a whole SOQL query in
    one parameter, so the window cannot be a parameter of its own."""
    server = serve(ok({"records": []}))
    conn = SalesforceConnector()

    list(
        conn.fetch(
            SalesforceConfig(instance="acme.my.salesforce.com"),
            SalesforceCredentials(access_token="tok"),
            WHEN,
        )
    )

    sent = server.params()["q"]
    assert "LastModifiedDate > 2026-08-26T09:30:00Z" in sent
    assert "FROM Opportunity" in sent


def test_salesforce_adds_the_window_rather_than_trusting_the_admin_to(serve):
    """**The one thing this connector will not let somebody get wrong.** A query
    filtered on `CloseDate` looks right and silently never returns an opportunity
    edited after it closed — the same trap the SQL connector refuses a query for."""
    spec = salesforce_spec(soql="SELECT Id FROM Opportunity WHERE CloseDate = THIS_YEAR")

    assert "LastModifiedDate > {since}" in spec.since_template


def test_salesforce_joins_with_and_when_the_query_already_filters():
    """A second `WHERE` is a syntax error, and the admin's query almost always has
    one."""
    spec = salesforce_spec(soql="SELECT Id FROM Opportunity WHERE IsWon = true")

    assert " AND LastModifiedDate" in spec.since_template
    assert spec.since_template.lower().count("where") == 1


def test_salesforce_joins_with_where_when_the_query_does_not():
    spec = salesforce_spec(soql="SELECT Id FROM Opportunity")

    assert " WHERE LastModifiedDate" in spec.since_template


def test_salesforce_is_not_confused_by_the_word_where_in_a_field_name():
    """`Where__c` is a real thing somebody has called a custom field."""
    spec = salesforce_spec(soql="SELECT Id, Where__c FROM Opportunity")

    assert " WHERE LastModifiedDate" in spec.since_template


def test_salesforce_tolerates_a_trailing_semicolon():
    """Which is what you get pasting out of a query tool."""
    spec = salesforce_spec(soql="SELECT Id FROM Opportunity;")

    assert ";" not in spec.since_template


def test_a_first_sync_asks_without_a_window(serve):
    """No window yet, so the clause is dropped rather than sent containing the
    literal word `{since}` — which Salesforce would reject as malformed SOQL."""
    server = serve(ok({"records": []}))
    conn = SalesforceConnector()

    list(
        conn.fetch(
            SalesforceConfig(instance="a.b.c"),
            SalesforceCredentials(access_token="t"),
            None,
        )
    )

    assert "{since}" not in server.params()["q"]


def test_salesforce_reads_records_from_where_it_puts_them(serve):
    server = serve(ok({"records": [{"Id": "006x"}], "done": True}))
    conn = SalesforceConnector()

    found = list(
        conn.fetch(
            SalesforceConfig(instance="a.b.c"),
            SalesforceCredentials(access_token="t"),
            WHEN,
        )
    )

    assert found[0].values == {"Id": "006x"}


def test_salesforce_addresses_the_instance_that_was_given(serve):
    server = serve(ok({"records": []}))
    conn = SalesforceConnector()

    list(
        conn.fetch(
            SalesforceConfig(instance="acme.my.salesforce.com", version="v59.0"),
            SalesforceCredentials(access_token="t"),
            WHEN,
        )
    )

    assert server.asked[0].url.host == "acme.my.salesforce.com"
    assert server.asked[0].url.path == "/services/data/v59.0/query"


# ── Pipedrive ────────────────────────────────────────────────────────────────


def pipedrive_read(config=None, since=None):
    conn = PipedriveConnector()
    return list(
        conn.fetch(
            config or PipedriveConfig(company="acme"),
            PipedriveToken(api_key="tok"),
            since,
        )
    )


def test_pipedrive_uses_v2_for_the_sake_of_the_window(serve):
    """v1 has no modified filter on its list endpoints, and its `/recents`
    alternative returns a mixture of record types no single mapping can describe."""
    server = serve(ok({"data": []}))

    pipedrive_read(since=WHEN)

    assert "/api/v2/deals" == server.asked[0].url.path
    assert server.params()["updated_since"] == "2026-08-26T09:30:00Z"


def test_pipedrive_sends_its_token_as_a_query_parameter(serve):
    """Which Pipedrive requires — and is the reason this engine never puts a URL in
    an error message."""
    server = serve(ok({"data": []}))

    pipedrive_read()

    assert server.params()["api_token"] == "tok"


def test_a_pipedrive_error_does_not_leak_the_token(serve):
    serve((400, {}))

    with pytest.raises(Exception) as raised:
        pipedrive_read()

    assert "tok" not in str(raised.value)
    assert "pipedrive.com" not in str(raised.value)


def test_pipedrive_pages_by_cursor(serve):
    server = serve(
        ok({"data": [{"id": 1}], "additional_data": {"next_cursor": "c2"}}),
        ok({"data": [{"id": 2}]}),
    )

    found = pipedrive_read()

    assert [row.values["id"] for row in found] == [1, 2]
    assert server.params(1)["cursor"] == "c2"


def test_pipedrive_stops_when_the_cursor_runs_out(serve):
    server = serve(ok({"data": [{"id": 1}], "additional_data": {}}))

    pipedrive_read()

    assert len(server.asked) == 1


def test_pipedrive_addresses_the_company_domain(serve):
    server = serve(ok({"data": []}))

    pipedrive_read(PipedriveConfig(company="contoso", records="activities"))

    assert server.asked[0].url.host == "contoso.pipedrive.com"
    assert server.asked[0].url.path == "/api/v2/activities"


def test_a_missing_company_is_named_rather_than_requested(serve):
    server = serve(ok({"data": []}))

    with pytest.raises(Exception, match="Company domain is not filled in"):
        pipedrive_read(PipedriveConfig(company=""))

    assert server.asked == []


# ── All three ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", ["hubspot", "salesforce", "pipedrive"])
def test_each_satisfies_the_connector_protocol(key):
    assert isinstance(connectors.get(key), connectors.Connector)


@pytest.mark.parametrize("key", ["hubspot", "salesforce", "pipedrive"])
def test_none_of_them_invents_a_row_id(key):
    """The mapping names the id column — every one of these has an obvious `id` or
    `Id`, and guessing which would be a decision made in the wrong place."""
    connector = connectors.get(key)

    assert connectors.endpoint_credential_of(connector) is None


@pytest.mark.parametrize("key", ["hubspot", "pipedrive", "close"])
def test_a_provider_with_a_lasting_key_takes_one_rather_than_signing_in(key):
    """A token pasted once is fewer steps than an app registration plus a consent
    screen, and it does not stop working when the person who authorised it leaves.

    **The test named Salesforce until Salesforce started signing in**, which is the
    trap in listing providers rather than stating the property. What actually
    decides is whether the provider issues a credential that lasts.
    """
    assert connectors.oauth_of(connectors.get(key)) is None
    assert "api_key" in connectors.get(key).credential_schema.model_fields


def test_salesforce_signs_in_because_its_tokens_expire():
    """**The exception, and the reason for it.** A Salesforce access token expires
    within hours, so the pasted-token version of this connector stopped working on
    its own with nothing to explain why. Signing in is what lets the sync renew one.
    """
    spec = connectors.oauth_of(connectors.get("salesforce"))

    assert spec is not None
    assert spec.provider == "salesforce"
    # Salesforce's spelling of offline access. Without it there is no refresh token
    # at all, and the connector is back to working for two hours.
    assert "refresh_token" in spec.scopes
    assert "api_key" not in connectors.get("salesforce").credential_schema.model_fields


def test_the_salesforce_login_host_falls_back_to_production():
    """`common` is Microsoft's word and means nothing to Salesforce. A connection
    that names no login host is a production org."""
    from app.oauth import endpoints_for

    spec = connectors.oauth_of(connectors.get("salesforce"))

    class NoTenant:
        tenant_id = None

    authorize, token = endpoints_for(spec, NoTenant())

    assert authorize.startswith("https://login.salesforce.com/services/oauth2/")
    assert token.startswith("https://login.salesforce.com/services/oauth2/")
    assert "{tenant}" not in authorize + token


def test_a_sandbox_or_my_domain_is_signed_in_to_directly():
    """Salesforce rejects an authorization request sent to the wrong host, and the
    error says nothing about which — so the login host is asked for rather than
    guessed."""
    from app.oauth import endpoints_for

    spec = connectors.oauth_of(connectors.get("salesforce"))

    class Sandbox:
        tenant_id = "test.salesforce.com"

    authorize, _ = endpoints_for(spec, Sandbox())

    assert authorize.startswith("https://test.salesforce.com/services/oauth2/")


def test_hubspot_asks_for_a_hundred_records_a_page(serve):
    """**HubSpot's default is ten.** It was getting the default, because the page
    size used to be sent only for page and offset paging — so a company with twenty
    thousand deals needed two thousand requests and hit the page cap having read a
    quarter of them. And HubSpot has no modified filter, so it does that every
    single sync."""
    server = serve(ok({"results": []}))

    hubspot_read()

    assert server.params()["limit"] == "100"


def test_pipedrive_asks_for_a_page_size_too(serve):
    """Same fix, same reason. Pipedrive's own default is kinder, but relying on a
    provider's default is relying on something that can change without notice."""
    server = serve(ok({"data": []}))

    conn = PipedriveConnector()
    list(conn.fetch(PipedriveConfig(company="acme"), PipedriveToken(api_key="k"), None))

    assert server.params()["limit"] == "100"
