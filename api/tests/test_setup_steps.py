"""The first-wall checklist on Home.

Each step is a question about the data, so it cannot say done when it is not,
and it finishes itself when the work is done anywhere in the app.
"""

from datetime import UTC, datetime

import pytest

from app.models import Channel, ChannelScreen, DataSource, Display, Leaderboard


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Alex Morgan"))


def checklist(client):
    return {s["key"]: s["done"] for s in client.get("/api/dashboard").json()["setup"]}


def test_a_new_deployment_has_everything_still_to_do_except_people(client, admin):
    # Nobody here looks like a printer, so there is nothing to hide.
    assert checklist(client) == {
        "data": False,
        "people": True,
        "teams": False,
        "board": False,
        "channel": False,
        "tv": False,
    }


def test_each_step_ticks_itself_from_what_exists(
    client, db, org, admin, make_user, make_team, make_metric
):
    db.add(DataSource(organization_id=org.id, name="CRM", connector="webhook",
                      activated_at=datetime.now(UTC)))
    make_user("agent", make_team(), name="Peter Parker")
    metric = make_metric()
    db.add(Leaderboard(organization_id=org.id, name="Deals", metric_definition_id=metric.id,
                       period_type="month"))
    channel = Channel(organization_id=org.id, name="Floor")
    db.add(channel)
    db.flush()
    db.add(ChannelScreen(channel_id=channel.id, position=0, kind="message",
                         title="Hello", dwell_seconds=20))
    db.add(Display(organization_id=org.id, name="TV", channel_id=channel.id,
                   token="t" * 40, last_seen_at=datetime.now(UTC)))
    db.flush()

    assert all(checklist(client).values())


def test_a_printer_in_the_directory_leaves_people_to_do(client, admin, make_user):
    make_user("agent", name="MFP 3100")

    steps = client.get("/api/dashboard").json()["setup"]
    people = next(s for s in steps if s["key"] == "people")

    assert people["done"] is False
    assert people["detail"] == "1 account looks like a device or a mailbox"


def test_a_tv_link_nobody_opened_is_not_a_connected_tv(client, db, org, admin):
    channel = Channel(organization_id=org.id, name="Floor")
    db.add(channel)
    db.flush()
    db.add(Display(organization_id=org.id, name="TV", channel_id=channel.id, token="u" * 40))
    db.flush()

    assert checklist(client)["tv"] is False


def test_only_an_admin_gets_the_checklist(client, make_user, sign_in):
    sign_in(make_user("manager"))

    assert client.get("/api/dashboard").json()["setup"] is None
