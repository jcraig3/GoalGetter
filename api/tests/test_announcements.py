"""Posting wins into a Microsoft Teams channel.

The properties that matter are the ones a channel full of people would notice:
each win posted once however often the job runs, nothing from before the
channel was added, only the kinds of win it asked for and only whose it asked
for, a failure retried and then reported rather than lost or looped on — and
the server never posting anywhere but Microsoft's own webhook hosts.

Every post goes through a fake: no test touches the network.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import announcements, crypto
from app.models import AnnouncementDelivery, AnnouncementDestination, Notification, Office

LINK = "https://prod-12.westus.logic.azure.com/workflows/abc/triggers/manual/paths/invoke?sig=secret123"


@pytest.fixture(autouse=True)
def _teams_on(db, org):
    """Microsoft Teams switched on — it is off for a new organization."""
    org.teams_enabled = True
    db.flush()


class Poster:
    """Records what would have been posted, and answers as told."""

    def __init__(self, status=202, error=None):
        self.calls: list[tuple[str, dict]] = []
        self.status = status
        self.error = error

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        if self.error:
            raise self.error
        return httpx.Response(self.status)


@pytest.fixture
def world(db, org, make_team, make_user):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix)
    db.flush()
    team = make_team("Enterprise")
    team.office_id = phoenix.id
    other = make_team("SMB")
    db.flush()
    return {
        "phoenix": phoenix, "enterprise": team, "smb": other,
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", team, name="Peter Parker"),
        "clark": make_user("agent", other, name="Clark Kent"),
    }


def destination(db, org, **extra):
    fields = {
        "organization_id": org.id, "kind": "teams", "name": "Sales floor",
        "webhook_url": crypto.encrypt(LINK),
        "events": list(announcements.DEFAULT_CHOICES),
        "last_notification_id": announcements.newest_notification_id(db, org.id),
        **extra,
    }
    row = AnnouncementDestination(**fields)
    db.add(row)
    db.flush()
    return row


def win(db, org, person, event_key="goal.achieved", subject_id=1, title="Calls this month achieved", **extra):
    row = Notification(
        organization_id=org.id, user_id=person.id, event_key=event_key,
        subject_type="goal", subject_id=subject_id, title=title,
        about_name=person.full_name, about_user_id=person.id,
        about_team_id=person.team_id, link_url="/goals/1", **extra,
    )
    db.add(row)
    db.flush()
    return row


# -- Links -------------------------------------------------------------------


def test_a_teams_workflows_link_is_accepted():
    assert announcements.check_link("teams", LINK) == LINK


@pytest.mark.parametrize(
    "bad",
    [
        "http://prod-12.westus.logic.azure.com/workflows/abc",  # not https
        "https://example.com/hook",  # somewhere else
        "https://logic.azure.com.example.net/hook",  # a look-alike
        "https://10.0.0.5/internal",  # inside the network
    ],
)
def test_anything_but_microsofts_webhook_hosts_is_refused(bad):
    """**The server posts to whatever is stored**, so an unchecked link would
    let it be pointed at any address inside the network it runs on."""
    with pytest.raises(announcements.LinkProblem):
        announcements.check_link("teams", bad)


def test_the_refusal_says_how_to_make_a_proper_link():
    with pytest.raises(announcements.LinkProblem) as refused:
        announcements.check_link("teams", "https://example.com/hook")

    assert "Workflows" in str(refused.value)


def test_a_stored_link_is_shown_as_a_hint_not_the_link():
    """It carries its own signature: whoever holds it can post as the Workflow."""
    hint = announcements.hint_of(crypto.encrypt(LINK))

    assert "secret123" not in hint
    assert hint.startswith("prod-12.westus.logic.azure.com")


# -- What gets posted --------------------------------------------------------


def test_a_goal_hit_is_posted(db, org, world):
    destination(db, org)
    win(db, org, world["peter"])
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert len(poster.calls) == 1
    url, payload = poster.calls[0]
    assert url == LINK
    texts = [b["text"] for b in payload["attachments"][0]["content"]["body"]]
    assert texts[:2] == ["GOAL HIT", "Peter Parker"]


def test_the_card_links_back_to_goalgetter(db, org, world):
    destination(db, org)
    win(db, org, world["peter"])
    poster = Poster()

    announcements.deliver(db, post=poster)

    action = poster.calls[0][1]["attachments"][0]["content"]["actions"][0]
    assert action["url"].endswith("/goals/1")


def test_running_twice_posts_once(db, org, world):
    """The job runs every few minutes, and a channel that heard the same win
    twice would stop trusting the feed."""
    destination(db, org)
    win(db, org, world["peter"])
    poster = Poster()

    announcements.deliver(db, post=poster)
    announcements.deliver(db, post=poster)

    assert len(poster.calls) == 1


def test_one_win_reaching_many_people_is_one_post(db, org, world):
    """A team goal is eight notification rows and one thing that happened."""
    destination(db, org)
    win(db, org, world["peter"])
    win(db, org, world["clark"])  # same goal, same key

    poster = Poster()
    announcements.deliver(db, post=poster)

    assert len(poster.calls) == 1


def test_a_new_channel_is_not_flooded_with_old_wins(db, org, world):
    win(db, org, world["peter"], subject_id=7)
    destination(db, org)
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert poster.calls == []


def test_only_the_kinds_of_win_it_asked_for(db, org, world):
    destination(db, org, events=["recognition"])
    win(db, org, world["peter"])
    win(db, org, world["peter"], event_key="recognition", subject_id=2, title="Great call!")
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert len(poster.calls) == 1


def test_achievements_are_one_choice_for_every_rule(db, org, world):
    destination(db, org, events=["achievement"])
    win(db, org, world["peter"], event_key="achievement:4", subject_id=3, title="Big deal")
    win(db, org, world["peter"], event_key="achievement:9", subject_id=4, title="Five stars")
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert len(poster.calls) == 2


def test_nothing_private_is_ever_posted(db, org, world):
    """A channel is read by a whole team, so the rule that keeps "behind on
    your goal" off the wall keeps it out of the channel too — even if somebody
    managed to ask for it."""
    destination(db, org, events=["goal.period_ending"])
    win(db, org, world["peter"], event_key="goal.period_ending")
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert poster.calls == []


def test_only_whose_it_asked_for(db, org, world):
    destination(db, org, office_id=world["phoenix"].id)
    win(db, org, world["peter"], about_office_id=world["phoenix"].id, subject_id=1)
    win(db, org, world["clark"], subject_id=2)
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert [c[1]["attachments"][0]["content"]["body"][1]["text"] for c in poster.calls] == [
        "Peter Parker"
    ]


def test_a_switched_off_channel_posts_nothing(db, org, world):
    destination(db, org, enabled=False)
    win(db, org, world["peter"])
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert poster.calls == []


def test_typed_markdown_is_shown_as_typed(db, org, world):
    """An asterisk in "5* service" should not turn the rest of the card bold."""
    destination(db, org, events=["recognition"])
    win(db, org, world["peter"], event_key="recognition", title="5* service *today*")
    poster = Poster()

    announcements.deliver(db, post=poster)

    texts = [b["text"] for b in poster.calls[0][1]["attachments"][0]["content"]["body"]]
    assert "5\\* service \\*today\\*" in texts


# -- When it goes wrong ------------------------------------------------------


def test_a_failure_is_retried_later_and_said(db, org, world):
    row = destination(db, org)
    win(db, org, world["peter"])
    now = datetime.now(UTC)

    announcements.deliver(db, now=now, post=Poster(status=500))
    delivery = db.scalars(select(AnnouncementDelivery)).one()

    assert delivery.status == "retrying"
    assert delivery.next_attempt_at > now
    assert "500" in row.last_error


def test_it_is_not_retried_before_its_time(db, org, world):
    destination(db, org)
    win(db, org, world["peter"])
    now = datetime.now(UTC)
    announcements.deliver(db, now=now, post=Poster(status=500))

    again = Poster()
    announcements.deliver(db, now=now + timedelta(seconds=10), post=again)

    assert again.calls == []


def test_a_retry_that_succeeds_is_sent_once(db, org, world):
    destination(db, org)
    win(db, org, world["peter"])
    now = datetime.now(UTC)
    announcements.deliver(db, now=now, post=Poster(status=500))

    later = Poster()
    announcements.deliver(db, now=now + timedelta(hours=1), post=later)

    assert len(later.calls) == 1
    assert db.scalars(select(AnnouncementDelivery)).one().status == "sent"


def test_it_gives_up_eventually_rather_than_trying_forever(db, org, world):
    destination(db, org)
    win(db, org, world["peter"])
    now = datetime.now(UTC)
    for hours in range(10):
        announcements.deliver(db, now=now + timedelta(hours=hours * 2), post=Poster(status=500))

    assert db.scalars(select(AnnouncementDelivery)).one().status == "gave_up"


def test_a_deleted_workflow_says_to_make_a_new_link(db, org, world):
    row = destination(db, org)
    win(db, org, world["peter"])

    announcements.deliver(db, post=Poster(status=404))

    assert "make a new link" in row.last_error


def test_an_unreachable_channel_is_said_in_words(db, org, world):
    row = destination(db, org)
    win(db, org, world["peter"])

    announcements.deliver(db, post=Poster(error=httpx.ConnectError("no route")))

    assert "Could not reach" in row.last_error


def test_a_stored_link_that_no_longer_passes_is_never_posted_to(db, org, world):
    """Nothing is posted to an address this code would refuse to save."""
    destination(db, org)
    row = db.scalars(select(AnnouncementDestination)).one()
    row.webhook_url = crypto.encrypt("https://example.com/hook")
    win(db, org, world["peter"])
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert poster.calls == []


# -- Over the wire -----------------------------------------------------------


def add(client, **body):
    return client.post(
        "/api/announcements/destinations",
        json={"name": "Sales floor", "webhook_url": LINK, **body},
    )


def test_an_admin_adds_a_channel(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = add(client)

    assert reply.status_code == 201, reply.json()
    assert "secret123" not in reply.text


def test_the_stored_link_is_encrypted(client, db, world, sign_in):
    sign_in(world["admin"])
    add(client)

    row = db.scalars(select(AnnouncementDestination)).one()

    assert "logic.azure.com" not in row.webhook_url


def test_a_bad_link_is_refused_when_saved(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = add(client, webhook_url="https://example.com/hook")

    assert reply.status_code == 422
    assert "Workflows" in reply.json()["detail"]


def test_changing_the_name_keeps_the_link(client, db, world, sign_in):
    sign_in(world["admin"])
    made = add(client).json()

    client.patch(f"/api/announcements/destinations/{made['id']}", json={"name": "Floor"})

    row = db.scalars(select(AnnouncementDestination)).one()
    assert crypto.decrypt(row.webhook_url) == LINK


def test_one_office_or_one_team_not_both(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = add(client, office_id=world["phoenix"].id, team_id=world["smb"].id)

    assert reply.status_code == 422


def test_nothing_to_announce_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    assert add(client, events=[]).status_code == 422


def test_a_manager_cannot_add_one(client, db, world, sign_in, make_user):
    sign_in(make_user("manager", world["enterprise"], name="Manager"))

    assert add(client).status_code == 403


def test_the_list_offers_the_choices_and_says_when_one_is_failing(
    client, db, org, world, sign_in
):
    sign_in(world["admin"])
    add(client)
    row = db.scalars(select(AnnouncementDestination)).one()
    row.last_error, row.last_error_at = "The channel answered 500.", datetime.now(UTC)
    db.commit()

    body = client.get("/api/announcements/destinations").json()

    assert {c["key"] for c in body["choices"]} >= {"goal.achieved", "recognition", "wheel.won"}
    assert body["destinations"][0]["failing"] is True


def test_the_test_button_posts_one_card(client, db, world, sign_in, monkeypatch):
    sign_in(world["admin"])
    made = add(client).json()
    poster = Poster()
    monkeypatch.setattr(announcements, "_post", poster)

    reply = client.post(f"/api/announcements/destinations/{made['id']}/test")

    assert reply.json() == {"ok": True, "error": None}
    assert len(poster.calls) == 1


# -- Switching it off --------------------------------------------------------


def test_the_master_switch_pauses_every_channel(db, org, world):
    destination(db, org)
    org.teams_enabled = False
    win(db, org, world["peter"])
    poster = Poster()

    announcements.deliver(db, post=poster)

    assert poster.calls == []


def test_resuming_starts_from_now_rather_than_a_burst(db, org, world):
    """**A pause does not save wins up.** A week of them arriving at once would
    be worse than missing them."""
    destination(db, org)
    org.teams_enabled = False
    win(db, org, world["peter"], subject_id=1)
    announcements.deliver(db, post=Poster())

    announcements.resume(db, org.id)
    org.teams_enabled = True
    poster = Poster()
    announcements.deliver(db, post=poster)

    assert poster.calls == []


def test_something_queued_before_a_pause_is_dropped_on_resume(db, org, world):
    destination(db, org)
    win(db, org, world["peter"])
    announcements.deliver(db, post=Poster(status=500))  # queued, retrying

    announcements.resume(db, org.id)

    assert db.scalars(select(AnnouncementDelivery)).one().status == "gave_up"


def test_the_switch_over_the_wire(client, db, org, world, sign_in):
    sign_in(world["admin"])

    body = client.put("/api/announcements/enabled", json={"on": False}).json()

    assert body["enabled"] is False
    db.refresh(org)
    assert org.teams_enabled is False


def test_one_channel_switched_off_in_one_press(client, db, world, sign_in):
    sign_in(world["admin"])
    made = add(client).json()

    reply = client.put(f"/api/announcements/destinations/{made['id']}/enabled", json={"on": False})

    assert reply.json()["enabled"] is False


def test_a_manager_cannot_pause_posting(client, db, world, sign_in, make_user):
    sign_in(make_user("manager", world["enterprise"], name="Manager"))

    assert client.put("/api/announcements/enabled", json={"on": False}).status_code == 403
