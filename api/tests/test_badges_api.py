"""Badges over the wire.

The scoping here goes the ordinary way, unlike the season table: a badge is
about one person's history rather than about where everybody stands, so what
somebody holds is read under the same rules as anything else about them. What
*can* be earned is readable by everybody, because a badge nobody can see the
terms of is a badge nobody aims at.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import badges
from app.models import AchievementRule, AuditLog, Badge


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", smb, name="Clark Kent"),
        "metric": make_metric("deal_value", unit="currency"),
    }


@pytest.fixture
def rule(db, org, world):
    row = AchievementRule(
        organization_id=org.id,
        name="Big deal",
        metric_definition_id=world["metric"].id,
        comparator="gte",
        threshold=100,
        scope="everyone",
        message="",
        points=10,
        created_at=datetime.now(UTC) - timedelta(days=200),
    )
    db.add(row)
    db.flush()
    return row


def create(client, **body):
    return client.post(
        "/api/points/badges",
        json={"name": "Good egg", "description": "Helped somebody out", **body},
    )


# -- Defining badges ---------------------------------------------------------


def test_an_admin_defines_a_badge_given_by_hand(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = create(client)

    assert reply.status_code == 201, reply.json()
    assert reply.json()["kind"] == "manual"


def test_an_admin_defines_a_counted_badge(client, db, world, sign_in, rule):
    sign_in(world["admin"])

    reply = create(
        client, name="Closer", kind="count",
        achievement_rule_id=rule.id, threshold=3, counted_over="month",
    )

    assert reply.status_code == 201, reply.json()
    assert reply.json()["achievement_rule_name"] == "Big deal"


def test_a_counted_badge_with_nothing_to_count_is_refused_in_words(
    client, db, world, sign_in
):
    """The CHECK constraint says the same thing as a 500. This says it as
    something somebody can act on."""
    sign_in(world["admin"])

    reply = create(client, kind="count", threshold=3, counted_over="month")

    assert reply.status_code == 404
    assert "achievement rule" in reply.json()["detail"]


def test_a_counted_badge_needs_a_number(client, db, world, sign_in, rule):
    sign_in(world["admin"])

    reply = create(
        client, kind="count", achievement_rule_id=rule.id, counted_over="month"
    )

    assert reply.status_code == 422
    assert "how many times" in reply.json()["detail"]


def test_a_counted_badge_needs_a_window(client, db, world, sign_in, rule):
    sign_in(world["admin"])

    reply = create(
        client, kind="count", achievement_rule_id=rule.id, threshold=3,
        counted_over="fortnight",
    )

    assert reply.status_code == 422


def test_switching_a_badge_to_manual_clears_what_it_counted(
    client, db, world, sign_in, rule
):
    """Cleared rather than left behind — a manual badge carrying a stale
    threshold is a row the CHECK refuses, and this edit is exactly how
    somebody would get there."""
    sign_in(world["admin"])
    made = create(
        client, name="Closer", kind="count",
        achievement_rule_id=rule.id, threshold=3, counted_over="month",
    ).json()

    reply = client.patch(
        f"/api/points/badges/{made['id']}",
        json={"name": "Closer", "kind": "manual"},
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["threshold"] is None


def test_two_badges_with_one_name_are_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    create(client)

    assert create(client).status_code == 409


def test_a_manager_cannot_define_a_badge(client, db, world, sign_in):
    sign_in(world["manager"])

    assert create(client).status_code == 403


def test_everybody_can_see_what_can_be_earned(client, db, world, sign_in):
    """A badge nobody can see the terms of is a badge nobody aims at."""
    sign_in(world["admin"])
    create(client)

    sign_in(world["peter"])
    names = [b["name"] for b in client.get("/api/points/badges").json()]

    assert names == ["Good egg"]


# -- Pinning one on ----------------------------------------------------------


def test_a_manager_pins_a_badge_on_their_own_person(client, db, world, sign_in):
    sign_in(world["admin"])
    badge = create(client).json()

    sign_in(world["manager"])
    reply = client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["peter"].id, "reason": "Covered a shift"},
    )

    assert reply.status_code == 201, reply.json()
    assert reply.json()["name"] == "Good egg"


def test_a_manager_cannot_pin_one_outside_their_team(
    client, db, world, sign_in
):
    sign_in(world["admin"])
    badge = create(client).json()

    sign_in(world["manager"])
    reply = client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["clark"].id},
    )

    assert reply.status_code == 404


def test_an_agent_cannot_pin_badges(client, db, world, sign_in):
    sign_in(world["admin"])
    badge = create(client).json()

    sign_in(world["peter"])
    reply = client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["clark"].id},
    )

    assert reply.status_code == 403


def test_a_counted_badge_can_be_given_by_hand_too(
    client, db, world, sign_in, rule
):
    """Somebody who did the work while a connector was down should not lose it
    to a gap in the data."""
    sign_in(world["admin"])
    badge = create(
        client, name="Closer", kind="count",
        achievement_rule_id=rule.id, threshold=3, counted_over="month",
    ).json()

    reply = client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["peter"].id, "reason": "Sync was down"},
    )

    assert reply.status_code == 201, reply.json()


def test_pinning_a_badge_is_audited(client, db, world, sign_in):
    """A public statement about somebody that outlives the season it was made
    in."""
    sign_in(world["admin"])
    badge = create(client).json()
    client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["peter"].id},
    )

    assert "badge.awarded" in db.scalars(select(AuditLog.action)).all()


# -- What somebody holds -----------------------------------------------------


def test_my_badges_and_how_many_times(client, db, world, sign_in):
    sign_in(world["admin"])
    badge = create(client).json()
    for _ in range(2):
        client.post(
            f"/api/points/badges/{badge['id']}/award",
            json={"user_id": world["peter"].id},
        )

    sign_in(world["peter"])
    held = client.get("/api/points/badges/mine").json()["held"]

    assert [(b["name"], b["times"]) for b in held] == [("Good egg", 2)]


def test_my_progress_toward_a_counted_badge(
    client, db, org, world, sign_in, rule, make_fact
):
    """**The half that changes behaviour.**"""
    sign_in(world["admin"])
    create(
        client, name="Closer", kind="count",
        achievement_rule_id=rule.id, threshold=3, counted_over="month",
    )
    now = datetime.now(UTC)
    when = min(now.replace(day=1, hour=12) + timedelta(days=1), now - timedelta(minutes=1))
    for _ in range(2):
        make_fact(world["metric"], world["peter"], 500, when)
    db.commit()

    sign_in(world["peter"])
    progress = client.get("/api/points/badges/mine").json()["progress"]

    assert [(p["name"], p["remaining"]) for p in progress] == [("Closer", 1)]


def test_a_manager_can_read_their_own_persons_badges(
    client, db, world, sign_in
):
    sign_in(world["admin"])
    badge = create(client).json()
    client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["peter"].id},
    )

    sign_in(world["manager"])
    reply = client.get(f"/api/points/badges/user/{world['peter'].id}")

    assert reply.status_code == 200
    assert [b["name"] for b in reply.json()] == ["Good egg"]


def test_a_manager_cannot_read_badges_outside_their_team(
    client, db, world, sign_in
):
    """**Scoped the ordinary way**, unlike the season table: a badge is about
    one person's history, not about where everybody stands."""
    sign_in(world["manager"])

    assert (
        client.get(f"/api/points/badges/user/{world['clark'].id}").status_code
        == 404
    )


# -- Deleting ----------------------------------------------------------------


def test_the_list_says_how_many_hold_each_badge(client, db, world, sign_in):
    """Shown because deleting a badge takes every award of it with it."""
    sign_in(world["admin"])
    badge = create(client).json()
    for person in (world["peter"], world["clark"]):
        client.post(
            f"/api/points/badges/{badge['id']}/award",
            json={"user_id": person.id},
        )

    listed = client.get("/api/points/badges").json()

    assert listed[0]["holders"] == 2


def test_deleting_a_badge_takes_its_awards_with_it(client, db, world, sign_in):
    """**This really deletes, and it takes history with it.** Which is why the
    list shows the holder count beside the button."""
    sign_in(world["admin"])
    badge = create(client).json()
    client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["peter"].id},
    )

    assert client.delete(f"/api/points/badges/{badge['id']}").status_code == 204

    sign_in(world["peter"])
    assert client.get("/api/points/badges/mine").json()["held"] == []


def test_renaming_a_badge_does_not_rewrite_what_was_given(
    client, db, world, sign_in
):
    """An award stores what it was given for, so a rename does not change what
    somebody was told they had."""
    sign_in(world["admin"])
    badge = create(client).json()
    client.post(
        f"/api/points/badges/{badge['id']}/award",
        json={"user_id": world["peter"].id, "reason": "Covered a shift"},
    )
    client.patch(
        f"/api/points/badges/{badge['id']}",
        json={"name": "Team player"},
    )

    sign_in(world["peter"])
    held = client.get("/api/points/badges/mine").json()["held"][0]

    assert held["reason"] == "Covered a shift"


# ── Badge art (6.5) ──────────────────────────────────────────────────────────


def badge_body(**overrides):
    return {"name": "Rocket launch", "kind": "manual", **overrides}


def test_a_badge_wears_a_drawn_emblem_by_key(client, world, sign_in):
    sign_in(world["admin"])
    made = client.post("/api/points/badges", json=badge_body(icon="rocket"))
    assert made.status_code == 201, made.json()
    assert made.json()["icon"] == "rocket"


def test_a_badge_can_wear_the_organizations_own_picture(client, db, org, world, sign_in):
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", (300, 300), (255, 0, 0, 0)).save(out, format="PNG")
    sign_in(world["admin"])
    art = client.post(
        "/api/assets", content=out.getvalue(),
        headers={"content-type": "image/png", "x-file-name": "Our star.png"},
    ).json()

    made = client.post("/api/points/badges", json=badge_body(icon=f"asset:{art['digest']}"))
    assert made.status_code == 201, made.json()

    # And Assets says where it is used, and will not remove it.
    listed = next(a for a in client.get("/api/assets").json() if a["digest"] == art["digest"])
    assert listed["used_in"] == [{"label": "Badge “Rocket launch”", "link": "/points/setup"}]
    assert client.delete(f"/api/assets/{art['digest']}").status_code == 409


def test_a_picture_the_organization_does_not_hold_is_refused(client, world, sign_in):
    sign_in(world["admin"])
    reply = client.post("/api/points/badges", json=badge_body(icon="asset:" + "a" * 64))
    assert reply.status_code == 422


def test_art_that_is_neither_a_key_nor_a_picture_is_refused(client, world, sign_in):
    sign_in(world["admin"])
    reply = client.post("/api/points/badges", json=badge_body(icon="https://example.com/x.png"))
    assert reply.status_code == 422
