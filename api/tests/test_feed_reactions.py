"""Reactions and comments on the recognition feed (6.15)."""

from datetime import date

import pytest
from sqlalchemy import select

from app import events, notifications
from app.models import FeedComment, FeedReaction, Notification


@pytest.fixture
def world(db, org, make_team, make_user):
    team = make_team("Sales")
    return {
        "team": team,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", team, name="Manager"),
        "alice": make_user("agent", team, name="Alice"),
        "bob": make_user("agent", team, name="Bob"),
        "cat": make_user("agent", team, name="Cat"),
    }


def shout(client, world, sign_in, about="alice"):
    sign_in(world["manager"])
    response = client.post(
        "/api/recognition", json={"user_id": world[about].id, "message": "Saved the Henderson account"}
    )
    assert response.status_code == 201, response.json()
    return client.get("/api/achievements").json()[0]


def bell(client, person, sign_in):
    sign_in(person)
    return client.get("/api/notifications").json()["notifications"]


def test_anybody_can_react_and_take_it_back(client, db, world, sign_in):
    entry = shout(client, world, sign_in)

    sign_in(world["bob"])
    thread = client.post(f"/api/feed/{entry['id']}/reactions", json={"reaction": "clap"}).json()
    assert thread["reactions"] == [{"reaction": "clap", "count": 1, "mine": True, "names": ["Bob"]}]

    sign_in(world["cat"])
    client.post(f"/api/feed/{entry['id']}/reactions", json={"reaction": "clap"})
    feed = client.get("/api/achievements").json()
    assert feed[0]["reactions"][0]["count"] == 2
    assert feed[0]["reactions"][0]["mine"] is True

    # The same button again takes it back.
    again = client.post(f"/api/feed/{entry['id']}/reactions", json={"reaction": "clap"}).json()
    assert again["reactions"][0]["count"] == 1
    assert again["reactions"][0]["mine"] is False


def test_only_the_offered_reactions(client, db, world, sign_in):
    entry = shout(client, world, sign_in)
    sign_in(world["bob"])
    response = client.post(f"/api/feed/{entry['id']}/reactions", json={"reaction": "poop"})
    assert response.status_code == 422


def test_a_comment_reaches_the_person_and_the_author_not_the_commenter(
    client, db, world, sign_in
):
    entry = shout(client, world, sign_in)

    sign_in(world["bob"])
    thread = client.post(
        f"/api/feed/{entry['id']}/comments", json={"body": "  Nobody   deserved it more  "}
    ).json()
    assert [c["body"] for c in thread["comments"]] == ["Nobody deserved it more"]
    assert thread["comments"][0]["author_name"] == "Bob"

    def comments_for(person):
        return [
            n for n in bell(client, person, sign_in)
            if n["event_key"] == events.FEED_COMMENT.key
        ]

    assert comments_for(world["alice"])[0]["title"] == "Bob commented: “Nobody deserved it more”"
    assert len(comments_for(world["manager"])) == 1
    assert comments_for(world["bob"]) == []


def test_a_comment_stays_off_the_wall(client, db, world, sign_in):
    """A conversation, not news."""
    assert events.is_public(events.FEED_COMMENT.key) is False


def test_a_comment_can_be_taken_back_by_its_author_or_an_admin(client, db, world, sign_in):
    entry = shout(client, world, sign_in)
    sign_in(world["bob"])
    first = client.post(f"/api/feed/{entry['id']}/comments", json={"body": "One"}).json()["comments"][0]
    second = client.post(f"/api/feed/{entry['id']}/comments", json={"body": "Two"}).json()["comments"][1]

    sign_in(world["cat"])
    assert client.delete(f"/api/feed/comments/{first['id']}").status_code == 404

    sign_in(world["bob"])
    assert client.delete(f"/api/feed/comments/{first['id']}").status_code == 200

    sign_in(world["admin"])
    left = client.delete(f"/api/feed/comments/{second['id']}").json()
    assert left["comments"] == []


def test_a_team_win_is_one_thread_whichever_row_the_feed_shows(client, db, org, world, sign_in):
    """A team hitting its goal is a notification per member, shown as one
    entry. Reacting through any member's row lands on the same entry."""
    rows = []
    for person in (world["alice"], world["bob"]):
        notifications.emit(
            db, org_id=org.id, user_id=person.id, event=events.GOAL_ACHIEVED,
            subject_type="goal", subject_id=77, period_anchor=date(2026, 10, 1),
            title="Sales hit their target", about_name="Sales",
        )
        rows.append(
            db.scalar(
                select(Notification.id).where(
                    Notification.user_id == person.id, Notification.subject_id == 77
                )
            )
        )
    db.commit()

    sign_in(world["cat"])
    client.post(f"/api/feed/{rows[0]}/reactions", json={"reaction": "fire"})
    thread = client.post(f"/api/feed/{rows[1]}/reactions", json={"reaction": "party"}).json()
    assert [r["reaction"] for r in thread["reactions"]] == ["fire", "party"]

    entry = next(e for e in client.get("/api/achievements").json() if e["title"] == "Sales hit their target")
    assert [r["reaction"] for r in entry["reactions"]] == ["fire", "party"]


def test_a_private_event_cannot_be_reacted_to(client, db, org, world, sign_in):
    notifications.emit(
        db, org_id=org.id, user_id=world["alice"].id, event=events.GOAL_PERIOD_ENDING,
        subject_type="goal", subject_id=5, title="Your goal ends Friday",
    )
    db.commit()
    row = db.scalar(select(Notification.id).where(Notification.subject_id == 5))
    sign_in(world["bob"])
    assert client.post(f"/api/feed/{row}/reactions", json={"reaction": "clap"}).status_code == 404


def test_deleting_a_shout_out_takes_its_thread_with_it(client, db, world, sign_in):
    entry = shout(client, world, sign_in)
    sign_in(world["bob"])
    client.post(f"/api/feed/{entry['id']}/reactions", json={"reaction": "heart"})
    client.post(f"/api/feed/{entry['id']}/comments", json={"body": "Well done"})

    sign_in(world["manager"])
    assert client.delete(f"/api/recognition/{entry['id']}").status_code == 204
    assert db.scalars(select(FeedReaction)).all() == []
    assert db.scalars(select(FeedComment)).all() == []
