"""Achievement rules: celebrating a piece of work, not a goal.

The dangerous case here is not a missed celebration — it is a connector
backfilling six months of history and announcing every deal in it, live, on
every screen in the building. Most of what follows is about that.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import notifications
from app.models import AchievementRule, Notification

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
#: Rules are created "before" the facts in these tests, since a rule never
#: fires for work done before it existed.
EARLIER = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "revenue": make_metric("revenue_closed", unit="currency", decimal_places=2),
        "response": make_metric("response_time", direction="lower_is_better"),
    }


def make_rule(db, org, world, **overrides):
    fields = {
        "organization_id": org.id,
        "name": "Big deal closed",
        "metric_definition_id": world["revenue"].id,
        "comparator": "gte",
        "threshold": Decimal(5000),
        "scope": "everyone",
        "created_at": EARLIER,
    }
    fields.update(overrides)
    rule = AchievementRule(**fields)
    db.add(rule)
    db.flush()
    return rule


def announced(db) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.event_key.startswith("achievement:"))
            .order_by(Notification.id)
        ).all()
    )


# ── Firing ───────────────────────────────────────────────────────────────────


def test_a_big_enough_fact_is_celebrated(db, org, world, make_fact):
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    assert [n.about_name for n in announced(db)] == ["Alice"]


def test_a_smaller_one_is_not(db, org, world, make_fact):
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 4999, WHEN)

    notifications.detect_rules(db)

    assert announced(db) == []


def test_the_threshold_is_inclusive(db, org, world, make_fact):
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 5000, WHEN)

    notifications.detect_rules(db)

    assert len(announced(db)) == 1


def test_a_lower_is_better_rule_fires_on_small_values(db, org, world, make_fact):
    """"Answered in under 60 seconds" is as much an achievement as a big deal."""
    make_rule(
        db, org, world,
        name="Fast response",
        metric_definition_id=world["response"].id,
        comparator="lte",
        threshold=Decimal(60),
    )
    make_fact(world["response"], world["alice"], 45, WHEN)
    make_fact(world["response"], world["bob"], 90, WHEN)

    notifications.detect_rules(db)

    assert [n.about_name for n in announced(db)] == ["Alice"]


def test_the_announcement_carries_the_figure(db, org, world, make_fact):
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    row = announced(db)[0]
    assert row.title == "Big deal closed"
    assert "12,400" in row.body
    # And on its own, for the takeover to lead with (7.9).
    assert row.figure == "$12,400"


def test_each_qualifying_fact_is_its_own_celebration(db, org, world, make_fact):
    """Two big deals are two wins, unlike a goal, which is hit once."""
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 8000, WHEN)
    make_fact(world["revenue"], world["alice"], 9000, WHEN)

    notifications.detect_rules(db)

    assert len(announced(db)) == 2


# ── Never twice, and never a backfill ────────────────────────────────────────


def test_a_second_pass_announces_nothing_new(db, org, world, make_fact):
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    first = notifications.detect_rules(db)
    second = notifications.detect_rules(db)

    assert first.emitted == 1
    assert second.emitted == 0
    assert len(announced(db)) == 1


def test_work_done_before_the_rule_existed_is_never_celebrated(
    db, org, world, make_fact
):
    """Spinify's stated constraint, and the one that protects the wall.

    Without it, creating a rule would immediately announce every historic deal
    that would have qualified — on every screen, at once.
    """
    make_rule(db, org, world, created_at=WHEN)
    make_fact(world["revenue"], world["alice"], 12400, WHEN - timedelta(days=30))

    notifications.detect_rules(db)

    assert announced(db) == []


def test_a_six_month_backfill_does_not_flood_the_wall(db, org, world, make_fact):
    """The failure this is really guarding against.

    A connector syncing history inserts rows with *fresh ids* and *old
    timestamps*. The id watermark alone would let every one through, because
    they are all new to it.
    """
    rule = make_rule(db, org, world, created_at=WHEN)
    for days in range(1, 60):
        make_fact(world["revenue"], world["alice"], 9000, WHEN - timedelta(days=days))
    make_fact(world["revenue"], world["alice"], 9000, WHEN + timedelta(hours=1))

    notifications.detect_rules(db)

    # Only the one that happened after the rule was created.
    assert len(announced(db)) == 1
    assert rule.last_fact_id > 0


def test_the_watermark_is_only_an_optimisation(db, org, world, make_fact):
    """Correctness comes from the unique index, not the high-water mark — so
    resetting it must not produce a second announcement."""
    rule = make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)
    notifications.detect_rules(db)

    rule.last_fact_id = 0
    db.flush()
    again = notifications.detect_rules(db)

    assert again.emitted == 0
    assert len(announced(db)) == 1


def test_two_rules_on_one_metric_both_fire(db, org, world, make_fact):
    """The event key carries the rule id, so neither can suppress the other
    through the unique index."""
    make_rule(db, org, world, name="Big deal", threshold=Decimal(5000))
    make_rule(db, org, world, name="Huge deal", threshold=Decimal(10000))
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    assert sorted(n.title for n in announced(db)) == ["Big deal", "Huge deal"]


# ── Scope and switching off ──────────────────────────────────────────────────


def test_a_team_rule_only_covers_that_team(db, org, world, make_fact):
    make_rule(db, org, world, scope="team", scope_team_id=world["enterprise"].id)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)
    make_fact(world["revenue"], world["stranger"], 99000, WHEN)

    notifications.detect_rules(db)

    assert [n.about_name for n in announced(db)] == ["Alice"]


def test_a_team_rule_uses_the_snapshot_not_current_membership(
    db, org, world, make_fact
):
    """Somebody who has since transferred still earned it on the team they
    were on — the same rule every other query here follows."""
    make_rule(db, org, world, scope="team", scope_team_id=world["smb"].id)
    make_fact(world["revenue"], world["alice"], 12400, WHEN, team=world["smb"])

    notifications.detect_rules(db)

    assert [n.about_name for n in announced(db)] == ["Alice"]


def test_a_disabled_rule_says_nothing(db, org, world, make_fact):
    """The org-wide off switch, separate from anybody's own mute."""
    make_rule(db, org, world, enabled=False)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    assert announced(db) == []


def test_a_disabled_rule_says_nothing(db, org, world, make_fact):
    """Disabling is what archiving used to be, and it is reversible.

    There was an `archived_at` column doing this same job one way only — the list
    filtered archived rules out and nothing could restore one. This test used to
    set it; `enabled` is the whole mechanism now.
    """
    make_rule(db, org, world, enabled=False)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    assert announced(db) == []


def test_a_hidden_person_is_not_announced(db, org, world, make_fact):
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)
    world["alice"].hidden_at = WHEN
    db.flush()

    notifications.detect_rules(db)

    assert announced(db) == []


# ── Media ────────────────────────────────────────────────────────────────────

SONG = "https://youtu.be/dQw4w9WgXcQ"
FANFARE = "https://cdn.example.com/fanfare.gif"


def test_a_persons_own_music_beats_the_rules(db, org, world, make_fact):
    """The rule's clip is a **fallback**, not an override.

    Most people never open their settings, so a rule with media is how a floor
    gets sound at all — and the few who have chosen their own should keep it.
    The first version had this the other way round, which meant setting a
    rule's media silently overwrote everybody's choice.
    """
    from app.models import WalkupMedia

    db.add(WalkupMedia(user_id=world["alice"].id, url=SONG, start_seconds=0, end_seconds=15))
    make_rule(db, org, world, media_url=FANFARE, media_start_seconds=0, media_end_seconds=15)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    assert announced(db)[0].media_url == SONG


def test_the_rules_media_covers_everybody_else(db, org, world, make_fact):
    """Somebody who has never set a walk-up still gets something."""
    make_rule(db, org, world, media_url=FANFARE, media_start_seconds=0, media_end_seconds=15)
    make_fact(world["revenue"], world["bob"], 12400, WHEN)

    notifications.detect_rules(db)

    assert announced(db)[0].media_url == FANFARE


def test_a_rule_can_force_its_own_media_on_everybody(db, org, world, make_fact):
    """For the win that should always sound the same — a gong for a record
    month, whatever anybody has chosen for themselves."""
    from app.models import WalkupMedia

    db.add(WalkupMedia(user_id=world["alice"].id, url=SONG, start_seconds=0, end_seconds=15))
    make_rule(
        db, org, world,
        media_url=FANFARE, media_start_seconds=0, media_end_seconds=15,
        allow_personal_media=False,
    )
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    assert announced(db)[0].media_url == FANFARE


def test_forcing_no_media_is_a_deliberate_silence(db, org, world, make_fact):
    """Switch personal media off and set none: the announcement still appears
    on the screen, it just plays nothing."""
    from app.models import WalkupMedia

    db.add(WalkupMedia(user_id=world["alice"].id, url=SONG, start_seconds=0, end_seconds=15))
    make_rule(db, org, world, allow_personal_media=False)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    row = announced(db)[0]
    assert row.media_url is None
    # The announcement itself is unaffected.
    assert row.title == "Big deal closed"


def test_without_rule_media_their_walkup_plays(db, org, world, make_fact):
    from app.models import WalkupMedia

    db.add(WalkupMedia(user_id=world["alice"].id, url=SONG, start_seconds=7, end_seconds=22))
    make_rule(db, org, world)
    make_fact(world["revenue"], world["alice"], 12400, WHEN)

    notifications.detect_rules(db)

    row = announced(db)[0]
    assert row.media_url == SONG
    assert row.media_start_seconds == 7


# ── Managing rules ───────────────────────────────────────────────────────────


def soon():
    """A moment after *real* now.

    Rules created through the API get today's timestamp, so a fact dated in the
    fixture's 12 August has already happened as far as the rule is concerned
    and is correctly ignored. Two tests below passed vacuously for exactly that
    reason before this existed — they asserted "nothing announced" and got it
    for the wrong cause entirely.
    """
    return datetime.now(UTC) + timedelta(minutes=1)


def rule_body(world, **overrides):
    body = {
        "name": "Big deal closed",
        "metric_id": world["revenue"].id,
        "comparator": "gte",
        "threshold": "5000",
        "scope": "everyone",
    }
    return {**body, **overrides}


def test_an_admin_can_create_a_rule(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post("/api/achievement-rules", json=rule_body(world))

    assert response.status_code == 201, response.json()
    assert response.json()["metric_name"] == "Revenue Closed"
    assert response.json()["enabled"] is True


def test_a_manager_cannot(client, db, world, sign_in):
    """A rule puts a celebration on every screen every time it matches.
    Setting the bar too low does not fail loudly, it just makes the wall
    noise — not a delegation worth making cheap."""
    sign_in(world["alice"])
    assert client.post("/api/achievement-rules", json=rule_body(world)).status_code == 403


def test_a_rule_created_now_does_not_announce_old_work(
    client, db, world, sign_in, make_fact
):
    """The guard, from the API's side: creating a rule must not immediately
    announce every historic deal that would have qualified."""
    make_fact(world["revenue"], world["alice"], 12400, WHEN - timedelta(days=5))

    sign_in(world["admin"])
    client.post("/api/achievement-rules", json=rule_body(world))
    db.commit()
    notifications.detect_rules(db)

    assert announced(db) == []


def test_a_bad_threshold_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/achievement-rules", json=rule_body(world, threshold="0")
    ).status_code == 422


def test_a_bad_comparator_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/achievement-rules", json=rule_body(world, comparator="roughly")
    ).status_code == 422


def test_a_team_scope_needs_a_team(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/achievement-rules", json=rule_body(world, scope="team")
    ).status_code == 404


def test_bad_media_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/achievement-rules",
        json=rule_body(world, media_url="javascript:alert(1)"),
    ).status_code == 422


def test_disabling_a_rule_stops_it(client, db, world, sign_in, make_fact):
    sign_in(world["admin"])
    created = client.post("/api/achievement-rules", json=rule_body(world)).json()
    client.patch(
        f"/api/achievement-rules/{created['id']}",
        json=rule_body(world, enabled=False),
    )
    db.commit()

    make_fact(world["revenue"], world["alice"], 12400, soon())
    notifications.detect_rules(db)

    assert announced(db) == []


def test_editing_a_rule_does_not_reach_back(client, db, world, sign_in, make_fact):
    """The flood this prevents.

    An admin sets the bar at $50,000, sees nothing, and lowers it to $5,000.
    If the watermark only advanced past *matches*, every deal since would
    suddenly qualify and announce at once — a backfill arrived at from the
    other direction.
    """
    sign_in(world["admin"])
    created = client.post(
        "/api/achievement-rules", json=rule_body(world, threshold="50000")
    ).json()
    db.commit()

    make_fact(world["revenue"], world["alice"], 12400, soon())
    notifications.detect_rules(db)
    assert announced(db) == []

    client.patch(
        f"/api/achievement-rules/{created['id']}", json=rule_body(world, threshold="5000")
    )
    db.commit()
    notifications.detect_rules(db)

    # Examined under the old bar, so it stays examined.
    assert announced(db) == []

    # New work still qualifies, so the rule is not simply dead.
    make_fact(world["revenue"], world["alice"], 9000, soon())
    notifications.detect_rules(db)
    assert len(announced(db)) == 1


def test_deleting_a_rule_takes_what_it_announced(client, db, world, sign_in, make_fact):
    """A real delete, and its wins go with it (7.5, Q2-6) — a win left in
    the bells and the feed for a rule that no longer exists is a sentence
    about nothing. Pausing is how to stop a rule and keep what it said; the
    points it paid stay either way."""
    from app.models import PointAward

    sign_in(world["admin"])
    body = {**rule_body(world), "points": 5}
    created = client.post("/api/achievement-rules", json=body).json()
    db.commit()
    make_fact(world["revenue"], world["alice"], 12400, soon())
    notifications.detect_rules(db)
    db.commit()
    assert len(announced(db)) == 1
    paid = db.scalar(select(func.count()).select_from(PointAward))

    assert client.delete(f"/api/achievement-rules/{created['id']}").status_code == 204
    assert client.get("/api/achievement-rules").json() == []
    # The row is gone, not hidden — and so is what it announced.
    assert db.get(AchievementRule, created["id"]) is None
    assert announced(db) == []
    # Points already paid stay (as decided).
    assert db.scalar(select(func.count()).select_from(PointAward)) == paid


def test_a_disabled_rule_stays_in_the_list(client, db, world, sign_in):
    """The difference from the old archive, and the reason it replaced it: a
    disabled rule is visible and one click from being back on."""
    sign_in(world["admin"])
    created = client.post("/api/achievement-rules", json=rule_body(world)).json()
    db.commit()

    client.patch(
        f"/api/achievement-rules/{created['id']}",
        json={**rule_body(world), "enabled": False},
    )

    listed = client.get("/api/achievement-rules").json()
    assert [(r["name"], r["enabled"]) for r in listed] == [(created["name"], False)]


def test_rules_do_not_cross_organizations(client, db, org, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        AchievementRule(
            organization_id=other.id,
            name="Theirs",
            metric_definition_id=world["revenue"].id,
            comparator="gte",
            threshold=Decimal(1),
            scope="everyone",
        )
    )
    db.commit()

    sign_in(world["admin"])
    assert client.get("/api/achievement-rules").json() == []


# ── Straight away, not on the hour (QA-2) ────────────────────────────────────


def test_a_correction_over_the_bar_is_announced_before_the_reply(
    client, db, org, world, sign_in
):
    """Only the hourly job used to look, so a rule promising "the moment it
    happens" fired up to an hour late. The pass now runs after the response,
    and the test client finishes background work before it returns."""
    make_rule(db, org, world)
    sign_in(world["admin"])

    response = client.post(
        "/api/metric-facts",
        json={
            "metric_id": world["revenue"].id,
            "subject_user_id": world["alice"].id,
            "value": "12400",
            "occurred_at": WHEN.isoformat(),
        },
    )

    assert response.status_code == 201
    assert [n.title for n in announced(db)] == ["Big deal closed"]


def test_a_second_request_waits_behind_the_one_already_queued():
    """A queued pass announces everything new, so a second caller has nothing
    to add — and parking a request thread for it would cost a thread per
    webhook in a burst."""
    from app import jobs

    opened = []
    jobs._queued.acquire()
    try:
        jobs.announce_now(lambda: opened.append(True))
    finally:
        jobs._queued.release()

    assert opened == []


def test_a_failed_pass_is_logged_and_left_to_the_hourly_job(caplog, monkeypatch):
    from contextlib import contextmanager

    from app import jobs

    # Alembic's logging config, run by the suite's migrations, switches off
    # every logger that already existed — this one included.
    monkeypatch.setattr(jobs.logger, "disabled", False)

    @contextmanager
    def broken():
        raise RuntimeError("database went away")
        yield

    jobs.announce_now(broken)

    assert "the hourly job will" in caplog.text
    # And the next number is not locked out by the one that failed.
    assert jobs._queued.acquire(blocking=False)
    jobs._queued.release()


# ── Trying a rule before it is saved ─────────────────────────────────────────


def test_the_check_counts_last_weeks_matches(client, db, world, sign_in, make_fact):
    """Two of Alice's and one of Bob's cleared the bar in the last four weeks
    — the suggestion's window too (Q2-4); one was too small; one was before
    the window. Three times, by two people."""
    now = datetime.now(UTC)
    make_fact(world["revenue"], world["alice"], 6000, now - timedelta(days=1))
    make_fact(world["revenue"], world["alice"], 7000, now - timedelta(days=2))
    make_fact(world["revenue"], world["bob"], 5000, now - timedelta(days=3))
    make_fact(world["revenue"], world["bob"], 4999, now - timedelta(days=3))
    make_fact(world["revenue"], world["bob"], 9000, now - timedelta(days=30))
    db.commit()

    sign_in(world["admin"])
    response = client.post("/api/achievement-rules/preview", json=rule_body(world))

    assert response.status_code == 200, response.json()
    found = response.json()
    assert (found["fired"], found["people"], found["days"]) == (3, 2, 28)
    # Every number of the metric in the window, whatever its size.
    assert found["recorded"] == 4
    # The most recent of them, said as the wall would say it.
    assert found["celebration"]["about_name"] == "Alice"
    assert found["celebration"]["title"] == "Big deal closed"
    assert found["celebration"]["body"] == "Alice — $6,000"


def test_the_check_writes_nothing(client, db, world, sign_in, make_fact):
    make_fact(world["revenue"], world["alice"], 6000, datetime.now(UTC) - timedelta(days=1))
    db.commit()

    sign_in(world["admin"])
    client.post("/api/achievement-rules/preview", json=rule_body(world))

    assert db.scalars(select(AchievementRule)).all() == []
    assert announced(db) == []


def test_with_no_matches_the_celebration_is_the_checker_at_the_bar(
    client, db, world, sign_in
):
    sign_in(world["admin"])
    found = client.post(
        "/api/achievement-rules/preview",
        json=rule_body(world, message="{first_name} just closed {value}!"),
    ).json()

    assert (found["fired"], found["people"]) == (0, 0)
    # With its currency, and without cents on a whole amount (Q2-2).
    assert found["celebration"]["body"] == "Admin just closed $5,000!"


def test_the_check_skips_hidden_people_and_other_teams(
    client, db, world, sign_in, make_fact
):
    now = datetime.now(UTC)
    world["bob"].hidden_at = now
    make_fact(world["revenue"], world["bob"], 6000, now - timedelta(days=1))
    make_fact(world["revenue"], world["alice"], 6000, now - timedelta(days=1))
    make_fact(world["revenue"], world["stranger"], 6000, now - timedelta(days=1))
    db.commit()

    sign_in(world["admin"])
    found = client.post(
        "/api/achievement-rules/preview",
        json=rule_body(world, scope="team", scope_team_id=world["enterprise"].id),
    ).json()

    assert (found["fired"], found["people"]) == (1, 1)


def test_the_check_refuses_what_saving_refuses(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/achievement-rules/preview", json=rule_body(world, message="{squad}")
    ).status_code == 422
    sign_in(world["alice"])
    assert client.post(
        "/api/achievement-rules/preview", json=rule_body(world)
    ).status_code == 403


# ── A suggested bar, for the starter templates (6.4) ─────────────────────────


def test_a_suggested_bar_fires_about_as_often_as_asked(client, db, world, sign_in, make_fact):
    """Fourteen deals in the window and a bar for about once every other day
    (per_week=1 over four weeks is four): the fourth largest, rounded down to
    two figures, so it clears four of them."""
    now = datetime.now(UTC)
    for n, value in enumerate([9100, 8250, 7300, 6237.5, 5000, 4000, 3000, 2000, 1500,
                               1200, 1100, 900, 800, 700]):
        make_fact(world["revenue"], world["alice"], value, now - timedelta(days=1 + n))
    make_fact(world["revenue"], world["alice"], 99000, now - timedelta(days=40))
    db.commit()

    sign_in(world["admin"])
    found = client.get(
        f"/api/achievement-rules/suggest?metric_id={world['revenue'].id}&per_week=1"
    ).json()

    assert Decimal(found["threshold"]) == Decimal(6200)
    assert (found["would_fire"], found["weeks"]) == (4, 4)


def test_no_recent_data_suggests_nothing(client, db, world, sign_in):
    sign_in(world["admin"])
    found = client.get(
        f"/api/achievement-rules/suggest?metric_id={world['revenue'].id}"
    ).json()
    assert found["threshold"] is None


def test_by_unit_the_busiest_metric_of_that_kind_is_chosen(
    client, db, world, sign_in, make_metric, make_fact
):
    quiet = make_metric("pipeline_value", unit="currency", decimal_places=2)
    now = datetime.now(UTC)
    make_fact(quiet, world["alice"], 1000, now - timedelta(days=60))
    for n in range(5):
        make_fact(world["revenue"], world["alice"], 5000 + n, now - timedelta(days=1 + n))
    db.commit()

    sign_in(world["admin"])
    found = client.get("/api/achievement-rules/suggest?unit=currency&per_week=1").json()

    assert found["metric_id"] == world["revenue"].id
    assert found["threshold"] is not None

