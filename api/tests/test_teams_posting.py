"""Posting announcements to a Teams channel picked from a list.

The other way to reach a channel: one account signs in, and any channel it is
in can be chosen instead of making a Workflows link inside it. What has to be
true: the same card is posted either way, a channel is only saved when the
account can see it, each refusal says what to do about it, the picker lists
what the account is in — and nothing here reaches Microsoft from the suite.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import announcements, crypto, providers, teams_account
from app.models import AnnouncementDelivery, AnnouncementDestination, Notification, OauthClient

def soon() -> datetime:
    """A moment just ahead of the real clock, worked out when asked.

    A queued delivery is due from the database's own now(), so a fixed date in
    the past finds nothing due — and a moment fixed when the file loads is in
    the past by the time a two-minute suite reaches it.
    """
    return datetime.now(UTC) + timedelta(minutes=1)


@pytest.fixture(autouse=True)
def _teams_on(db, org):
    """Microsoft Teams switched on — it is off for a new organization."""
    org.teams_enabled = True
    db.flush()


@pytest.fixture
def connection(db, org):
    row = OauthClient(
        organization_id=org.id, provider="microsoft", client_id="client",
        client_secret_encrypted=crypto.encrypt("s"), tenant_id="contoso.onmicrosoft.com",
        teams_post_refresh_token_encrypted=crypto.encrypt("refresh"),
        teams_post_connected_as="goalgetter@contoso.com",
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(teams_account, "access_token", lambda db, connection: "token")


class GraphPoster:
    def __init__(self, status=201):
        self.calls: list[tuple] = []
        self.status = status

    def __call__(self, token, team_id, channel_id, payload):
        self.calls.append((token, team_id, channel_id, payload))
        return httpx.Response(self.status)


def picked(db, org, **extra):
    row = AnnouncementDestination(
        organization_id=org.id, kind="teams", name="Closers", via="graph",
        team_external_id="team-1", channel_external_id="chan-1",
        channel_label="Metropolis Sales Team › Closers",
        events=list(announcements.DEFAULT_CHOICES),
        last_notification_id=announcements.newest_notification_id(db, org.id),
        **extra,
    )
    db.add(row)
    db.flush()
    return row


def win(db, org, person):
    row = Notification(
        organization_id=org.id, user_id=person.id, event_key="goal.achieved",
        subject_type="goal", subject_id=1, title="Calls this month achieved",
        about_name=person.full_name, about_user_id=person.id, about_team_id=person.team_id,
        link_url="/goals/1",
    )
    db.add(row)
    db.flush()
    return row


# ── Posting ─────────────────────────────────────────────────────────────────


def test_a_picked_channel_is_posted_to_through_graph(db, org, connection, signed_in, make_user):
    destination = picked(db, org)
    win(db, org, make_user("agent", name="Peter Parker"))
    poster = GraphPoster()
    now = soon()

    announcements.deliver(db, now=now, post_graph=poster)

    assert [(t, team, chan) for t, team, chan, _ in poster.calls] == [("token", "team-1", "chan-1")]
    assert destination.last_sent_at == now


def test_the_same_card_either_way(db, org, connection, signed_in, make_user):
    """Graph wants the card as a string in an attachment; it is the same card."""
    picked(db, org)
    row = win(db, org, make_user("agent", name="Peter Parker"))
    poster = GraphPoster()

    announcements.deliver(db, now=soon(), post_graph=poster)

    message = teams_account.message_of(poster.calls[0][3])
    assert json.loads(message["attachments"][0]["content"]) == announcements.card(row)["attachments"][0]["content"]
    assert message["body"]["content"] == '<attachment id="goalgetter"></attachment>'


def test_an_account_not_in_the_channel_is_told_to_join_it(db, org, connection, signed_in, make_user):
    destination = picked(db, org)
    win(db, org, make_user("agent", name="Peter Parker"))

    announcements.deliver(db, now=soon(), post_graph=GraphPoster(status=403))

    assert "goalgetter@contoso.com cannot post in Metropolis Sales Team › Closers" in destination.last_error
    assert "private" in destination.last_error


def test_a_deleted_channel_says_pick_another(db, org, connection, signed_in, make_user):
    destination = picked(db, org)
    win(db, org, make_user("agent", name="Peter Parker"))

    announcements.deliver(db, now=soon(), post_graph=GraphPoster(status=404))

    assert "Pick another channel" in destination.last_error


def test_no_account_is_one_error_not_one_per_win(db, org, connection, make_user, monkeypatch):
    def not_connected(db, connection):
        raise teams_account.NotConnected("No account is signed in to post to Teams.")

    monkeypatch.setattr(teams_account, "access_token", not_connected)
    destination = picked(db, org)
    win(db, org, make_user("agent", name="Peter Parker"))
    poster = GraphPoster()

    announcements.deliver(db, now=soon(), post_graph=poster)

    assert poster.calls == []
    assert "No account is signed in" in destination.last_error
    assert db.query(AnnouncementDelivery).one().status == "pending", "kept for when it is signed in"


def test_the_test_button_posts_through_graph(db, org, connection, signed_in):
    poster = GraphPoster()

    error = announcements.send_test(picked(db, org), db=db, post_graph=poster)

    assert error is None
    assert len(poster.calls) == 1


# ── Saving a picked channel ─────────────────────────────────────────────────


def test_a_picked_channel_is_checked_and_named(client, sign_in, db, org, connection, signed_in, make_user, monkeypatch):
    sign_in(make_user("admin"))
    monkeypatch.setattr(
        teams_account, "describe_channel", lambda token, team, chan: "Metropolis Sales Team › Closers"
    )

    body = client.post(
        "/api/announcements/destinations",
        json={"name": "Closers", "via": "graph", "team_external_id": "team-1", "channel_external_id": "chan-1"},
    ).json()

    assert body["via"] == "graph"
    assert body["channel_label"] == "Metropolis Sales Team › Closers"
    assert body["link_hint"] == ""


def test_a_channel_the_account_cannot_see_is_not_saved(client, sign_in, db, org, connection, signed_in, make_user, monkeypatch):
    sign_in(make_user("admin"))

    def unseen(token, team, chan):
        raise teams_account.GraphProblem("That Team or channel no longer exists, or this account is not in it.")

    monkeypatch.setattr(teams_account, "describe_channel", unseen)

    reply = client.post(
        "/api/announcements/destinations",
        json={"name": "Closers", "via": "graph", "team_external_id": "team-1", "channel_external_id": "x"},
    )

    assert reply.status_code == 422
    assert db.query(AnnouncementDestination).count() == 0


def test_a_workflows_channel_still_needs_its_link(client, sign_in, make_user):
    sign_in(make_user("admin"))

    reply = client.post("/api/announcements/destinations", json={"name": "Floor", "via": "workflow"})

    assert reply.status_code == 422
    assert "Workflows link" in reply.json()["detail"]


# ── The picker ───────────────────────────────────────────────────────────────


def test_the_picker_lists_the_accounts_teams_then_their_channels(client, sign_in, db, connection, signed_in, make_user, monkeypatch):
    sign_in(make_user("admin"))
    monkeypatch.setattr(teams_account, "joined_teams", lambda token: [{"id": "team-1", "name": "Metropolis Sales Team"}])
    monkeypatch.setattr(
        teams_account, "channels",
        lambda token, team: [{"id": "chan-1", "name": "Closers", "membership": "private"}],
    )

    assert client.get("/api/announcements/account/teams").json() == [{"id": "team-1", "name": "Metropolis Sales Team"}]
    assert client.get("/api/announcements/account/teams/team-1/channels").json()[0]["name"] == "Closers"


def test_the_account_says_who_posts(client, sign_in, connection, make_user):
    sign_in(make_user("admin"))

    body = client.get("/api/announcements/account").json()

    assert body == {"registered": True, "connected": True, "connected_as": "goalgetter@contoso.com"}


def test_signing_out_keeps_the_channels(client, sign_in, db, org, connection, make_user):
    sign_in(make_user("admin"))
    picked(db, org)

    client.delete("/api/announcements/account")

    assert connection.teams_post_refresh_token_encrypted is None
    assert db.query(AnnouncementDestination).count() == 1


def test_general_comes_first_like_teams_lists_it(monkeypatch):
    monkeypatch.setattr(
        teams_account, "_get",
        lambda token, path, params=None: {"value": [
            {"id": "b", "displayName": "Closers", "membershipType": "private"},
            {"id": "a", "displayName": "General", "membershipType": "standard"},
        ]},
    )

    assert [c["name"] for c in teams_account.channels("t", "team")] == ["General", "Closers"]


# ── The registration ─────────────────────────────────────────────────────────


def test_both_kinds_of_channel_permission_go_on_the_registration():
    """The app role reads every Team's channels; the delegated one is for the
    account that posts. Same label in Entra, two different permissions."""
    wanted = providers.permissions_for(providers.MICROSOFT, {"directory", "teams"}, "application")

    kinds = {p.kind for p, _ in wanted if p.name == "Channel.ReadBasic.All"}
    assert kinds == {"application", "delegated"}
    assert any(p.name == "ChannelMessage.Send" and p.kind == "delegated" for p, _ in wanted)


def test_the_microsoft_365_card_ticks_teams_and_email_when_on(client, sign_in, db, org, connection, make_user):
    sign_in(make_user("admin"))
    connection.mail_enabled = True
    connection.mail_from = "noreply@contoso.com"
    db.flush()

    microsoft = next(p for p in client.get("/api/integrations/oauth-clients").json() if p["provider"] == "microsoft")
    active = {c["key"]: c["active"] for c in microsoft["capabilities"]}

    assert active["teams"] is True
    assert active["email"] is True


def test_teams_off_is_unticked(client, sign_in, db, org, connection, make_user):
    sign_in(make_user("admin"))
    org.teams_enabled = False
    db.flush()

    microsoft = next(p for p in client.get("/api/integrations/oauth-clients").json() if p["provider"] == "microsoft")

    assert {c["key"]: c["active"] for c in microsoft["capabilities"]}["teams"] is False


def test_switched_off_nothing_is_posted(db, org, connection, signed_in, make_user):
    org.teams_enabled = False
    picked(db, org)
    win(db, org, make_user("agent", name="Peter Parker"))
    poster = GraphPoster()

    announcements.deliver(db, now=soon(), post_graph=poster)

    assert poster.calls == []

