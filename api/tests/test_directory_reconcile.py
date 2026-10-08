"""Turning a snapshot of a directory into rows, without overwriting decisions.

**Reconcile, not append** — which is the whole reason directory sync is a sibling of
the metric pipeline rather than a connector on it. There is no watermark here: a
provider hands back the entire current membership, and what is *absent* from it is
how somebody who left the company is noticed.

Three rules, and most of what follows is one of them stated precisely:

1. a decision an admin made outranks anything the directory says;
2. nobody is created or changed silently;
3. absence means archived, never deleted.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.directory.reconcile import reconcile
from app.directory.rules import Person, Rule
from app.models import DirectoryPerson

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def person(external_id="e1", **kwargs) -> Person:
    defaults = dict(
        email=f"{external_id}@acme.com",
        display_name="Sam Rivera",
        job_title="Account Executive",
        department="Sales",
        office_location="Phoenix",
    )
    defaults.update(kwargs)
    return Person(external_id=external_id, **defaults)


@pytest.fixture
def run(db, org):
    def _run(people, rules=None, *, now=NOW, provider="microsoft"):
        return reconcile(
            db,
            organization_id=org.id,
            provider=provider,
            people=list(people),
            rules=rules,
            now=now,
        )

    return _run


@pytest.fixture
def rows(db, org):
    def _rows():
        return {
            row.external_id: row
            for row in db.query(DirectoryPerson)
            .filter_by(organization_id=org.id)
            .all()
        }

    return _rows


# ── Arriving ─────────────────────────────────────────────────────────────────


# Somebody new arrives **pending**, never as an account. That is the whole design —
# sync proposes, an admin disposes — and it is what makes "people are added by hand"
# the default without a second mode to maintain.


def test_a_new_person_is_recorded_and_waits(run, rows):
    outcome = run([person()])

    assert outcome.created == 1
    assert outcome.pending == 1
    assert rows()["e1"].status == "pending"
    assert rows()["e1"].user_account_id is None


def test_everything_the_directory_said_is_kept(run, rows):
    """The rules read these, and an admin reads them too when deciding. Losing the
    department would make every rule about departments silently match nobody."""
    run([person(department="Support", job_title="Agent", office_location="Dallas",
                groups=("Dallas Support",))])

    row = rows()["e1"]

    assert row.department == "Support"
    assert row.job_title == "Agent"
    assert row.office_location == "Dallas"
    assert row.groups == ["Dallas Support"]


def test_somebody_already_disabled_arrives_archived_not_pending(run, rows):
    """The first sync of a company with years of history would otherwise propose
    every leaver they have ever had, burying the actual joiners."""
    outcome = run([person(enabled=False)])

    assert rows()["e1"].status == "archived"
    assert rows()["e1"].archived_at == NOW
    assert outcome.pending == 0


def test_reading_the_same_directory_twice_creates_nothing_new(run, rows):
    """Reconcile runs on a schedule. If it were not idempotent, an hourly sync
    would produce a duplicate of everybody every hour."""
    run([person()])
    outcome = run([person()], now=LATER)

    assert outcome.created == 0
    assert outcome.updated == 1
    assert len(rows()) == 1


def test_two_providers_do_not_merge_people_who_share_an_id(run, rows, db, org):
    """Ids are only unique within the directory that issued them."""
    run([person()], provider="microsoft")
    run([person()], provider="google")

    assert db.query(DirectoryPerson).filter_by(organization_id=org.id).count() == 2


# ── Rule 1: a decision outranks the directory ────────────────────────────────


def test_somebody_declined_stays_declined(run, rows):
    """**The rule that decides whether anybody trusts this feature.** Without it,
    declining somebody lasts until the next sync and they are proposed again every
    hour for ever."""
    run([person()])
    rows()["e1"].status = "declined"

    outcome = run([person()], now=LATER)

    assert rows()["e1"].status == "declined"
    # And they are not counted as waiting on anybody. The count drives a badge on
    # the tab, so including declined people would show work that does not exist —
    # which is how a badge gets ignored.
    assert outcome.pending == 0


def test_somebody_still_pending_is_still_counted_as_waiting(run, rows):
    """The other side of the same count. Somebody seen again before anybody got to
    them is still waiting, and dropping them from the total would make the badge
    disappear while the list stayed full."""
    run([person()])

    outcome = run([person()], now=LATER)

    assert rows()["e1"].status == "pending"
    assert outcome.pending == 1


def test_somebody_approved_stays_approved_when_nothing_changed(run, rows):
    run([person()])
    rows()["e1"].status = "approved"

    run([person()], now=LATER)

    assert rows()["e1"].status == "approved"


def test_their_details_are_still_updated_even_when_the_decision_is_not(run, rows):
    """A decision is about *whether* somebody belongs here, not about what their
    job title is. Freezing the details would leave an approved person's department
    wrong for ever."""
    run([person(department="Sales")])
    rows()["e1"].status = "declined"

    run([person(department="Support")], now=LATER)

    assert rows()["e1"].status == "declined"
    assert rows()["e1"].department == "Support"


# ── Rule 2: nothing changes silently ─────────────────────────────────────────


def test_an_approved_person_whose_rule_now_points_elsewhere_goes_back_for_review(
    run, rows, db, make_user, make_team
):
    """**A promotion must not silently change what somebody is.** Reassigning them
    without a human seeing it is exactly the behaviour that makes an admin distrust
    every number on the board afterwards."""
    sales, support = make_team("Sales"), make_team("Support")
    account = make_user("agent", sales)
    run([person()])
    row = rows()["e1"]
    row.status = "approved"
    row.user_account_id = account.id
    db.flush()

    outcome = run(
        [person(department="Support")],
        rules=[Rule(department="Support", team_id=support.id)],
        now=LATER,
    )

    assert outcome.needs_review == 1
    assert rows()["e1"].status == "pending"
    assert "changed" in rows()["e1"].pending_reason


def test_an_approved_person_the_rules_still_agree_with_is_left_alone(
    run, rows, db, make_user, make_team
):
    sales = make_team("Sales")
    account = make_user("agent", sales)
    run([person()])
    row = rows()["e1"]
    row.status = "approved"
    row.user_account_id = account.id
    db.flush()

    outcome = run(
        [person()], rules=[Rule(department="Sales", team_id=sales.id)], now=LATER
    )

    assert outcome.needs_review == 0
    assert rows()["e1"].status == "approved"


def test_deleting_a_rule_does_not_send_everybody_back_for_review(
    run, rows, db, make_user, make_team
):
    """An unplaced result is not a difference. Otherwise removing one rule would
    put every person it used to place into the pending list at once — a stampede
    rather than a signal, and an admin would clear it without reading it."""
    sales = make_team("Sales")
    account = make_user("agent", sales)
    run([person()])
    row = rows()["e1"]
    row.status = "approved"
    row.user_account_id = account.id
    db.flush()

    outcome = run([person()], rules=[], now=LATER)

    assert outcome.needs_review == 0
    assert rows()["e1"].status == "approved"


def test_a_changed_role_sends_somebody_back_even_when_the_team_is_the_same(
    run, rows, db, make_user, make_team
):
    """Both halves of a placement are compared. A promotion within the same team —
    agent to manager — is exactly the change most likely to happen and the one a
    team-only comparison would miss."""
    sales = make_team("Sales")
    account = make_user("agent", sales)
    run([person()])
    row = rows()["e1"]
    row.status = "approved"
    row.user_account_id = account.id
    db.flush()

    outcome = run(
        [person()],
        rules=[Rule(department="Sales", team_id=sales.id, role="manager")],
        now=LATER,
    )

    assert outcome.needs_review == 1


def test_an_approved_person_with_no_account_is_not_compared(run, rows):
    """Approved but never applied — the window between deciding and the next sync.
    There is nothing to differ from yet."""
    run([person()])
    rows()["e1"].status = "approved"

    outcome = run(
        [person()], rules=[Rule(department="Sales", team_id=99)], now=LATER
    )

    assert outcome.needs_review == 0


# ── Rule 3: absence means archived ───────────────────────────────────────────


def test_somebody_the_directory_stopped_returning_is_archived(run, rows):
    """The reason this reconciles rather than appends: no directory API has a field
    meaning "this person no longer exists". Absence is the signal."""
    run([person("e1"), person("e2")])

    outcome = run([person("e1")], now=LATER)

    assert outcome.archived == 1
    assert rows()["e2"].status == "archived"
    assert rows()["e2"].archived_at == LATER
    assert rows()["e1"].status == "pending"


def test_somebody_disabled_at_the_far_end_is_archived(run, rows):
    """Still returned, but switched off. Not an admin's preference being
    overridden — the account no longer exists."""
    run([person()])
    rows()["e1"].status = "approved"

    outcome = run([person(enabled=False)], now=LATER)

    assert outcome.archived == 1
    assert rows()["e1"].status == "archived"


def test_archiving_happens_even_to_somebody_who_was_declined(run, rows):
    """Declined and gone is still gone. Leaving them declined for ever would mean
    the list of declined people grew without bound and never told the truth."""
    run([person()])
    rows()["e1"].status = "declined"

    run([], now=LATER)

    assert rows()["e1"].status == "archived"


def test_archiving_is_not_repeated_on_every_later_sync(run, rows):
    """Otherwise the run summary would report the same leavers as newly archived
    every hour, and the number would mean nothing."""
    run([person()])
    run([], now=LATER)

    outcome = run([], now=LATER + timedelta(hours=1))

    assert outcome.archived == 0
    # Still there, and still archived. Tidying away a row the sync has stopped
    # caring about would take its history with it.
    assert rows()["e1"].status == "archived"


def test_somebody_disabled_and_still_returned_is_archived_once_not_every_sync(
    run, rows
):
    """A disabled account keeps being returned by the directory for as long as it
    exists. Counting it as newly archived on every pass would make the run summary
    permanently report leavers that left months ago."""
    run([person()])
    first = run([person(enabled=False)], now=LATER)

    second = run([person(enabled=False)], now=LATER + timedelta(hours=1))

    assert first.archived == 1
    assert second.archived == 0
    assert rows()["e1"].status == "archived"


def test_nobody_is_ever_deleted_however_many_syncs_pass(run, rows, db, org):
    """Anything attached to a person still says where it came from.

    Run three times on purpose: the first archives them, and it is the *later*
    passes — the ones that see an already-archived row and have nothing to do —
    where a tidy-up would be tempting and would quietly take their history.
    """
    run([person()])
    run([], now=LATER)
    run([], now=LATER + timedelta(hours=1))

    assert db.query(DirectoryPerson).filter_by(organization_id=org.id).count() == 1


def test_somebody_who_comes_back_is_proposed_again_rather_than_restored_silently(
    run, rows
):
    """Leaving and rejoining is exactly the moment a human should look — a
    contractor returning on different terms, or somebody rehired into another
    team."""
    run([person()])
    run([], now=LATER)

    outcome = run([person()], now=LATER + timedelta(hours=1))

    assert outcome.restored == 1
    assert rows()["e1"].status == "pending"
    assert rows()["e1"].archived_at is None
    assert "Returned" in rows()["e1"].pending_reason


# ── An empty directory ───────────────────────────────────────────────────────


def test_an_empty_first_sync_does_nothing_rather_than_failing(run, rows):
    outcome = run([])

    assert outcome.created == 0
    assert outcome.archived == 0
    assert rows() == {}


def test_last_seen_is_stamped_so_a_stale_row_can_be_spotted(run, rows):
    run([person()])

    run([person()], now=LATER)

    assert rows()["e1"].last_seen_at == LATER
