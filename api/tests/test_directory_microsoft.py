"""Reading people out of a Microsoft 365 tenant.

**None of this is verification against a live tenant.** It proves the requests are
built and the responses read the way they are written; only a real Entra app
registration proves the endpoints and permissions are the ones Microsoft still
serves. Same caveat as every REST connector, and worth as much here.

The thing most worth pinning down is what gets *excluded*. A tenant is full of
accounts that are not people, and without this a leaderboard grows an entry called
"Conference Room B".
"""

import httpx
import pytest

from app.directory import microsoft
from app.models import OauthClient


@pytest.fixture
def connection(db, org):
    row = OauthClient(
        organization_id=org.id,
        provider="microsoft",
        client_id="client",
        # `secret_of` decrypts, so this has to be real ciphertext.
        client_secret_encrypted=__import__("app.crypto", fromlist=["encrypt"]).encrypt(
            "shhh"
        ),
        tenant_id="contoso.onmicrosoft.com",
    )
    db.add(row)
    db.flush()
    return row


class Graph:
    """A tenant that answers, so the shape of every request is visible."""

    def __init__(self, users=None, groups=None, members=None, purposes=None):
        self.users = users or []
        self.groups = groups or []
        self.members = members or {}
        self.purposes = purposes or {}
        self.asked: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        path = request.url.path

        if path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "graph-token"})
        if path.endswith("/$batch"):
            import json as jsonlib

            wanted = jsonlib.loads(request.content)["requests"]
            return httpx.Response(
                200,
                json={
                    "responses": [
                        {
                            "id": item["id"],
                            "status": 200,
                            "body": {
                                "userPurpose": self.purposes.get(
                                    item["url"].split("/")[2], "user"
                                )
                            },
                        }
                        for item in wanted
                    ]
                },
            )
        if path.endswith("/v1.0/users"):
            return httpx.Response(200, json={"value": self.users})
        if path.endswith("/v1.0/groups"):
            return httpx.Response(200, json={"value": self.groups})
        if "/groups/" in path and path.endswith("/members"):
            group_id = path.split("/groups/")[1].split("/")[0]
            return httpx.Response(
                200, json={"value": self.members.get(group_id, [])}
            )
        return httpx.Response(404, json={"error": {"message": f"no route for {path}"}})


#: Captured **at import**, before any fixture patches it.
#:
#: A test that grabbed `httpx.Client` after the fixture had replaced it, and then
#: wrapped it with its own transport, got its transport silently discarded — the
#: fixture's wrapper overwrites `transport` on the way through. Three tests here did
#: that, and two of them passed anyway because the fixture's own tenant happened to
#: answer correctly. They were asserting nothing.
REAL_CLIENT = httpx.Client


@pytest.fixture
def tenant(monkeypatch):
    """A tenant that answers, optionally through a handler of the test's own.

    `handler` exists so a test can make one endpoint misbehave without rebuilding
    the transport plumbing — and, more importantly, without the footgun above.
    """

    def _install(handler=None, **kwargs):
        graph = Graph(**kwargs)
        answer = handler(graph) if handler else graph

        def client(*args, **kw):
            kw["transport"] = httpx.MockTransport(answer)
            return REAL_CLIENT(*args, **kw)

        def post(url, **kw):
            with client() as c:
                return c.post(url, **kw)

        monkeypatch.setattr(microsoft.httpx, "Client", client)
        monkeypatch.setattr(microsoft.httpx, "post", post)
        return graph

    return _install


def account(user_id="u1", **kwargs):
    defaults = dict(
        id=user_id,
        displayName="Sam Rivera",
        mail=f"{user_id}@acme.com",
        userPrincipalName=f"{user_id}@acme.com",
        jobTitle="Account Executive",
        department="Sales",
        officeLocation="Phoenix",
        accountEnabled=True,
        userType="Member",
    )
    defaults.update(kwargs)
    return defaults


# ── Getting a token ──────────────────────────────────────────────────────────


def test_the_token_is_asked_for_with_client_credentials(db, tenant, connection):
    """**Nobody signs in for a directory sync**, and the round trip to delegated
    and back is why this says so twice.

    Delegated was tried because a Cloud Application Administrator cannot consent
    to Microsoft Graph app roles on paper. It cost a sync that acted as one person
    and stopped when they left. Acting as the application has no account to
    offboard and no token to expire — it needs one press of *Grant admin consent*
    instead, which is a step, not an expiry date.
    """
    graph = tenant(users=[])

    microsoft.people(db, connection)

    asked = dict(httpx.QueryParams(graph.asked[0].content.decode()))
    assert asked["grant_type"] == "client_credentials"
    # `.default` means "whatever admin consent already granted", which is the only
    # thing this grant accepts — naming scopes individually is not how it works.
    assert asked["scope"] == "https://graph.microsoft.com/.default"
    assert "refresh_token" not in asked

def test_a_connection_with_no_tenant_says_so_rather_than_failing_obscurely(db, tenant, connection):
    """The token endpoint is per-tenant, so there is no request to make at all."""
    tenant(users=[])
    connection.tenant_id = None

    with pytest.raises(microsoft.DirectoryProblem, match="tenant"):
        microsoft.people(db, connection)


# ── Who counts as a person ───────────────────────────────────────────────────


def test_a_normal_employee_comes_back_with_everything_a_rule_needs(db, tenant, connection):
    tenant(users=[account()])

    found = microsoft.people(db, connection, with_groups=False)

    assert len(found) == 1
    assert found[0].external_id == "u1"
    assert found[0].email == "u1@acme.com"
    assert found[0].display_name == "Sam Rivera"
    assert found[0].job_title == "Account Executive"
    assert found[0].department == "Sales"
    assert found[0].office_location == "Phoenix"


def test_a_meeting_room_is_not_a_person(db, tenant, connection):
    """**Without this a leaderboard grows an entry called "Conference Room B".**
    The mailbox's purpose is the only reliable signal Graph offers."""
    tenant(users=[account("room1")], purposes={"room1": "room"})

    assert microsoft.people(db, connection, with_groups=False) == []


def test_a_shared_mailbox_is_not_a_person(db, tenant, connection):
    tenant(users=[account("sales-inbox")], purposes={"sales-inbox": "shared"})

    assert microsoft.people(db, connection, with_groups=False) == []


def test_a_guest_is_not_staff(db, tenant, connection):
    """External collaborators are in the directory. Including them would put a
    customer's own employees on the client's leaderboard."""
    tenant(users=[account("guest1", userType="Guest")])

    assert microsoft.people(db, connection, with_groups=False) == []


def test_an_account_with_no_address_at_all_is_skipped(db, tenant, connection):
    """Service accounts, mostly. Somebody with no address could not sign in here,
    and there would be nothing to match their metric rows against either."""
    tenant(users=[account("svc", mail=None, userPrincipalName=None)])

    assert microsoft.people(db, connection, with_groups=False) == []


def test_a_tenant_that_sets_no_mail_falls_back_to_the_sign_in_name(db, tenant, connection):
    """Some tenants never populate `mail`. Every person would otherwise be skipped,
    which is a whole company silently missing."""
    tenant(users=[account("u1", mail=None)])

    found = microsoft.people(db, connection, with_groups=False)

    assert found[0].email == "u1@acme.com"


def test_a_disabled_account_comes_back_marked_rather_than_dropped(db, tenant, connection):
    """**This is how a leaver gets noticed at all.** Dropping them here would look
    identical to them never having existed, and reconcile would archive them for
    the wrong reason — or not at all, if the tenant kept returning them."""
    tenant(users=[account(accountEnabled=False)])

    found = microsoft.people(db, connection, with_groups=False)

    assert len(found) == 1
    assert found[0].enabled is False


def test_the_mailbox_check_is_batched_rather_than_one_request_each(db, tenant, connection):
    """One request per account is the difference between a sync and a rate-limit
    ban. Graph allows twenty per batch."""
    graph = tenant(users=[account(f"u{n}") for n in range(45)])

    microsoft.people(db, connection, with_groups=False)

    batches = [r for r in graph.asked if r.url.path.endswith("/$batch")]
    assert len(batches) == 3  # 45 accounts, twenty at a time


def test_a_batch_that_fails_does_not_lose_the_people(db, tenant, connection):
    """**Including a meeting room by mistake is visible and fixable.** Excluding a
    real employee because one sub-request failed is somebody silently missing from
    the leaderboard, which nobody notices for a month — so an unreadable mailbox is
    treated as a person."""

    def failing_batch(graph):
        def handler(request):
            if request.url.path.endswith("/$batch"):
                return httpx.Response(500, json={"error": {"message": "busy"}})
            return graph(request)

        return handler

    tenant(handler=failing_batch, users=[account()])

    found = microsoft.people(db, connection, with_groups=False)

    assert len(found) == 1


# ── Groups ───────────────────────────────────────────────────────────────────


def test_group_membership_comes_from_the_same_token(db, tenant, connection):
    """**Microsoft Teams are Microsoft 365 groups**, so this needs no separate
    integration — which is what makes group membership a rule condition rather than
    a project."""
    tenant(
        users=[account("u1"), account("u2")],
        groups=[{"id": "g1", "displayName": "Phoenix Sales"}],
        members={"g1": [{"id": "u1"}]},
    )

    found = {p.external_id: p for p in microsoft.people(db, connection)}

    assert found["u1"].groups == ("Phoenix Sales",)
    assert found["u2"].groups == ()


def test_only_real_groups_are_asked_for(db, tenant, connection):
    """Unified groups — Teams and Microsoft 365 groups. Security groups and mail
    distribution lists would flood the rule dropdown with things nobody organises
    a leaderboard by."""
    graph = tenant(users=[account()], groups=[])

    microsoft.people(db, connection)

    groups_request = next(r for r in graph.asked if r.url.path.endswith("/v1.0/groups"))
    assert "Unified" in str(groups_request.url)


def test_one_unreadable_group_does_not_cost_the_whole_sync(db, tenant, connection):
    """Its rules simply match nobody this time round, rather than every person
    vanishing from the directory — which reconcile would read as the whole company
    leaving."""
    def broken_group(graph):
        def handler(request):
            if "/groups/g1/members" in request.url.path:
                return httpx.Response(500, json={"error": {"message": "busy"}})
            return graph(request)

        return handler

    tenant(
        handler=broken_group,
        users=[account("u1")],
        groups=[
            {"id": "g1", "displayName": "Broken"},
            {"id": "g2", "displayName": "Fine"},
        ],
        members={"g2": [{"id": "u1"}]},
    )

    found = microsoft.people(db, connection)

    assert found[0].groups == ("Fine",)


# ── Paging ───────────────────────────────────────────────────────────────────


def test_every_page_of_a_large_tenant_is_read(db, tenant, connection):
    """`@odata.nextLink` is a **complete URL** with its own query string, so it is
    requested as-is. Merging parameters into it would duplicate `$select` and
    produce a request Graph rejects."""
    pages = iter(
        [
            {
                "value": [account("u1")],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/users?$skiptoken=abc"
                ),
            },
            {"value": [account("u2")]},
        ]
    )

    def paged(graph):
        def handler(request):
            graph.asked.append(request)
            if request.url.path.endswith("/v1.0/users"):
                return httpx.Response(200, json=next(pages))
            return graph(request)

        return handler

    graph = tenant(handler=paged, users=[])

    found = microsoft.people(db, connection, with_groups=False)

    assert {p.external_id for p in found} == {"u1", "u2"}

    # And the follow-up carried *only* what the link already had. Merging our
    # parameters back in would send `$select` twice, which Graph rejects — so the
    # second request must not look like the first.
    second = [r for r in graph.asked if r.url.path.endswith("/v1.0/users")][1]
    assert dict(second.url.params) == {"$skiptoken": "abc"}


def test_the_largest_page_graph_allows_is_asked_for(db, tenant, connection):
    """Its default is far smaller, and a tenant of two thousand people would be
    twenty round trips instead of three."""
    graph = tenant(users=[account()])

    microsoft.people(db, connection, with_groups=False)

    users_request = next(r for r in graph.asked if r.url.path.endswith("/v1.0/users"))
    assert dict(users_request.url.params)["$top"] == "999"


# ── When Graph says no ───────────────────────────────────────────────────────


def test_a_403_names_the_permissions_rather_than_blaming_the_credential(db, tenant, connection, monkeypatch):
    """**The message this replaces sent people round a loop.** A 403 came back as
    "refused the credential — check it and reconnect", so the obvious response was
    to reconnect, which produces a working credential refused for exactly the same
    reason. The credential was never wrong; the app role was never consented to.
    """
    directory = tenant(users=[])

    def refuse(request):
        if request.url.path.endswith("/v1.0/users"):
            return httpx.Response(403, json={"error": {"message": "Insufficient."}})
        return None

    # `Graph` has no override hook, so the transport is replaced for this test.
    real = directory.__call__

    class Refusing:
        def __call__(self, request):
            answered = refuse(request)
            return answered if answered is not None else real(request)

    monkeypatch.setattr(microsoft.httpx, "Client", _client_with(Refusing()))

    with pytest.raises(microsoft.DirectoryProblem) as raised:
        microsoft.people(db, connection)

    said = str(raised.value)
    # **Only the permission that is actually required.** Naming the optional two
    # here sent an admin looking for three grants when one was missing, and made
    # a partial-but-working consent look like a failure.
    assert "User.Read.All" in said
    assert "GroupMember.Read.All" not in said
    # The page that fixes it, which is the half somebody has to act on.
    assert "adminconsent" in said
    # **And the trap that wasted an afternoon**: the delegated version of this
    # permission consents cleanly, shows green in Entra, and is invisible to a
    # client-credentials token. Consenting before re-running grants it again.
    assert "Delegated" in said
    assert "APPLICATION" in said
    assert connection.client_id in said
    # And emphatically not the advice that cannot work.
    assert "reconnect" not in said.lower()


def _client_with(handler):
    def build(*args, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return REAL_CLIENT(*args, **kw)

    return build


def test_a_401_still_says_to_check_the_credential(db, tenant, connection, monkeypatch):
    """The opposite case, kept apart on purpose: a rejected secret really does mean
    reconnect, and folding both into one message is what lost the distinction."""
    directory = tenant(users=[])
    real = directory.__call__

    class Rejecting:
        def __call__(self, request):
            if request.url.path.endswith("/v1.0/users"):
                return httpx.Response(401, json={"error": {"message": "nope"}})
            return real(request)

    monkeypatch.setattr(microsoft.httpx, "Client", _client_with(Rejecting()))

    with pytest.raises(Exception) as raised:
        microsoft.people(db, connection)

    assert "User.Read.All" not in str(raised.value)


def test_a_tenant_without_group_permission_still_syncs_everybody(db, tenant, monkeypatch):
    """**The permission this proved optional.** A working registration for the
    sibling product this was modelled on carries `User.Read.All` and not
    `GroupMember.Read.All` — so a 403 on groups has to cost group rules and
    nothing else. It used to kill the whole sync, trading every person in the
    tenant for one of the four things a rule can match on."""
    directory = tenant(users=[account("u1")])
    real = directory.__call__

    class NoGroups:
        def __call__(self, request):
            if request.url.path.endswith("/v1.0/groups"):
                return httpx.Response(403, json={"error": {"message": "Insufficient."}})
            return real(request)

    monkeypatch.setattr(microsoft.httpx, "Client", _client_with(NoGroups()))

    found = microsoft.people(db, connection_for())

    assert [p.email for p in found] == ["u1@acme.com"]
    # The one thing lost, and it is the only thing lost.
    assert found[0].groups == ()


def connection_for():
    from app.crypto import encrypt
    from app.models import OauthClient

    return OauthClient(
        organization_id=1,
        provider="microsoft",
        client_id="client",
        client_secret_encrypted=encrypt("shhh"),
        tenant_id="contoso.onmicrosoft.com",
    )


# ── Who counts as somebody who works here ────────────────────────────────────


def licensed(user_id="u1", **kwargs):
    return account(user_id, assignedLicenses=[{"skuId": "sku-1"}], **kwargs)


def unlicensed(user_id="u2", **kwargs):
    return account(user_id, assignedLicenses=[], **kwargs)


def test_unlicensed_accounts_are_kept_by_default(db, tenant):
    """**Off unless asked for.** It changes who a sync proposes, and a deployment
    already running should not silently start ignoring people."""
    tenant(users=[licensed("u1"), unlicensed("u2")])

    found = microsoft.people(db, connection_for())

    assert {p.external_id for p in found} == {"u1", "u2"}


def test_unlicensed_accounts_are_skipped_when_asked(db, tenant):
    """A licence is the closest thing a directory has to "this person works here".
    Without this, the approval queue for a tenant of six hundred fills with
    service accounts and shared mailboxes."""
    tenant(users=[licensed("u1"), unlicensed("u2")])
    connection = connection_for()
    connection.directory_ignore_unlicensed = True

    found = microsoft.people(db, connection)

    assert {p.external_id for p in found} == {"u1"}


def test_a_missing_licence_field_counts_as_unlicensed(db, tenant):
    """Graph omits the field rather than sending an empty list for some accounts,
    and treating absent as licensed would quietly keep exactly the objects this is
    meant to remove."""
    tenant(users=[account("u3")])
    connection = connection_for()
    connection.directory_ignore_unlicensed = True

    assert microsoft.people(db, connection) == []
