"""Leaderboards.

The one place per-person scope is deliberately relaxed, so the visibility tests
carry the weight the scope tests carry everywhere else.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Leaderboard

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def world(make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "metric": make_metric("calls_made"),
    }


def board_body(world, **overrides):
    return {
        "name": "Board",
        "metric_id": world["metric"].id,
        "period_type": "month",
        "visibility": "org",
        **overrides,
    }


def make_board(client, world, sign_in, actor="admin", **overrides):
    sign_in(world[actor])
    response = client.post("/api/leaderboards", json=board_body(world, **overrides))
    assert response.status_code == 201, response.json()
    return response.json()["id"]


# ── Visibility: who may look ─────────────────────────────────────────────────


def test_an_agent_sees_every_entrant_on_an_org_board(
    client, db, world, make_fact, sign_in
):
    """The deliberate hole, and the reason leaderboards exist.

    Everywhere else an agent sees only their own numbers. A board that showed
    them a single row — theirs — would not be a ranking.
    """
    for person, value in (("teammate", 10), ("stranger", 30), ("manager", 20)):
        make_fact(world["metric"], world[person], value, WHEN)

    board_id = make_board(client, world, sign_in)

    sign_in(world["teammate"])
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert body["total_entrants"] == 3
    assert {e["entity_name"] for e in body["entries"]} == {
        "Teammate",
        "Stranger",
        "Manager",
    }


def test_that_hole_does_not_widen_the_rest_of_the_app(client, db, world, make_fact, sign_in):
    """The relaxation stops at the board. An agent who can see everyone's rank
    still cannot list users or read raw facts."""
    make_fact(world["metric"], world["stranger"], 30, WHEN)
    make_board(client, world, sign_in)

    sign_in(world["teammate"])
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/metric-facts").status_code == 403

    # And the general query endpoint still narrows to them alone.
    query = client.post(
        "/api/metrics/query",
        json={
            "metric_id": world["metric"].id,
            "period": {"type": "month", "anchor": "2026-08-12"},
        },
    ).json()
    assert all(r["subject_name"] == "Teammate" for r in query["rows"])


def test_a_team_board_is_visible_to_that_team_only(client, db, world, sign_in):
    board_id = make_board(
        client, world, sign_in,
        scope_type="team", scope_team_id=world["enterprise"].id, visibility="team",
    )

    sign_in(world["teammate"])  # on Enterprise
    assert client.get(f"/api/leaderboards/{board_id}/results").status_code == 200

    sign_in(world["stranger"])  # on SMB
    assert client.get(f"/api/leaderboards/{board_id}/results").status_code == 404


def test_a_private_board_is_invisible_to_everyone_else(client, db, world, sign_in):
    """404, not 403 — the existence and name of a private board is itself
    information about what someone is tracking."""
    board_id = make_board(client, world, sign_in, visibility="private")

    sign_in(world["teammate"])
    assert client.get(f"/api/leaderboards/{board_id}/results").status_code == 404
    assert client.get("/api/leaderboards").json() == []


def test_an_admin_can_open_any_board(client, db, world, sign_in):
    board_id = make_board(client, world, sign_in, actor="manager",
                          scope_type="team", scope_team_id=world["enterprise"].id,
                          visibility="private")
    sign_in(world["admin"])
    assert client.get(f"/api/leaderboards/{board_id}/results").status_code == 200


def test_the_list_hides_boards_you_cannot_open(client, db, world, sign_in):
    make_board(client, world, sign_in, name="Public")
    make_board(client, world, sign_in, name="Secret", visibility="private")

    sign_in(world["teammate"])
    assert [b["name"] for b in client.get("/api/leaderboards").json()] == ["Public"]


# ── Entrants: who appears ────────────────────────────────────────────────────


def test_a_team_scoped_board_lists_only_that_team(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["stranger"], 30, WHEN)

    board_id = make_board(
        client, world, sign_in,
        scope_type="team", scope_team_id=world["enterprise"].id, visibility="team",
    )
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert [e["entity_name"] for e in body["entries"]] == ["Teammate"]


def test_a_board_can_rank_teams_against_each_other(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["manager"], 15, WHEN)
    make_fact(world["metric"], world["stranger"], 30, WHEN)

    board_id = make_board(client, world, sign_in, entity_type="team")
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert [(e["entity_name"], e["value"]) for e in body["entries"]] == [
        ("SMB", "30.0000"),
        ("Enterprise", "25.0000"),
    ]


def test_display_limit_truncates_the_board_but_not_the_count(
    client, db, world, make_user, make_fact, sign_in
):
    for index in range(4):
        make_fact(world["metric"], make_user("agent", name=f"P{index}"), index + 1, WHEN)

    board_id = make_board(client, world, sign_in, display_limit=2)
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert len(body["entries"]) == 2
    assert body["total_entrants"] == 4


def test_the_viewer_is_pinned_when_they_fall_outside_the_limit(
    client, db, world, make_user, make_fact, sign_in
):
    """Being 14th on a top-10 board is exactly when a person most wants to know
    where they are."""
    for index in range(3):
        make_fact(world["metric"], make_user("agent", name=f"P{index}"), 100 + index, WHEN)
    make_fact(world["metric"], world["teammate"], 1, WHEN)

    board_id = make_board(client, world, sign_in, display_limit=2)
    sign_in(world["teammate"])
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()

    assert len(body["entries"]) == 2
    assert body["viewer_entry"]["entity_name"] == "Teammate"
    assert body["viewer_entry"]["rank"] == 4


def test_the_viewer_row_is_omitted_when_already_on_screen(
    client, db, world, make_fact, sign_in
):
    """Returning it anyway would render the same person twice."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    board_id = make_board(client, world, sign_in, display_limit=10)

    sign_in(world["teammate"])
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert body["viewer_entry"] is None


# ── Movement ─────────────────────────────────────────────────────────────────


def test_movement_reports_places_gained(client, db, world, make_fact, sign_in):
    """Positive means moved UP: rank 2 → 1 is a gain of one, and nobody says
    "improved by minus one"."""
    last_month = WHEN.replace(month=7)
    # July: Teammate ahead. August: Stranger overtakes.
    make_fact(world["metric"], world["teammate"], 100, last_month)
    make_fact(world["metric"], world["stranger"], 10, last_month)
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["stranger"], 100, WHEN)

    board_id = make_board(client, world, sign_in)
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()

    movement = {e["entity_name"]: e["movement"] for e in body["entries"]}
    assert movement["Stranger"] == 1  # 2nd -> 1st
    assert movement["Teammate"] == -1  # 1st -> 2nd


def test_an_unchanged_order_reports_no_movement(client, db, world, make_fact, sign_in):
    for when in (WHEN.replace(month=7), WHEN):
        make_fact(world["metric"], world["teammate"], 100, when)
        make_fact(world["metric"], world["stranger"], 10, when)

    board_id = make_board(client, world, sign_in)
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert {e["movement"] for e in body["entries"]} == {0}


def test_a_new_entrant_has_no_movement_rather_than_zero(
    client, db, world, make_fact, sign_in
):
    """Null and zero mean different things — "arrived" is not "did not move",
    and showing 0 would claim otherwise."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    board_id = make_board(client, world, sign_in)
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert body["entries"][0]["movement"] is None


def test_a_rolling_board_compares_against_a_non_overlapping_window(
    client, db, world, make_fact, sign_in
):
    """A rolling window's predecessor is the whole window before it. Stepping
    back one day instead would compare six of the same seven days against
    themselves and report nobody moving."""
    now = datetime.now(UTC)
    make_fact(world["metric"], world["teammate"], 5, now - timedelta(days=2))
    make_fact(world["metric"], world["stranger"], 50, now - timedelta(days=10))

    board_id = make_board(client, world, sign_in, period_type="rolling_7")
    body = client.get(f"/api/leaderboards/{board_id}/results").json()

    # Only Teammate is inside the last 7 days; Stranger is in the window before.
    assert [e["entity_name"] for e in body["entries"]] == ["Teammate"]


# ── Building and editing ─────────────────────────────────────────────────────


def test_a_manager_can_build_a_board_for_their_own_team(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/leaderboards",
        json=board_body(
            world, scope_type="team", scope_team_id=world["enterprise"].id,
            visibility="team",
        ),
    )
    assert response.status_code == 201


def test_a_manager_cannot_build_one_for_another_team(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/leaderboards",
        json=board_body(
            world, scope_type="team", scope_team_id=world["smb"].id, visibility="team"
        ),
    )
    assert response.status_code == 403


def test_a_manager_cannot_publish_to_the_whole_organization(client, db, world, sign_in):
    """That is publishing their team's numbers to everyone, which is not
    theirs to decide."""
    sign_in(world["manager"])
    response = client.post("/api/leaderboards", json=board_body(world, visibility="org"))
    assert response.status_code == 403
    assert "admin" in response.json()["detail"]


def test_an_agent_cannot_build_a_board(client, db, world, sign_in):
    sign_in(world["teammate"])
    assert client.post("/api/leaderboards", json=board_body(world)).status_code == 403


def test_a_manager_cannot_edit_someone_elses_board(client, db, world, sign_in):
    """Otherwise a published org board would be editable by everyone who can
    see it."""
    board_id = make_board(client, world, sign_in)
    sign_in(world["manager"])
    assert client.patch(
        f"/api/leaderboards/{board_id}", json={"name": "Hijacked"}
    ).status_code == 403


def test_can_edit_is_reported_so_the_client_does_not_re_derive_it(
    client, db, world, sign_in
):
    board_id = make_board(client, world, sign_in)
    sign_in(world["teammate"])
    body = client.get(f"/api/leaderboards/{board_id}/results").json()
    assert body["leaderboard"]["can_edit"] is False


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"scope_type": "team"}, 400),  # no team given
        ({"visibility": "team"}, 400),  # nothing for "team" to mean
        ({"scope_type": "organization", "scope_team_id": 1}, 400),
        ({"period_type": "custom"}, 422),  # a board pinned to a fixed past range
        # "office" stood in for an invalid entity type here. It is a real
        # one now, so this needs a value that genuinely is not.
        ({"entity_type": "region"}, 422),
        ({"scope_type": "office"}, 400),  # no office given
        ({"rank_method": "olympic"}, 422),
        ({"metric_id": 999999}, 404),
        ({"display_limit": 0}, 422),
        ({"note": "extra"}, 422),
    ],
)
def test_invalid_boards_are_refused(client, db, world, sign_in, override, expected):
    sign_in(world["admin"])
    assert client.post(
        "/api/leaderboards", json=board_body(world, **override)
    ).status_code == expected


def test_the_database_refuses_team_visibility_without_a_team(db, org, world):
    """The CHECK constraint, not just the API. An undefined audience defaults
    to nobody or everybody, and both are wrong."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        Leaderboard(
            organization_id=org.id,
            name="Bad",
            metric_definition_id=world["metric"].id,
            entity_type="user",
            scope_type="organization",
            period_type="month",
            visibility="team",
            rank_method="rank",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_switching_to_an_organization_scope_drops_the_team(client, db, world, sign_in):
    """Leaving a stale team id behind would trip the CHECK with a message
    nobody can act on."""
    board_id = make_board(
        client, world, sign_in,
        scope_type="team", scope_team_id=world["enterprise"].id, visibility="team",
    )
    body = client.patch(
        f"/api/leaderboards/{board_id}",
        json={"scope_type": "organization", "visibility": "org"},
    ).json()
    assert body["scope_team_id"] is None


def test_the_metric_can_be_changed_unlike_a_goal(client, db, world, make_metric, sign_in):
    """A board makes no claim about the past — it is a question asked fresh
    each time it is opened, so there is no history to protect."""
    other = make_metric("emails_sent")
    board_id = make_board(client, world, sign_in)
    body = client.patch(f"/api/leaderboards/{board_id}", json={"metric_id": other.id}).json()
    assert body["metric_id"] == other.id


# ── Lifecycle and audit ──────────────────────────────────────────────────────


def test_archive_hides_it_and_restore_brings_it_back(client, db, world, sign_in):
    board_id = make_board(client, world, sign_in)
    client.post(f"/api/leaderboards/{board_id}/archive")
    assert board_id not in [b["id"] for b in client.get("/api/leaderboards").json()]
    assert board_id in [
        b["id"] for b in client.get("/api/leaderboards?include_archived=true").json()
    ]
    client.post(f"/api/leaderboards/{board_id}/restore")
    assert board_id in [b["id"] for b in client.get("/api/leaderboards").json()]


def test_creating_and_deleting_are_audited(client, db, world, sign_in):
    board_id = make_board(client, world, sign_in)
    assert db.scalar(
        select(AuditLog).order_by(AuditLog.id.desc())
    ).action == "leaderboard.created"

    client.delete(f"/api/leaderboards/{board_id}")
    assert db.scalar(
        select(AuditLog).order_by(AuditLog.id.desc())
    ).action == "leaderboard.deleted"


def test_changing_who_can_see_a_board_is_audited(client, db, world, sign_in):
    """Who can see a board is the decision worth being able to trace later."""
    board_id = make_board(client, world, sign_in, visibility="private")
    client.patch(f"/api/leaderboards/{board_id}", json={"visibility": "org"})

    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == "leaderboard.visibility_changed"
    assert latest.details["visibility"] == {"from": "private", "to": "org"}


def test_a_refused_board_writes_nothing(client, db, world, sign_in):
    before = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    sign_in(world["manager"])
    assert client.post("/api/leaderboards", json=board_body(world)).status_code == 403
    assert (db.scalar(select(func.count()).select_from(AuditLog)) or 0) == before
    assert (db.scalar(select(func.count()).select_from(Leaderboard)) or 0) == 0


def test_another_organizations_board_is_not_found(client, db, org, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = Leaderboard(
        organization_id=other.id, name="Theirs",
        metric_definition_id=world["metric"].id, entity_type="user",
        scope_type="organization", period_type="month", visibility="org",
        rank_method="rank",
    )
    db.add(theirs)
    db.flush()

    sign_in(world["admin"])
    assert client.get(f"/api/leaderboards/{theirs.id}/results").status_code == 404
    assert client.patch(
        f"/api/leaderboards/{theirs.id}", json={"name": "x"}
    ).status_code == 404


def test_an_empty_board_is_not_an_error(client, db, world, sign_in):
    """A new deployment, or a quiet period. A board with nothing on it is a
    real state the UI has to render."""
    board_id = make_board(client, world, sign_in)
    body = client.get(f"/api/leaderboards/{board_id}/results").json()
    assert body["entries"] == []
    assert body["total_entrants"] == 0


def test_the_rank_method_is_honoured(client, db, world, make_user, make_fact, sign_in):
    for value in (50, 30, 30, 10):
        make_fact(world["metric"], make_user("agent"), value, WHEN)

    ranks = {}
    for method in ("rank", "dense_rank"):
        board_id = make_board(client, world, sign_in, name=method, rank_method=method)
        body = client.get(
            f"/api/leaderboards/{board_id}/results?anchor=2026-08-12"
        ).json()
        ranks[method] = [e["rank"] for e in body["entries"]]

    assert ranks["rank"] == [1, 2, 2, 4]
    assert ranks["dense_rank"] == [1, 2, 2, 3]


# ── Office boards ────────────────────────────────────────────────────────────


@pytest.fixture
def offices(db, org, world):
    from app.models import Office

    phoenix = Office(organization_id=org.id, name="Phoenix")
    dallas = Office(organization_id=org.id, name="Dallas")
    db.add_all([phoenix, dallas])
    db.flush()
    world["enterprise"].office_id = phoenix.id
    world["smb"].office_id = dallas.id
    db.flush()
    return {"phoenix": phoenix, "dallas": dallas}


def test_a_board_can_rank_offices_against_each_other(
    client, db, world, offices, make_fact, sign_in
):
    make_fact(world["metric"], world["teammate"], 10, WHEN, office_id=offices["phoenix"].id)
    make_fact(world["metric"], world["manager"], 15, WHEN, office_id=offices["phoenix"].id)
    make_fact(world["metric"], world["stranger"], 40, WHEN, office_id=offices["dallas"].id)

    board_id = make_board(client, world, sign_in, entity_type="office")
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert [(e["entity_name"], e["value"]) for e in body["entries"]] == [
        ("Dallas", "40.0000"),
        ("Phoenix", "25.0000"),
    ]


def test_an_office_scoped_board_lists_only_that_office(
    client, db, world, offices, make_fact, sign_in
):
    make_fact(world["metric"], world["teammate"], 10, WHEN, office_id=offices["phoenix"].id)
    make_fact(world["metric"], world["stranger"], 40, WHEN, office_id=offices["dallas"].id)

    board_id = make_board(
        client, world, sign_in, scope_type="office", scope_office_id=offices["phoenix"].id
    )
    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert [e["entity_name"] for e in body["entries"]] == ["Teammate"]


def test_an_office_board_uses_the_snapshot_not_the_teams_current_office(
    client, db, world, offices, make_fact, sign_in
):
    """The reason `subject_office_id` exists. A restructure must not rewrite
    which office won last quarter."""
    make_fact(world["metric"], world["teammate"], 40, WHEN, office_id=offices["phoenix"].id)
    board_id = make_board(client, world, sign_in, entity_type="office")

    world["enterprise"].office_id = offices["dallas"].id
    db.flush()

    body = client.get(f"/api/leaderboards/{board_id}/results?anchor=2026-08-12").json()
    assert [e["entity_name"] for e in body["entries"]] == ["Phoenix"]


def test_a_manager_cannot_build_an_office_board(client, db, world, offices, sign_in):
    """An office spans several teams, so scoping a board to one is a
    cross-team decision."""
    sign_in(world["manager"])
    response = client.post(
        "/api/leaderboards",
        json=board_body(
            world, scope_type="office", scope_office_id=offices["phoenix"].id,
            visibility="private",
        ),
    )
    assert response.status_code == 403


def test_switching_scope_drops_the_other_scope_id(client, db, world, offices, sign_in):
    """Exactly one survives, or the CHECK refuses with a message nobody can
    act on."""
    board_id = make_board(
        client, world, sign_in, scope_type="office", scope_office_id=offices["phoenix"].id
    )
    body = client.patch(
        f"/api/leaderboards/{board_id}",
        json={"scope_type": "team", "scope_team_id": world["enterprise"].id,
              "visibility": "team"},
    ).json()
    assert body["scope_office_id"] is None
    assert body["scope_team_id"] == world["enterprise"].id


def test_the_database_refuses_two_scope_ids_at_once(db, org, world, offices):
    from sqlalchemy.exc import IntegrityError

    db.add(
        Leaderboard(
            organization_id=org.id, name="Bad",
            metric_definition_id=world["metric"].id, entity_type="user",
            scope_type="team", scope_team_id=world["enterprise"].id,
            scope_office_id=offices["phoenix"].id,
            period_type="month", visibility="private", rank_method="rank",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_the_board_page_can_draw_it_as_the_wall_does(client, db, world, make_fact, sign_in):
    """QA-37: a podium or a race was only ever seen on a TV — the board's own
    page drew a plain table."""
    make_fact(world["metric"], world["teammate"], 9, WHEN)
    board_id = make_board(client, world, sign_in, appearance={"ranked_layout": "podium"})

    slide = client.get(
        f"/api/leaderboards/{board_id}/slide?anchor={WHEN.date().isoformat()}"
    ).json()

    assert slide["appearance"]["ranked_layout"] == "podium"
    assert [e["entity_name"] for e in slide["entries"]] == ["Teammate"]


def test_a_board_you_cannot_see_has_no_slide_either(client, db, world, sign_in):
    board_id = make_board(client, world, sign_in, visibility="private")
    sign_in(world["stranger"])

    assert client.get(f"/api/leaderboards/{board_id}/slide").status_code == 404


# ── Real numbers in the form (8.7) ───────────────────────────────────────────


def test_the_form_can_draw_its_board_with_real_numbers_and_save_nothing(
    client, db, world, sign_in, make_fact
):
    from tests.conftest import within_this_month

    make_fact(world["metric"], world["teammate"], 7, within_this_month())
    sign_in(world["admin"])
    before = db.scalar(select(func.count()).select_from(Leaderboard))

    slide = client.post(
        "/api/leaderboards/draft-slide",
        json=board_body(world, name="Unsaved", visibility="private"),
    ).json()

    assert slide["title"] == "Unsaved"
    assert [(e["entity_name"], float(e["value"])) for e in slide["entries"]][:1] == [("Teammate", 7.0)]
    assert db.scalar(select(func.count()).select_from(Leaderboard)) == before
