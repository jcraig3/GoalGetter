"""Admin correction.

The only write path to metric data that a person can reach, so it gets the same
both-directions treatment as the permission tests: what each role may do, and
what it must not.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, MetricFact

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


def payload(world, **overrides):
    body = {
        "metric_id": world["metric"].id,
        "subject_user_id": world["teammate"].id,
        "value": "12",
        "occurred_at": WHEN.isoformat(),
    }
    return {**body, **overrides}


def audit_count(db) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0


# ── Creating ─────────────────────────────────────────────────────────────────


def test_an_admin_can_record_a_correction(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post("/api/metric-facts", json=payload(world))
    assert response.status_code == 201
    body = response.json()
    assert body["value"] == "12.0000"
    assert body["subject_name"] == "Teammate"


def test_a_hand_entered_row_is_always_marked(client, db, world, sign_in):
    """Both `source_type` and the corrected flag, so a hand-keyed number can
    never be mistaken for a synced one — in the UI or by the future connector
    sync."""
    sign_in(world["admin"])
    body = client.post("/api/metric-facts", json=payload(world)).json()
    assert body["source_type"] == "manual"
    assert body["corrected"] is True
    assert body["corrected_at"]


def test_the_client_cannot_claim_a_row_came_from_a_connector(client, db, world, sign_in):
    """The whole point of marking manual entries is defeated if the caller can
    label its own. `source_type` is not an accepted field."""
    sign_in(world["admin"])
    response = client.post(
        "/api/metric-facts", json=payload(world, source_type="connector")
    )
    assert response.status_code == 422


def test_the_team_snapshot_is_taken_at_write_time(client, db, world, sign_in):
    sign_in(world["admin"])
    body = client.post("/api/metric-facts", json=payload(world)).json()
    assert body["team_name"] == "Enterprise"


def test_a_correction_appears_in_the_aggregation(client, db, world, org, sign_in):
    """The point of the whole feature: the number on the leaderboard moves."""
    sign_in(world["admin"])
    client.post("/api/metric-facts", json=payload(world, value="7"))

    result = client.post(
        "/api/metrics/query",
        json={"metric_id": world["metric"].id, "period": {"type": "month", "anchor": "2026-08-12"}},
    ).json()
    assert result["total"] == "7.0000"


def test_a_decimal_value_keeps_its_precision(client, db, world, sign_in):
    sign_in(world["admin"])
    body = client.post("/api/metric-facts", json=payload(world, value="1234.5678")).json()
    assert Decimal(body["value"]) == Decimal("1234.5678")


# ── Validation ───────────────────────────────────────────────────────────────


def test_a_far_future_date_is_refused(client, db, world, sign_in):
    """A typo'd year lands somewhere nobody looks and quietly inflates a yearly
    total that has not been opened yet."""
    sign_in(world["admin"])
    response = client.post(
        "/api/metric-facts",
        json=payload(world, occurred_at=(datetime.now(UTC) + timedelta(days=400)).isoformat()),
    )
    assert response.status_code == 400
    assert "future" in response.json()["detail"]


def test_tomorrow_is_allowed(client, db, world, sign_in):
    """Not zero tolerance: a fact recorded in Sydney is already "tomorrow" for
    a server on UTC, and refusing it would make the tool unusable there."""
    sign_in(world["admin"])
    response = client.post(
        "/api/metric-facts",
        json=payload(world, occurred_at=(datetime.now(UTC) + timedelta(hours=20)).isoformat()),
    )
    assert response.status_code == 201


def test_a_date_decades_ago_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post(
        "/api/metric-facts", json=payload(world, occurred_at="1999-01-01T00:00:00+00:00")
    )
    assert response.status_code == 400


def test_backfilling_last_year_is_allowed(client, db, world, sign_in):
    """Backfilling history before switching on a connector is a legitimate
    first-day task."""
    sign_in(world["admin"])
    response = client.post(
        "/api/metric-facts",
        json=payload(world, occurred_at=(datetime.now(UTC) - timedelta(days=300)).isoformat()),
    )
    assert response.status_code == 201


def test_an_archived_metric_cannot_receive_new_data(client, db, world, sign_in):
    """It appears in no picker afterwards, so recording against it is almost
    certainly a mistake."""
    sign_in(world["admin"])
    client.post(f"/api/metrics/{world['metric'].id}/archive")
    response = client.post("/api/metric-facts", json=payload(world))
    assert response.status_code == 409
    assert "archived" in response.json()["detail"]


def test_an_unknown_metric_or_user_is_a_404(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post("/api/metric-facts", json=payload(world, metric_id=999999)).status_code == 404
    assert client.post(
        "/api/metric-facts", json=payload(world, subject_user_id=999999)
    ).status_code == 404


def test_a_hidden_user_cannot_receive_new_data(client, db, world, sign_in):
    sign_in(world["admin"])
    world["teammate"].hidden_at = datetime.now(UTC)
    db.flush()
    assert client.post("/api/metric-facts", json=payload(world)).status_code == 404


def test_unknown_fields_are_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/metric-facts", json=payload(world, note="please")
    ).status_code == 422


# ── Editing ──────────────────────────────────────────────────────────────────


@pytest.fixture
def existing(db, world, make_fact):
    return make_fact(world["metric"], world["teammate"], 10, WHEN)


def test_editing_a_value(client, db, world, existing, sign_in):
    sign_in(world["admin"])
    body = client.patch(f"/api/metric-facts/{existing.id}", json={"value": "99"}).json()
    assert Decimal(body["value"]) == Decimal(99)


def test_editing_marks_the_row_as_corrected(client, db, world, existing, sign_in):
    """The flag the connector sync will read, so a later sync does not silently
    overwrite a human's fix."""
    assert existing.corrected_at is None
    sign_in(world["admin"])
    body = client.patch(f"/api/metric-facts/{existing.id}", json={"value": "99"}).json()
    assert body["corrected"] is True

    db.refresh(existing)
    assert existing.corrected_by_user_id == world["admin"].id


def test_an_edit_that_changes_nothing_does_not_mark_the_row(client, db, world, existing, sign_in):
    """Marking an untouched row would tell the sync path to preserve something
    nobody edited."""
    sign_in(world["admin"])
    body = client.patch(f"/api/metric-facts/{existing.id}", json={"value": "10"}).json()
    assert body["corrected"] is False


def test_the_metric_and_subject_cannot_be_changed(client, db, world, existing, sign_in):
    """Moving a fact to a different person is not a correction — it is a delete
    and a create. Allowing it in one step would leave an audit row reading
    "value changed" while something else entirely happened."""
    sign_in(world["admin"])
    for field, value in (("metric_id", world["metric"].id), ("subject_user_id", world["stranger"].id)):
        assert client.patch(
            f"/api/metric-facts/{existing.id}", json={field: value}
        ).status_code == 422


def test_an_edit_moving_the_date_out_of_range_is_refused(client, db, world, existing, sign_in):
    sign_in(world["admin"])
    assert client.patch(
        f"/api/metric-facts/{existing.id}",
        json={"occurred_at": (datetime.now(UTC) + timedelta(days=400)).isoformat()},
    ).status_code == 400


def test_moving_the_date_moves_the_fact_between_periods(client, db, world, existing, sign_in):
    """Correcting `occurred_at` is the fix for a fact filed under the wrong
    day, so it has to actually change which period counts it."""
    sign_in(world["admin"])
    client.patch(
        f"/api/metric-facts/{existing.id}", json={"occurred_at": "2026-07-15T15:00:00+00:00"}
    )

    def total_for(anchor):
        return client.post(
            "/api/metrics/query",
            json={"metric_id": world["metric"].id, "period": {"type": "month", "anchor": anchor}},
        ).json()["total"]

    assert total_for("2026-08-12") == "0"
    assert Decimal(total_for("2026-07-15")) == Decimal(10)


# ── Deleting ─────────────────────────────────────────────────────────────────


def test_deleting_removes_the_row(client, db, world, existing, sign_in):
    sign_in(world["admin"])
    assert client.delete(f"/api/metric-facts/{existing.id}").status_code == 204
    assert db.get(MetricFact, existing.id) is None


def test_deleting_reduces_the_total(client, db, world, existing, sign_in):
    """The reason there is no stored `current_total` anywhere — every mutation
    path would otherwise have to remember to decrement it."""
    sign_in(world["admin"])
    client.delete(f"/api/metric-facts/{existing.id}")
    result = client.post(
        "/api/metrics/query",
        json={"metric_id": world["metric"].id, "period": {"type": "month", "anchor": "2026-08-12"}},
    ).json()
    assert result["total"] == "0"


def test_a_deletion_is_fully_reconstructable_from_the_audit_row(client, db, world, existing, sign_in):
    """A hard delete is only acceptable because nothing is actually lost."""
    sign_in(world["admin"])
    client.delete(f"/api/metric-facts/{existing.id}")

    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == "metric_fact.deleted"
    assert latest.target_email == world["teammate"].email
    assert latest.details["metric"] == "calls_made"
    assert Decimal(latest.details["value"]) == Decimal(10)
    assert latest.details["occurred_at"]


# ── Reading ──────────────────────────────────────────────────────────────────


def test_listing_returns_rows_newest_first(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 1, WHEN - timedelta(days=2))
    make_fact(world["metric"], world["teammate"], 2, WHEN)
    sign_in(world["admin"])
    values = [Decimal(r["value"]) for r in client.get("/api/metric-facts").json()]
    assert values == [Decimal(2), Decimal(1)]


def test_listing_can_filter(client, db, world, make_metric, make_fact, sign_in):
    other = make_metric("emails_sent")
    make_fact(world["metric"], world["teammate"], 1, WHEN)
    make_fact(other, world["teammate"], 2, WHEN)
    make_fact(world["metric"], world["stranger"], 3, WHEN)
    sign_in(world["admin"])

    assert len(client.get(f"/api/metric-facts?metric_id={world['metric'].id}").json()) == 2
    assert len(
        client.get(f"/api/metric-facts?subject_user_id={world['teammate'].id}").json()
    ) == 2
    assert len(client.get("/api/metric-facts?source_type=manual").json()) == 3


def test_the_list_limit_is_capped(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.get("/api/metric-facts?limit=100000").status_code == 422


# ── Permissions ──────────────────────────────────────────────────────────────


def test_an_agent_has_no_write_path_at_all(client, db, world, existing, sign_in):
    """Self-reporting is not a permission toggle that happens to be off — the
    endpoints reject agents outright. Hand-keyed numbers from the people being
    measured is exactly what makes a leaderboard worthless."""
    sign_in(world["teammate"])
    assert client.post("/api/metric-facts", json=payload(world)).status_code == 403
    assert client.patch(f"/api/metric-facts/{existing.id}", json={"value": "1"}).status_code == 403
    assert client.delete(f"/api/metric-facts/{existing.id}").status_code == 403
    assert client.get("/api/metric-facts").status_code == 403


def test_a_manager_can_correct_their_own_team(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.post("/api/metric-facts", json=payload(world)).status_code == 201


def test_a_manager_cannot_record_for_another_team(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/metric-facts", json=payload(world, subject_user_id=world["stranger"].id)
    )
    assert response.status_code == 404


def test_a_manager_cannot_edit_or_delete_another_teams_row(client, db, world, make_fact, sign_in):
    theirs = make_fact(world["metric"], world["stranger"], 10, WHEN)
    sign_in(world["manager"])
    assert client.patch(f"/api/metric-facts/{theirs.id}", json={"value": "1"}).status_code == 404
    assert client.delete(f"/api/metric-facts/{theirs.id}").status_code == 404


def test_a_manager_only_lists_rows_they_can_see(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 1, WHEN)
    make_fact(world["metric"], world["stranger"], 2, WHEN)
    sign_in(world["manager"])
    names = {r["subject_name"] for r in client.get("/api/metric-facts").json()}
    assert names == {"Teammate"}


def test_another_organizations_row_is_not_found(client, db, org, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = MetricFact(
        organization_id=other.id,
        metric_definition_id=world["metric"].id,
        subject_user_id=world["teammate"].id,
        value=Decimal(5),
        occurred_at=WHEN,
        source_type="manual",
        created_at=datetime.now(UTC),
    )
    db.add(theirs)
    db.flush()

    sign_in(world["admin"])
    assert client.patch(f"/api/metric-facts/{theirs.id}", json={"value": "1"}).status_code == 404
    assert client.delete(f"/api/metric-facts/{theirs.id}").status_code == 404


# ── Audit ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "body", "expected"),
    [
        ("post", "create", "metric_fact.created"),
        ("patch", {"value": "77"}, "metric_fact.edited"),
        ("delete", None, "metric_fact.deleted"),
    ],
)
def test_every_write_is_audited(client, db, world, existing, sign_in, method, body, expected):
    sign_in(world["admin"])
    if method == "post":
        client.post("/api/metric-facts", json=payload(world))
    elif method == "patch":
        client.patch(f"/api/metric-facts/{existing.id}", json=body)
    else:
        client.delete(f"/api/metric-facts/{existing.id}")

    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == expected
    assert latest.actor_email == world["admin"].email


def test_an_edit_records_both_sides_of_the_change(client, db, world, existing, sign_in):
    sign_in(world["admin"])
    client.patch(f"/api/metric-facts/{existing.id}", json={"value": "77"})
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert Decimal(latest.details["value"]["from"]) == Decimal(10)
    assert Decimal(latest.details["value"]["to"]) == Decimal(77)


def test_a_refused_write_records_nothing_and_changes_nothing(client, db, world, make_fact, sign_in):
    theirs = make_fact(world["metric"], world["stranger"], 10, WHEN)
    sign_in(world["manager"])
    before = audit_count(db)

    assert client.post(
        "/api/metric-facts", json=payload(world, subject_user_id=world["stranger"].id)
    ).status_code == 404
    assert client.delete(f"/api/metric-facts/{theirs.id}").status_code == 404

    assert audit_count(db) == before
    assert db.get(MetricFact, theirs.id) is not None


def test_a_no_op_edit_records_nothing(client, db, world, existing, sign_in):
    sign_in(world["admin"])
    before = audit_count(db)
    client.patch(f"/api/metric-facts/{existing.id}", json={"value": "10"})
    assert audit_count(db) == before


def test_corrections_can_be_found_by_day_and_paged(client, db, world, org, sign_in, make_fact):
    """Only the newest hundred could be seen, and nothing narrowed them by date
    (review §7)."""
    from datetime import timedelta

    sign_in(world["admin"])
    for day in range(3):
        make_fact(world["metric"], world["teammate"], day + 1, WHEN - timedelta(days=day))

    one_day = client.get(
        f"/api/metric-facts?since={(WHEN.date() - timedelta(days=1)).isoformat()}"
        f"&until={(WHEN.date() - timedelta(days=1)).isoformat()}"
    ).json()
    assert [Decimal(r["value"]) for r in one_day] == [Decimal(2)]

    second_page = client.get("/api/metric-facts?limit=1&offset=1").json()
    assert [Decimal(r["value"]) for r in second_page] == [Decimal(2)]
