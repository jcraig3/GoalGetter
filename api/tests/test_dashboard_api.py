"""The role-aware dashboard.

Three different questions wearing one page: how am I doing, who needs me, and
is this thing working. The tests are mostly about keeping them apart.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from calendar import monthrange

from tests.conftest import within_this_month

from app.dashboard import QUIET_DAYS, health
from app.models import (
    Channel,
    DataSource,
    Organization,
    SyncRun,
)

#: Inside the current month, whatever month that is. A literal here read
#: correctly in August and silently excluded itself from every "this month"
#: board on the first of September. See `conftest.within_this_month`.
WHEN = within_this_month()


def _channel(db, org) -> Channel:
    """A display has to point at a channel. These tests are about whether one
    is alive, not about what it plays, so any channel will do."""
    channel = db.scalar(select(Channel)) if "select" in globals() else None
    if channel is None:
        channel = Channel(organization_id=org.id, name="Wall")
        db.add(channel)
        db.flush()
    return channel


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
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


def make_board(client, world, sign_in, **overrides):
    sign_in(world["admin"])
    response = client.post(
        "/api/leaderboards",
        json={
            "name": "Board",
            "metric_id": world["metric"].id,
            "period_type": "month",
            "visibility": "org",
            **overrides,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def dashboard(client):
    return client.get("/api/dashboard").json()


# ── Placements ───────────────────────────────────────────────────────────────


def test_your_own_position_on_a_board_you_can_see(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["stranger"], 30, WHEN)
    make_board(client, world, sign_in, name="Calls")

    sign_in(world["teammate"])
    placements = dashboard(client)["placements"]
    assert len(placements) == 1
    assert (placements[0]["rank"], placements[0]["total_entrants"]) == (2, 2)


def test_a_board_you_do_not_appear_on_is_skipped(client, db, world, make_fact, sign_in):
    """A row saying you are nowhere is discouraging and tells you nothing you
    can act on."""
    make_fact(world["metric"], world["stranger"], 30, WHEN)
    make_board(client, world, sign_in)

    sign_in(world["teammate"])
    assert dashboard(client)["placements"] == []


def test_a_board_you_cannot_open_never_appears(client, db, world, make_fact, sign_in):
    """The dashboard must not become a way around a board's visibility."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_board(client, world, sign_in, name="Secret", visibility="private")

    sign_in(world["teammate"])
    assert dashboard(client)["placements"] == []


def test_the_best_position_comes_first(client, db, world, make_fact, make_metric, sign_in):
    """The one worth showing at the top is the one they are doing well on."""
    other = make_metric("emails_sent")
    make_fact(world["metric"], world["teammate"], 5, WHEN)
    make_fact(world["metric"], world["stranger"], 50, WHEN)
    make_fact(other, world["teammate"], 50, WHEN)
    make_fact(other, world["stranger"], 5, WHEN)

    make_board(client, world, sign_in, name="Calls")
    make_board(client, world, sign_in, name="Emails", metric_id=other.id)

    sign_in(world["teammate"])
    ranks = [p["rank"] for p in dashboard(client)["placements"]]
    assert ranks == sorted(ranks)


def test_a_placement_is_not_truncated_by_display_limit(
    client, db, world, make_user, make_fact, sign_in
):
    """Being 14th on a top-3 board is exactly when you most want to be told."""
    for index in range(3):
        make_fact(world["metric"], make_user("agent", name=f"P{index}"), 100 + index, WHEN)
    make_fact(world["metric"], world["teammate"], 1, WHEN)

    make_board(client, world, sign_in, display_limit=2)
    sign_in(world["teammate"])
    placements = dashboard(client)["placements"]
    assert placements[0]["rank"] == 4


def test_a_team_board_places_you_by_your_team(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["stranger"], 30, WHEN)
    make_board(client, world, sign_in, entity_type="team")

    sign_in(world["teammate"])
    placements = dashboard(client)["placements"]
    # Enterprise is second to SMB, and that is the row that is "theirs".
    assert placements[0]["rank"] == 2


# ── Attention ────────────────────────────────────────────────────────────────


def test_a_goal_behind_pace_is_surfaced(client, db, world, make_fact, sign_in):
    sign_in(world["admin"])
    client.post(
        "/api/goals",
        json={
            "metric_id": world["metric"].id,
            "subject_type": "user",
            "subject_id": world["teammate"].id,
            "target_value": "10000",
            "period_type": "year",
        },
    )
    sign_in(world["teammate"])
    kinds = {a["kind"] for a in dashboard(client)["attention"]}
    assert "goals_behind" in kinds


def test_quiet_people_are_surfaced_to_a_manager(client, db, world, make_fact, sign_in):
    """Someone with no data for a week is on leave, missing from a sync, or has
    stopped — all three worth knowing before the month closes."""
    make_fact(world["metric"], world["teammate"], 10, datetime.now(UTC))
    # `stranger` has nothing at all, but is on another team.

    sign_in(world["manager"])
    items = {a["kind"]: a for a in dashboard(client)["attention"]}
    # Nobody in the manager's scope is quiet — teammate recorded today.
    assert "quiet_people" not in items

    sign_in(world["admin"])
    items = {a["kind"]: a for a in dashboard(client)["attention"]}
    assert items["quiet_people"]["count"] == 1  # stranger


def test_someone_who_recorded_recently_is_not_quiet(client, db, world, make_fact, sign_in):
    for person in ("teammate", "stranger"):
        make_fact(world["metric"], world[person], 10, datetime.now(UTC))
    sign_in(world["admin"])
    assert "quiet_people" not in {a["kind"] for a in dashboard(client)["attention"]}


def test_the_quiet_window_is_generous(client, db, world, make_fact, sign_in):
    """A warning that fires because somebody took Friday off is a warning
    people learn to ignore."""
    recent = datetime.now(UTC) - timedelta(days=QUIET_DAYS - 2)
    for person in ("teammate", "stranger"):
        make_fact(world["metric"], world[person], 10, recent)
    sign_in(world["admin"])
    assert "quiet_people" not in {a["kind"] for a in dashboard(client)["attention"]}


def test_an_agent_is_not_told_about_other_people(client, db, world, sign_in):
    """Their dashboard answers "how am I doing", not "who needs managing"."""
    sign_in(world["teammate"])
    kinds = {a["kind"] for a in dashboard(client)["attention"]}
    assert "quiet_people" not in kinds
    assert "unassigned_agents" not in kinds


def test_unassigned_agents_are_an_admin_concern(client, db, world, make_user, sign_in):
    """They are missing from every team board, which is a structural problem
    only an admin can fix."""
    make_user("agent", None, name="Unplaced")

    sign_in(world["admin"])
    items = {a["kind"]: a for a in dashboard(client)["attention"]}
    assert items["unassigned_agents"]["count"] == 1

    sign_in(world["manager"])
    assert "unassigned_agents" not in {a["kind"] for a in dashboard(client)["attention"]}


def test_attention_items_carry_a_kind_and_a_link(client, db, world, make_user, sign_in):
    """The client styles and routes from `kind` rather than parsing prose, so
    the wording can change without breaking anything."""
    make_user("agent", None)
    sign_in(world["admin"])
    for item in dashboard(client)["attention"]:
        assert item["kind"] and item["link"].startswith("/")
        assert item["count"] > 0


def test_nothing_wrong_means_an_empty_list(client, db, world, make_fact, sign_in):
    for person in ("teammate", "stranger"):
        make_fact(world["metric"], world[person], 10, datetime.now(UTC))
    sign_in(world["admin"])
    assert dashboard(client)["attention"] == []


# ── Health ───────────────────────────────────────────────────────────────────


def test_health_is_admin_only(client, db, world, sign_in):
    """Operations, not motivation. An agent has no use for it and no way to act
    on it."""
    sign_in(world["admin"])
    assert dashboard(client)["health"] is not None

    for role in ("manager", "teammate"):
        sign_in(world[role])
        assert dashboard(client)["health"] is None


def test_health_reports_when_data_last_arrived(client, db, world, make_fact, sign_in):
    """The question from the integrations doc: a board showing three-day-old
    figures because a sync is failing looks exactly like one showing current
    figures. The staleness has to be visible somewhere a person looks."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    sign_in(world["admin"])
    health = dashboard(client)["health"]
    assert health["last_fact_at"] is not None
    assert health["active_people"] == 4


def test_health_counts_metrics_that_have_never_received_data(
    client, db, world, make_metric, sign_in
):
    """A metric nobody is feeding is a connector that was never wired up."""
    make_metric("never_fed")
    sign_in(world["admin"])
    assert dashboard(client)["health"]["metrics_without_data"] >= 1


def test_health_counts_offline_displays(client, db, org, world, sign_in):
    """A screen that stopped polling is a screen showing stale numbers to a
    room, and nobody in that room can tell."""
    from app.models import Display

    db.add(
        Display(
            organization_id=org.id, name="Unplugged", token="x" * 32, channel_id=_channel(db, org).id,
            last_seen_at=datetime.now(UTC) - timedelta(days=3),
        )
    )
    db.flush()
    sign_in(world["admin"])
    assert dashboard(client)["health"]["displays_offline"] == 1


def test_a_live_display_is_not_counted_as_offline(client, db, org, world, sign_in):
    from app.models import Display

    db.add(
        Display(
            organization_id=org.id, name="Live", token="y" * 32, channel_id=_channel(db, org).id,
            last_seen_at=datetime.now(UTC),
        )
    )
    db.flush()
    sign_in(world["admin"])
    assert dashboard(client)["health"]["displays_offline"] == 0


def test_a_revoked_display_is_not_counted_as_offline(client, db, org, world, sign_in):
    """It was switched off on purpose. Reporting it forever would train people
    to ignore the number."""
    from app.models import Display

    db.add(
        Display(
            organization_id=org.id, name="Retired", token="z" * 32, channel_id=_channel(db, org).id,
            last_seen_at=None, revoked_at=datetime.now(UTC),
        )
    )
    db.flush()
    sign_in(world["admin"])
    assert dashboard(client)["health"]["displays_offline"] == 0


# ── Boundaries ───────────────────────────────────────────────────────────────


def test_the_dashboard_needs_a_session(client, world):
    assert client.get("/api/dashboard").status_code == 401


def test_another_organizations_data_never_appears(client, db, org, world, make_fact, sign_in):
    from app.models import Organization, UserAccount

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    for index in range(3):
        db.add(
            UserAccount(
                organization_id=other.id, email=f"o{index}@other.example",
                full_name=f"Other {index}", org_role="agent", status="active",
            )
        )
    db.flush()

    sign_in(world["admin"])
    # Four people in this organization, not seven.
    assert dashboard(client)["health"]["active_people"] == 4


def test_placements_agree_with_the_board_itself(client, db, world, make_fact, sign_in):
    """The dashboard runs the same board service the leaderboard pages use, so
    a rank here and a rank there cannot disagree."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["stranger"], 30, WHEN)
    board_id = make_board(client, world, sign_in)

    sign_in(world["teammate"])
    placement = dashboard(client)["placements"][0]
    board = client.get(
        f"/api/leaderboards/{board_id}/results?anchor={WHEN.date().isoformat()}"
    ).json()
    mine = next(
        e for e in board["entries"] if e["entity_name"] == "Teammate"
    )
    assert placement["rank"] == mine["rank"]
    assert Decimal(placement["value"]) == Decimal(mine["value"])


def test_nothing_yet_is_not_a_placement(client, db, world, make_fact, sign_in):
    """A source that writes a row for everybody put an admin who never sells at
    "39th of 137 · $0.00" on Home — nowhere, with a number attached."""
    make_fact(world["metric"], world["teammate"], 0, WHEN)
    make_fact(world["metric"], world["stranger"], 30, WHEN)
    make_board(client, world, sign_in)

    sign_in(world["teammate"])

    assert dashboard(client)["placements"] == []


# ── Sparklines ───────────────────────────────────────────────────────────────


def test_a_placement_carries_the_viewers_own_line(
    client, db, world, sign_in, make_fact
):
    """Not the leader's line and not the board's total. A placement answers
    "how am I doing", so the shape beside it has to be the viewer's."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["stranger"], 90, WHEN)
    make_board(client, world, sign_in)

    sign_in(world["teammate"])
    placement = dashboard(client)["placements"][0]

    assert Decimal(placement["trend"]["points"][-1]["value"]) == Decimal(
        placement["value"]
    )


def test_a_placement_line_closes_on_the_figure_the_rank_came_from(
    client, db, world, sign_in, make_fact
):
    """The anti-drift check, at the API level."""
    for value in (5, 5, 7):
        make_fact(world["metric"], world["teammate"], value, WHEN)
    make_board(client, world, sign_in)

    sign_in(world["teammate"])
    placement = dashboard(client)["placements"][0]

    assert placement["trend"]["cumulative"] is True
    assert Decimal(placement["trend"]["points"][-1]["value"]) == Decimal(17)


def test_a_placement_line_spans_the_boards_period(
    client, db, world, sign_in, make_fact
):
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_board(client, world, sign_in)

    sign_in(world["teammate"])
    placement = dashboard(client)["placements"][0]

    assert placement["trend"]["unit"] == "day"
    # One point per day of *this* month. Hard-coding 31 was correct in August and
    # wrong in every thirty-day month after it.
    days = monthrange(WHEN.year, WHEN.month)[1]
    assert len(placement["trend"]["points"]) == days


def test_a_team_boards_line_is_the_whole_teams(client, db, world, sign_in, make_fact):
    """An agent's default scope is only themselves, so without the explicit
    override the line would cover less than the rank printed beside it — a
    chart quietly disagreeing with the number it sits next to."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    make_fact(world["metric"], world["manager"], 25, WHEN)
    make_board(client, world, sign_in, entity_type="team")

    sign_in(world["teammate"])
    placement = dashboard(client)["placements"][0]

    assert Decimal(placement["trend"]["points"][-1]["value"]) == Decimal(35)
    assert Decimal(placement["value"]) == Decimal(35)


# ── Data source health on the admin dashboard ────────────────────────────────
#
# Promised by `10-dashboards.md` — "data source sync status and last-error
# (Phase 3)" — and missing until the end of the phase. `metrics_without_data` was
# the closest thing and is not the same question.


def _source(db, org, **kwargs):
    defaults = dict(
        organization_id=org.id,
        name="CRM",
        connector="webhook",
        activated_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    row = DataSource(**defaults)
    db.add(row)
    db.flush()
    return row


def test_a_failing_source_is_reported_on_the_dashboard(db, org):
    """**A broken sync is invisible on a leaderboard** — it looks exactly like a
    quiet week. This is the one page where an admin should not have to go hunting."""
    _source(db, org, last_status="failed")

    assert health(db, org).sources_failing == 1


def test_a_working_source_is_not_reported(db, org):
    _source(db, org, last_status="ok")

    assert health(db, org).sources_failing == 0


def test_a_partial_source_is_not_counted_as_failing(db, org):
    """`partial` is rows written *and* rows held back — the normal first-sync
    result. Calling it failed trains somebody to ignore the word."""
    _source(db, org, last_status="partial")

    assert health(db, org).sources_failing == 0


def test_a_draft_nobody_finished_is_not_reported_as_broken(db, org):
    """The same rule the sources list follows: an abandoned click is not an alarm."""
    _source(db, org, last_status="failed", activated_at=None)

    assert health(db, org).sources_failing == 0


def test_a_removed_source_is_not_reported_as_broken(db, org):
    _source(db, org, last_status="failed", archived_at=datetime.now(UTC))

    assert health(db, org).sources_failing == 0


def test_a_source_that_missed_its_run_is_reported_as_overdue(db, org):
    """A separate count from failing, because the fixes differ: an overdue source
    usually means the background job is not running at all, which no per-source
    error would ever say."""
    _source(db, org, next_run_at=datetime.now(UTC) - timedelta(hours=6))

    assert health(db, org).sources_overdue == 1


def test_a_source_due_a_moment_ago_is_not_overdue_yet(db, org):
    """One interval of grace. The job pass that would have run it is itself hourly,
    so a source is not a problem at sixty-one minutes — and a number that flickers
    every tick is a number an admin learns to ignore."""
    _source(db, org, next_run_at=datetime.now(UTC) - timedelta(minutes=5))

    assert health(db, org).sources_overdue == 0


def test_a_source_that_reads_once_is_never_overdue(db, org):
    """It has no schedule to miss (QA-12). Even one written before its next run
    was cleared, whose date is long past."""
    _source(db, org, interval_minutes=0, next_run_at=datetime.now(UTC) - timedelta(days=7))

    assert health(db, org).sources_overdue == 0


def test_a_source_that_has_never_run_is_not_overdue(db, org):
    """It has just been switched on and the first pass is minutes away."""
    _source(db, org, next_run_at=None)

    assert health(db, org).sources_overdue == 0


def test_the_most_recent_failures_own_words_come_back(db, org):
    """"Something went wrong" sends somebody hunting. The provider's own sentence
    tells them where to go."""
    source = _source(db, org, last_status="failed")
    db.add_all(
        [
            SyncRun(
                organization_id=org.id,
                data_source_id=source.id,
                trigger="schedule",
                status="failed",
                started_at=datetime.now(UTC) - timedelta(hours=2),
                error="An older problem.",
            ),
            SyncRun(
                organization_id=org.id,
                data_source_id=source.id,
                trigger="schedule",
                status="failed",
                started_at=datetime.now(UTC),
                error="The credential was refused.",
            ),
        ]
    )
    db.flush()

    assert health(db, org).source_error == "The credential was refused."


def test_no_error_is_reported_when_nothing_has_failed(db, org):
    source = _source(db, org, last_status="ok")
    db.add(
        SyncRun(
            organization_id=org.id,
            data_source_id=source.id,
            trigger="schedule",
            status="ok",
            started_at=datetime.now(UTC),
        )
    )
    db.flush()

    assert health(db, org).source_error is None


def test_another_organizations_broken_source_is_not_reported(db, org):
    other = Organization(name="Other")
    db.add(other)
    db.flush()
    _source(db, other, last_status="failed")

    assert health(db, org).sources_failing == 0
