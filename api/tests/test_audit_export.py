"""Exporting the activity log, and streaming it to a SIEM.

What has to be true: an export holds every entry in its range, oldest first,
as CSV or JSON Lines; a stream sends each entry once, in order, and only moves
on when the collector accepts; a new stream starts from now; Splunk gets its
own format; the address and credential are never shown back; and only an
admin can do any of it.
"""

import json
from datetime import UTC, datetime

import httpx
import pytest

from app import audit_stream, crypto
from app.models import AuditLog, AuditStream

URL = "https://siem.acme.example/collector"


class Collector:
    def __init__(self, status=200):
        self.calls: list[tuple[str, dict, bytes]] = []
        self.status = status

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, body))
        return httpx.Response(self.status)


def log(db, org, action="user.role_changed", when=None, **extra):
    row = AuditLog(
        organization_id=org.id, action=action, actor_email="bruce@acme.example",
        target_email="peter@acme.example", details={"role": {"from": "agent", "to": "manager"}},
        occurred_at=when or datetime.now(UTC), **extra,
    )
    db.add(row)
    db.flush()
    return row


def stream(db, org, **extra):
    fields = dict(
        organization_id=org.id, url_encrypted=crypto.encrypt(URL), format="json",
        header_name="Authorization", header_value_encrypted=crypto.encrypt("Bearer secret"),
        last_audit_id=0,
    )
    row = AuditStream(**{**fields, **extra})
    db.add(row)
    db.flush()
    return row


# ── Streaming ───────────────────────────────────────────────────────────────


def test_entries_are_sent_in_order_with_the_credential(db, org):
    log(db, org, "a")
    second = log(db, org, "b")
    row = stream(db, org)
    collector = Collector()

    audit_stream.push_due(db, post=collector)

    [(url, headers, body)] = collector.calls
    assert url == URL and headers["Authorization"] == "Bearer secret"
    assert [e["action"] for e in json.loads(body)["events"]] == ["a", "b"]
    assert row.last_audit_id == second.id


def test_each_entry_is_sent_once(db, org):
    log(db, org)
    stream(db, org)
    collector = Collector()

    audit_stream.push_due(db, post=collector)
    audit_stream.push_due(db, post=collector)

    assert len(collector.calls) == 1


def test_a_refusal_keeps_the_entries_for_next_time(db, org):
    entry = log(db, org)
    row = stream(db, org)

    audit_stream.push_due(db, post=Collector(status=503))

    assert row.last_audit_id == 0
    assert "503" in row.last_error

    audit_stream.push_due(db, post=(ok := Collector()))
    assert row.last_audit_id == entry.id and len(ok.calls) == 1
    assert row.last_error is None


def test_a_bad_credential_says_so(db, org):
    log(db, org)
    row = stream(db, org)

    audit_stream.push_due(db, post=Collector(status=403))

    assert "refused the credential" in row.last_error


def test_splunk_gets_its_own_format(db, org):
    log(db, org, "user.suspended")
    stream(db, org, format="splunk")
    collector = Collector()

    audit_stream.push_due(db, post=collector)

    event = json.loads(collector.calls[0][2].decode().splitlines()[0])
    assert event["sourcetype"] == "goalgetter:audit"
    assert event["event"]["action"] == "user.suspended"


def test_another_organizations_entries_are_not_sent(db, org):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC", week_starts_on=1, fiscal_year_start_month=1, currency="USD")
    db.add(other)
    db.flush()
    log(db, other, "theirs")
    stream(db, org)
    collector = Collector()

    audit_stream.push_due(db, post=collector)

    assert collector.calls == []


def test_only_https_collectors():
    with pytest.raises(audit_stream.StreamProblem):
        audit_stream.check_url("http://siem.acme.example/collector")


# ── The API ─────────────────────────────────────────────────────────────────


def test_a_new_stream_starts_from_now(client, sign_in, db, org, make_user):
    sign_in(make_user("admin"))
    old = log(db, org)

    client.put("/api/audit/stream", json={"url": URL, "header_value": "Bearer secret"})

    row = db.query(AuditStream).one()
    assert row.last_audit_id >= old.id


def test_the_address_and_credential_are_never_shown_back(client, sign_in, make_user):
    sign_in(make_user("admin"))

    saved = client.put("/api/audit/stream", json={"url": URL, "header_value": "Bearer secret"}).json()

    assert "secret" not in json.dumps(saved)
    assert saved["url_hint"] == "siem.acme.example/…lector"
    assert saved["header_set"] is True


def test_the_test_button_reports_what_happened(client, sign_in, db, org, make_user, monkeypatch):
    sign_in(make_user("admin"))
    stream(db, org)
    monkeypatch.setattr(audit_stream, "_post", Collector(status=404))

    reply = client.post("/api/audit/stream/test").json()

    assert reply["ok"] is False and "404" in reply["error"]


def test_only_an_admin_streams(client, sign_in, make_user):
    sign_in(make_user("manager"))

    assert client.put("/api/audit/stream", json={"url": URL}).status_code == 403
    assert client.get("/api/audit/export").status_code == 403


# ── Exporting ───────────────────────────────────────────────────────────────


def test_export_as_csv_oldest_first(client, sign_in, db, org, make_user):
    admin = make_user("admin")
    sign_in(admin)
    log(db, org, "first", when=datetime(2026, 9, 1, tzinfo=UTC))
    log(db, org, "second", when=datetime(2026, 9, 2, tzinfo=UTC))

    reply = client.get("/api/audit/export?format=csv")

    # The byte-order mark is on purpose: it is what makes Excel read UTF-8.
    lines = reply.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("id,time,action")
    assert [line.split(",")[2] for line in lines[1:3]] == ["first", "second"]


def test_export_as_json_lines_within_a_range(client, sign_in, db, org, make_user):
    sign_in(make_user("admin"))
    log(db, org, "august", when=datetime(2026, 8, 20, tzinfo=UTC))
    log(db, org, "september", when=datetime(2026, 9, 2, 12, tzinfo=UTC))

    reply = client.get("/api/audit/export?format=jsonl&since=2026-09-01&until=2026-09-02")

    actions = [json.loads(line)["action"] for line in reply.text.strip().splitlines()]
    assert actions == ["september"], "until includes the whole of that day"


# ── Filtering the list (8.4) ────────────────────────────────────────────────


def test_the_list_narrows_by_who_what_and_when(client, db, org, make_user, sign_in):
    sign_in(make_user("admin", name="Admin"))
    log(db, org, action="user.role_changed", when=datetime(2026, 9, 1, 12, tzinfo=UTC))
    db.add(AuditLog(
        organization_id=org.id, action="competition.created", actor_email="diana@acme.example",
        target_email=None, details=None, occurred_at=datetime(2026, 9, 20, 12, tzinfo=UTC),
    ))
    db.commit()

    def actions(**params):
        return [e["action"] for e in client.get("/api/audit", params=params).json()]

    assert actions(kind="competition") == ["competition.created"]
    assert actions(person="peter") == ["user.role_changed"]
    assert actions(person="diana") == ["competition.created"]
    assert actions(since="2026-09-10") == ["competition.created"]
    assert actions(until="2026-09-01") == ["user.role_changed"]
    assert client.get("/api/audit/kinds").json() == ["competition", "user"]


def test_the_list_names_people_rather_than_giving_addresses(client, db, org, make_user, sign_in):
    """P3-19: rows read as a list of addresses."""
    admin = sign_in(make_user("admin", name="Ada Admin"))
    peter = make_user("agent", name="Peter Parker")
    db.add(AuditLog(
        organization_id=org.id, action="user.suspended", actor_user_id=admin.id,
        actor_email=admin.email, target_user_id=peter.id, target_email=peter.email,
        details=None, occurred_at=datetime.now(UTC),
    ))
    db.commit()

    [row] = [e for e in client.get("/api/audit").json() if e["action"] == "user.suspended"]

    assert (row["actor_name"], row["target_name"]) == ("Ada Admin", "Peter Parker")
