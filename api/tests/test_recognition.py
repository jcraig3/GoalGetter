"""Shout-outs, and the feed a whole floor reads.

Two things here differ from everything else in the product and both are
deliberate: the feed is org-wide rather than scoped to the viewer, and the
same person can be recognised twice for two different things.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app import events, notifications
from app.models import AuditLog, Goal, Notification, Organization, UserAccount

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "other_manager": make_user("manager", smb, name="Other Manager"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "metric": make_metric("calls_made"),
    }


def send(client, user, message="Great save on the Henderson account"):
    return client.post(
        "/api/recognition", json={"user_id": user.id, "message": message}
    )


def achievements(client):
    response = client.get("/api/achievements")
    assert response.status_code == 200, response.json()
    return response.json()


# ── Sending ──────────────────────────────────────────────────────────────────


def test_a_manager_can_recognise_their_own_team(client, db, world, sign_in):
    sign_in(world["manager"])
    response = send(client, world["alice"])

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["title"] == "Great save on the Henderson account"
    assert body["about_name"] == "Alice"
    assert body["from_name"] == "Manager"


def test_it_reaches_the_recipients_bell(client, db, world, sign_in):
    sign_in(world["manager"])
    send(client, world["alice"])

    sign_in(world["alice"])
    feed = client.get("/api/notifications").json()
    assert feed["unread"] == 1
    assert feed["notifications"][0]["from_name"] == "Manager"
    assert feed["notifications"][0]["celebrate"] is True


def test_a_manager_cannot_recognise_somebody_they_cannot_see(client, db, world, sign_in):
    """A shout-out is a broadcast. Without this it doubles as a way to find out
    who works in another office."""
    sign_in(world["manager"])
    assert send(client, world["stranger"]).status_code == 404


def test_an_agent_cannot_send_one(client, db, world, sign_in):
    sign_in(world["alice"])
    assert send(client, world["bob"]).status_code == 403


def test_an_admin_can_recognise_anybody(client, db, world, sign_in):
    sign_in(world["admin"])
    assert send(client, world["stranger"]).status_code == 201


def test_the_same_person_can_be_recognised_twice(client, db, world, sign_in):
    """The partial index, from the recipient's side.

    Detected events latch; authored ones must repeat. Two good weeks are two
    shout-outs, and swallowing the second as a duplicate would be the feature
    failing rather than working.
    """
    sign_in(world["manager"])
    assert send(client, world["alice"], "Closed the Whitfield deal").status_code == 201
    assert send(client, world["alice"], "Covered Bob's shift").status_code == 201

    assert db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.event_key == "recognition"
        )
    ) == 2


def test_a_message_is_required(client, db, world, sign_in):
    """"Great work" tells the floor nothing, so there is no default."""
    sign_in(world["manager"])
    assert client.post(
        "/api/recognition", json={"user_id": world["alice"].id, "message": ""}
    ).status_code == 422


def test_sending_is_audited(client, db, world, sign_in):
    """This puts a sentence in front of a whole floor. "Who sent that" needs an
    answer that does not depend on the row still existing."""
    sign_in(world["manager"])
    send(client, world["alice"])

    entry = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert entry.action == "recognition.sent"


# ── The feed ─────────────────────────────────────────────────────────────────


def test_the_feed_is_org_wide_not_scoped(client, db, world, sign_in):
    """Deliberately unlike every other list here.

    These same rows go on a wall screen anybody walking past can read, so
    "public" has to mean the same thing at a desk and in a corridor.
    """
    sign_in(world["admin"])
    send(client, world["stranger"])

    sign_in(world["alice"])
    assert [a["about_name"] for a in achievements(client)] == ["Stranger"]


def test_private_events_never_reach_the_feed(client, db, org, world, sign_in):
    """The catalogue is what keeps this safe, not a filter here. Being behind
    on a goal is a conversation with your manager, not wall material."""
    notifications.emit(
        db,
        org_id=org.id,
        user_id=world["alice"].id,
        event=events.GOAL_PERIOD_ENDING,
        subject_type="goal",
        subject_id=1,
        period_anchor=WHEN.date(),
        title="Calls Made is running out of time",
        about_name="Alice",
    )
    notifications.emit(
        db,
        org_id=org.id,
        user_id=world["alice"].id,
        event=events.GOAL_ASSIGNED,
        subject_type="goal",
        subject_id=1,
        period_anchor=WHEN.date(),
        title="New goal: Calls Made",
        about_name="Alice",
    )
    db.commit()

    sign_in(world["alice"])
    assert achievements(client) == []


def test_a_team_achievement_appears_once_not_once_per_member(
    client, db, org, world, sign_in, make_fact
):
    """The reason `about_name` exists.

    A team goal sends a row to every member — one event, four recipients — and
    a feed keyed on the addressee would list the same news four times under
    four names, none of which is the achiever.
    """
    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="team",
            subject_team_id=world["enterprise"].id,
            target_value=100,
            period_type="month",
            period_anchor=WHEN.date().replace(day=1),
        )
    )
    db.flush()
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)
    db.commit()

    # Three team members each got a copy.
    assert db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.event_key == "goal.achieved"
        )
    ) == 3

    sign_in(world["alice"])
    feed = achievements(client)
    assert len(feed) == 1
    assert feed[0]["about_name"] == "Enterprise"
    assert feed[0]["about_user_id"] is None


def test_a_personal_achievement_names_the_person_not_the_manager(
    client, db, org, world, sign_in, make_fact
):
    """It goes to Alice and her manager. The feed is about Alice."""
    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="user",
            subject_user_id=world["alice"].id,
            target_value=100,
            period_type="month",
            period_anchor=WHEN.date().replace(day=1),
        )
    )
    db.flush()
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)
    db.commit()

    sign_in(world["bob"])
    feed = achievements(client)
    assert len(feed) == 1
    assert feed[0]["about_name"] == "Alice"
    assert feed[0]["about_user_id"] == world["alice"].id


def test_another_organizations_achievements_never_appear(
    client, db, world, sign_in
):
    """The feed is org-wide by design, which makes the organization filter the
    *only* thing standing between it and every tenant's celebrations.

    Every other list here is narrowed by scope as well, so a missing tenant
    filter would still be caught by something. This one has no second line of
    defence, and a mutation removing the filter passed every test until this
    existed.
    """
    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = UserAccount(
        organization_id=other.id,
        email="someone@other.example",
        full_name="Their Person",
        org_role="agent",
        status="active",
    )
    db.add(theirs)
    db.flush()
    notifications.emit(
        db,
        org_id=other.id,
        user_id=theirs.id,
        event=events.RECOGNITION,
        subject_type="user",
        subject_id=theirs.id,
        title="Their private business",
        about_name="Their Person",
        created_by_user_id=theirs.id,
    )
    db.commit()

    sign_in(world["manager"])
    send(client, world["alice"], "Ours")

    titles = [a["title"] for a in achievements(client)]
    assert titles == ["Ours"]


def test_the_feed_is_newest_first(client, db, world, sign_in):
    sign_in(world["manager"])
    send(client, world["alice"], "First")
    send(client, world["bob"], "Second")

    assert [a["title"] for a in achievements(client)] == ["Second", "First"]


def test_an_agent_can_read_the_feed(client, db, world, sign_in):
    """Everybody sees what the organization celebrates. That is the point."""
    sign_in(world["manager"])
    send(client, world["alice"])
    sign_in(world["alice"])
    assert len(achievements(client)) == 1


def test_the_feed_needs_a_session(client, db, world):
    assert client.get("/api/achievements").status_code == 401


# ── Taking one back ──────────────────────────────────────────────────────────


def test_a_manager_can_delete_their_own(client, db, world, sign_in):
    """For the inevitable typo in front of the whole floor."""
    sign_in(world["manager"])
    created = send(client, world["alice"]).json()

    assert client.delete(f"/api/recognition/{created['id']}").status_code == 204
    assert achievements(client) == []


def test_a_manager_cannot_delete_somebody_elses(client, db, world, sign_in):
    sign_in(world["admin"])
    created = send(client, world["alice"]).json()

    sign_in(world["manager"])
    assert client.delete(f"/api/recognition/{created['id']}").status_code == 404


def test_an_admin_can_delete_any(client, db, world, sign_in):
    sign_in(world["manager"])
    created = send(client, world["alice"]).json()

    sign_in(world["admin"])
    assert client.delete(f"/api/recognition/{created['id']}").status_code == 204


def test_a_detected_achievement_cannot_be_deleted(client, db, org, world, sign_in):
    """Nobody gets to un-hit a target."""
    notifications.emit(
        db,
        org_id=org.id,
        user_id=world["alice"].id,
        event=events.GOAL_ACHIEVED,
        subject_type="goal",
        subject_id=1,
        period_anchor=WHEN.date(),
        title="Calls Made achieved",
        about_name="Alice",
    )
    db.commit()
    target = db.scalar(select(Notification.id))

    sign_in(world["admin"])
    assert client.delete(f"/api/recognition/{target}").status_code == 404
    assert db.get(Notification, target) is not None


def test_deleting_is_audited(client, db, world, sign_in):
    sign_in(world["manager"])
    created = send(client, world["alice"]).json()
    client.delete(f"/api/recognition/{created['id']}")

    entry = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert entry.action == "recognition.deleted"


# ── Walk-up media ────────────────────────────────────────────────────────────

SONG = "https://youtu.be/dQw4w9WgXcQ"
GIF = "https://cdn.example.com/party.gif"


def set_walkup(client, url, start=None):
    return client.put("/api/me/walkup", json={"url": url, "start_seconds": start})


def test_you_set_your_own_walkup(client, db, world, sign_in):
    sign_in(world["alice"])
    response = set_walkup(client, SONG, 42)

    assert response.status_code == 200, response.json()
    assert response.json() == {
        "url": SONG,
        "kind": "youtube",
        "start_seconds": 42,
        "end_seconds": 42 + 15,
    }


def test_an_agent_can_set_theirs(client, db, world, sign_in):
    """No capability. A walk-up song is the one thing here that is purely an
    expression of the person it belongs to."""
    sign_in(world["alice"])
    assert set_walkup(client, GIF).status_code == 200


def test_a_bad_link_is_refused_with_a_message(client, db, world, sign_in):
    sign_in(world["alice"])
    response = set_walkup(client, "https://example.com/whatever")

    assert response.status_code == 422
    assert "YouTube" in response.json()["detail"]


def test_clearing_it_removes_it(client, db, world, sign_in):
    sign_in(world["alice"])
    set_walkup(client, SONG)
    assert set_walkup(client, "").json()["url"] is None
    assert client.get("/api/me/walkup").json()["url"] is None


def test_yours_is_yours(client, db, world, sign_in):
    sign_in(world["alice"])
    set_walkup(client, SONG)

    sign_in(world["bob"])
    assert client.get("/api/me/walkup").json()["url"] is None


def test_a_shout_out_plays_the_recipients_walkup(client, db, world, sign_in):
    """The default is what makes it a walk-up rather than a one-off."""
    sign_in(world["alice"])
    set_walkup(client, SONG, 12)

    sign_in(world["manager"])
    created = send(client, world["alice"]).json()

    assert created["media_url"] == SONG
    assert created["media_kind"] == "youtube"
    assert created["media_start_seconds"] == 12


def test_an_override_beats_the_default(client, db, world, sign_in):
    """The occasion that deserves a specific joke."""
    sign_in(world["alice"])
    set_walkup(client, SONG)

    sign_in(world["manager"])
    response = client.post(
        "/api/recognition",
        json={"user_id": world["alice"].id, "message": "Nice", "media_url": GIF},
    )

    assert response.json()["media_url"] == GIF
    assert response.json()["media_kind"] == "image"


def test_a_bad_override_is_refused(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/recognition",
        json={
            "user_id": world["alice"].id,
            "message": "Nice",
            "media_url": "javascript:alert(1)",
        },
    )
    assert response.status_code == 422


def test_media_is_frozen_at_send_not_looked_up_later(client, db, world, sign_in):
    """Changing your walk-up music should soundtrack your NEXT win, not
    retroactively re-score every one you have already had."""
    sign_in(world["alice"])
    set_walkup(client, SONG)

    sign_in(world["manager"])
    send(client, world["alice"], "First win")

    sign_in(world["alice"])
    set_walkup(client, GIF)

    sign_in(world["manager"])
    feed = achievements(client)
    assert [a["media_url"] for a in feed] == [SONG]


def test_a_detected_achievement_plays_the_achievers_walkup(
    client, db, org, world, sign_in, make_fact
):
    """Most celebrations are detected, so a default that only applied to
    shout-outs would barely apply at all."""
    sign_in(world["alice"])
    set_walkup(client, SONG, 5)

    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="user",
            subject_user_id=world["alice"].id,
            target_value=100,
            period_type="month",
            period_anchor=WHEN.date().replace(day=1),
        )
    )
    db.flush()
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)
    db.commit()

    sign_in(world["bob"])
    hit = next(a for a in achievements(client) if a["event_key"] == "goal.achieved")
    assert hit["media_url"] == SONG
    assert hit["media_start_seconds"] == 5


def test_a_team_achievement_has_no_walkup(client, db, org, world, sign_in, make_fact):
    """A team has no walk-up song, and picking one member's would be worse than
    silence — it would credit the wrong person in front of the room.

    Every member gets one, deliberately. Setting only Alice's would let a
    fallback to "whichever member the query returned first" pass whenever that
    happened not to be Alice — a mutation proved exactly that.
    """
    for member in ("alice", "bob", "manager"):
        sign_in(world[member])
        set_walkup(client, SONG)

    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="team",
            subject_team_id=world["enterprise"].id,
            target_value=100,
            period_type="month",
            period_anchor=WHEN.date().replace(day=1),
        )
    )
    db.flush()
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)
    db.commit()

    sign_in(world["bob"])
    hit = next(a for a in achievements(client) if a["about_name"] == "Enterprise")
    assert hit["media_url"] is None


def test_walkup_needs_a_session(client, db, world):
    assert client.get("/api/me/walkup").status_code == 401
    assert client.put("/api/me/walkup", json={"url": SONG}).status_code == 401


# ── Achievement rules reach the same surfaces ────────────────────────────────


def test_a_rule_fired_achievement_reaches_the_public_feed(
    client, db, org, world, sign_in, make_fact, make_metric
):
    """A rule's event key is invented at runtime, so it cannot be in the fixed
    list of public events — the feed matches the prefix as well.

    Without this the wall would show goals and shout-outs but silently drop the
    thing the rules were built for.
    """
    from decimal import Decimal
    from app.models import AchievementRule

    revenue = make_metric("revenue_closed", unit="currency", decimal_places=2)
    db.add(
        AchievementRule(
            organization_id=org.id,
            name="Big deal closed",
            metric_definition_id=revenue.id,
            comparator="gte",
            threshold=Decimal(5000),
            scope="everyone",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    db.flush()
    make_fact(revenue, world["alice"], 12400, WHEN)
    notifications.detect_rules(db)
    db.commit()

    sign_in(world["bob"])
    feed = achievements(client)

    assert [a["title"] for a in feed] == ["Big deal closed"]
    assert feed[0]["about_name"] == "Alice"


def test_a_rule_fired_achievement_celebrates_in_the_bell(
    client, db, org, world, sign_in, make_fact, make_metric
):
    """Same problem one surface over: the bell resolves `celebrate` from the
    catalogue, which a runtime key is not in."""
    from decimal import Decimal
    from app.models import AchievementRule

    revenue = make_metric("revenue_closed", unit="currency", decimal_places=2)
    db.add(
        AchievementRule(
            organization_id=org.id,
            name="Big deal closed",
            metric_definition_id=revenue.id,
            comparator="gte",
            threshold=Decimal(5000),
            scope="everyone",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    db.flush()
    make_fact(revenue, world["alice"], 12400, WHEN)
    notifications.detect_rules(db)
    db.commit()

    sign_in(world["alice"])
    bell = client.get("/api/notifications").json()

    assert bell["notifications"][0]["celebrate"] is True


# ── Setting walk-up media on somebody else's behalf ──────────────────────────


def set_walkup_for(client, user, url, start=None):
    return client.put(
        f"/api/me/walkup?user_id={user.id}", json={"url": url, "start_seconds": start}
    )


def test_a_manager_can_set_their_own_teams_music(client, db, world, sign_in):
    """How most of these actually get set: plenty of people never open their
    own settings, and a wall with no music is the result."""
    sign_in(world["manager"])
    response = set_walkup_for(client, world["alice"], SONG, 30)

    assert response.status_code == 200, response.json()
    assert response.json()["start_seconds"] == 30

    sign_in(world["alice"])
    assert client.get("/api/me/walkup").json()["url"] == SONG


def test_a_manager_cannot_set_somebody_elses_teams(client, db, world, sign_in):
    sign_in(world["manager"])
    assert set_walkup_for(client, world["stranger"], SONG).status_code == 404


def test_an_admin_can_set_anybodys(client, db, world, sign_in):
    sign_in(world["admin"])
    assert set_walkup_for(client, world["stranger"], SONG).status_code == 200


def test_an_agent_cannot_set_a_colleagues(client, db, world, sign_in):
    """403 rather than 404: an agent can already see their teammates, so
    pretending Bob does not exist would be a lie Alice can disprove."""
    sign_in(world["alice"])
    assert set_walkup_for(client, world["bob"], SONG).status_code == 403


def test_an_agent_can_still_set_their_own_by_id(client, db, world, sign_in):
    sign_in(world["alice"])
    assert set_walkup_for(client, world["alice"], SONG).status_code == 200


def test_a_manager_can_read_their_teams(client, db, world, sign_in):
    sign_in(world["alice"])
    set_walkup(client, SONG)

    sign_in(world["manager"])
    assert client.get(f"/api/me/walkup?user_id={world['alice'].id}").json()["url"] == SONG


def test_reading_somebody_out_of_scope_is_refused(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.get(f"/api/me/walkup?user_id={world['stranger'].id}").status_code == 404


def test_setting_somebody_elses_is_audited(client, db, world, sign_in):
    """That clip plays in a room in front of them. "Who set that" needs an
    answer."""
    sign_in(world["manager"])
    set_walkup_for(client, world["alice"], SONG)

    entry = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert entry.action == "walkup.changed"


def test_setting_your_own_is_not_audited(client, db, world, sign_in):
    """Not worth a row. The audit log is for things done to other people."""
    sign_in(world["alice"])
    before = db.scalar(select(func.count()).select_from(AuditLog))
    set_walkup(client, SONG)

    assert db.scalar(select(func.count()).select_from(AuditLog)) == before


# ── Recognising a team ───────────────────────────────────────────────────────


def send_team(client, team, message="Cleared the whole backlog"):
    return client.post("/api/recognition", json={"team_id": team.id, "message": message})


def test_a_team_can_be_recognised(client, db, world, sign_in):
    sign_in(world["manager"])
    response = send_team(client, world["enterprise"])

    assert response.status_code == 201, response.json()
    assert response.json()["about_name"] == "Enterprise"
    assert response.json()["about_user_id"] is None


def test_every_member_hears_about_it(client, db, world, sign_in):
    sign_in(world["manager"])
    send_team(client, world["enterprise"])

    told = {
        n.user_id
        for n in db.scalars(
            select(Notification).where(Notification.event_key == "recognition")
        ).all()
    }
    assert told == {world["alice"].id, world["bob"].id, world["manager"].id}


def test_the_feed_shows_it_once_under_the_team(client, db, world, sign_in):
    """The same shape a team goal produces — one event, many recipients."""
    sign_in(world["manager"])
    send_team(client, world["enterprise"])

    feed = achievements(client)
    assert len(feed) == 1
    assert feed[0]["about_name"] == "Enterprise"


def test_a_team_shout_out_has_no_walkup(client, db, world, sign_in):
    """Borrowing a member's would credit the wrong person in front of the
    room."""
    sign_in(world["alice"])
    set_walkup(client, SONG)

    sign_in(world["manager"])
    assert send_team(client, world["enterprise"]).json()["media_url"] is None


def test_a_manager_cannot_recognise_another_teamitself(client, db, world, sign_in):
    sign_in(world["manager"])
    assert send_team(client, world["smb"]).status_code == 404


def test_exactly_one_target_is_required(client, db, world, sign_in):
    sign_in(world["manager"])
    both = client.post(
        "/api/recognition",
        json={
            "user_id": world["alice"].id,
            "team_id": world["enterprise"].id,
            "message": "Nice",
        },
    )
    neither = client.post("/api/recognition", json={"message": "Nice"})

    assert both.status_code == 422
    assert neither.status_code == 422
