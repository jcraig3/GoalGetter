"""Emailing the coaching digest on a schedule.

What has to be true: a schedule sends once per slot however often the job
runs, and never a backlog; each recipient's digest is worked out in their own
scope; only admins and managers receive it; a manager can schedule it only for
themselves; a new schedule waits for its next slot; and the digest says what
the reporting page says.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app import mail, report_delivery
from app.models import Goal, ReportSchedule

# Monday 5 October 2026, 9am in New York (13:00 UTC). The fixture org is there.
MONDAY_9AM = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)


class Outbox:
    def __init__(self, ok=True):
        self.sent: list[dict] = []
        self.ok = ok

    def __call__(self, db, organization_id, *, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})
        return mail.Sent(ok=self.ok, detail="sent" if self.ok else "The mail server refused.")


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    closers = make_team("Closers")
    other = make_team("Other")
    return {
        "admin": make_user("admin", name="Bruce Wayne"),
        "manager": make_user("manager", closers, name="Diana Prince"),
        "peter": make_user("agent", closers, name="Peter Parker"),
        "clark": make_user("agent", other, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def schedule(db, org, world, **extra):
    fields = {
        "organization_id": org.id, "name": "Monday digest", "cadence": "weekly",
        "weekday": 0, "hour": 8, "recipient_ids": [world["admin"].id], "enabled": True,
        **extra,
    }
    row = ReportSchedule(**fields)
    db.add(row)
    db.flush()
    return row


def behind_goal(db, org, world, person):
    goal = Goal(
        organization_id=org.id, metric_definition_id=world["metric"].id, subject_type="user",
        subject_user_id=person.id, target_value=Decimal(100), period_type="month",
        period_anchor=date(2026, 10, 1),
    )
    db.add(goal)
    db.flush()
    return goal


# ── When it sends ───────────────────────────────────────────────────────────


def test_it_sends_once_for_its_slot(db, org, world):
    schedule(db, org, world)
    outbox = Outbox()

    report_delivery.deliver_due(db, now=MONDAY_9AM, send=outbox)
    report_delivery.deliver_due(db, now=MONDAY_9AM + timedelta(hours=1), send=outbox)

    assert len(outbox.sent) == 1


def test_it_does_not_send_before_its_hour(db, org, world):
    row = schedule(db, org, world, last_slot_at=MONDAY_9AM - timedelta(days=7, hours=1))
    outbox = Outbox()

    report_delivery.deliver_due(db, now=MONDAY_9AM - timedelta(hours=2), send=outbox)

    assert outbox.sent == []
    assert row.last_slot_at == MONDAY_9AM - timedelta(days=7, hours=1)


def test_a_long_outage_sends_one_digest_not_a_backlog(db, org, world):
    schedule(db, org, world, cadence="weekdays", last_slot_at=MONDAY_9AM - timedelta(days=10))
    outbox = Outbox()

    report_delivery.deliver_due(db, now=MONDAY_9AM, send=outbox)

    assert len(outbox.sent) == 1


def test_weekdays_skip_the_weekend():
    row = ReportSchedule(cadence="weekdays", hour=8)
    from app.models import Organization

    org = Organization(name="Acme", timezone="America/New_York")
    saturday_noon = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)

    slot = report_delivery.due_slot(org, row, saturday_noon)

    assert slot == datetime(2026, 10, 9, 12, 0, tzinfo=UTC), "Friday 8am New York"


def test_monthly_is_the_first(org):
    row = ReportSchedule(cadence="monthly", hour=8)

    slot = report_delivery.due_slot(org, row, MONDAY_9AM)

    assert slot.astimezone(report_delivery.periods.tz(org)).day == 1


def test_a_failed_send_says_why(db, org, world):
    row = schedule(db, org, world)

    report_delivery.deliver_due(db, now=MONDAY_9AM, send=Outbox(ok=False))

    assert row.last_error == "The mail server refused."
    assert row.last_sent_at is None


# ── Who gets what ───────────────────────────────────────────────────────────


def test_each_recipient_sees_their_own_scope(db, org, world):
    """The manager on an admin's schedule is sent their team, not everyone."""
    behind_goal(db, org, world, world["peter"])
    behind_goal(db, org, world, world["clark"])
    schedule(db, org, world, recipient_ids=[world["admin"].id, world["manager"].id])
    outbox = Outbox()

    report_delivery.deliver_due(db, now=MONDAY_9AM, send=outbox)

    by = {m["to"]: m["body"] for m in outbox.sent}
    assert "Clark Kent" in by[world["admin"].email]
    assert "Clark Kent" not in by[world["manager"].email]
    assert "Peter Parker" in by[world["manager"].email]


def test_an_agent_on_a_schedule_is_skipped(db, org, world):
    schedule(db, org, world, recipient_ids=[world["peter"].id])

    report_delivery.deliver_due(db, now=MONDAY_9AM, send=(outbox := Outbox()))

    assert outbox.sent == []


def test_the_digest_says_what_the_page_says(db, org, world):
    behind_goal(db, org, world, world["peter"])

    subject, body = report_delivery.digest(db, org, world["admin"], now=MONDAY_9AM)

    assert subject == "Coaching digest — Monday 5 October"
    assert "1 goal running" in body
    assert "Peter Parker — Calls Made: 0 of 100" in body
    assert "/reporting" in body


# ── The API ─────────────────────────────────────────────────────────────────


def body(world, **extra):
    return {"name": "Monday digest", "cadence": "weekly", "weekday": 0, "hour": 8,
            "recipient_ids": [world["admin"].id], **extra}


def test_an_admin_schedules_it_for_managers(client, sign_in, world):
    sign_in(world["admin"])

    made = client.post(
        "/api/reporting/schedules",
        json=body(world, recipient_ids=[world["admin"].id, world["manager"].id]),
    )

    assert made.status_code == 201, made.text
    assert {r["name"] for r in made.json()["recipients"]} == {"Bruce Wayne", "Diana Prince"}


def test_a_manager_schedules_it_only_for_themselves(client, sign_in, world):
    sign_in(world["manager"])

    reply = client.post("/api/reporting/schedules", json=body(world, recipient_ids=[world["admin"].id]))
    mine = client.post("/api/reporting/schedules", json=body(world, recipient_ids=[world["manager"].id]))

    assert reply.status_code == 403
    assert mine.status_code == 201


def test_an_agent_cannot_be_a_recipient(client, sign_in, world):
    sign_in(world["admin"])

    reply = client.post("/api/reporting/schedules", json=body(world, recipient_ids=[world["peter"].id]))

    assert reply.status_code == 422
    assert "admins and managers" in reply.json()["detail"]


def test_a_new_schedule_waits_for_its_next_slot(client, sign_in, db, world):
    """Saved at 10am for 8am: nothing goes out until the next slot."""
    sign_in(world["admin"])
    made = client.post("/api/reporting/schedules", json=body(world, cadence="weekdays")).json()
    row = db.get(ReportSchedule, made["id"])
    outbox = Outbox()

    report_delivery.deliver_due(db, now=datetime.now(UTC), send=outbox)

    assert outbox.sent == []
    assert row.last_slot_at is not None


def test_send_a_test_goes_to_me(client, sign_in, db, org, world, monkeypatch):
    sign_in(world["admin"])
    row = schedule(db, org, world, recipient_ids=[world["manager"].id])
    outbox = Outbox()
    monkeypatch.setattr(report_delivery, "_send", outbox)

    reply = client.post(f"/api/reporting/schedules/{row.id}/send").json()

    assert reply == {"ok": True, "error": None}
    assert [m["to"] for m in outbox.sent] == [world["admin"].email]


def test_agents_have_no_schedules(client, sign_in, world):
    sign_in(world["peter"])

    assert client.get("/api/reporting/schedules").status_code == 403


def test_the_email_tab_is_told_whether_mail_is_set_up(client, db, org, make_user, sign_in):
    """8.3: it said "It needs email set up" whether it was or not."""
    from app.models import SmtpConfig

    sign_in(make_user("admin", name="Admin"))
    assert client.get("/api/reporting/mail").json() == {"ready": False, "sending_from": None}

    db.add(SmtpConfig(
        organization_id=org.id, enabled=True, host="smtp.acme.test", port=587,
        security="starttls", from_address="goalgetter@acme.com", from_name="GoalGetter",
    ))
    db.commit()

    assert client.get("/api/reporting/mail").json() == {
        "ready": True, "sending_from": "goalgetter@acme.com",
    }
