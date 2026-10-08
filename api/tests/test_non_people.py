"""Spotting accounts that are devices, rooms or shared mailboxes.

Directory sync brings them all in, and until they are hidden every count a new
admin sees is wrong. This only suggests; hiding stays the admin's bulk action.
"""

from datetime import UTC, datetime

import pytest

from app.directory.non_people import reason_for

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("MFP 3100", "mfp3100@acme.example"),
        ("test user8", "testuser8@acme.example"),
        ("No Reply", "noreply@acme.example"),
        ("Deal Desk", "dealdesk@acme.example"),
        ("Device Admin", "deviceadmin@acme.example"),
        ("OneDrive", "onedrive@acme.example"),
        ("Client Success", "former_clientsuccess@acme.example"),
        ("Krypto", "krypto@acme.example"),
        # Q2-15: run-together words, and the company's own name.
        ("FastSourcing NTax", "fastsourcing@northwindtax.example"),
        ("Northwind Vegas", "vegas@northwindtax.example"),
        ("Jarvis Bot", "jarvisbot@acme.example"),
    ],
)
def test_things_are_suggested(name, email):
    assert reason_for(name, email) is not None


def test_the_organizations_own_name_counts_from_its_name_or_its_address():
    own = "the organization's own name"
    assert reason_for("Summit Phoenix", "phx@corp.example", "Summit Tax") == own
    assert reason_for("Northwind Vegas", "vegas@northwindtax.example") == own
    # Too short to say anything: a "Co" or an "Acme" is somebody's name too.
    assert reason_for("Wile Acme", "wile@acme.example", "Acme Co") is None


@pytest.mark.parametrize(
    ("name", "email"),
    [
        ("Oliver Queen", "oqueen@acme.example"),
        ("Jean-Paul Valley", "jpvalley@acme.example"),
        ("Selina Kyle", "skyle@acme.example"),
    ],
)
def test_people_with_ordinary_names_are_not(name, email):
    assert reason_for(name, email) is None


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Admin Person"))


def listed(client):
    return [p["full_name"] for p in client.get("/api/users/non-people").json()]


def test_a_printer_with_nothing_else_is_listed_with_its_reason(client, admin, make_user):
    make_user("agent", name="MFP 3100")

    rows = client.get("/api/users/non-people").json()

    assert [(r["full_name"], r["reason"]) for r in rows] == [("MFP 3100", "a number in the name")]


def test_anything_that_marks_a_person_outweighs_the_name(
    client, db, admin, make_user, make_metric, make_fact
):
    """A number recorded or a job title is somebody having treated the account
    as a person — "Krypto" with a sale is a person called Krypto."""
    titled = make_user("agent", name="TS")
    titled.job_title = "Closer"
    sold = make_user("agent", name="Krypto")
    make_fact(make_metric(), sold, 1, WHEN)
    db.flush()

    assert listed(client) == []


def test_a_team_alone_does_not_make_a_person(client, admin, make_user, make_team):
    """Q2-15: "Jarvis Bot" was put on a team so it could dial."""
    make_user("agent", make_team(), name="Scans")

    assert listed(client) == ["Scans"]


def test_a_stand_in_keeps_the_title_it_was_copied_with(client, db, admin, make_user):
    """Q2-15: test accounts are copies of real ones, title and all."""
    for name in ("Test User 69", "Jarvis Bot", "Pat Closer"):
        user = make_user("agent", name=name)
        user.job_title = "Closer"
        user.department = "Sales"
    db.flush()

    assert listed(client) == ["Jarvis Bot", "Test User 69"]


def test_hidden_accounts_are_not_suggested_again(client, db, admin, make_user):
    printer = make_user("agent", name="MFP 3100")
    printer.hidden_at = WHEN
    db.flush()

    assert listed(client) == []


def test_only_an_admin_sees_the_suggestions(client, make_user, sign_in):
    sign_in(make_user("manager"))

    assert client.get("/api/users/non-people").status_code == 403


def test_an_admin_or_manager_was_made_one_on_purpose(client, admin, make_user):
    make_user("manager", name="Device Admin")

    assert listed(client) == []
