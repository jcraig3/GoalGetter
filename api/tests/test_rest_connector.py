"""The REST engine, and Freshdesk as the first provider on it.

**Driven by a fake HTTP server rather than a mocked function.** `httpx.MockTransport`
sits where the socket would, so the requests under test are real requests — the
paging loop actually pages, the auth header is actually on the wire, the retry
actually retries. Patching `client.get` would prove the code called something.

What the engine is for is that twenty-five providers are one connector. So most of
these tests are about the parts that differ between providers — how they page, how
they authenticate, where the array is — because getting those wrong is silent: a bad
paging rule returns a plausible number of rows and quietly drops the rest.
"""

from datetime import UTC, datetime

import httpx
import pytest

from app.connectors import rest
from app.connectors.freshdesk import FreshdeskConfig, FreshdeskConnector, FreshdeskKey
from app.connectors.rest import (
    ApiKey,
    AuthStyle,
    NoConfig,
    Paging,
    RestConnector,
    RestProblem,
    RestSpec,
    dig,
    format_since,
    next_page_params,
    rows_in,
)

WHEN = datetime(2026, 8, 21, 12, 30, 45, tzinfo=UTC)


class Server:
    """A fake provider. Records what it was asked, replies with what it was given.

    Installed by pointing `httpx.Client` at a `MockTransport`, so everything between
    the connector and the socket is the real client.
    """

    def __init__(self, replies):
        #: Each entry is a status, a JSON body, and optional headers.
        self.replies = list(replies)
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        status, body, headers = self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]
        return httpx.Response(status, json=body, headers=headers or {})

    def params(self, index=0) -> dict[str, str]:
        return dict(self.asked[index].url.params)


def ok(body, headers=None):
    return (200, body, headers)


@pytest.fixture
def serve(monkeypatch):
    """Install a fake provider for the duration of one test."""

    def _install(*replies):
        server = Server(replies)
        real = httpx.Client

        def client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(server)
            return real(*args, **kwargs)

        monkeypatch.setattr(rest.httpx, "Client", client)
        return server

    return _install


def connector(spec_changes=None, **kwargs) -> RestConnector:
    from dataclasses import replace

    spec = RestSpec(
        base_url="https://api.example.test",
        path="records",
        provider_name="Example",
        since_param="updated_since",
    )
    if spec_changes:
        spec = replace(spec, **spec_changes)
    return RestConnector(
        "example", "Example", spec, NoConfig, ApiKey, **kwargs
    )


def read(conn: RestConnector, since=None) -> list[dict]:
    return [row.values for row in conn.fetch(NoConfig(), ApiKey(api_key="k"), since)]


# ── Reading a body ───────────────────────────────────────────────────────────


def test_dig_returns_the_body_itself_for_an_empty_path():
    """Which is how "the response is the array" is spelled, and it is the commonest
    shape there is."""
    assert dig([1, 2], "") == [1, 2]


def test_dig_follows_a_dotted_path():
    assert dig({"a": {"b": [1]}}, "a.b") == [1]


def test_dig_returns_none_for_a_missing_key_rather_than_raising():
    """A provider omitting `paging.next` is how it says "no more pages", not a
    malformed response."""
    assert dig({"a": {}}, "a.next") is None
    assert dig({"a": 1}, "a.b.c") is None


def test_rows_come_from_wherever_the_spec_says():
    spec = RestSpec(base_url="x", path="y", rows_at="results.items")

    assert rows_in({"results": {"items": [{"id": 1}]}}, spec) == [{"id": 1}]


def test_a_body_that_is_the_array_needs_no_path():
    assert rows_in([{"id": 1}], RestSpec(base_url="x", path="y")) == [{"id": 1}]


def test_non_records_are_dropped_rather_than_passed_on():
    """`rows_at` pointing one level too deep returns a list of ids. Letting those
    through produces a mapping error per row instead of one clear empty result."""
    assert rows_in([1, "two", {"id": 3}], RestSpec(base_url="x", path="y")) == [{"id": 3}]


# ── The window ───────────────────────────────────────────────────────────────


def test_the_window_is_formatted_the_way_each_provider_reads_it():
    assert format_since(WHEN, "iso") == "2026-08-21T12:30:45Z"
    assert format_since(WHEN, "date") == "2026-08-21"
    assert format_since(WHEN, "epoch") == str(int(WHEN.timestamp()))


def test_iso_uses_z_rather_than_an_offset():
    """Both are valid ISO 8601 and a handful of APIs reject the second."""
    assert "+00:00" not in format_since(WHEN, "iso")


def test_a_non_utc_window_is_converted_rather_than_relabelled():
    """Otherwise a deployment in Phoenix asks for the wrong seven hours."""
    from datetime import timedelta, timezone

    phoenix = WHEN.astimezone(timezone(timedelta(hours=-7)))

    assert format_since(phoenix, "iso") == "2026-08-21T12:30:45Z"


def test_no_window_means_no_parameter(serve):
    """Sending an empty one is how you ask some APIs for nothing at all."""
    server = serve(ok([]))

    read(connector())

    assert "updated_since" not in server.params()


def test_the_window_is_sent_when_there_is_one(serve):
    server = serve(ok([]))

    read(connector(), since=WHEN)

    assert server.params()["updated_since"] == "2026-08-21T12:30:45Z"


# ── Knowing when to stop ─────────────────────────────────────────────────────


def test_a_short_page_is_the_last_one():
    paging = Paging(kind="page", page_size=100)
    spec = RestSpec(base_url="x", path="y", paging=paging)

    assert next_page_params({}, spec, page=1, seen=40, batch=40) is None


def test_a_full_page_asks_for_another():
    paging = Paging(kind="page", page_size=100)
    spec = RestSpec(base_url="x", path="y", paging=paging)

    assert next_page_params({}, spec, page=1, seen=100, batch=100) == {"page": 2}


def test_a_provider_that_says_there_is_no_more_is_believed_over_arithmetic():
    """A full final page looks like a middle page. A provider that tells us is more
    reliable than counting, in both directions."""
    spec = RestSpec(
        base_url="x",
        path="y",
        paging=Paging(kind="page", page_size=100, more_at="has_more"),
    )

    assert next_page_params({"has_more": False}, spec, page=1, seen=100, batch=100) is None
    assert next_page_params({"has_more": True}, spec, page=1, seen=40, batch=40) == {
        "page": 2
    }


def test_a_missing_more_flag_falls_back_to_the_row_count():
    """Rather than treating an absent field as "no more", which would read one page
    of everything."""
    spec = RestSpec(
        base_url="x",
        path="y",
        paging=Paging(kind="page", page_size=100, more_at="has_more"),
    )

    assert next_page_params({}, spec, page=1, seen=100, batch=100) == {"page": 2}


def test_a_cursor_is_taken_from_the_response():
    spec = RestSpec(
        base_url="x",
        path="y",
        paging=Paging(kind="cursor", cursor_at="paging.next.after", cursor_param="after"),
    )

    assert next_page_params(
        {"paging": {"next": {"after": "abc"}}}, spec, page=1, seen=100, batch=100
    ) == {"after": "abc"}


def test_no_cursor_means_the_end_however_full_the_page():
    """The whole point of a cursor: the provider decides, and a full last page is
    normal."""
    spec = RestSpec(base_url="x", path="y", paging=Paging(kind="cursor", cursor_at="next"))

    assert next_page_params({}, spec, page=1, seen=100, batch=100) is None


def test_an_offset_advances_by_what_has_been_seen():
    spec = RestSpec(
        base_url="x", path="y", paging=Paging(kind="offset", page_size=50)
    )

    assert next_page_params({}, spec, page=1, seen=50, batch=50) == {"offset": 50}


def test_a_single_response_provider_never_asks_again():
    spec = RestSpec(base_url="x", path="y", paging=Paging(kind="none"))

    assert next_page_params({}, spec, page=1, seen=999, batch=999) is None


def test_paging_actually_pages(serve):
    """End to end through a real client: two full pages then a short one."""
    page = [{"id": n} for n in range(100)]
    server = serve(ok(page), ok(page), ok([{"id": 999}]))

    found = read(connector({"paging": Paging(page_size=100)}))

    assert len(found) == 201
    assert [server.params(i).get("page") for i in range(3)] == ["1", "2", "3"]


def test_the_page_size_is_asked_for(serve):
    server = serve(ok([]))

    read(connector({"paging": Paging(page_size=25, size_param="per_page")}))

    assert server.params()["per_page"] == "25"


def test_a_provider_that_pages_forever_is_stopped(serve, monkeypatch):
    """A cursor that loops, or a `has_more` that is always true."""
    from app.connectors import Truncated

    monkeypatch.setattr(rest, "MAX_PAGES", 3)
    server = serve(ok({"rows": [{"id": 1}] * 100, "has_more": True}))

    stream = connector(
        {"rows_at": "rows", "paging": Paging(page_size=100, more_at="has_more")}
    ).fetch(NoConfig(), ApiKey(api_key="k"))

    found = []
    with pytest.raises(Truncated):
        for row in stream:
            found.append(row)

    assert len(server.asked) == 3
    # The rows already read are kept: `Truncated` comes after them, never instead.
    assert len(found) == 300


def test_hitting_the_page_cap_says_the_run_is_incomplete(serve, monkeypatch):
    """**This used to log a line and return, and the run reported `ok`** — so the
    watermark moved past pages nobody had read and they were never read again. The
    message has to say the run is incomplete, because that is what makes the run
    partial and holds the watermark."""
    from app.connectors import Truncated

    monkeypatch.setattr(rest, "MAX_PAGES", 2)
    serve(ok({"rows": [{"id": 1}] * 100, "has_more": True}))

    with pytest.raises(Truncated, match="incomplete"):
        read(connector({"rows_at": "rows", "paging": Paging(page_size=100, more_at="has_more")}))


def test_the_row_cap_keeps_what_it_read_and_says_it_stopped(serve, monkeypatch):
    from app.connectors import Truncated

    monkeypatch.setattr(rest, "MAX_ROWS", 5)
    serve(ok([{"id": n} for n in range(100)]))

    stream = connector({"paging": Paging(page_size=100)}).fetch(
        NoConfig(), ApiKey(api_key="k")
    )
    found = []
    with pytest.raises(Truncated, match="incomplete"):
        for row in stream:
            found.append(row)

    assert len(found) == 5


def test_a_read_that_fits_raises_nothing(serve, monkeypatch):
    """The other half: the cap must not fire on a normal sync, or every source
    would report itself incomplete forever."""
    monkeypatch.setattr(rest, "MAX_ROWS", 500)
    serve(ok([{"id": n} for n in range(10)]))

    assert len(read(connector({"paging": Paging(page_size=100)}))) == 10


def test_it_streams_rather_than_reading_everything_first(serve):
    """A generator, so the first record is available before the last page is asked
    for — and abandoning it stops the requests."""
    page = [{"id": n} for n in range(100)]
    server = serve(ok(page), ok(page), ok([]))

    stream = connector({"paging": Paging(page_size=100)}).fetch(NoConfig(), ApiKey(api_key="k"))
    first = next(stream)
    asked_after_one_row = len(server.asked)
    stream.close()

    assert first.values["id"] == 0
    assert asked_after_one_row == 1


# ── Authenticating ───────────────────────────────────────────────────────────


def test_a_bearer_token_goes_in_the_header(serve):
    server = serve(ok([]))

    read(connector({"auth": AuthStyle(kind="bearer")}))

    assert server.asked[0].headers["authorization"] == "Bearer k"


def test_basic_auth_puts_the_key_in_the_username(serve):
    """Freshdesk and several others do this, with an ignored constant password."""
    import base64

    server = serve(ok([]))

    read(connector({"auth": AuthStyle(kind="basic", basic_password="X")}))

    sent = server.asked[0].headers["authorization"]
    assert sent.startswith("Basic ")
    assert base64.b64decode(sent.split()[1]).decode() == "k:X"


def test_a_named_header_is_used_when_the_provider_wants_one(serve):
    server = serve(ok([]))

    read(connector({"auth": AuthStyle(kind="header", header="X-Api-Token")}))

    assert server.asked[0].headers["x-api-token"] == "k"


def test_a_query_credential_is_sent_as_a_parameter(serve):
    server = serve(ok([]))

    read(connector({"auth": AuthStyle(kind="query", param="apikey")}))

    assert server.params()["apikey"] == "k"


def test_a_missing_credential_says_so_before_any_request(serve):
    server = serve(ok([]))

    with pytest.raises(RestProblem, match="No credential"):
        list(connector().fetch(NoConfig(), ApiKey(api_key="")))

    assert server.asked == []


# ── When the provider is unhappy ─────────────────────────────────────────────


def test_a_rejected_credential_is_not_retried(serve):
    """Hammering an authentication endpoint is how an account gets locked."""
    server = serve((401, {"error": "nope"}, None))

    with pytest.raises(RestProblem, match="refused the credential"):
        read(connector())

    assert len(server.asked) == 1


def test_a_rate_limit_is_waited_out_and_retried(serve, monkeypatch):
    """Honouring `Retry-After` is the difference between an integration a provider
    tolerates and one they block."""
    slept: list[float] = []
    monkeypatch.setattr(rest.time if hasattr(rest, "time") else __import__("time"), "sleep", lambda s: slept.append(s))
    server = serve((429, {}, {"Retry-After": "2"}), ok([{"id": 1}]))

    found = read(connector())

    assert slept == [2.0]
    assert found == [{"id": 1}]


def test_an_absurd_retry_after_is_capped(serve, monkeypatch):
    """A sync that sleeps for ten minutes is a sync that has stopped."""
    slept: list[float] = []
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: slept.append(s))
    serve((429, {}, {"Retry-After": "3600"}), ok([]))

    read(connector())

    assert slept == [rest.MAX_RETRY_WAIT]


def test_a_retry_after_that_is_not_a_number_still_waits_briefly(serve, monkeypatch):
    """Some providers send an HTTP date. A second is enough for the transient case
    and short enough not to look like a hang."""
    slept: list[float] = []
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: slept.append(s))
    serve((429, {}, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), ok([]))

    read(connector())

    assert slept == [1.0]


def test_a_server_error_is_retried(serve, monkeypatch):
    """A transient gateway error should not fail a sync that would have worked a
    second later."""
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)
    server = serve((502, {}, None), ok([{"id": 1}]))

    assert read(connector()) == [{"id": 1}]
    assert len(server.asked) == 2


def test_it_gives_up_after_enough_attempts(serve, monkeypatch):
    monkeypatch.setattr(__import__("time"), "sleep", lambda s: None)
    server = serve((502, {}, None))

    with pytest.raises(RestProblem, match="502"):
        read(connector())

    assert len(server.asked) == rest.MAX_ATTEMPTS


def test_a_missing_endpoint_points_at_the_settings(serve):
    serve((404, {}, None))

    with pytest.raises(RestProblem, match="nothing at that path"):
        read(connector())


def test_a_non_json_reply_is_reported_as_such(serve, monkeypatch):
    """An HTML error page from a proxy, which is what a misconfigured host returns."""

    def html(request):
        return httpx.Response(200, text="<html>gateway</html>")

    real = httpx.Client
    monkeypatch.setattr(
        rest.httpx,
        "Client",
        lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(html)}),
    )

    with pytest.raises(RestProblem, match="not JSON"):
        read(connector())


def test_an_error_never_quotes_the_url(serve):
    """A `query`-style credential lives in the query string, so a message quoting
    the URL would put an API key into the run history — where the entire point is
    that it is encrypted."""
    serve((400, {}, None))

    with pytest.raises(RestProblem) as raised:
        read(connector({"auth": AuthStyle(kind="query", param="apikey")}))

    assert "apikey" not in str(raised.value)
    assert "api.example.test" not in str(raised.value)


# ── Placeholders in the spec ─────────────────────────────────────────────────


def test_a_placeholder_is_filled_from_the_source_settings():
    conn = FreshdeskConnector()

    spec = conn._spec_for(FreshdeskConfig(domain="acme", records="contacts"))

    assert spec.base_url == "https://acme.freshdesk.com/api/v2"
    assert spec.path == "contacts"


def test_a_blank_setting_is_caught_by_the_name_on_its_own_form():
    """**Formatting hides an empty value.** `{domain}` with `domain=""` produces
    `https://.freshdesk.com/api/v2` — no placeholder left, structurally a fine URL,
    and it fails at DNS resolution with a message about a hostname rather than about
    the box somebody left blank.

    The message uses the field's own label, so it matches what is on screen."""
    conn = FreshdeskConnector()

    with pytest.raises(RestProblem) as raised:
        conn._spec_for(FreshdeskConfig(domain="", records="tickets"))

    assert "Freshdesk domain is not filled in" in str(raised.value)


def test_whitespace_is_not_a_setting_either():
    conn = FreshdeskConnector()

    with pytest.raises(RestProblem, match="not filled in"):
        conn._spec_for(FreshdeskConfig(domain="   ", records="tickets"))


def test_a_setting_the_spec_needs_but_the_form_lacks_is_a_connector_bug():
    """A spec and a config model that disagree. Not something an admin can fix, so
    the message says whose fault it is rather than sending them to a form."""
    conn = RestConnector(
        "x", "X", RestSpec(base_url="https://{missing}.test", path="p"), NoConfig, ApiKey
    )

    with pytest.raises(RestProblem, match="bug in the connector"):
        conn._spec_for(NoConfig())


# ── Discovery and the Test button ────────────────────────────────────────────


def test_discovery_reads_one_page_and_stops(serve):
    """Six columns described without reading two hundred pages."""
    page = [{"id": n, "subject": "s"} for n in range(100)]
    server = serve(ok(page), ok(page))

    found = connector({"paging": Paging(page_size=100)}).discover(
        NoConfig(), ApiKey(api_key="k")
    )

    assert [f.name for f in found] == ["id", "subject"]
    assert len(server.asked) == 1


def test_discovery_guesses_kinds_from_the_records(serve):
    serve(
        ok(
            [
                {
                    "id": 7,
                    "owner": "sam@example.test",
                    "amount": "1,250.00",
                    "closed_at": "2026-08-20",
                    "open": True,
                    "tags": ["a"],
                }
            ]
        )
    )

    kinds = {f.name: f.kind for f in connector().discover(NoConfig(), ApiKey(api_key="k"))}

    assert kinds == {
        "id": "number",
        "owner": "email",
        "amount": "number",
        "closed_at": "date",
        "open": "boolean",
        "tags": "string",
    }


def test_a_nested_object_is_not_silently_unwrapped(serve):
    """A mapping pointing at `contact.owner.email` would be a second place where
    the shape of somebody's data is interpreted. That belongs in the spec or in a
    mapping feature, not in a quiet unwrap here."""
    serve(ok([{"requester": {"email": "sam@example.test"}}]))

    found = connector().discover(NoConfig(), ApiKey(api_key="k"))

    assert [(f.name, f.kind) for f in found] == [("requester", "string")]


def test_a_column_whose_first_value_is_null_is_typed_from_a_later_record(serve):
    serve(ok([{"amount": None}, {"amount": 1250}]))

    found = connector().discover(NoConfig(), ApiKey(api_key="k"))

    assert [(f.name, f.kind) for f in found] == [("amount", "number")]


def test_discovery_is_empty_rather_than_raising_when_the_provider_refuses(serve):
    """An empty answer, like every other connector's discover — the page says "no
    columns known yet" and the Test button carries the reason."""
    serve((401, {}, None))

    assert connector().discover(NoConfig(), ApiKey(api_key="k")) == []


def test_a_good_test_reports_what_came_back(serve):
    serve(ok([{"id": 1, "subject": "hello"}]))

    result = connector().test_connection(NoConfig(), ApiKey(api_key="k"))

    assert result.ok is True
    assert "1 record" in result.detail
    assert result.info["columns"] == "id, subject"


def test_finding_no_records_says_where_they_actually_are(serve):
    """**What turns "connected, 0 records" from a dead end into an instruction.**
    Getting the records path right is the fiddliest part of pointing this engine at
    a new provider, and the response itself knows the answer."""
    serve(ok({"meta": {"count": 2}, "data": [{"id": 1}]}))

    result = connector().test_connection(NoConfig(), ApiKey(api_key="k"))

    assert result.ok is False
    assert "'data'" in result.detail
    assert "the response itself" in result.detail


def test_it_names_the_path_that_was_tried(serve):
    """So the message reads as a comparison rather than a riddle."""
    serve(ok({"records": [{"id": 1}]}))

    result = connector({"rows_at": "results"}).test_connection(
        NoConfig(), ApiKey(api_key="k")
    )

    assert "'results'" in result.detail
    assert "'records'" in result.detail


def test_a_genuinely_empty_response_is_not_reported_as_a_problem(serve):
    """Nothing changed since the window opened is the normal state of a healthy
    source, and calling it a failure would train people to ignore the word.

    Told apart from a wrong path by whether the configured location holds a *list*:
    an empty list is the right shape and nothing in it; a missing one is the wrong
    place."""
    serve(ok([]))

    result = connector().test_connection(NoConfig(), ApiKey(api_key="k"))

    assert result.ok is True
    assert "no records" in result.detail


def test_an_empty_list_at_the_configured_path_is_also_normal(serve):
    serve(ok({"data": []}))

    result = connector({"rows_at": "data"}).test_connection(NoConfig(), ApiKey(api_key="k"))

    assert result.ok is True


def test_a_response_with_no_lists_at_all_points_at_the_url(serve):
    """**The third case, and the one a live probe found.** `{"status": "ok"}` is not
    an empty result — it is a summary endpoint, or the wrong URL entirely. Reporting
    it as "normally empty" sends somebody away satisfied with a source that will
    never import anything."""
    serve(ok({"status": "ok", "version": "1.2"}))

    result = connector().test_connection(NoConfig(), ApiKey(api_key="k"))

    assert result.ok is False
    assert "no list of records at all" in result.detail
    # The keys it did get, so they can see what they actually pointed at.
    assert "status, version" in result.detail


def test_array_paths_finds_the_lists_worth_offering():
    from app.connectors.rest import array_paths

    assert array_paths({"data": [{"id": 1}]}) == ["data"]
    assert array_paths({"results": {"items": [{"id": 1}]}}) == ["results.items"]


def test_array_paths_ignores_lists_that_are_not_records():
    """A list of ids or tag names is not where the records are, and offering it
    would send somebody down a path that produces a mapping error per row."""
    from app.connectors.rest import array_paths

    assert array_paths({"tags": ["a", "b"], "ids": [1, 2], "data": [{"id": 1}]}) == [
        "data"
    ]


def test_array_paths_stops_before_it_gets_silly():
    """Two levels covers every shape anybody ships. Deeper starts reporting paths
    more confusing than helpful."""
    from app.connectors.rest import array_paths

    deep = {"a": {"b": {"c": {"d": [{"id": 1}]}}}}

    assert array_paths(deep) == []


def test_array_paths_has_nothing_to_say_about_a_list_response():
    from app.connectors.rest import array_paths

    assert array_paths([{"id": 1}]) == []


def test_a_failed_test_is_reported_not_raised(serve):
    serve((401, {}, None))

    result = connector().test_connection(NoConfig(), ApiKey(api_key="k"))

    assert result.ok is False
    assert "refused the credential" in result.detail


def test_a_test_with_nothing_configured_needs_no_network(serve):
    server = serve(ok([]))
    conn = FreshdeskConnector()

    result = conn.test_connection(FreshdeskConfig(), FreshdeskKey())

    assert result.ok is False
    assert server.asked == []


# ── Freshdesk's own spec ─────────────────────────────────────────────────────


def test_freshdesk_filters_on_when_a_ticket_changed_not_when_it_opened():
    """**The field worth checking twice.** A ticket opened last month and resolved
    today has to come back; a filter on the creation date never returns it. The
    same trap the SQL connector refuses a query for."""
    from app.connectors.freshdesk import FRESHDESK

    assert FRESHDESK.since_param == "updated_since"


def test_freshdesk_asks_oldest_first():
    """So a run interrupted halfway leaves the window somewhere sensible, rather
    than having read the newest records and none of the middle."""
    from app.connectors.freshdesk import FRESHDESK

    assert ("order_type", "asc") in FRESHDESK.extra_params


def test_freshdesk_reads_the_endpoint_the_admin_chose(serve):
    server = serve(ok([]))
    conn = FreshdeskConnector()

    list(conn.fetch(FreshdeskConfig(domain="acme", records="companies"), FreshdeskKey(api_key="k")))

    assert str(server.asked[0].url).startswith(
        "https://acme.freshdesk.com/api/v2/companies"
    )


def test_freshdesk_only_offers_endpoints_it_can_read():
    """A free-text endpoint would be a way to point the connector at anything and
    get a 404 with no explanation."""
    schema = FreshdeskConfig.model_json_schema()

    assert schema["properties"]["records"]["enum"] == ["tickets", "contacts", "companies"]


def test_freshdesk_needs_no_oauth():
    """Which is why it went first among the REST providers: the engine gets proven
    against a real provider's paging without a consent flow in the way."""
    from app import connectors

    assert connectors.oauth_of(FreshdeskConnector()) is None


# -- The generic API connector -----------------------------------------------
#
# The engine with its spec on the form, so an unbuilt provider is not a dead end.
# What matters here is that a pasted URL survives the round trip intact and that
# the form's answers land in the right places.


def api_conn():
    from app.connectors.api import GenericApiConnector

    return GenericApiConnector()


def api_config(**overrides):
    from app.connectors.api import ApiConfig

    body = {"url": "https://api.example.test/v2/records"}
    body.update(overrides)
    return ApiConfig(**body)


def api_key(key="k"):
    from app.connectors.api import ApiSecrets

    return ApiSecrets(api_key=key)


def test_a_pasted_url_is_requested_exactly_as_pasted(serve):
    """Split and rejoined by the engine, so a doubled or missing slash would show
    up here — and a 404 from a mangled path is a horrible thing to debug."""
    server = serve(ok([]))

    list(api_conn().fetch(api_config(), api_key()))

    assert str(server.asked[0].url).startswith("https://api.example.test/v2/records")


def test_a_url_with_no_path_still_works(serve):
    server = serve(ok([]))

    list(api_conn().fetch(api_config(url="https://api.example.test"), api_key()))

    assert server.asked[0].url.path in ("/", "")


def test_an_empty_url_says_so_before_any_request(serve):
    server = serve(ok([]))

    with pytest.raises(RestProblem, match="not filled in"):
        list(api_conn().fetch(api_config(url=""), api_key()))

    assert server.asked == []


def test_a_url_without_a_scheme_is_refused_with_the_fix(serve):
    """`api.example.com/deals` is what somebody pastes out of documentation, and it
    would otherwise be requested as a relative path against nothing."""
    with pytest.raises(RestProblem, match="http:// or https://"):
        list(api_conn().fetch(api_config(url="api.example.test/v2"), api_key()))


def test_the_form_decides_how_it_authenticates(serve):
    server = serve(ok([]))

    list(
        api_conn().fetch(
            api_config(auth_kind="header", auth_header="X-Token"), api_key("abc")
        )
    )

    assert server.asked[0].headers["x-token"] == "abc"


def test_no_credential_is_allowed_for_a_public_endpoint(serve):
    """Unlike every named connector. An internal service the deployment is already
    inside needs no key, and refusing that would make this useless for the case it
    is most obviously good for."""
    server = serve(ok([{"id": 1}]))

    found = [r.values for r in api_conn().fetch(api_config(auth_kind="none"), api_key(""))]

    assert found == [{"id": 1}]


def test_the_form_decides_where_the_records_are(serve):
    serve(ok({"results": {"items": [{"id": 1}]}}))

    found = [
        r.values
        for r in api_conn().fetch(api_config(rows_at="results.items"), api_key())
    ]

    assert found == [{"id": 1}]


def test_the_form_decides_how_it_pages(serve):
    page = [{"id": n} for n in range(50)]
    server = serve(ok(page), ok([{"id": 999}]))

    found = [
        r.values
        for r in api_conn().fetch(
            api_config(paging_kind="page", page_size=50), api_key()
        )
    ]

    assert len(found) == 51
    assert server.params(1)["page"] == "2"


def test_paging_defaults_to_a_single_request(serve):
    """The safe default for an API nobody has characterised yet: asking for page two
    of something that does not page can return page one again, and a loop that reads
    the same hundred rows five hundred times is worse than reading one page."""
    server = serve(ok([{"id": n} for n in range(100)]))

    list(api_conn().fetch(api_config(), api_key()))

    assert len(server.asked) == 1


def test_extra_parameters_are_sent_on_every_request(serve):
    server = serve(ok([]))

    list(api_conn().fetch(api_config(extra_params={"status": "won"}), api_key()))

    assert server.params()["status"] == "won"


def test_the_window_uses_the_parameter_and_format_from_the_form(serve):
    server = serve(ok([]))

    list(
        api_conn().fetch(
            api_config(since_param="modified_after", since_format="date"),
            api_key(),
            WHEN,
        )
    )

    assert server.params()["modified_after"] == "2026-08-21"


def test_a_failure_is_named_after_whatever_the_admin_called_it(serve):
    """So the run history says which integration broke rather than "the API"."""
    serve((401, {}, None))

    result = api_conn().test_connection(
        api_config(provider_name="Example CRM"), api_key()
    )

    assert result.ok is False
    assert "Example CRM" in result.detail


def test_it_falls_back_to_a_neutral_name(serve):
    serve((401, {}, None))

    result = api_conn().test_connection(api_config(), api_key())

    assert "the API refused" in result.detail


def test_an_unrecognised_since_format_is_refused_rather_than_guessed():
    """**The lenient branch that existed to be safe and did the opposite.**

    `format_since` returned ISO for any style it did not recognise, so a spec
    written with `since_format="unix"` — not a name it knows — sent an ISO string
    to a parameter that reads Unix seconds. The provider then answers with either
    everything or nothing and never says which, and nothing anywhere logs a word.

    Zendesk's spec was written that way the first time, which is how this was
    found. A spec is code we write rather than input from a user, so a name it
    does not know is a bug to raise on.
    """
    from datetime import UTC, datetime

    from app.connectors.rest import format_since

    with pytest.raises(ValueError, match="unix"):
        format_since(datetime(2026, 8, 26, tzinfo=UTC), "unix")


def test_the_three_known_since_formats_all_still_work():
    """The guard above must refuse only what is genuinely unknown — a check that
    rejected a real style would break every connector at once."""
    from datetime import UTC, datetime

    from app.connectors.rest import format_since

    when = datetime(2026, 8, 26, 9, 30, tzinfo=UTC)

    assert format_since(when, "iso") == "2026-08-26T09:30:00Z"
    assert format_since(when, "epoch") == str(int(when.timestamp()))
    assert format_since(when, "date") == "2026-08-26"
    # No window at all is not an unknown format; it means "ask for everything".
    assert format_since(None, "nonsense") is None


def test_a_cursor_provider_is_told_how_many_rows_to_send(serve):
    """**Nothing caught this, and it was costing HubSpot ten times the requests.**

    The page size was sent only for page and offset paging. A cursor connector
    therefore got the provider's *default* — ten, for HubSpot — so a company with
    twenty thousand deals needed two thousand requests and stopped at the
    five-hundred-page cap having read a quarter of them. Compounded by HubSpot
    having no modified filter, so it re-reads everything every sync.
    """
    server = serve(ok({"rows": [], "next": None}))

    read(
        connector(
            {
                "rows_at": "rows",
                "paging": Paging(
                    kind="cursor", cursor_at="next", size_param="limit", page_size=100
                ),
            }
        )
    )

    assert server.params()["limit"] == "100"


def test_the_page_size_is_still_sent_once_a_cursor_is_being_followed(serve):
    """It is set once and carried by `params.update`, so page two must still say
    how many rows it wants — otherwise the first page is large and every one after
    it is ten rows."""
    server = serve(
        ok({"rows": [{"id": 1}], "next": "more"}),
        ok({"rows": [{"id": 2}], "next": None}),
    )

    read(
        connector(
            {
                "rows_at": "rows",
                "paging": Paging(
                    kind="cursor",
                    cursor_at="next",
                    cursor_param="cursor",
                    size_param="limit",
                    page_size=100,
                ),
            }
        )
    )

    assert server.params(1)["limit"] == "100"
    assert server.params(1)["cursor"] == "more"


def test_a_provider_that_takes_no_page_size_is_not_sent_one(serve):
    """Some cursor APIs reject an unexpected parameter outright, so a spec says so
    with an empty `size_param` and is left alone."""
    server = serve(ok({"rows": [], "next": None}))

    read(
        connector(
            {
                "rows_at": "rows",
                "paging": Paging(kind="cursor", cursor_at="next", size_param=""),
            }
        )
    )

    assert "per_page" not in server.params()
    assert "limit" not in server.params()


def test_a_single_response_provider_is_not_sent_a_page_size(serve):
    """`kind="none"` means one request and everything in it. Salesforce's query
    endpoint takes no such parameter and Zendesk's incremental export has its own
    meaning for one."""
    server = serve(ok({"rows": []}))

    read(connector({"rows_at": "rows", "paging": Paging(kind="none")}))

    assert "per_page" not in server.params()
