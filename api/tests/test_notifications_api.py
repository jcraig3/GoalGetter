"""The notification centre.

Scope here is the WHERE clause rather than a permission rule: the recipient is
a column, so there is no version of these endpoints that reads somebody else's.
Most of what follows is checking that.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import events, notifications
from app.models import Notification

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user):
    enterprise = make_team("Enterprise")
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
    }


def give(db, org, user, *, title="Something happened", subject_id=1, author=None,
         event=events.GOAL_ACHIEVED):
    assert notifications.emit(
        db,
        org_id=org.id,
        user_id=user.id,
        event=event,
        subject_type="goal",
        subject_id=subject_id,
        period_anchor=WHEN.date(),
        title=title,
        created_by_user_id=author.id if author else None,
    )
    db.commit()


def feed(client):
    response = client.get("/api/notifications")
    assert response.status_code == 200, response.json()
    return response.json()


# ── Reading your own ─────────────────────────────────────────────────────────


def test_you_see_your_own(client, db, org, world, sign_in):
    give(db, org, world["alice"], title="You hit your target")
    sign_in(world["alice"])

    body = feed(client)
    assert [n["title"] for n in body["notifications"]] == ["You hit your target"]
    assert body["unread"] == 1


def test_you_never_see_anybody_elses(client, db, org, world, sign_in):
    """The recipient is a column, so this is the query rather than a rule."""
    give(db, org, world["bob"], title="Bob's business")
    sign_in(world["alice"])

    body = feed(client)
    assert body["notifications"] == []
    assert body["unread"] == 0


def test_an_admin_has_no_special_access(client, db, org, world, sign_in):
    """There is no capability for this. An admin reading somebody's bell would
    be reading their mail."""
    give(db, org, world["alice"], title="Alice's business")
    sign_in(world["admin"])
    assert feed(client)["notifications"] == []


def test_newest_first(client, db, org, world, sign_in):
    give(db, org, world["alice"], title="Older", subject_id=1)
    give(db, org, world["alice"], title="Newer", subject_id=2)
    sign_in(world["alice"])
    assert [n["title"] for n in feed(client)["notifications"]] == ["Newer", "Older"]


def test_signing_out_is_required(client, db, org, world):
    assert client.get("/api/notifications").status_code == 401


# ── Marking read ─────────────────────────────────────────────────────────────


def test_marking_one_read_clears_it_from_the_count(client, db, org, world, sign_in):
    give(db, org, world["alice"])
    sign_in(world["alice"])

    first = feed(client)["notifications"][0]
    assert client.post(f"/api/notifications/{first['id']}/read").status_code == 200

    assert feed(client)["unread"] == 0


def test_reading_something_twice_does_not_move_when_it_was_seen(
    client, db, org, world, sign_in
):
    """Re-opening the panel must not rewrite history."""
    give(db, org, world["alice"])
    sign_in(world["alice"])
    target = feed(client)["notifications"][0]["id"]

    first = client.post(f"/api/notifications/{target}/read").json()["read_at"]
    second = client.post(f"/api/notifications/{target}/read").json()["read_at"]

    assert first == second


def test_you_cannot_mark_somebody_elses_read(client, db, org, world, sign_in):
    """404 rather than 403 — a 403 would confirm it exists."""
    give(db, org, world["bob"])
    target = db.scalar(select(Notification.id))

    sign_in(world["alice"])
    assert client.post(f"/api/notifications/{target}/read").status_code == 404
    assert db.get(Notification, target).read_at is None


def test_mark_all_read_clears_everything(client, db, org, world, sign_in):
    for n in range(5):
        give(db, org, world["alice"], subject_id=n)
    sign_in(world["alice"])

    assert client.post("/api/notifications/read-all").status_code == 204
    assert feed(client)["unread"] == 0


def test_mark_all_read_is_only_yours(client, db, org, world, sign_in):
    give(db, org, world["bob"])
    theirs = db.scalar(select(Notification.id))

    sign_in(world["alice"])
    client.post("/api/notifications/read-all")

    db.expire_all()
    assert db.get(Notification, theirs).read_at is None


def test_unread_only_filters_the_list_but_not_the_count(
    client, db, org, world, sign_in
):
    give(db, org, world["alice"], subject_id=1)
    give(db, org, world["alice"], subject_id=2)
    sign_in(world["alice"])

    first = feed(client)["notifications"][0]["id"]
    client.post(f"/api/notifications/{first}/read")

    response = client.get("/api/notifications?unread_only=true").json()
    assert len(response["notifications"]) == 1
    assert response["unread"] == 1


# ── What the panel is told ───────────────────────────────────────────────────


def test_a_celebratory_event_is_flagged(client, db, org, world, sign_in):
    """Resolved from the catalogue rather than stored per row, so changing what
    celebrates needs no backfill."""
    give(db, org, world["alice"], event=events.GOAL_ACHIEVED)
    sign_in(world["alice"])
    assert feed(client)["notifications"][0]["celebrate"] is True


def test_a_routine_event_is_not(client, db, org, world, sign_in):
    give(db, org, world["alice"], event=events.GOAL_ASSIGNED)
    sign_in(world["alice"])
    assert feed(client)["notifications"][0]["celebrate"] is False


def test_an_authored_notification_names_its_author(client, db, org, world, sign_in):
    """"Manager recognised you" reads very differently from an announcement
    that appeared on its own."""
    give(db, org, world["alice"], event=events.RECOGNITION, author=world["manager"])
    sign_in(world["alice"])
    assert feed(client)["notifications"][0]["from_name"] == "Manager"


def test_a_detected_notification_has_no_author(client, db, org, world, sign_in):
    give(db, org, world["alice"])
    sign_in(world["alice"])
    assert feed(client)["notifications"][0]["from_name"] is None


def test_an_unknown_event_still_renders(client, db, org, world, sign_in):
    """A notification written by a newer API must not break an older bell."""
    db.add(
        Notification(
            organization_id=org.id,
            user_id=world["alice"].id,
            event_key="something.invented.later",
            subject_type="goal",
            subject_id=1,
            title="From the future",
        )
    )
    db.commit()

    sign_in(world["alice"])
    body = feed(client)
    assert body["notifications"][0]["title"] == "From the future"
    assert body["notifications"][0]["celebrate"] is False


# ── Retention ────────────────────────────────────────────────────────────────


def test_old_notifications_are_pruned(db, org, world):
    give(db, org, world["alice"], subject_id=1)
    stale = db.scalar(select(Notification))
    stale.created_at = datetime.now(UTC) - timedelta(days=events.RETENTION_DAYS + 1)
    db.commit()

    assert notifications.prune(db) == 1
    db.commit()
    assert db.scalars(select(Notification)).all() == []


def test_recent_notifications_survive_a_prune(db, org, world):
    give(db, org, world["alice"], subject_id=1)
    assert notifications.prune(db) == 0
    assert len(db.scalars(select(Notification)).all()) == 1


def test_the_retention_window_is_ninety_days(db, org, world):
    """Absolute ages, not `RETENTION_DAYS ± 1`.

    The other prune tests express the *rule* and move with the constant, so
    they would pass just as happily if the window were widened to a decade —
    which a mutation proved. This one pins the number, because how long a feed
    keeps things is a product decision rather than an implementation detail.
    """
    for age, subject_id in ((100, 1), (30, 2)):
        give(db, org, world["alice"], subject_id=subject_id)
        row = db.scalars(
            select(Notification).where(Notification.subject_id == subject_id)
        ).one()
        row.created_at = datetime.now(UTC) - timedelta(days=age)
    db.commit()

    assert notifications.prune(db) == 1
    db.commit()

    survivors = db.scalars(select(Notification.subject_id)).all()
    assert list(survivors) == [2]


def test_pruning_takes_unread_ones_too(db, org, world):
    """An unread notification from three months ago is not something anybody is
    about to act on. Keeping it would leave a badge that can only be cleared by
    reading rows nobody wants."""
    give(db, org, world["alice"], subject_id=1)
    stale = db.scalar(select(Notification))
    stale.created_at = datetime.now(UTC) - timedelta(days=events.RETENTION_DAYS + 1)
    assert stale.read_at is None
    db.commit()

    assert notifications.prune(db) == 1


# ── Preferences ──────────────────────────────────────────────────────────────


def prefs(client):
    response = client.get("/api/notifications/preferences")
    assert response.status_code == 200, response.json()
    return {p["event_key"]: p["enabled"] for p in response.json()}


def set_prefs(client, enabled):
    response = client.put(
        "/api/notifications/preferences", json={"enabled": list(enabled)}
    )
    assert response.status_code == 200, response.json()
    return {p["event_key"]: p["enabled"] for p in response.json()}


def test_everything_is_on_for_somebody_who_never_looked(client, db, world, sign_in):
    """Built from the catalogue, not from the table. Somebody who has never
    opened the settings has no rows at all."""
    sign_in(world["alice"])
    current = prefs(client)
    assert current
    assert all(current.values())


def test_muting_hides_it_from_your_bell(client, db, org, world, sign_in):
    give(db, org, world["alice"], event=events.GOAL_ASSIGNED, subject_id=1)
    give(db, org, world["alice"], event=events.GOAL_ACHIEVED, subject_id=2)
    sign_in(world["alice"])
    assert feed(client)["unread"] == 2

    set_prefs(client, [events.GOAL_ACHIEVED.key])

    body = feed(client)
    assert [n["event_key"] for n in body["notifications"]] == ["goal.achieved"]
    assert body["unread"] == 1


def test_muting_does_not_delete_anything(client, db, org, world, sign_in):
    """A preference filters at read. The row is the organization's record that
    something happened, and the same rows feed the achievements feed and the
    wall screens — muting your own achievement must not remove you from what
    everybody else celebrates."""
    give(db, org, world["alice"], event=events.GOAL_ACHIEVED)
    sign_in(world["alice"])
    set_prefs(client, [])

    assert feed(client)["notifications"] == []
    assert len(db.scalars(select(Notification)).all()) == 1


def test_unmuting_shows_what_you_missed(client, db, org, world, sign_in):
    sign_in(world["alice"])
    set_prefs(client, [])
    give(db, org, world["alice"], event=events.GOAL_ACHIEVED)
    assert feed(client)["notifications"] == []

    set_prefs(client, [events.GOAL_ACHIEVED.key])
    assert len(feed(client)["notifications"]) == 1


def test_preferences_are_per_person(client, db, org, world, sign_in):
    give(db, org, world["alice"], event=events.GOAL_ACHIEVED)
    give(db, org, world["bob"], event=events.GOAL_ACHIEVED)

    sign_in(world["alice"])
    set_prefs(client, [])
    assert feed(client)["notifications"] == []

    sign_in(world["bob"])
    assert len(feed(client)["notifications"]) == 1


def test_the_whole_set_is_replaced_not_merged(client, db, world, sign_in):
    """A toggle list has no meaningful partial state, so PUT replaces. That
    also makes two toggles clicked quickly order-independent."""
    sign_in(world["alice"])
    set_prefs(client, [events.GOAL_ACHIEVED.key])
    assert prefs(client) == {
        "goal.achieved": True,
        "goal.assigned": False,
        "goal.period_ending": False,
        "recognition": False,
        "feed.comment": False,
        "competition.started": False,
        "competition.finished": False,
        "competition.won": False,
    }

    set_prefs(client, [events.GOAL_ASSIGNED.key])
    assert prefs(client)["goal.achieved"] is False
    assert prefs(client)["goal.assigned"] is True


def test_an_unknown_event_key_is_ignored_not_rejected(client, db, world, sign_in):
    """A client one deploy behind must not get a 422 for sending a key the API
    has since renamed."""
    sign_in(world["alice"])
    current = set_prefs(client, [events.GOAL_ACHIEVED.key, "invented.later"])
    assert current["goal.achieved"] is True
    assert "invented.later" not in current


def test_preferences_need_a_session(client, db, world):
    assert client.get("/api/notifications/preferences").status_code == 401
    assert client.put("/api/notifications/preferences", json={"enabled": []}).status_code == 401


# ── Celebrations ─────────────────────────────────────────────────────────────


def test_a_celebration_is_recorded_separately_from_being_read(
    client, db, org, world, sign_in
):
    """Two different questions. "Have you seen it in the list" governs the
    badge; "have we already thrown confetti at you" governs the overlay."""
    give(db, org, world["alice"])
    sign_in(world["alice"])
    target = feed(client)["notifications"][0]["id"]

    assert client.post(f"/api/notifications/{target}/celebrated").status_code == 204

    shown = feed(client)["notifications"][0]
    assert shown["celebrated_at"] is not None
    assert shown["read_at"] is None
    assert feed(client)["unread"] == 1


def test_reading_does_not_count_as_celebrating(client, db, org, world, sign_in):
    """Opening the bell must not cancel a celebration somebody never saw."""
    give(db, org, world["alice"])
    sign_in(world["alice"])
    target = feed(client)["notifications"][0]["id"]

    client.post(f"/api/notifications/{target}/read")

    assert feed(client)["notifications"][0]["celebrated_at"] is None


def test_celebrating_twice_does_not_move_the_timestamp(
    client, db, org, world, sign_in
):
    """A repeated call would otherwise look like a second celebration."""
    give(db, org, world["alice"])
    sign_in(world["alice"])
    target = feed(client)["notifications"][0]["id"]

    client.post(f"/api/notifications/{target}/celebrated")
    first = feed(client)["notifications"][0]["celebrated_at"]
    client.post(f"/api/notifications/{target}/celebrated")

    assert feed(client)["notifications"][0]["celebrated_at"] == first


def test_you_cannot_celebrate_somebody_elses(client, db, org, world, sign_in):
    give(db, org, world["bob"])
    target = db.scalar(select(Notification.id))

    sign_in(world["alice"])
    assert client.post(f"/api/notifications/{target}/celebrated").status_code == 404
    assert db.get(Notification, target).celebrated_at is None


def test_competition_events_can_be_turned_off(client, db, world, sign_in):
    """QA-38: they were sent, and missing from the list that turns things off."""
    sign_in(world["alice"])

    keys = {p["event_key"] for p in client.get("/api/notifications/preferences").json()}

    assert {"competition.started", "competition.finished", "competition.won"} <= keys
