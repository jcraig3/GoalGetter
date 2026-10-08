"""Turning an approved directory row into a real account, and keeping it honest.

**Nothing here runs without an admin having approved somebody.** Reconcile proposes;
this is the disposing half.

## Who owns a field afterwards

A human edit wins, and the difference is flagged for as long as it differs.

Overwriting an admin's correction on the next sync is unacceptable — they changed it
for a reason, usually one the directory does not know. But silently diverging from
the tenant for ever is its own problem: *"why does this say Sam Rivera when Entra
says Samantha Rivera"* is a question somebody eventually asks, and "nobody knows" is
a bad answer.

So the account keeps what it has, and `differences` reports what the directory
disagrees with. No extra columns are needed for that: `directory_person` already
holds what the tenant last said, because reconcile refreshes it every pass, and
`user_account` holds what we show. The comparison is between two rows that already
exist.

## What is set, and what is only set once

**Set on every apply:** email — because that is the identity the whole product joins
on, and letting it drift would break the link between a person and their metric rows.

**Set on creation only:** name, role, team. After that they are the admin's, and the
rules only *propose* changes — through reconcile, which sends somebody back to
pending rather than reassigning them. That is the same rule stated in a second
place, and it is load-bearing in both.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import sign_in
from app.directory.rules import Person, Rule, place
from app.models import DirectoryPerson, UserAccount


class ApplyProblem(Exception):
    """Something an admin can act on, phrased for them rather than for a log."""


@dataclass(frozen=True)
class Difference:
    """One field where the account and the directory disagree."""

    field: str
    #: What GoalGetter shows.
    ours: str
    #: What the directory last said.
    theirs: str


#: What is compared, and what each is called on either side.
#:
#: Only the fields a person would notice being wrong. Job title and department are
#: deliberately absent: they are not stored on the account at all — they exist to
#: drive the rules, and comparing something we never copied would report a
#: difference nobody can act on.
COMPARED = (("full_name", "display_name"), ("email", "email"))


def differences(row: DirectoryPerson) -> list[Difference]:
    """Where the account and the directory disagree, right now.

    Computed rather than stored, so it cannot go stale. A stored flag would need
    clearing when either side changed, and the one that gets forgotten is the
    clearing.
    """
    account = row.account
    if account is None:
        return []
    found = []
    for ours, theirs in COMPARED:
        mine = str(getattr(account, ours, "") or "")
        yours = str(getattr(row, theirs, "") or "")
        # A field the directory has nothing for is not a disagreement — half of
        # every directory's optional fields are empty, and reporting each as a
        # conflict would bury the real ones.
        if yours and mine != yours:
            found.append(Difference(field=ours, ours=mine, theirs=yours))
    return found


def _person_of(row: DirectoryPerson) -> Person:
    return Person(
        external_id=row.external_id,
        email=row.email,
        display_name=row.display_name,
        job_title=row.job_title,
        department=row.department,
        office_location=row.office_location,
        groups=tuple(row.groups or ()),
        enabled=row.enabled,
    )


def _existing_account(db: DbSession, row: DirectoryPerson) -> UserAccount | None:
    """An account this person already has, by email.

    **Matched case-insensitively**, because a directory will happily return
    `Sam.Rivera@acme.com` for somebody invited here as `sam.rivera@acme.com`, and
    creating a second account for the same human is the worst outcome available:
    two rows on the leaderboard, each with half the numbers.
    """
    if not row.email:
        return None
    return db.scalar(
        select(UserAccount).where(
            UserAccount.organization_id == row.organization_id,
            func.lower(UserAccount.email) == row.email.strip().lower(),
        )
    )


#: The decisions that produce a real account.
#:
#: **"Hidden" is an addition, not a refusal.** The person exists, can be found,
#: given a photograph and moved onto a team later — they are simply off every
#: board until somebody says otherwise. "Declined" is the refusal, and it
#: creates nothing.
ADDS_AN_ACCOUNT = ("approved", "hidden")


def apply(
    db: DbSession,
    row: DirectoryPerson,
    *,
    rules: list[Rule] | None = None,
    now: datetime,
    default_role: str = "agent",
) -> UserAccount:
    """Give an approved person an account, or link them to the one they have.

    Refuses rather than guessing when there is no email: an account is identified
    by its address everywhere else in the product, and one without is a row nobody
    can sign in to, invite, or match a metric row against.
    """
    if row.status not in ADDS_AN_ACCOUNT:
        raise ApplyProblem("Only a person somebody decided to add becomes an account.")
    if not row.email.strip():
        raise ApplyProblem(
            f"{row.display_name or 'This person'} has no email address in the "
            "directory, so there is nothing to create an account against."
        )

    placement = place(rules or [], _person_of(row), default_role=default_role)
    account = row.account or _existing_account(db, row)

    if account is None:
        account = UserAccount(
            organization_id=row.organization_id,
            email=row.email.strip().lower(),
            full_name=row.display_name or row.email,
            org_role=placement.role,
            team_id=placement.team_id,
            # **`active`, not `invited`**, and the reasoning reversed on contact
            # with the sign-in path it was meant to reuse.
            #
            # `invited` was chosen so directory people would come through the
            # same door as anybody an admin types in. But they do not: an
            # invitation is an email with a link, and these people are already
            # in the tenant — nobody needs telling they exist. They sign in with
            # the work account they already have.
            #
            # And `invited` did not merely add a pointless step, it *closed the
            # door*: `routers/sso.py` refuses any account whose status is not
            # `active`, so every synced person was locked out of the one way in
            # they were expected to use. Auto-provisioned SSO accounts have
            # always been created `active` for exactly this reason.
            #
            # No password is set, so the only way in is single sign-on — which
            # is the intent.
            status="active",
            # **Hidden from the start, not hidden afterwards.** An account
            # created visible and hidden a moment later is on a leaderboard for
            # that moment — and on a wall, if the timing is unlucky. Most of a
            # directory belongs here: contractors, service accounts, the
            # departments that do not sell.
            hidden_at=now if row.status == "hidden" else None,
        )
        db.add(account)
        db.flush()

    # **Refreshed every pass, unlike name and role.** Those are things an admin
    # may have corrected and the directory has no better claim to — see below.
    # These three are the directory's own facts, nothing here edits them, and the
    # People list filters on them, so a stale department is a filter that quietly
    # stops matching somebody who moved teams.
    account.job_title = row.job_title
    account.department = row.department
    account.office_location = row.office_location
    # An account that already existed is *linked*, not overwritten. Somebody added
    # by hand last month and now appearing in the directory keeps their name, their
    # role and their team — the directory has no better claim to those than the
    # admin who typed them.

    # **The relationship, not only the foreign key.** `row.account` is read a few
    # lines above to find an existing link, which loads it — as `None`, for
    # somebody being applied for the first time — and SQLAlchemy caches that.
    # Setting only `user_account_id` leaves the cached `None` in place, so
    # `differences` on the same row a moment later sees no account and reports
    # nothing. Found by a test asserting a rename was flagged.
    row.account = account
    row.user_account_id = account.id
    row.pending_reason = ""
    # **Invited by hand, then found in the directory**: they sign in with the
    # work account they have, so the invitation is overtaken. Left `invited`,
    # they showed as waiting on the People list and SSO refused them.
    sign_in.activate(db, account)
    db.flush()
    return account
