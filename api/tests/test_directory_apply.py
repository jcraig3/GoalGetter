"""Turning an approved directory row into a real account.

Reconcile proposes; this is the disposing half, and it runs only because an admin
decided somebody belongs here.

The rule that governs all of it: **a human edit wins, and the difference is flagged
for as long as it differs.** Overwriting an admin's correction on the next sync is
unacceptable — they changed it for a reason the directory does not know. Silently
diverging from the tenant for ever is its own problem, because *"why does this say
Sam when Entra says Samantha"* is a question somebody eventually asks.
"""

from datetime import UTC, datetime

import pytest

from app.directory.apply import ApplyProblem, apply, differences
from app.directory.rules import Rule
from app.models import DirectoryPerson, UserAccount

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


@pytest.fixture
def approved(db, org):
    def _approved(**kwargs):
        defaults = dict(
            organization_id=org.id,
            provider="microsoft",
            external_id="e1",
            email="sam@acme.com",
            display_name="Sam Rivera",
            job_title="Account Executive",
            department="Sales",
            office_location="Phoenix",
            groups=[],
            enabled=True,
            status="approved",
        )
        defaults.update(kwargs)
        row = DirectoryPerson(**defaults)
        db.add(row)
        db.flush()
        return row

    return _approved


# ── Creating somebody ────────────────────────────────────────────────────────


def test_an_approved_person_gets_an_account(db, approved):
    row = approved()

    account = apply(db, row, now=NOW)

    assert account.email == "sam@acme.com"
    assert account.full_name == "Sam Rivera"
    assert row.user_account_id == account.id


def test_the_rules_decide_the_role_and_the_team(db, approved, make_team):
    sales = make_team("Sales")

    account = apply(
        db,
        approved(),
        rules=[Rule(department="Sales", role="manager", team_id=sales.id)],
        now=NOW,
    )

    assert account.org_role == "manager"
    assert account.team_id == sales.id


def test_somebody_no_rule_places_still_gets_an_account_with_no_team(db, approved):
    """`team_id` is nullable precisely so this works. An admin approved them, so
    they belong here — where exactly is a separate question, and the Needs
    assignment list is where it gets answered."""
    account = apply(db, approved(), now=NOW)

    assert account.team_id is None
    assert account.org_role == "agent"


def test_the_email_is_stored_folded_so_it_matches_everywhere_else(db, approved):
    """Every other lookup in the product compares addresses in lower case."""
    account = apply(db, approved(email="Sam.Rivera@ACME.com"), now=NOW)

    assert account.email == "sam.rivera@acme.com"


# ── Not creating somebody twice ──────────────────────────────────────────────


def test_an_existing_account_is_linked_rather_than_duplicated(db, org, approved, make_user):
    """**The worst outcome available is two rows for one human**, each carrying half
    their numbers. Somebody added by hand last month and now appearing in the
    directory is the same person."""
    existing = make_user("agent")
    existing.email = "sam@acme.com"
    db.flush()

    account = apply(db, approved(), now=NOW)

    assert account.id == existing.id
    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == 1


def test_matching_an_existing_account_ignores_case(db, org, approved, make_user):
    """A directory will happily return `Sam.Rivera@acme.com` for somebody invited
    here as `sam.rivera@acme.com`."""
    existing = make_user("agent")
    existing.email = "sam.rivera@acme.com"
    db.flush()

    account = apply(db, approved(email="Sam.Rivera@ACME.com"), now=NOW)

    assert account.id == existing.id


def test_linking_leaves_the_existing_account_exactly_as_it_was(
    db, approved, make_user, make_team
):
    """**The directory has no better claim than the admin who typed it.** A person
    added by hand, put on a team and given a role keeps all three — otherwise
    connecting a directory would silently rewrite everybody already here."""
    support = make_team("Support")
    existing = make_user("manager", support, name="Samantha Rivera")
    existing.email = "sam@acme.com"
    db.flush()

    apply(
        db,
        approved(),
        rules=[Rule(department="Sales", role="agent", team_id=None)],
        now=NOW,
    )

    assert existing.full_name == "Samantha Rivera"
    assert existing.org_role == "manager"
    assert existing.team_id == support.id


def test_applying_twice_changes_nothing_the_second_time(db, org, approved, make_team):
    """A sync runs on a schedule, so this happens constantly."""
    sales = make_team("Sales")
    row = approved()
    rules = [Rule(department="Sales", team_id=sales.id)]

    first = apply(db, row, rules=rules, now=NOW)
    second = apply(db, row, rules=rules, now=NOW)

    assert first.id == second.id
    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == 1


# ── Refusing ─────────────────────────────────────────────────────────────────


def test_somebody_not_decided_about_is_refused(db, approved):
    """The whole design rests on nobody becoming an account without a decision, so
    this is checked here as well as at the caller.

    Two decisions add somebody now — visible and hidden — so the refusal names
    the act rather than one of the two statuses."""
    row = approved(status="pending")

    with pytest.raises(ApplyProblem, match="decided to add"):
        apply(db, row, now=NOW)


def test_somebody_with_no_email_is_refused_with_their_name_in_the_message(db, approved):
    """An account is identified by its address everywhere else in the product. One
    without is a row nobody can sign in to, invite, or match a metric row against."""
    row = approved(email="", display_name="Sam Rivera")

    with pytest.raises(ApplyProblem, match="Sam Rivera"):
        apply(db, row, now=NOW)


def test_an_email_of_only_spaces_is_refused_too(db, approved):
    with pytest.raises(ApplyProblem, match="no email"):
        apply(db, approved(email="   "), now=NOW)


# ── Where the two sides disagree ─────────────────────────────────────────────


def test_an_account_matching_the_directory_reports_no_difference(db, approved):
    row = approved()
    apply(db, row, now=NOW)

    assert differences(row) == []


def test_a_renamed_person_is_flagged_rather_than_overwritten(db, approved):
    """Both halves matter and neither alone is right: the admin's name stays, *and*
    the disagreement is visible."""
    row = approved()
    account = apply(db, row, now=NOW)

    account.full_name = "Sam"
    db.flush()
    row.display_name = "Samantha Rivera"

    found = differences(row)

    assert account.full_name == "Sam"
    assert [(d.field, d.ours, d.theirs) for d in found] == [
        ("full_name", "Sam", "Samantha Rivera")
    ]


def test_a_changed_address_is_flagged_too(db, approved):
    """Both compared fields matter. Somebody's address changing at the far end —
    a marriage, a rebrand of the company domain — is the one most likely to break
    the link between them and their metric rows, so it must be visible."""
    row = approved()
    account = apply(db, row, now=NOW)

    row.email = "samantha@acme.com"

    found = differences(row)

    assert account.email == "sam@acme.com"
    assert [(d.field, d.theirs) for d in found] == [("email", "samantha@acme.com")]


def test_a_field_the_directory_left_empty_is_not_a_disagreement(db, approved):
    """Half of every directory's optional fields are empty. Reporting each as a
    conflict would bury the real ones."""
    row = approved()
    apply(db, row, now=NOW)
    row.display_name = ""

    assert differences(row) == []


def test_somebody_with_no_account_yet_has_nothing_to_disagree_with(db, approved):
    assert differences(approved()) == []


def test_the_difference_is_computed_rather_than_stored(db, approved):
    """So it cannot go stale. A stored flag would need clearing when either side
    changed, and the clearing is the part that gets forgotten."""
    row = approved()
    account = apply(db, row, now=NOW)

    account.full_name = "Sam"
    db.flush()
    row.display_name = "Samantha Rivera"
    assert len(differences(row)) == 1

    # Fixed at the app's end: the disagreement goes away by itself.
    account.full_name = "Samantha Rivera"
    db.flush()

    assert differences(row) == []


# ── The floor ────────────────────────────────────────────────────────────────


def test_somebody_no_rule_matches_arrives_as_an_agent(db, approved):
    """**A security floor, not a convenience.**

    `place` defaults to agent and `test_directory_rules` pins that — but
    `default_role` is a *parameter*, and every caller passing the right one is a
    separate fact from the default existing. This asserts the end of the pipeline:
    the role on the account that actually gets created, which is the thing that
    grants access.

    A caller that started passing `manager` would elevate exactly the population
    nobody has written a rule for, and therefore nobody has looked at.
    """
    account = apply(
        db,
        approved(department="Finance"),
        rules=[Rule(department="Sales", role="manager")],
        now=NOW,
    )

    assert account.org_role == "agent"
    assert account.team_id is None


def test_everybody_arrives_as_an_agent_when_there_are_no_rules(db, approved):
    """The state a directory is in the moment sync is switched on: no rules written
    yet, and a tenant's worth of people arriving. They get the least access there
    is, and an admin raises it from there rather than lowering it."""
    account = apply(db, approved(), rules=[], now=NOW)

    assert account.org_role == "agent"


def test_a_rule_matching_with_no_role_named_still_lands_on_agent(db, approved):
    """A rule may name only a team — "Sales goes in the Sales team" — and say
    nothing about access. The blank is the default, never an absence of one."""
    account = apply(
        db,
        approved(),
        rules=[Rule(department="Sales", team_id=None)],
        now=NOW,
    )

    assert account.org_role == "agent"


def test_somebody_from_the_directory_arrives_able_to_sign_in(db, approved):
    """**`invited` did not just add a pointless step, it closed the door.**

    `routers/sso.py` refuses any account whose status is not `active`, so an
    account created `invited` locked the person out of the single sign-on they
    were expected to arrive through. Auto-provisioned SSO accounts have always
    been created `active` for exactly this reason.

    There is no invitation to send either: these people are already in the
    tenant, and an invitation is an email telling somebody an account exists.
    """
    account = apply(db, approved(), now=NOW)

    assert account.status == "active"
    # And no password, so single sign-on is the only way in — which is the point.
    assert account.password_hash is None


def test_a_hidden_decision_also_becomes_an_account(db, approved):
    """The other half of `ADDS_AN_ACCOUNT`. A refusal here would mean the panel
    offering a button that silently does nothing."""
    row = approved(status="hidden")

    account = apply(db, row, now=NOW)

    assert account.id is not None
    assert account.hidden_at is not None


def test_a_declined_person_never_becomes_an_account(db, approved):
    row = approved(status="declined")

    with pytest.raises(ApplyProblem):
        apply(db, row, now=NOW)
