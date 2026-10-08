"""Organization settings, and the things that depend on them.

These four fields are load-bearing: `timezone`, `week_starts_on`, and
`fiscal_year_start_month` decide what "this week" and "this quarter" mean, so
an invalid value here does not fail loudly — it silently re-slices every
historical figure.
"""

import pytest

from app.periods import resolve
from app.routers.organization import CURRENCIES


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def test_anyone_signed_in_can_read_the_settings(client, db, make_user, sign_in):
    """Every screen showing a date or an amount needs these — a leaderboard has
    to know which timezone "today" means. Only editing is restricted."""
    sign_in(make_user("agent"))
    assert client.get("/api/organization").status_code == 200


def test_only_an_admin_can_edit_them(client, db, make_user, make_team, sign_in):
    sign_in(make_user("manager", make_team("Enterprise")))
    assert client.patch("/api/organization", json={"name": "New"}).status_code == 403


def test_an_admin_can_edit_them(client, admin):
    response = client.patch(
        "/api/organization",
        json={"timezone": "Europe/London", "week_starts_on": 0, "fiscal_year_start_month": 4},
    )
    assert response.status_code == 200
    assert response.json()["timezone"] == "Europe/London"


@pytest.mark.parametrize(
    "payload",
    [
        {"timezone": "Mars/Olympus"},
        {"timezone": "GMT+5"},  # plausible-looking, not in the tz database
        {"timezone": ""},
        {"week_starts_on": 7},
        {"week_starts_on": -1},
        {"fiscal_year_start_month": 0},
        {"fiscal_year_start_month": 13},
        {"currency": "BTC"},
        {"currency": ""},
        {"name": ""},
    ],
)
def test_invalid_settings_are_refused(client, admin, payload):
    assert client.patch("/api/organization", json=payload).status_code in (400, 422)


def test_a_lowercase_currency_is_normalised_rather_than_refused(client, admin):
    """Forgiving input, strict storage. The stored value is always the ISO
    code, so nothing downstream has to case-fold before formatting."""
    assert client.patch("/api/organization", json={"currency": "usd"}).json()["currency"] == "USD"


def test_a_rejected_setting_changes_nothing(client, admin):
    """A partial apply here would be worse than a refusal — half-updated period
    settings re-slice history in a way nobody asked for."""
    before = client.get("/api/organization").json()
    client.patch("/api/organization", json={"name": "Valid", "timezone": "Mars/Olympus"})
    assert client.get("/api/organization").json() == before


def test_every_offered_currency_is_accepted(client, admin):
    """Guards the picker against the validator. A code in the list that the
    server rejects is a control that always fails."""
    for code in CURRENCIES:
        assert client.patch("/api/organization", json={"currency": code}).status_code == 200


def test_every_offered_timezone_actually_resolves_a_period(client, db, admin, org):
    """The settings and the period engine have to agree.

    A timezone the API accepts but ZoneInfo cannot load would raise inside
    every aggregation query rather than at the point it was set.
    """
    for timezone in ("UTC", "America/New_York", "America/Phoenix", "Europe/London",
                     "Australia/Sydney", "Asia/Kolkata", "Pacific/Chatham"):
        assert client.patch("/api/organization", json={"timezone": timezone}).status_code == 200
        db.refresh(org)
        period = resolve(org, "month")
        assert period.start < period.end


def test_changing_the_week_start_changes_what_this_week_means(client, db, admin, org):
    """The reason the Settings page warns that this re-slices past periods."""
    from datetime import date

    client.patch("/api/organization", json={"week_starts_on": 1})
    db.refresh(org)
    monday = resolve(org, "week", date(2026, 8, 12)).start

    client.patch("/api/organization", json={"week_starts_on": 0})
    db.refresh(org)
    sunday = resolve(org, "week", date(2026, 8, 12)).start

    assert sunday < monday


def test_an_omitted_field_is_left_alone(client, admin):
    before = client.get("/api/organization").json()
    updated = client.patch("/api/organization", json={"name": "Renamed"}).json()
    assert updated["name"] == "Renamed"
    assert updated["timezone"] == before["timezone"]
    assert updated["fiscal_year_start_month"] == before["fiscal_year_start_month"]


def test_settings_are_not_readable_without_a_session(client, org):
    assert client.get("/api/organization").status_code == 401
