"""Hiding somebody, and the directory turning somebody off.

Two states that are deliberately not the same one, and the tests that keep them
apart. Every assertion here is about a promise made in a docstring somewhere
else — the promises are the point, and a promise with no test is a comment.

The three that matter most:

**A hidden person is not on the leaderboard.** For a long time hiding somebody
took them off the roster and left them ranked, which is the one place the word
has to mean something.

**Their team's total does not move.** A board somebody screenshotted last week
still adds up, because team numbers group on the fact rather than on whoever is
still around.

**The sync cannot undo a hide.** A decision an admin made outranks anything the
directory later reports, in both directions.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app import aggregate
from app.directory.reconcile import _deactivate_account, _reactivate_account
from app.models import DirectoryPerson, Session
from app.periods import resolve

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
ANCHOR = WHEN.date()


@pytest.fixture
def month(org):
    return resolve(org, "month", ANCHOR)


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


# ── The roster splits three ways ─────────────────────────────────────────────


def test_the_three_rosters_are_disjoint(signed_in, db, make_user):
    """Nobody appears on two of them, and everybody appears on one."""
    here = make_user("agent", name="Here")
    hidden = make_user("agent", name="Hidden")
    off = make_user("agent", name="Switched Off")
    hidden.hidden_at = datetime.now(UTC)
    off.status = "deactivated"
    db.commit()

    def names(roster):
        return {u["full_name"] for u in signed_in.get(f"/api/users?roster={roster}").json()}

    active, gone, dead = names("active"), names("hidden"), names("deactivated")

    assert "Here" in active and "Hidden" not in active and "Switched Off" not in active
    assert gone == {"Hidden"}
    assert dead == {"Switched Off"}
    assert not (active & gone) and not (active & dead) and not (gone & dead)


def test_hidden_wins_when_somebody_is_both(signed_in, db, make_user):
    """**Otherwise a hide could be undone by Entra.** Somebody sitting only on
    the Deactivated tab could be re-enabled upstream and quietly reappear on a
    board an admin had hidden them from, so the admin's decision is the one
    shown and the one to undo."""
    both = make_user("agent", name="Both")
    both.hidden_at = datetime.now(UTC)
    both.status = "deactivated"
    db.commit()

    hidden = signed_in.get("/api/users?roster=hidden").json()
    deactivated = signed_in.get("/api/users?roster=deactivated").json()

    assert [u["full_name"] for u in hidden] == ["Both"]
    assert deactivated == []


def test_the_detail_roster_finds_anybody(signed_in, db, make_user):
    """`roster=all` exists because the detail page has to render one person
    whichever roster they are on — including one being un-hidden."""
    hidden = make_user("agent", name="Hidden")
    hidden.hidden_at = datetime.now(UTC)
    db.commit()

    found = {u["full_name"] for u in signed_in.get("/api/users?roster=all").json()}

    assert "Hidden" in found


def test_a_row_says_which_of_the_two_it_is(signed_in, db, make_user):
    person = make_user("agent", name="Person")
    person.status = "deactivated"
    db.commit()

    row = next(
        u
        for u in signed_in.get("/api/users?roster=deactivated").json()
        if u["full_name"] == "Person"
    )

    assert row["deactivated"] is True
    assert row["hidden"] is False


# ── What hiding actually does ────────────────────────────────────────────────


def test_hiding_takes_them_off_the_leaderboard(
    db, org, admin, make_user, make_metric, make_fact, month
):
    """**The substance of the whole change.** `aggregate._scored` joined
    UserAccount only to put a name beside a score, so a hidden person stayed
    ranked for as long as the feature existed."""
    metric = make_metric()
    ana = make_user("agent", name="Ana")
    marco = make_user("agent", name="Marco")
    make_fact(metric, ana, 10, WHEN)
    make_fact(metric, marco, 20, WHEN)

    before = {r.subject_name for r in aggregate.run(db, org.id, admin, metric, month)}
    assert before == {"Ana", "Marco"}

    marco.hidden_at = datetime.now(UTC)
    db.flush()

    after = {r.subject_name for r in aggregate.run(db, org.id, admin, metric, month)}
    assert after == {"Ana"}


def test_hiding_does_not_move_their_teams_total(
    db, org, admin, make_user, make_team, make_metric, make_fact, month
):
    """**The chosen semantics, asserted.** Team numbers group on
    `metric_fact.subject_team_id` — a snapshot written when the fact arrived —
    so they never reach the join that drops hidden people. Removing them from
    totals as well would silently rewrite last week's team figures."""
    metric = make_metric()
    west = make_team("West")
    ana = make_user("agent", west, name="Ana")
    marco = make_user("agent", west, name="Marco")
    make_fact(metric, ana, 10, WHEN)
    make_fact(metric, marco, 20, WHEN)

    def west_total():
        rows = aggregate.run(db, org.id, admin, metric, month, group_by="team")
        return next(r.value for r in rows if r.subject_id == west.id)

    assert west_total() == Decimal(30)

    marco.hidden_at = datetime.now(UTC)
    db.flush()

    assert west_total() == Decimal(30)


def test_hiding_ends_their_sessions_and_shuts_the_door(signed_in, db, make_user):
    from app.models import Session

    person = make_user("agent", name="Person")
    now = datetime.now(UTC)
    db.add(
        Session(
            user_id=person.id,
            token_hash="x" * 64,
            expires_at=now + timedelta(days=1),
            created_at=now,
            last_used_at=now,
        )
    )
    db.commit()

    assert signed_in.post(f"/api/users/{person.id}/hide").status_code == 200

    db.refresh(person)
    assert person.hidden_at is not None
    assert person.status == "suspended"
    assert db.query(Session).filter(Session.user_id == person.id).count() == 0


def test_unhiding_brings_them_back_off_the_boards_until_reactivated(signed_in, db, make_user):
    """Two steps on purpose. Unhiding is a decision to put somebody back in the
    list, which is not a decision to let them straight back in."""
    person = make_user("agent", name="Person")
    db.commit()
    signed_in.post(f"/api/users/{person.id}/hide")

    body = signed_in.post(f"/api/users/{person.id}/unhide").json()

    assert body["hidden"] is False
    assert body["status"] == "suspended"


# ── Bulk, one action per roster ──────────────────────────────────────────────


def test_a_bulk_hide_moves_them_all_to_the_hidden_roster(signed_in, db, make_user):
    people = [make_user("agent", name=f"P{i}") for i in range(3)]
    db.commit()

    body = signed_in.post(
        "/api/users/bulk", json={"ids": [p.id for p in people], "action": "hide"}
    ).json()

    assert body["changed"] == 3
    hidden = {u["full_name"] for u in signed_in.get("/api/users?roster=hidden").json()}
    assert hidden == {"P0", "P1", "P2"}


def test_a_bulk_unhide_puts_them_all_back(signed_in, db, make_user):
    people = [make_user("agent", name=f"P{i}") for i in range(3)]
    db.commit()
    signed_in.post("/api/users/bulk", json={"ids": [p.id for p in people], "action": "hide"})

    body = signed_in.post(
        "/api/users/bulk", json={"ids": [p.id for p in people], "action": "unhide"}
    ).json()

    assert body["changed"] == 3
    assert signed_in.get("/api/users?roster=hidden").json() == []


def test_a_bulk_reactivate_only_touches_the_deactivated(signed_in, db, make_user):
    """**The guard that matters.** Letting Reactivate clear a suspension would
    turn a bulk sweep into a way of handing access back to somebody an admin had
    deliberately shut out — and the two look identical in a list."""
    off = make_user("agent", name="Switched Off")
    off.status = "deactivated"
    off.password_hash = "x"
    suspended = make_user("agent", name="Suspended")
    suspended.status = "suspended"
    db.commit()

    body = signed_in.post(
        "/api/users/bulk",
        json={"ids": [off.id, suspended.id], "action": "reactivate"},
    ).json()

    assert body["changed"] == 1
    assert any("not deactivated" in s for s in body["skipped"])
    db.refresh(off)
    db.refresh(suspended)
    assert off.status == "active"
    assert suspended.status == "suspended"


def test_reactivating_somebody_with_no_way_in_returns_them_to_invited(signed_in, db, make_user):
    """Matching `users.reactivate_user`: calling an account with no password and
    no SSO subject `active` would be a lie."""
    off = make_user("agent", name="Never Signed In")
    off.status = "deactivated"
    off.password_hash = None
    off.external_subject_id = None
    db.commit()

    signed_in.post("/api/users/bulk", json={"ids": [off.id], "action": "reactivate"})

    db.refresh(off)
    assert off.status == "invited"


# ── The sync's half, and what it refuses to touch ────────────────────────────


def _person(db, org, account, *, enabled: bool) -> DirectoryPerson:
    row = DirectoryPerson(
        organization_id=org.id,
        provider="microsoft",
        external_id=f"ext-{account.id}",
        email=account.email,
        display_name=account.full_name,
        status="approved",
        enabled=enabled,
        user_account_id=account.id,
    )
    row.account = account
    db.add(row)
    db.flush()
    return row


def test_the_directory_turning_somebody_off_turns_their_account_off(db, org, make_user):
    """The gap this closed: `directory_person.enabled` was recorded on every
    pass and nothing ever acted on it, so somebody offboarded in Entra kept
    their login and their place on the board."""
    account = make_user("agent", name="Leaver")
    row = _person(db, org, account, enabled=False)

    assert _deactivate_account(row) is True
    assert account.status == "deactivated"


def test_the_directory_cannot_unhide_somebody(db, org, make_user):
    """**Rule one.** An admin hid them; the directory does not get a vote. This
    matters in both directions — if deactivation wrote over a hide, re-enabling
    the account upstream would quietly un-hide them."""
    account = make_user("agent", name="Hidden")
    account.hidden_at = datetime.now(UTC)
    row = _person(db, org, account, enabled=False)

    assert _deactivate_account(row) is False
    assert account.hidden_at is not None

    row.enabled = True
    assert _reactivate_account(row) is False
    assert account.hidden_at is not None


def test_the_directory_cannot_lift_a_suspension(db, org, make_user):
    """A suspension means strictly more than deactivation and was somebody's
    decision. Overwriting it with a state the sync can reverse by itself would
    hand access back to somebody who was shut out."""
    account = make_user("agent", name="Suspended")
    account.status = "suspended"
    row = _person(db, org, account, enabled=False)

    assert _deactivate_account(row) is False
    assert account.status == "suspended"

    row.enabled = True
    assert _reactivate_account(row) is False
    assert account.status == "suspended"


def test_re_enabling_upstream_brings_the_account_back(db, org, make_user):
    account = make_user("agent", name="Returner")
    account.status = "deactivated"
    account.password_hash = "x"
    row = _person(db, org, account, enabled=True)

    assert _reactivate_account(row) is True
    assert account.status == "active"


def test_a_second_pass_over_a_deactivated_person_changes_nothing(db, org, make_user):
    """So a daily sync is not a daily audit entry."""
    account = make_user("agent", name="Leaver")
    account.status = "deactivated"
    row = _person(db, org, account, enabled=False)

    assert _deactivate_account(row) is False


def test_a_staged_person_with_no_account_is_not_a_crash(db, org):
    """Somebody archived before they were ever approved owns no account at all."""
    row = DirectoryPerson(
        organization_id=org.id,
        provider="microsoft",
        external_id="ext-none",
        email="nobody@acme.example",
        display_name="Nobody",
        status="pending",
        enabled=False,
    )
    db.add(row)
    db.flush()

    assert _deactivate_account(row) is False
    assert _reactivate_account(row) is False


def test_applying_an_approved_person_never_unhides_them(db, org, make_user):
    """**Rule one again, at the other end of the sync.** `apply` runs
    on every pass for every approved row; if it wrote status or hidden_at, a
    hide would last exactly until the next sync."""
    from app.directory.apply import apply

    account = make_user("agent", name="Hidden")
    account.hidden_at = datetime.now(UTC)
    account.status = "suspended"
    row = _person(db, org, account, enabled=True)

    apply(db, row, now=datetime.now(UTC))

    assert account.hidden_at is not None
    assert account.status == "suspended"
