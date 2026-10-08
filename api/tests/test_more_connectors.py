"""Zendesk, Gong, Aircall and Close.

The engine is tested in `test_rest_connector.py`, so what is left per provider is
what is genuinely theirs. For these four that is mostly **how each one is
authenticated**, because between them they are the reason the engine grew a second
Basic-auth secret — and a wrong password half is a 401 with nothing else to go on.

**None of this is verification against a live account.** These prove the specs are
read the way they are written; only a trial login proves each endpoint is the one
that provider still serves.
"""

import base64
from datetime import UTC, datetime

import httpx
import pytest

from app.connectors import rest as rest_module
from app.connectors.calls import (
    AircallConfig,
    AircallConnector,
    AircallSecrets,
    GongConfig,
    GongConnector,
    GongSecrets,
)
from app.connectors.crm import CloseConfig, CloseConnector, CloseToken
from app.connectors.rest import RestProblem
from app.connectors.support import ZendeskConfig, ZendeskConnector, ZendeskSecrets

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

    def signed_in_as(self, index=0) -> tuple[str, str]:
        """The two halves of Basic auth, as the provider would decode them.

        Decoded rather than compared against a pre-built header, so the test knows
        what was actually sent rather than what we think base64 of it looks like —
        which is the mistake that made an earlier fixture unable to tell a correct
        value from a wrong one.
        """
        header = self.asked[index].headers["authorization"]
        assert header.startswith("Basic ")
        user, _, password = (
            base64.b64decode(header.removeprefix("Basic ")).decode().partition(":")
        )
        return user, password


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


# ── Zendesk ──────────────────────────────────────────────────────────────────


def zendesk_read(config=None, secrets=None, since=None):
    return list(
        ZendeskConnector().fetch(
            config or ZendeskConfig(subdomain="acme"),
            secrets or ZendeskSecrets(email="bot@acme.com", api_key="tok"),
            since,
        )
    )


def test_zendesk_reaches_the_customers_own_subdomain(serve):
    server = serve(ok({"tickets": [{"id": 1}]}))

    zendesk_read()

    assert server.asked[0].url.host == "acme.zendesk.com"


def test_zendesk_uses_the_incremental_export_for_the_chosen_records(serve):
    server = serve(ok({"users": [{"id": 1}]}))

    zendesk_read(ZendeskConfig(subdomain="acme", records="users"))

    assert server.asked[0].url.path == "/api/v2/incremental/users.json"


def test_zendesk_reads_the_array_named_after_the_endpoint(serve):
    """`rows_at` moves with the endpoint. Hard-coding it to `tickets` would make
    the users endpoint return nothing at all, with no error to explain it."""
    serve(ok({"users": [{"id": 7}, {"id": 8}]}))

    rows = zendesk_read(ZendeskConfig(subdomain="acme", records="users"))

    assert [row.values["id"] for row in rows] == [7, 8]


def test_zendesk_signs_in_as_email_slash_token(serve):
    """Zendesk's own spelling, and the thing nobody types correctly by hand: the
    username is the agent's address with `/token` appended, and the password is the
    API token itself."""
    server = serve(ok({"tickets": []}))

    zendesk_read()

    assert server.signed_in_as() == ("bot@acme.com/token", "tok")


def test_zendesk_says_so_when_the_email_is_missing(serve):
    """Without it the request is a 401 the admin has no way to interpret."""
    serve(ok({"tickets": []}))

    with pytest.raises(RestProblem, match="email"):
        zendesk_read(secrets=ZendeskSecrets(email="", api_key="tok"))


def test_zendesk_asks_for_changes_as_a_unix_timestamp(serve):
    """`start_time` is seconds since the epoch, not ISO. Sending the wrong shape is
    how a provider answers with everything, or with nothing, and never says which.
    """
    server = serve(ok({"tickets": []}))

    zendesk_read(since=WHEN)

    assert server.params()["start_time"] == str(int(WHEN.timestamp()))


def test_zendesk_omits_the_window_on_a_first_sync(serve):
    server = serve(ok({"tickets": []}))

    zendesk_read()

    assert "start_time" not in server.params()


# ── Gong ─────────────────────────────────────────────────────────────────────


def gong_read(config=None, since=None):
    return list(
        GongConnector().fetch(
            config or GongConfig(),
            GongSecrets(api_key="key", api_secret="secret"),
            since,
        )
    )


def test_gong_signs_with_both_halves_of_the_pair(serve):
    """The access key and its secret. The engine's default password is the constant
    `X`, which Gong rejects — this is the case `basic_password_field` was added
    for."""
    server = serve(ok({"calls": []}))

    gong_read()

    assert server.signed_in_as() == ("key", "secret")


def test_gong_asks_for_calls_changed_since(serve):
    server = serve(ok({"calls": []}))

    gong_read(since=WHEN)

    assert server.params()["fromDateTime"] == "2026-08-26T09:30:00Z"


def test_gong_follows_the_cursor_it_is_handed(serve):
    """Gong's cursor sits under `records`, not at the top level. A cursor read from
    the wrong place reads page one for ever, which looks like success."""
    server = serve(
        ok({"calls": [{"id": "a"}], "records": {"cursor": "next-please"}}),
        ok({"calls": [{"id": "b"}]}),
    )

    rows = gong_read()

    assert server.params(1)["cursor"] == "next-please"
    assert [row.values["id"] for row in rows] == ["a", "b"]


def test_gong_reads_the_endpoint_that_was_chosen(serve):
    server = serve(ok({"users": []}))

    gong_read(GongConfig(records="users"))

    assert server.asked[0].url.path == "/v2/users"


# ── Aircall ──────────────────────────────────────────────────────────────────


def aircall_read(config=None, since=None):
    return list(
        AircallConnector().fetch(
            config or AircallConfig(),
            AircallSecrets(api_key="id", api_token="tok"),
            since,
        )
    )


def test_aircall_signs_with_the_id_and_the_token(serve):
    server = serve(ok({"calls": []}))

    aircall_read()

    assert server.signed_in_as() == ("id", "tok")


def test_aircall_asks_for_calls_from_a_unix_timestamp(serve):
    server = serve(ok({"calls": []}))

    aircall_read(since=WHEN)

    assert server.params()["from"] == str(int(WHEN.timestamp()))


def test_aircall_pages_by_number_and_stops_on_a_short_page(serve):
    """Aircall returns a full `next_page_link` URL, which this engine will not
    follow — so stopping falls to the row-count arithmetic. A page shorter than the
    page size is the last one."""
    full = [{"id": n} for n in range(50)]
    server = serve(ok({"calls": full}), ok({"calls": [{"id": 99}]}))

    rows = aircall_read()

    assert server.params(1)["page"] == "2"
    assert len(rows) == 51
    assert len(server.asked) == 2


# ── Close ────────────────────────────────────────────────────────────────────


def close_read(config=None, since=None):
    return list(
        CloseConnector().fetch(
            config or CloseConfig(),
            CloseToken(api_key="api_abc"),
            since,
        )
    )


def test_close_sends_the_key_with_a_genuinely_blank_password(serve):
    """Close documents an empty password half, not the placeholder the other
    key-as-username providers ignore."""
    server = serve(ok({"data": [], "has_more": False}))

    close_read()

    assert server.signed_in_as() == ("api_abc", "")


def test_close_asks_only_for_what_changed(serve):
    server = serve(ok({"data": [], "has_more": False}))

    close_read(since=WHEN)

    assert server.params()["date_updated__gt"] == "2026-08-26T09:30:00Z"


def test_close_stops_when_close_says_there_is_no_more(serve):
    """`has_more` is checked before guessing from the row count, because a provider
    that tells us is more reliable than arithmetic — and a full page that happens to
    be the last one is exactly where arithmetic is wrong."""
    full = [{"id": n} for n in range(100)]
    server = serve(ok({"data": full, "has_more": False}))

    rows = close_read()

    assert len(server.asked) == 1
    assert len(rows) == 100


def test_close_advances_the_offset_rather_than_a_page_number(serve):
    server = serve(
        ok({"data": [{"id": n} for n in range(100)], "has_more": True}),
        ok({"data": [{"id": "last"}], "has_more": False}),
    )

    close_read()

    assert server.params(1)["_skip"] == "100"


def test_close_reads_the_endpoint_that_was_chosen(serve):
    server = serve(ok({"data": [], "has_more": False}))

    close_read(CloseConfig(records="lead"))

    assert server.asked[0].url.path == "/api/v1/lead/"


def test_gong_is_sent_no_page_size_because_it_documents_none(serve):
    """Cursor paging usually has to say how many rows it wants — but Gong does not
    take a page-size parameter, so the engine must not invent one.

    Written while fixing the opposite bug on HubSpot, and it immediately caught the
    fix over-reaching: sending the engine's default would have started giving Gong a
    `per_page` it never asked for.
    """
    server = serve(ok({"calls": []}))

    gong_read()

    assert "per_page" not in server.params()
    assert "limit" not in server.params()


def test_zendesk_is_sent_no_page_size_because_it_reads_one_response(serve):
    """Its incremental export returns everything up to its own cap in one go, and
    `per_page` there means something different from the page size on a paged API."""
    server = serve(ok({"tickets": []}))

    zendesk_read()

    assert "per_page" not in server.params()
    assert "limit" not in server.params()
