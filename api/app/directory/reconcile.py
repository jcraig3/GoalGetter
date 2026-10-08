"""Turning a snapshot of a directory into rows, without overwriting decisions.

**Reconcile, not append.** A provider hands back the *whole* current membership, and
this works out what changed by comparing it with what is already here — including
what is *absent*, which is how somebody who left the company is noticed. There is no
watermark and no window, because no directory API has a field meaning "this person
no longer exists".

Three rules, and every awkward case here is one of them applied:

**1. A decision an admin made outranks anything the directory says.** Somebody
declined stays declined; the next sync must not re-propose them, or the feature
becomes something people switch off.

**2. Nobody is created or changed silently.** New people arrive `pending`. An
approved person whose *rule now resolves differently* goes back to pending with a
reason, rather than being quietly reassigned — a promotion should not change what
somebody is on a leaderboard without a human seeing it.

**3. Absence is a fact, and it means archived rather than deleted.** Anything
attached to a person still says where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.directory.rules import Person, Placement, Rule, place
from app.models import DirectoryPerson
from app.models.directory import DECIDED


@dataclass
class Outcome:
    """What one reconcile did, for the run history and for the page afterwards."""

    created: int = 0
    updated: int = 0
    archived: int = 0
    restored: int = 0
    #: Approved people whose rule now resolves somewhere else, sent back for review.
    needs_review: int = 0
    #: People the directory returned that are still waiting on a decision. Not a
    #: count of what this pass did — a count of what an admin has to do.
    pending: int = 0

    #: Accounts switched off because the directory switched them off, and
    #: accounts switched back on because it switched them back on. Counted
    #: separately from `archived`/`restored`, which describe the staged row: a
    #: person can be archived here without owning an account at all.
    deactivated: int = 0
    reactivated: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def seen(self) -> int:
        return self.created + self.updated



def _deactivate_account(row: DirectoryPerson) -> bool:
    """Turn off the account of somebody the directory has turned off.

    **The gap this closes.** `directory_person` has always recorded that an
    account was disabled upstream; nothing ever acted on it. Somebody offboarded
    in Entra kept their GoalGetter login, kept their sessions, and kept their
    place on the leaderboard until an admin happened to notice.

    Three things are deliberately left alone:

    **A hidden person.** An admin decided that, and a decision outranks anything
    the directory reports — the same rule `DECIDED` states for a declined row. It
    also matters in the other direction: if this wrote over a hide, re-enabling
    the account in Entra would quietly un-hide them.

    **A suspended person.** Also an admin's decision, and one that means strictly
    more than this does. Overwriting it with a weaker state that the sync can
    reverse by itself would hand access back to somebody who was shut out.

    **Anybody already deactivated**, so a daily sync is not a daily audit entry.

    Returns whether anything changed, for the run's counters.
    """
    account = row.account
    if account is None or account.hidden_at is not None:
        return False
    if account.status not in ("active", "invited"):
        return False
    account.status = "deactivated"
    return True


def _reactivate_account(row: DirectoryPerson) -> bool:
    """Give it back when the directory changes its mind.

    Only ever undoes `deactivated`, which is the only status this module set. A
    suspension or a hide is somebody's decision and is not the directory's to
    reverse — that asymmetry is the point, and it is what makes the automatic
    half safe to leave running.

    Always `active`: somebody back in the directory signs in with the work
    account it holds. It used to come back `invited` for anybody with no
    password, which the SSO sign-in refuses.
    """
    account = row.account
    if account is None or account.status != "deactivated":
        return False
    account.status = "active"
    return True

def _fields_of(person: Person) -> dict[str, object]:
    return {
        "email": person.email,
        "display_name": person.display_name,
        "job_title": person.job_title,
        "department": person.department,
        "office_location": person.office_location,
        "groups": list(person.groups),
        "enabled": person.enabled,
    }


def _placement_of(row: DirectoryPerson, rules: list[Rule], default_role: str) -> Placement:
    return place(
        rules,
        Person(
            external_id=row.external_id,
            email=row.email,
            display_name=row.display_name,
            job_title=row.job_title,
            department=row.department,
            office_location=row.office_location,
            groups=tuple(row.groups or ()),
            enabled=row.enabled,
        ),
        default_role=default_role,
    )


def reconcile(
    db: DbSession,
    *,
    organization_id: int,
    provider: str,
    people: list[Person],
    rules: list[Rule] | None = None,
    now: datetime,
    default_role: str = "agent",
) -> Outcome:
    """Bring the staging table in line with what the directory just said.

    `people` is the **whole** membership, not a delta. Passing a partial list would
    archive everybody missing from it, which is why the provider must raise rather
    than return a short list when a read fails part-way.
    """
    rules = rules or []
    outcome = Outcome()

    existing = {
        row.external_id: row
        for row in db.scalars(
            select(DirectoryPerson).where(
                DirectoryPerson.organization_id == organization_id,
                DirectoryPerson.provider == provider,
            )
        ).all()
    }

    for person in people:
        row = existing.get(person.external_id)

        if row is None:
            row = DirectoryPerson(
                organization_id=organization_id,
                provider=provider,
                external_id=person.external_id,
                # Somebody already disabled at the far end arrives archived rather
                # than pending: proposing a leaver for approval on the first sync
                # of a company with years of history would bury the real joiners.
                status="pending" if person.enabled else "archived",
                archived_at=None if person.enabled else now,
                last_seen_at=now,
                **_fields_of(person),
            )
            db.add(row)
            outcome.created += 1
            if person.enabled:
                outcome.pending += 1
            continue

        was = row.status
        for key, value in _fields_of(person).items():
            setattr(row, key, value)
        row.last_seen_at = now
        outcome.updated += 1

        if not person.enabled:
            # Disabled at the far end. Archived whatever an admin had decided —
            # this is not a preference being overridden, it is the account no
            # longer existing.
            if was != "archived":
                row.status = "archived"
                row.archived_at = now
                outcome.archived += 1
            # And the account itself, which nothing used to do. See the helper
            # for the three cases it refuses to touch.
            if _deactivate_account(row):
                outcome.deactivated += 1
            continue

        if was == "archived":
            # Back from the dead: re-enabled in the directory, or returned after
            # being absent. Pending again rather than straight back to approved,
            # because somebody leaving and rejoining is exactly when a human should
            # look.
            row.status = "pending"
            row.archived_at = None
            row.pending_reason = "Returned to the directory"
            outcome.restored += 1
            outcome.pending += 1
            if _reactivate_account(row):
                outcome.reactivated += 1
            continue

        if was == "declined":
            # Rule 1. Declined stays declined.
            continue

        if was == "approved":
            # Rule 2. A rule that now resolves elsewhere is a question, not an
            # instruction — a promotion must not silently move somebody.
            wanted = _placement_of(row, rules, default_role)
            if _differs(row, wanted):
                row.status = "pending"
                row.pending_reason = "Their job details changed"
                outcome.needs_review += 1
                outcome.pending += 1
            continue

        outcome.pending += 1

    # Anybody the directory did not mention. Rule 3.
    for external_id, row in existing.items():
        if external_id in {person.external_id for person in people}:
            continue
        if row.status == "archived":
            continue
        row.status = "archived"
        row.archived_at = now
        outcome.archived += 1

    db.flush()
    return outcome


def _differs(row: DirectoryPerson, wanted: Placement) -> bool:
    """Whether an approved person's account no longer matches what the rules say.

    Compared against the **account**, not against the last placement: there is no
    stored "what we decided last time", and adding one would be a third thing that
    could disagree with the other two. What matters is whether the account and the
    rules agree *now*.

    An unplaced result — no rule matched, or a rule that names no team — is not a
    difference. Otherwise deleting a rule would send everybody it used to place
    back for review at once, which is a stampede rather than a signal.
    """
    if row.user_account_id is None:
        return False
    if not wanted.assigned:
        return False
    account = row.account
    if account is None:
        return False
    return account.team_id != wanted.team_id or account.org_role != wanted.role
