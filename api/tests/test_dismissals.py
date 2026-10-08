"""Dismissing notifications: the bell, the Inbox and Home's banners (Phase 12).

The bell's rows are events, so a dismissal is a column on them. The Inbox and
Home's banners are worked out on every request, so a dismissal remembers what
the item was about, and the item comes back when that changes or the next day.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import DirectoryPerson, Dismissal, Display, Notification


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Admin"))


def inbox(client):
    reply = client.get("/api/inbox")
    assert reply.status_code == 200, reply.json()
    return reply.json()


def dark_tv(client, db, name="Lobby TV"):
    floor = client.post("/api/channels", json={"name": f"{name} channel"}).json()
    client.post("/api/displays", json={"name": name, "channel_id": floor["id"]})
    tv = db.scalar(select(Display).where(Display.name == name))
    tv.last_seen_at = datetime.now(UTC) - timedelta(hours=5)
    db.commit()
    return tv


def waiting(db, org, n):
    for i in range(n):
        db.add(DirectoryPerson(
            organization_id=org.id, provider="entra", external_id=f"w{i}",
            email=f"w{i}@acme.example", status="pending",
        ))
    db.commit()


# ── The Inbox ────────────────────────────────────────────────────────────────


def test_a_dismissed_item_is_put_away_not_lost(client, db, admin):
    tv = dark_tv(client, db)
    [item] = inbox(client)["items"]
    assert item["key"] == f"tv_offline:{tv.id}"
    # What it is about is the server's to work out, not the page's to send.
    assert "fingerprint" not in item

    assert client.post("/api/inbox/dismiss", json={"key": item["key"]}).status_code == 204

    body = inbox(client)
    assert body["items"] == []
    assert [d["key"] for d in body["dismissed"]] == [item["key"]]
    # The badge counts what still asks for attention.
    assert body["count"] == 0


def test_only_that_one_goes(client, db, admin):
    lobby = dark_tv(client, db, "Lobby TV")
    dark_tv(client, db, "Floor TV")
    client.post("/api/inbox/dismiss", json={"key": f"tv_offline:{lobby.id}"})
    assert [i["title"] for i in inbox(client)["items"]] == ["Floor TV has stopped checking in"]


def test_it_comes_back_when_what_it_was_about_changes(client, db, admin):
    tv = dark_tv(client, db)
    client.post("/api/inbox/dismiss", json={"key": f"tv_offline:{tv.id}"})

    # Seen again, and gone dark again: a new story.
    tv.last_seen_at = datetime.now(UTC) - timedelta(hours=4)
    db.commit()

    assert len(inbox(client)["items"]) == 1


def test_it_comes_back_the_next_day(client, db, admin):
    """A dismissal is "not today", never "never"."""
    tv = dark_tv(client, db)
    client.post("/api/inbox/dismiss", json={"key": f"tv_offline:{tv.id}"})
    row = db.scalar(select(Dismissal))
    row.dismissed_on -= timedelta(days=1)
    db.commit()

    assert len(inbox(client)["items"]) == 1


def test_a_count_comes_back_only_when_it_grows(client, db, org, admin):
    waiting(db, org, 3)
    client.post("/api/inbox/dismiss", json={"key": "directory_waiting"})

    person = db.scalar(select(DirectoryPerson))
    person.status = "declined"
    db.commit()
    assert inbox(client)["items"] == []  # three to two is not news

    waiting_more = DirectoryPerson(
        organization_id=org.id, provider="entra", external_id="new",
        email="new@acme.example", status="pending",
    )
    db.add(waiting_more)
    db.add(DirectoryPerson(
        organization_id=org.id, provider="entra", external_id="new2",
        email="new2@acme.example", status="pending",
    ))
    db.commit()
    assert [i["key"] for i in inbox(client)["items"]] == ["directory_waiting"]


def test_one_admin_putting_it_away_leaves_it_for_another(client, db, make_user, sign_in, admin):
    tv = dark_tv(client, db)
    client.post("/api/inbox/dismiss", json={"key": f"tv_offline:{tv.id}"})

    sign_in(make_user("admin", name="Other admin"))
    assert len(inbox(client)["items"]) == 1


def test_undo_brings_it_back(client, db, admin):
    tv = dark_tv(client, db)
    key = f"tv_offline:{tv.id}"
    client.post("/api/inbox/dismiss", json={"key": key})
    assert client.post("/api/inbox/restore", json={"key": key}).status_code == 204
    assert len(inbox(client)["items"]) == 1


def test_nothing_to_put_away_once_fixed(client, admin):
    assert client.post("/api/inbox/dismiss", json={"key": "tv_offline:999"}).status_code == 404


def test_not_for_anybody_but_an_admin(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert client.post("/api/inbox/dismiss", json={"key": "directory_waiting"}).status_code == 403


# ── Home's banners ───────────────────────────────────────────────────────────


def test_a_home_banner_is_put_away_until_it_grows(client, db, org, make_user, admin):
    make_user("agent", name="Loose")  # on no team
    attention = client.get("/api/dashboard").json()["attention"]
    assert "unassigned_agents" in {a["kind"] for a in attention}

    assert client.post(
        "/api/dashboard/attention/dismiss", json={"kind": "unassigned_agents"}
    ).status_code == 204
    body = client.get("/api/dashboard").json()
    assert "unassigned_agents" not in {a["kind"] for a in body["attention"]}
    assert [a["kind"] for a in body["attention_dismissed"]] == ["unassigned_agents"]

    make_user("agent", name="Another")
    body = client.get("/api/dashboard").json()
    assert "unassigned_agents" in {a["kind"] for a in body["attention"]}


def test_a_home_banner_can_be_brought_back(client, make_user, admin):
    make_user("agent", name="Loose")
    client.post("/api/dashboard/attention/dismiss", json={"kind": "unassigned_agents"})
    client.post("/api/dashboard/attention/restore", json={"kind": "unassigned_agents"})
    assert "unassigned_agents" in {a["kind"] for a in client.get("/api/dashboard").json()["attention"]}


# ── The bell ─────────────────────────────────────────────────────────────────


def note(db, org, user, title):
    row = Notification(
        organization_id=org.id, user_id=user.id, event_key="recognition",
        # A distinct subject each: detected events latch once per subject.
        subject_type="goal", subject_id=sum(map(ord, title)), title=title,
    )
    db.add(row)
    db.commit()
    return row


def bell(client):
    return client.get("/api/notifications").json()


def test_clearing_one_from_the_bell(client, db, org, admin):
    gone = note(db, org, admin, "Gone")
    note(db, org, admin, "Kept")

    assert client.post(f"/api/notifications/{gone.id}/dismiss").status_code == 204

    body = bell(client)
    assert [n["title"] for n in body["notifications"]] == ["Kept"]
    # Read as well: a badge counting something not in the list explains nothing.
    assert body["unread"] == 1
    db.refresh(gone)
    assert gone.read_at is not None


def test_clear_all_and_undo(client, db, org, admin):
    a = note(db, org, admin, "A")
    b = note(db, org, admin, "B")

    cleared = client.post("/api/notifications/dismiss-all").json()["ids"]
    assert sorted(cleared) == sorted([a.id, b.id])
    assert bell(client) == {"notifications": [], "unread": 0}

    client.post("/api/notifications/restore", json={"ids": cleared})
    body = bell(client)
    assert {n["title"] for n in body["notifications"]} == {"A", "B"}
    assert body["unread"] == 0  # they had seen them


def test_somebody_elses_cannot_be_cleared(client, db, org, make_user, admin):
    theirs = note(db, org, make_user("agent"), "Theirs")
    assert client.post(f"/api/notifications/{theirs.id}/dismiss").status_code == 404
    client.post("/api/notifications/restore", json={"ids": [theirs.id]})
    db.refresh(theirs)
    assert theirs.dismissed_at is None


def test_cleared_from_the_bell_is_still_the_win_everywhere_else(client, db, org, admin):
    """Clearing your bell is about your list, not whether it happened."""
    row = note(db, org, admin, "Won")
    client.post(f"/api/notifications/{row.id}/dismiss")
    db.refresh(row)
    assert db.get(Notification, row.id) is not None


# ── One notice, both places (P4-9) ───────────────────────────────────────────


@pytest.fixture
def two_quiet_sources(db, org, make_metric, make_user):
    from tests.test_staleness import NOW, source

    from app.models import MetricFact

    metric = make_metric("deals")
    person = make_user("agent", name="Ann")
    made = []
    for name in ("Excel", "Sheets"):
        src = source(db, org, name=name)
        db.add(MetricFact(
            organization_id=org.id, metric_definition_id=metric.id, subject_user_id=person.id,
            value=1, occurred_at=NOW - timedelta(days=12), source_type="connector",
            data_source_id=src.id,
        ))
        made.append(src)
    db.commit()
    return made


def kinds_on_home(client):
    return {a["kind"] for a in client.get("/api/dashboard").json()["attention"]}


def test_putting_home_away_puts_the_inbox_away_too(client, admin, two_quiet_sources):
    assert "data_stale" in kinds_on_home(client)
    client.post("/api/dashboard/attention/dismiss", json={"kind": "data_stale"})
    assert [i["kind"] for i in inbox(client)["items"]] == []
    assert {d["kind"] for d in inbox(client)["dismissed"]} == {"source_quiet"}


def test_home_goes_once_every_source_it_speaks_for_is_put_away(client, admin, two_quiet_sources):
    excel, sheets = two_quiet_sources
    client.post("/api/inbox/dismiss", json={"key": f"source_quiet:{excel.id}"})
    # Sheets is still showing in the Inbox, so the banner still has something to say.
    assert "data_stale" in kinds_on_home(client)

    client.post("/api/inbox/dismiss", json={"key": f"source_quiet:{sheets.id}"})
    assert "data_stale" not in kinds_on_home(client)


def test_bringing_one_back_brings_back_the_other(client, admin, two_quiet_sources):
    excel, _ = two_quiet_sources
    client.post("/api/dashboard/attention/dismiss", json={"kind": "data_stale"})
    client.post("/api/inbox/restore", json={"key": f"source_quiet:{excel.id}"})
    assert "data_stale" in kinds_on_home(client)

    client.post("/api/dashboard/attention/dismiss", json={"kind": "data_stale"})
    client.post("/api/dashboard/attention/restore", json={"kind": "data_stale"})
    assert {i["kind"] for i in inbox(client)["items"]} == {"source_quiet"}
