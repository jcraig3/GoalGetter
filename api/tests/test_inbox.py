"""The admin's inbox, and reconnecting a TV from it (6.2).

What has to be true: each kind of item appears while its condition holds and
is gone once it is fixed; problems come first; only an admin can read it; and
a disconnected TV that is showing a code can be reconnected in one press, to
the channel it had, with the old row replaced.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import DataSource, DirectoryPerson, Display, Season, SyncRun


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Admin"))


def inbox(client):
    reply = client.get("/api/inbox")
    assert reply.status_code == 200, reply.json()
    return reply.json()["items"]


def kinds(client):
    return [item["kind"] for item in inbox(client)]


def source(db, org, **kwargs):
    row = DataSource(
        organization_id=org.id,
        name=kwargs.pop("name", "CRM"),
        connector="webhook",
        activated_at=datetime.now(UTC),
        **kwargs,
    )
    db.add(row)
    db.flush()
    return row


def test_an_empty_inbox_is_empty(client, admin):
    assert inbox(client) == []


def test_a_failing_source_says_why_and_goes_once_fixed(client, db, org, admin):
    crm = source(db, org, last_status="failed", last_run_at=datetime.now(UTC))
    db.add(
        SyncRun(
            organization_id=org.id,
            trigger="schedule",
            data_source_id=crm.id,
            status="failed",
            error="The password has expired.",
            started_at=datetime.now(UTC),
        )
    )
    db.commit()

    item = inbox(client)[0]
    assert item["title"] == "CRM is failing"
    assert item["detail"] == "The password has expired."
    assert item["link"] == f"/integrations/sources/{crm.id}"

    crm.last_status = "ok"
    db.commit()
    assert inbox(client) == []


def test_an_overdue_source_is_a_problem_but_a_failing_one_is_not_listed_twice(
    client, db, org, admin
):
    late = datetime.now(UTC) - timedelta(hours=3)
    source(db, org, name="Sheets", next_run_at=late)
    source(db, org, name="CRM", next_run_at=late, last_status="failed")
    db.commit()

    assert sorted(kinds(client)) == ["source_failing", "source_overdue"]


def test_people_waiting_in_the_directory(client, db, org, admin):
    for n in range(3):
        db.add(
            DirectoryPerson(
                organization_id=org.id, provider="entra", external_id=f"p{n}",
                email=f"p{n}@acme.example", status="pending",
            )
        )
    db.commit()

    item = inbox(client)[0]
    assert item["title"] == "3 people from your directory are waiting to be placed"
    assert item["link"] == "/users?tab=directory"


def test_a_tv_that_stopped_checking_in(client, db, org, admin):
    floor = client.post("/api/channels", json={"name": "Floor"}).json()
    client.post("/api/displays", json={"name": "Lobby TV", "channel_id": floor["id"]})
    tv = db.scalar(select(Display))
    tv.last_seen_at = datetime.now(UTC) - timedelta(hours=5)
    db.commit()

    item = inbox(client)[0]
    assert (item["kind"], item["severity"]) == ("tv_offline", "heads_up")
    assert item["title"] == "Lobby TV has stopped checking in"


def test_a_season_ending_soon(client, db, org, admin):
    today = datetime.now(UTC).date()
    db.add(
        Season(
            organization_id=org.id, name="Q4 2026",
            starts_on=today - timedelta(days=80), ends_on=today + timedelta(days=3),
        )
    )
    db.commit()

    item = inbox(client)[0]
    assert item["kind"] == "season_ending"
    assert item["title"].startswith("Q4 2026 ends in ")


def test_problems_come_first(client, db, org, admin):
    db.add(
        DirectoryPerson(
            organization_id=org.id, provider="entra", external_id="p",
            email="p@acme.example", status="pending",
        )
    )
    source(db, org, last_status="failed")
    db.commit()

    assert kinds(client) == ["source_failing", "directory_waiting"]


def test_only_an_admin_can_read_it(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert client.get("/api/inbox").status_code == 403


# ── A disconnected TV, reconnected from the inbox ────────────────────────────


def test_a_disconnected_tv_showing_a_code_can_be_reconnected(client, db, org, admin):
    floor = client.post("/api/channels", json={"name": "Floor"}).json()
    made = client.post(
        "/api/displays", json={"name": "Lobby TV", "channel_id": floor["id"]}
    ).json()
    old_token = made["url"].rsplit("/", 1)[-1]
    client.post(f"/api/displays/{made['id']}/revoke")

    # The screen, signed out, asks for a code and says which link it had.
    cookies = dict(client.cookies)
    client.cookies.clear()
    started = client.post(
        "/api/displays/pair/start", json={"previous_token": old_token}
    ).json()
    client.cookies.update(cookies)

    item = inbox(client)[0]
    assert item["title"] == "Lobby TV is showing a pairing code"
    assert item["action"]["path"] == f"/api/displays/{made['id']}/reconnect"

    reconnected = client.post(item["action"]["path"])
    assert reconnected.status_code == 201, reconnected.json()
    assert reconnected.json()["name"] == "Lobby TV"
    assert reconnected.json()["channel_id"] == floor["id"]

    # The screen's next poll gets its new link, and the old row is gone.
    client.cookies.clear()
    found = client.get(f"/api/displays/pair/{started['secret']}").json()
    assert found["url"].endswith(reconnected.json()["url"].rsplit("/", 1)[-1])
    assert db.get(Display, made["id"]) is None
    client.cookies.update(cookies)
    assert inbox(client) == []


def test_a_working_link_is_never_tied_to_a_code(client, db, org, admin):
    floor = client.post("/api/channels", json={"name": "Floor"}).json()
    made = client.post(
        "/api/displays", json={"name": "Lobby TV", "channel_id": floor["id"]}
    ).json()
    client.cookies.clear()
    client.post(
        "/api/displays/pair/start",
        json={"previous_token": made["url"].rsplit("/", 1)[-1]},
    )
    from app.models import DisplayPairing

    assert db.scalar(select(DisplayPairing)).previous_display_id is None


def test_reconnecting_a_tv_that_is_not_showing_a_code_says_so(client, db, org, admin):
    floor = client.post("/api/channels", json={"name": "Floor"}).json()
    made = client.post(
        "/api/displays", json={"name": "Lobby TV", "channel_id": floor["id"]}
    ).json()
    assert client.post(f"/api/displays/{made['id']}/reconnect").status_code == 409
    client.post(f"/api/displays/{made['id']}/revoke")
    assert client.post(f"/api/displays/{made['id']}/reconnect").status_code == 404


def test_a_new_screen_still_pairs_with_no_body(client, db):
    assert client.post("/api/displays/pair/start").status_code == 201


