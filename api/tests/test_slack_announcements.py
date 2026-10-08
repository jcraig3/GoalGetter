"""Posting wins into Slack channels.

What has to be true: only Slack's own webhook host is accepted; a win is posted
as a Slack message, with anything typed escaped so it cannot ping a channel;
the Microsoft Teams switch does not pause Slack; a refused post says what to
do; and nothing reaches Slack from the suite.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import announcements, crypto
from app.models import AnnouncementDestination, Notification

LINK = "https://hooks.slack.com/services/T000/B000/secret123"


class Poster:
    def __init__(self, status=200):
        self.calls: list[tuple[str, dict]] = []
        self.status = status

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        return httpx.Response(self.status)


def soon():
    return datetime.now(UTC) + timedelta(minutes=1)


@pytest.fixture
def peter(make_user):
    return make_user("agent", name="Peter Parker")


def slack(db, org, **extra):
    row = AnnouncementDestination(
        organization_id=org.id, kind="slack", name="#sales", via="workflow",
        webhook_url=crypto.encrypt(LINK), events=list(announcements.DEFAULT_CHOICES),
        last_notification_id=announcements.newest_notification_id(db, org.id), **extra,
    )
    db.add(row)
    db.flush()
    return row


def win(db, org, person, **extra):
    fields = dict(
        organization_id=org.id, user_id=person.id, event_key="goal.achieved",
        subject_type="goal", subject_id=1, title="Calls this month achieved",
        about_name=person.full_name, about_user_id=person.id, link_url="/goals/1",
    )
    fields.update(extra)
    row = Notification(**fields)
    db.add(row)
    db.flush()
    return row


def test_only_slacks_own_webhook_host_is_accepted():
    assert announcements.check_link("slack", LINK) == LINK
    for bad in (
        "https://hooks.slack.com.example.net/services/x",
        "https://example.com/services/x",
        "https://hooks.slack.com/api/other",
        "http://hooks.slack.com/services/x",
    ):
        with pytest.raises(announcements.LinkProblem):
            announcements.check_link("slack", bad)


def test_a_win_is_posted_as_a_slack_message(db, org, peter):
    slack(db, org)
    win(db, org, peter)
    poster = Poster()

    announcements.deliver(db, now=soon(), post=poster)

    [(url, payload)] = poster.calls
    assert url == LINK
    assert payload["text"].startswith("Goal hit — Peter Parker")
    assert "*Peter Parker*" in payload["blocks"][0]["text"]["text"]
    assert payload["blocks"][1]["elements"][0]["url"].endswith("/goals/1")


def test_typed_text_cannot_ping_a_channel(db, org, peter):
    slack(db, org)
    win(db, org, peter, event_key="recognition", title="Thanks!", body="<!channel> legend")
    poster = Poster()

    announcements.deliver(db, now=soon(), post=poster)

    text = poster.calls[0][1]["blocks"][0]["text"]["text"]
    assert "<!channel>" not in text
    assert "&lt;!channel&gt;" in text


def test_the_teams_switch_does_not_pause_slack(db, org, peter):
    org.teams_enabled = False
    slack(db, org)
    win(db, org, peter)
    poster = Poster()

    announcements.deliver(db, now=soon(), post=poster)

    assert len(poster.calls) == 1


def test_a_removed_webhook_says_make_a_new_one(db, org, peter):
    destination = slack(db, org)
    win(db, org, peter)

    announcements.deliver(db, now=soon(), post=Poster(status=404))

    assert "make a new webhook link" in destination.last_error


def test_the_test_button_says_hello_in_slack(db, org):
    poster = Poster()

    assert announcements.send_test(slack(db, org), post=poster) is None
    assert "Connected" in poster.calls[0][1]["blocks"][0]["text"]["text"]


# ── The API ─────────────────────────────────────────────────────────────────


def test_a_slack_channel_is_added_with_its_link(client, sign_in, make_user):
    sign_in(make_user("admin"))

    made = client.post(
        "/api/announcements/destinations",
        json={"kind": "slack", "name": "#sales", "webhook_url": LINK},
    )

    assert made.status_code == 201, made.text
    assert made.json()["kind"] == "slack"
    assert made.json()["link_hint"] == "hooks.slack.com/…ret123"


def test_slack_cannot_be_picked_through_microsoft(client, sign_in, make_user):
    sign_in(make_user("admin"))

    reply = client.post(
        "/api/announcements/destinations",
        json={"kind": "slack", "name": "#sales", "via": "graph", "team_external_id": "t", "channel_external_id": "c"},
    )

    assert reply.status_code == 422


def test_each_card_lists_its_own_kind(client, sign_in, db, org, make_user):
    sign_in(make_user("admin"))
    slack(db, org)
    db.add(AnnouncementDestination(
        organization_id=org.id, kind="teams", name="Floor", via="workflow",
        webhook_url=crypto.encrypt("https://prod-1.westus.logic.azure.com/workflows/x"), events=["recognition"],
    ))
    db.flush()

    names = [d["name"] for d in client.get("/api/announcements/destinations?kind=slack").json()["destinations"]]

    assert names == ["#sales"]
