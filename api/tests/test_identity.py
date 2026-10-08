"""Whose number is this, and what happens when nobody knows.

The interesting half is the middle outcome. Matching is easy; the decision worth
testing is that an unrecognised name **waits** rather than becoming a new account
or vanishing.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import identity
from app.models import DataSource, UserAccount, UserIdentity


@pytest.fixture
def source(db, org):
    row = DataSource(organization_id=org.id, name="CRM", connector="stub")
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def other_source(db, org):
    row = DataSource(organization_id=org.id, name="Sheet", connector="stub")
    db.add(row)
    db.flush()
    return row


def identities(db, source):
    return list(
        db.scalars(
            select(UserIdentity).where(UserIdentity.data_source_id == source.id)
        ).all()
    )


# ── Matching ─────────────────────────────────────────────────────────────────


def test_an_email_matches_a_user(db, source, make_user):
    """The common path, and the reason a deployment using SSO barely sees a
    quarantine list: the CRM's email is the address they sign in with."""
    alice = make_user("agent", None, name="Alice")

    got = identity.resolve(db, source, alice.email)

    assert got.outcome == identity.MATCHED
    assert got.user_id == alice.id


def test_email_matching_ignores_case(db, source, make_user):
    """`PParker@Acme.com` and `pparker@acme.com` are one person, and a CRM will send
    both."""
    alice = make_user("agent", None, name="Alice")

    got = identity.resolve(db, source, alice.email.upper())

    assert got.outcome == identity.MATCHED
    assert got.user_id == alice.id


def test_a_match_is_written_down_for_next_time(db, source, make_user):
    """So the next sync takes the fast path — and, more importantly, so the answer
    survives somebody later changing their email in GoalGetter."""
    alice = make_user("agent", None, name="Alice")

    identity.resolve(db, source, alice.email)

    stored = identities(db, source)
    assert len(stored) == 1
    assert stored[0].user_id == alice.id
    assert stored[0].pending_rows == 0


def test_a_stored_mapping_is_used_without_an_email_match(db, source, make_user):
    """The whole point of mapping: an identifier that looks nothing like an email
    still resolves, forever, after being answered once."""
    alice = make_user("agent", None, name="Alice")
    db.add(
        UserIdentity(
            organization_id=source.organization_id,
            data_source_id=source.id,
            external_identifier="0051x000ABCdef",
            user_id=alice.id,
        )
    )
    db.flush()

    got = identity.resolve(db, source, "0051x000ABCdef")

    assert got == identity.Resolution(identity.MATCHED, alice.id)


def test_an_admin_decision_outranks_an_email_match(db, source, make_user):
    """Two people, and the CRM's address belongs to the wrong one — a shared
    mailbox, a departed colleague's alias. The explicit answer wins."""
    alice = make_user("agent", None, name="Alice")
    bob = make_user("agent", None, name="Bob")
    db.add(
        UserIdentity(
            organization_id=source.organization_id,
            data_source_id=source.id,
            external_identifier=alice.email,
            user_id=bob.id,
        )
    )
    db.flush()

    got = identity.resolve(db, source, alice.email)

    assert got.user_id == bob.id


def test_a_hidden_user_is_not_matched(db, source, make_user):
    """Their facts should wait for a decision rather than being attributed to an
    account that no longer has access."""
    alice = make_user("agent", None, name="Alice")
    alice.hidden_at = datetime.now(UTC)
    db.flush()

    got = identity.resolve(db, source, alice.email)

    assert got.outcome == identity.QUARANTINED


def test_another_organizations_user_is_not_matched(db, source, make_user, org):
    """The cross-organization check. A shared email domain between two tenants
    would otherwise attribute one company's deals to another's rep."""
    from app.models import Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    stranger = UserAccount(
        organization_id=other.id,
        email="shared@example.com",
        full_name="Stranger",
        org_role="agent",
        status="active",
    )
    db.add(stranger)
    db.flush()

    got = identity.resolve(db, source, "shared@example.com")

    assert got.outcome == identity.QUARANTINED


def test_a_bare_name_is_never_guessed_at(db, source, make_user):
    """Matching a name against `full_name` is the obvious next idea and a bad one.
    Two people called B. Banner are one leaderboard scandal, and a wrong match is
    worse than a question — it silently credits somebody else's work."""
    make_user("agent", None, name="Clark Kent")

    got = identity.resolve(db, source, "Clark Kent")

    assert got.outcome == identity.QUARANTINED


# ── Quarantine ───────────────────────────────────────────────────────────────


def test_an_unknown_identifier_is_quarantined_not_created(db, source):
    """**The decision this module exists for.** No new account appears."""
    before = db.scalar(select(func.count()).select_from(UserAccount))

    got = identity.resolve(db, source, "nobody@acme.com")

    assert got.outcome == identity.QUARANTINED
    assert got.user_id is None
    assert db.scalar(select(func.count()).select_from(UserAccount)) == before


def test_repeated_rows_count_against_one_question(db, source):
    """Not one question per row. A source with two thousand rows from an
    unrecognised rep should produce one entry saying two thousand."""
    for _ in range(3):
        identity.resolve(db, source, "nobody@acme.com")

    stored = identities(db, source)
    assert len(stored) == 1
    assert stored[0].pending_rows == 3


def test_the_same_identifier_in_two_sources_is_two_questions(db, source, other_source):
    """Provider ids are only unique within the system that issued them, so the
    source has to be part of the key — and answering for the CRM should not answer
    for the spreadsheet."""
    identity.resolve(db, source, "42")
    identity.resolve(db, other_source, "42")

    assert len(identities(db, source)) == 1
    assert len(identities(db, other_source)) == 1


def test_a_blank_subject_is_quarantined_without_a_row(db, source):
    """A mapping pointed at the wrong column. Quarantining an empty string would
    collect every such row under one meaningless heading."""
    got = identity.resolve(db, source, "")

    assert got.outcome == identity.QUARANTINED
    assert identities(db, source) == []


def test_last_seen_is_recorded(db, source):
    """Context for the decision: an identifier nothing has referenced for months is
    probably an ex-employee."""
    when = datetime(2026, 8, 1, tzinfo=UTC)

    identity.resolve(db, source, "nobody@acme.com", now=when)

    assert identities(db, source)[0].last_seen_at == when


def test_last_seen_moves_on_a_later_row(db, source):
    first = datetime(2026, 8, 1, tzinfo=UTC)
    later = first + timedelta(days=5)

    identity.resolve(db, source, "nobody@acme.com", now=first)
    identity.resolve(db, source, "nobody@acme.com", now=later)

    assert identities(db, source)[0].last_seen_at == later


# ── Answering the questions ──────────────────────────────────────────────────


def test_pending_lists_the_busiest_first(db, source):
    """So the identifier holding up two thousand facts is at the top, rather than
    alphabetically somewhere in the middle."""
    for _ in range(1):
        identity.resolve(db, source, "quiet@acme.com")
    for _ in range(5):
        identity.resolve(db, source, "busy@acme.com")

    waiting = identity.pending(db, source)

    assert [i.external_identifier for i in waiting] == ["busy@acme.com", "quiet@acme.com"]


def test_mapping_releases_the_rows(db, source, make_user):
    """The count clears because those rows are no longer waiting — the next sync
    re-reads them and they match."""
    alice = make_user("agent", None, name="Alice")
    identity.resolve(db, source, "0051x")
    waiting = identity.pending(db, source)[0]

    identity.map_to(db, waiting, alice.id)

    assert identity.resolve(db, source, "0051x") == identity.Resolution(
        identity.MATCHED, alice.id
    )
    assert identity.pending(db, source) == []
    # Asserted directly, not just through `pending()`. That filters on
    # `user_id IS NULL`, so a mapped row drops out of the list whatever its count
    # says — which let a mutation leaving the count stale survive.
    assert waiting.pending_rows == 0


def test_ignoring_stops_it_asking(db, source):
    """For the `Integration User` a CRM owns half its records with."""
    identity.resolve(db, source, "integration@acme.com")
    waiting = identity.pending(db, source)[0]

    identity.ignore(db, waiting)

    assert identity.resolve(db, source, "integration@acme.com").outcome == (
        identity.IGNORED
    )
    assert identity.pending(db, source) == []


def test_an_ignored_identifier_stops_counting_rows(db, source):
    """Otherwise the count grows forever behind a question nobody will answer."""
    identity.resolve(db, source, "integration@acme.com")
    identity.ignore(db, identity.pending(db, source)[0])

    for _ in range(4):
        identity.resolve(db, source, "integration@acme.com")

    assert identities(db, source)[0].pending_rows == 0


def test_mapping_an_ignored_identifier_un_ignores_it(db, source, make_user):
    """Somebody changes their mind: the service account turns out to be a person
    after all. One field cannot be left contradicting the other."""
    alice = make_user("agent", None, name="Alice")
    identity.resolve(db, source, "maybe@acme.com")
    waiting = identity.pending(db, source)[0]
    identity.ignore(db, waiting)

    identity.map_to(db, waiting, alice.id)

    assert waiting.ignored is False
    assert identity.resolve(db, source, "maybe@acme.com").user_id == alice.id


def test_the_database_refuses_mapped_and_ignored_at_once(db, source, make_user):
    """A row claiming both would be a contradiction the resolver has to guess at.
    The constraint means it cannot exist."""
    from sqlalchemy.exc import IntegrityError

    alice = make_user("agent", None, name="Alice")
    db.add(
        UserIdentity(
            organization_id=source.organization_id,
            data_source_id=source.id,
            external_identifier="both@acme.com",
            user_id=alice.id,
            ignored=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
