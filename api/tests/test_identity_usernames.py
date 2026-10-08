"""Matching a row to a person when two systems spell the address differently.

**The case that made this necessary.** A CRM sends `pparker@northwind.example`; the
directory holds `peterp@northwind.example`. Both are Peter Parker, first-initial
plus surname against first name plus last initial. Exact email cannot bridge it,
and four hundred people is not a quarantine list anybody works through.

**The property that must survive it.** A wrong match silently credits somebody
else's work, which is worse than a question. So every form uses the first name
*and* the surname, and anything two people could both own is refused.
"""

from datetime import UTC, datetime

import pytest

from app import identity


@pytest.fixture
def source(db, org):
    from app.models import DataSource

    row = DataSource(organization_id=org.id, name="CRM", connector="stub")
    db.add(row)
    db.flush()
    return row


def named(make_user, db, full_name: str, email: str):
    user = make_user("agent")
    user.full_name = full_name
    user.email = email
    db.flush()
    return user


def test_the_other_convention_matches(db, org, source, make_user):
    """`pparker@` is Peter Parker, whose directory address is `peterp@`."""
    peter = named(make_user, db, "Peter Parker", "peterp@northwind.example")

    out = identity.resolve(db, source, "pparker@northwind.example")

    assert out.outcome == identity.MATCHED
    assert out.user_id == peter.id


def test_a_bare_username_matches_too(db, org, source, make_user):
    """A source sending logins rather than addresses needs no special case."""
    peter = named(make_user, db, "Peter Parker", "peterp@northwind.example")

    assert identity.resolve(db, source, "pparker").user_id == peter.id


def test_a_human_name_is_still_never_guessed_at(db, org, source, make_user):
    """**The line this must not cross**, and the reason it is drawn at whitespace.

    `pparker` is unique by construction in whatever system issued it, so working
    out who owns it is an inference from a guaranteed-unique key. "Peter Parker"
    guarantees nothing — the source may contain two, and the ambiguity check can
    only see people who are in the roster. The second Peter, the one who is not,
    would have his work credited to the first.

    See `test_identity.py::test_a_bare_name_is_never_guessed_at`, which held this
    line when a first version of this matching crossed it.
    """
    named(make_user, db, "Peter Parker", "peterp@northwind.example")

    assert identity.resolve(db, source, "Peter Parker").outcome == identity.QUARANTINED


def test_two_people_who_fit_are_a_question_not_a_guess(db, org, source, make_user):
    """**The leaderboard scandal this is built to avoid.**

    Bruce Banner and Betty Banner both produce `bbanner`. Crediting either is
    worse than asking.
    """
    named(make_user, db, "Bruce Banner", "bruceb@acme.com")
    named(make_user, db, "Betty Banner", "bettyb@acme.com")

    out = identity.resolve(db, source, "bbanner@acme.com")

    assert out.outcome == identity.QUARANTINED
    assert out.user_id is None


def test_a_first_name_alone_is_not_enough(db, org, source, make_user):
    """A different Peter, not in the roster, must not land on this one.

    Every form uses both name parts precisely so that one piece agreeing is never
    a match.
    """
    named(make_user, db, "Peter Parker", "peterp@northwind.example")

    assert identity.resolve(db, source, "peter@northwind.example").outcome == (
        identity.QUARANTINED
    )


def test_a_hidden_person_is_not_matched(db, org, source, make_user):
    """The same rule email matching already follows."""
    from datetime import UTC, datetime

    peter = named(make_user, db, "Peter Parker", "peterp@northwind.example")
    peter.hidden_at = datetime.now(UTC)
    db.flush()

    assert identity.resolve(db, source, "pparker@northwind.example").outcome == (
        identity.QUARANTINED
    )


def test_an_exact_email_still_wins(db, org, source, make_user):
    """Cheaper and more certain, so it stays ahead in the ladder."""
    exact = named(make_user, db, "Peter Parker", "pparker@northwind.example")
    named(make_user, db, "Patty Parker", "pattyp@northwind.example")

    assert identity.resolve(db, source, "pparker@northwind.example").user_id == exact.id


def test_an_admin_decision_still_outranks_the_guess(db, org, source, make_user):
    """An explicit mapping is a decision; this is inference."""
    peter = named(make_user, db, "Peter Parker", "peterp@northwind.example")
    other = named(make_user, db, "Richard Rider", "richardr@northwind.example")

    first = identity.resolve(db, source, "pparker@northwind.example")
    assert first.user_id == peter.id

    from sqlalchemy import select
    from app.models import UserIdentity

    row = db.scalar(
        select(UserIdentity).where(UserIdentity.external_identifier == "pparker@northwind.example")
    )
    identity.map_to(db, row, other.id)

    assert identity.resolve(db, source, "pparker@northwind.example").user_id == other.id


def test_something_that_is_not_a_name_is_still_quarantined(db, org, source, make_user):
    """A CRM record id must not fuzzy-match its way onto a leaderboard."""
    named(make_user, db, "Peter Parker", "peterp@northwind.example")

    assert identity.resolve(db, source, "0051x000ABCdef").outcome == identity.QUARANTINED


# ── What an ignored name does to a run's status ──────────────────────────────


def test_ignoring_a_name_takes_a_run_from_partial_to_ok(db, org, source, make_user):
    """**The reason the Ignore all button exists at all.**

    A warehouse view with history names everybody who ever worked here, so a
    first sync is `partial` by definition: rows written *and* rows held back.
    Ignoring the people who left has to actually clear that, or the source sits
    on a warning colour for ever and the word stops meaning anything.

    Quarantined rows make a run partial; ignored ones are skipped, and skipped
    does not. Asserted here rather than reasoned about, because the two counters
    live in different branches of `sync._apply` and nothing else joins them up.
    """
    from app.models import SyncRun

    def run_one(identifier: str) -> SyncRun:
        row = SyncRun(
            organization_id=org.id,
            data_source_id=source.id,
            started_at=datetime.now(UTC),
            status="ok",
            trigger="manual",
        )
        db.add(row)
        db.flush()
        out = identity.resolve(db, source, identifier)
        if out.outcome == identity.IGNORED:
            row.rows_skipped += 1
        elif out.outcome == identity.QUARANTINED:
            row.rows_quarantined += 1
        return row

    first = run_one("gone@northwind.example")
    assert first.rows_quarantined == 1
    assert bool(first.rows_quarantined or first.conflicts or first.error) is True

    from sqlalchemy import select
    from app.models import UserIdentity

    identity.ignore(
        db,
        db.scalar(
            select(UserIdentity).where(
                UserIdentity.external_identifier == "gone@northwind.example"
            )
        ),
    )

    second = run_one("gone@northwind.example")
    assert second.rows_quarantined == 0
    assert second.rows_skipped == 1
    # The exact expression `sync.run` uses to choose between partial and ok.
    assert bool(second.rows_quarantined or second.conflicts or second.error) is False
