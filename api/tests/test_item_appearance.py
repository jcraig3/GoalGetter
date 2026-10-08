"""A board, a goal or a contest carrying its own look.

**"Shark Week is blue everywhere it appears" is a different statement from "this
slide is blue".** Without this, an organization running one contest on four TVs
set its colours four times and kept them in step by hand — which is how one wall
ends up a month behind the others.

The chain, and the order it resolves in:

    organization -> item -> channel -> screen
"""

from decimal import Decimal

import pytest

from app.appearance import BASE, resolve


def make_board(client, **overrides):
    body = {
        "name": "Revenue",
        "metric_id": overrides.pop("metric_id"),
        "entity_type": "user",
        "scope_type": "organization",
        "period_type": "month",
        "visibility": "org",
        **overrides,
    }
    return client.post("/api/leaderboards", json=body)


# ── On the item ──────────────────────────────────────────────────────────────


def test_a_board_starts_with_no_opinion(client, db, org, make_user, sign_in, make_metric):
    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    db.commit()

    body = make_board(client, metric_id=metric.id).json()

    assert body["appearance"] == {}


def test_a_board_can_carry_its_own_look(client, db, org, make_user, sign_in, make_metric):
    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    db.commit()

    body = make_board(
        client, metric_id=metric.id, appearance={"ranked_layout": "podium"}
    ).json()

    assert body["appearance"] == {"ranked_layout": "podium"}


def test_only_what_was_chosen_is_kept(client, db, org, make_user, sign_in, make_metric):
    """**Sparse on disk is what "inherit" looks like.** A field nobody chose
    stays absent, so a later change to the organization's default reaches it."""
    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    db.commit()

    body = make_board(
        client, metric_id=metric.id, appearance={"primary": "#ff0000"}
    ).json()

    assert body["appearance"] == {"primary": "#ff0000"}


def test_editing_replaces_rather_than_merges(
    client, db, org, make_user, sign_in, make_metric
):
    """A merging update could not express "stop setting this and follow the
    default" — absence would mean "leave it alone"."""
    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    db.commit()
    board = make_board(
        client, metric_id=metric.id, appearance={"primary": "#ff0000"}
    ).json()

    updated = client.patch(
        f"/api/leaderboards/{board['id']}", json={"appearance": {}}
    ).json()

    assert updated["appearance"] == {}


def test_a_value_out_of_range_is_refused(
    client, db, org, make_user, sign_in, make_metric
):
    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    db.commit()

    reply = make_board(
        client, metric_id=metric.id, appearance={"font_scale": 9}
    )

    assert reply.status_code == 422


# ── The order the chain resolves in ──────────────────────────────────────────


def test_an_item_beats_the_organization():
    org = {"primary": "#000000"}
    item = {"primary": "#ff0000"}

    assert resolve(org, item).primary == "#ff0000"


def test_a_channel_beats_the_item():
    """**A venue's concerns beat a thing's own identity.** "This TV is in a
    lobby, show initials only" has to win over "this contest is themed red",
    because the legibility and privacy decisions belong to the room the screen
    is in and not to the contest being shown in it."""
    item = {"name_display": "full", "primary": "#ff0000"}
    channel = {"name_display": "first_initial"}

    out = resolve(None, item, channel)

    assert out.name_display == "first_initial"
    # And the contest keeps the part the room had no opinion about.
    assert out.primary == "#ff0000"


def test_a_single_screen_has_the_last_word():
    item = {"ranked_layout": "podium"}
    channel = {"ranked_layout": "list"}
    screen = {"ranked_layout": "podium"}

    assert resolve(None, item, channel, screen).ranked_layout == "podium"


def test_an_item_with_nothing_set_changes_nothing():
    assert resolve({"primary": "#123456"}, {}).primary == "#123456"


def test_the_whole_chain_still_produces_every_field():
    """A renderer never asks "and what if this is null?", however many layers
    were involved."""
    out = resolve({}, {}, {}, {})

    assert out.font == BASE.font
    assert out.ranked_layout == BASE.ranked_layout


# ── Restyling something that is already running ──────────────────────────────


def test_a_live_competition_can_still_be_recoloured(
    client, db, org, make_user, sign_in, make_metric
):
    """**Appearance is not a rule.** Changing a rule mid-contest makes the
    result meaningless, so it is refused — but what the screen looks like
    decides nothing about who wins, and the week it is on the wall is exactly
    when somebody wants to change it.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import Competition

    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    now = datetime.now(UTC)
    live = Competition(
        organization_id=org.id,
        name="Month-end push",
        metric_definition_id=metric.id,
        entity_type="user",
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=5),
        state="active",
    )
    db.add(live)
    db.commit()

    reply = client.patch(
        f"/api/competitions/{live.id}", json={"appearance": {"primary": "#ff0000"}}
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["appearance"] == {"primary": "#ff0000"}


def test_a_live_competition_still_refuses_a_rule_change(
    client, db, org, make_user, sign_in, make_metric
):
    """The guard this sits beside must keep working."""
    from datetime import UTC, datetime, timedelta

    from app.models import Competition

    sign_in(make_user("admin"))
    metric = make_metric("revenue")
    now = datetime.now(UTC)
    live = Competition(
        organization_id=org.id,
        name="Month-end push",
        metric_definition_id=metric.id,
        entity_type="user",
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=5),
        state="active",
    )
    db.add(live)
    db.commit()

    reply = client.patch(
        f"/api/competitions/{live.id}", json={"tie_break": "shared_rank"}
    )

    assert reply.status_code == 409


# ── A goal ───────────────────────────────────────────────────────────────────


def test_a_goal_can_carry_its_own_look(client, db, org, make_user, sign_in, make_metric):
    """A goal is a screen too, and the one most likely to want the big number:
    a revenue target reads at thirty feet, a completion rate does not."""
    sign_in(make_user("admin"))
    metric = make_metric("calls_made")
    subject = make_user("agent", name="Peter Parker")
    db.commit()

    reply = client.post(
        "/api/goals",
        json={
            "metric_id": metric.id,
            "subject_type": "user",
            "subject_id": subject.id,
            "target_value": "100",
            "period_type": "month",
            "appearance": {"goal_layout": "big_number"},
        },
    )

    assert reply.status_code == 201, reply.json()
    assert reply.json()["appearance"] == {"goal_layout": "big_number"}


def test_a_goal_starts_with_no_opinion(client, db, org, make_user, sign_in, make_metric):
    sign_in(make_user("admin"))
    metric = make_metric("calls_made")
    subject = make_user("agent", name="Clark Kent")
    db.commit()

    reply = client.post(
        "/api/goals",
        json={
            "metric_id": metric.id,
            "subject_type": "user",
            "subject_id": subject.id,
            "target_value": "100",
            "period_type": "month",
        },
    )

    assert reply.status_code == 201, reply.json()
    assert reply.json()["appearance"] == {}


def test_a_goals_look_can_be_changed_without_touching_its_target(
    client, db, org, make_user, sign_in, make_metric
):
    """**Restyling is not re-targeting.** Editing the colour must not quietly
    resend a target, or a goal somebody is halfway through moves under them."""
    sign_in(make_user("admin"))
    metric = make_metric("calls_made")
    subject = make_user("agent", name="Bruce Banner")
    db.commit()

    made = client.post(
        "/api/goals",
        json={
            "metric_id": metric.id,
            "subject_type": "user",
            "subject_id": subject.id,
            "target_value": "100",
            "period_type": "month",
        },
    ).json()

    reply = client.patch(
        f"/api/goals/{made['id']}", json={"appearance": {"primary": "#ff0000"}}
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["appearance"] == {"primary": "#ff0000"}
    assert Decimal(reply.json()["target_value"]) == Decimal("100")
