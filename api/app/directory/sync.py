"""One pass over a directory: read it, reconcile it, apply what was approved.

The three pieces in order, and the order is the whole of what this module decides:

    provider.people()   the whole current membership
    reconcile()         what changed, including who is absent
    apply()             approved rows become accounts

**Nothing here is a connector.** It writes to `user_account`, not `metric_fact`, and
it reconciles a snapshot rather than appending a window — see `app/directory` for the
argument. What it shares with the metric pipeline it shares by importing.

**Applying runs every pass, not only on approval.** Somebody approved while the sync
was not running, or approved before the rules were written, has to become an account
eventually without an admin pressing anything a second time. Applying is idempotent,
so doing it every time costs a comparison per approved person.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.directory import microsoft
from app.directory.apply import ApplyProblem
from app.directory import apply as apply_module
from app.directory.apply import apply as apply_one
from app.directory.reconcile import reconcile
from app.directory.rules import Person, Rule
from app.models import (
    DirectoryPerson,
    DirectoryRule,
    DirectoryRun,
    OauthClient,
    UserAccount,
)

logger = logging.getLogger(__name__)

#: How often a directory is read, when the connection does not say.
#:
#: Daily rather than hourly. People join and leave on a scale of days, and a tenant
#: of two thousand is a handful of Graph requests — but it is somebody else's API
#: quota, and reading it twenty-four times to notice one joiner is the kind of thing
#: that gets an integration switched off at the far end.
#:
#: **A default rather than the rule**, since `oauth_client.directory_sync_hours`.
#: Still used for a row that somehow holds nothing usable, because the alternative
#: — an interval of zero — is a sync that runs on every single tick of the job
#: loop, against somebody else's API.
INTERVAL = timedelta(hours=24)

#: The narrowest and widest a connection may ask for.
#:
#: The floor is not arbitrary: below an hour this stops being a schedule and
#: becomes polling, and Graph is rate-limited per tenant. The ceiling is a
#: fortnight, past which "is this still working?" has no answer anybody trusts.
MIN_SYNC_HOURS = 1
MAX_SYNC_HOURS = 336

#: How many problems to report before giving up on describing them.
#:
#: A rule pointing at a deleted team fails for every person it matches, and an error
#: field holding two hundred copies of the same sentence is unreadable.
MAX_REPORTED = 5

#: Who can read a directory. One entry, and the shape is what matters: a provider is
#: a function returning `Person`s, so Google Workspace is a second entry rather than
#: a second engine.
#:
#: Takes the session because delegated mode renews from a stored refresh token and
#: has to write a rotated one back. Application mode ignores it.
READERS: dict[str, Callable[[DbSession, OauthClient], list[Person]]] = {
    "microsoft": microsoft.people,
}

#: Who can read a Teams-style structure — Teams, channels and their members. A
#: dict for the same reason as `READERS`, and so a test can swap in a tenant.
STRUCTURE_READERS: dict[str, Callable] = {
    "microsoft": lambda db, connection, want=None: _structure().read(db, connection, want),
}


def _structure():
    from app.directory import structure

    return structure


def due(db: DbSession, *, now: datetime) -> list[OauthClient]:
    """Connections whose directory should be read now.

    Switched on explicitly — see `oauth_client.directory_sync_enabled`. A connection
    existing says nothing about whether a company wants two hundred accounts
    proposed from it.
    """
    connections = db.scalars(
        select(OauthClient).where(OauthClient.directory_sync_enabled.is_(True))
    ).all()
    return [c for c in connections if c.provider in READERS and _is_due(db, c, now=now)]


def _is_due(db: DbSession, connection: OauthClient, *, now: datetime) -> bool:
    last = db.scalar(
        select(DirectoryRun.started_at)
        .where(
            DirectoryRun.organization_id == connection.organization_id,
            DirectoryRun.provider == connection.provider,
            # A run that failed still counts as an attempt. Retrying a broken
            # credential every tick would hammer an authentication endpoint, which
            # is how an account gets locked.
            DirectoryRun.status.in_(("ok", "partial", "failed")),
        )
        .order_by(DirectoryRun.started_at.desc())
        .limit(1)
    )
    return last is None or (now - last) >= interval_of(connection)


def interval_of(connection: OauthClient) -> timedelta:
    """How long this connection waits between reads.

    Clamped rather than trusted. The column is bounded by the endpoint that writes
    it, but a value edited straight into the database — or left at zero by some
    future migration — would otherwise mean "read the directory on every tick",
    which is the one failure mode here that costs somebody else money.
    """
    hours = connection.directory_sync_hours or 0
    if hours < MIN_SYNC_HOURS or hours > MAX_SYNC_HOURS:
        return INTERVAL
    return timedelta(hours=hours)


def rules_for(db: DbSession, organization_id: int) -> list[Rule]:
    """The rules, as the engine wants them.

    Translated here rather than the engine reading the model, so `rules.py` stays
    free of the database and can be tested exhaustively without one.
    """
    return [
        Rule(
            department=row.department,
            job_title=row.job_title,
            office=row.office,
            group=row.group,
            role=row.role,
            team_id=row.team_id,
        )
        for row in db.scalars(
            select(DirectoryRule).where(
                DirectoryRule.organization_id == organization_id
            )
        ).all()
    ]


def run(
    db: DbSession,
    connection: OauthClient,
    *,
    now: datetime,
    trigger: str = "schedule",
) -> DirectoryRun:
    """Read one directory and act on it. Records the outcome rather than raising.

    A failure is a run with a message on it, not an exception escaping into the
    scheduler — a broken Microsoft credential must not stop goals from spawning or
    metrics from syncing in the same pass.
    """
    run_row = DirectoryRun(
        organization_id=connection.organization_id,
        provider=connection.provider,
        trigger=trigger,
        status="running",
        started_at=now,
    )
    db.add(run_row)
    db.flush()

    reader = READERS.get(connection.provider)
    if reader is None:
        run_row.status = "failed"
        run_row.error = f"This build cannot read a {connection.provider} directory."
        run_row.finished_at = now
        db.flush()
        return run_row

    try:
        people = reader(db, connection)
    except Exception as problem:  # noqa: BLE001 — recorded, not propagated
        # **Nothing is reconciled on a failed read.** A partial list would archive
        # everybody missing from it, so half a directory is far more dangerous than
        # none: it would look like half the company left.
        run_row.status = "failed"
        run_row.error = _describe(problem)
        run_row.finished_at = datetime.now(now.tzinfo)
        db.flush()
        return run_row

    rules = rules_for(db, connection.organization_id)
    outcome = reconcile(
        db,
        organization_id=connection.organization_id,
        provider=connection.provider,
        people=people,
        rules=rules,
        now=now,
    )

    applied, problems = apply_approved(
        db, connection.organization_id, rules=rules, now=now
    )

    # **After the people are settled**, so a mirror sees this pass's people.
    # The structure is read only when something is linked — see `structure.py`
    # for why a sync does not read every Team it could. Moving anybody needs an
    # admin to have switched it on: doing that unattended is a decision
    # somebody should have made on purpose. See `mirror.py`.
    if read_teams_structure(db, connection, now=now) and connection.directory_mirror_teams:
        from app.directory import mirror

        mirrored = mirror.apply(db, connection.organization_id)
        applied += len(mirrored.moves)

    # Offices and departments linked to offices and teams (Phase 28): after
    # the mirror, which places people more precisely.
    from app.directory import places

    applied += places.apply(db, connection.organization_id)

    # **After reconciliation, because a photograph needs somebody to belong to.**
    # Faces are the last thing done and the first thing skipped: a failure here
    # leaves the run's own status alone, because a directory sync that worked and
    # could not fetch a headshot has still worked.
    photos = _photographs(db, connection, now=now)

    run_row.people_seen = len(people)
    run_row.created = outcome.created
    run_row.archived = outcome.archived
    run_row.needs_review = outcome.needs_review
    run_row.pending = outcome.pending
    run_row.applied = applied
    run_row.error = " ".join(problems) or None
    # `partial` on the same rule as a metric sync: work done *and* work held back.
    run_row.status = "partial" if problems else "ok"
    run_row.finished_at = datetime.now(now.tzinfo)
    db.flush()
    return run_row


def read_teams_structure(
    db: DbSession, connection: OauthClient, *, now: datetime, everything: bool = False
) -> bool:
    """Refresh the Microsoft Teams structure. True when it could be read.

    `everything` is the admin's "Read from Microsoft Teams" button: every
    channel of every Team, so one can be picked. A scheduled sync asks only
    about what is linked, and nothing at all when nothing is.

    Never raises: the Teams structure is not worth failing a directory sync for.
    """
    reader = STRUCTURE_READERS.get(connection.provider)
    if reader is None:
        return False
    if not everything:
        # Microsoft Teams switched off: nothing scheduled reads it. The admin's
        # own "Read from Microsoft Teams" still works, so it can be set up first.
        from app.models import Organization

        org = db.get(Organization, connection.organization_id)
        if org is None or not org.teams_enabled:
            return False
    structure = _structure()
    want = None if everything else structure.wanted(db, connection.organization_id)
    if want is not None and not want.members_for:
        return False
    try:
        found = reader(db, connection, want)
    except Exception as problem:  # noqa: BLE001 — shown on the panel, not raised
        logger.warning("directory: Teams structure could not be read", exc_info=True)
        connection.teams_read_note = _describe(problem)[:1000]
        db.flush()
        return False
    structure.store(db, connection.organization_id, found, now=now)
    connection.teams_read_at = now
    connection.teams_read_note = " ".join(found.problems)[:1000] or None
    db.flush()
    return found.teams_read


def _photographs(
    db: DbSession, connection: OauthClient, *, now: datetime
) -> int:
    """Pull the tenant's photographs for people who have an account here.

    **Metadata first, bytes second.** Graph cannot batch a binary, so each photo
    is its own request — but *asking what the photo is* batches twenty at a time,
    so the download happens only for the faces that changed. The first run of a
    four-hundred-person tenant is four hundred requests; every run after it is
    twenty, and fetches nothing.

    Never raises. A face is not worth failing a directory sync for.
    """
    if connection.provider != "microsoft":
        return 0

    from app import photos as photo_store
    from app.directory import microsoft as graph

    linked = list(
        db.scalars(
            select(UserAccount).where(
                UserAccount.organization_id == connection.organization_id,
                UserAccount.external_subject_id.is_not(None),
                UserAccount.hidden_at.is_(None),
            )
        )
    )
    if not linked:
        return 0

    by_subject = {u.external_subject_id: u for u in linked if u.external_subject_id}

    try:
        token = graph.token_for(db, connection)
        with httpx.Client(
            timeout=graph.HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
        ) as client:
            tags = graph.photo_tags(client, list(by_subject))

            changed = 0
            for subject_id, tag in tags.items():
                user = by_subject.get(subject_id)
                if user is None or user.tenant_photo_etag == tag:
                    continue
                raw = graph.photo_bytes(client, subject_id)
                if raw is None:
                    continue
                photo_store.set_tenant(db, user, raw, etag=tag)
                changed += 1
    except Exception:  # noqa: BLE001 — recorded in the log, not on the run
        logger.warning("directory: photographs could not be read", exc_info=True)
        return 0

    return changed


def apply_approved(
    db: DbSession, organization_id: int, *, rules: list[Rule], now: datetime
) -> tuple[int, list[str]]:
    """Give everybody somebody decided to add an account, skipping the ones that
    cannot have one.

    Both decisions that add somebody come through here — visible and hidden —
    because they differ only in one column on the account. Two sweeps would be
    two places to remember when a third kind of addition arrives.

    One person's problem — no email address, usually — must not stop everybody
    else's account being created. Reported per person, like a mapping error on the
    metric side.
    """
    applied = 0
    problems: list[str] = []
    waiting = db.scalars(
        select(DirectoryPerson).where(
            DirectoryPerson.organization_id == organization_id,
            DirectoryPerson.status.in_(apply_module.ADDS_AN_ACCOUNT),
            DirectoryPerson.user_account_id.is_(None),
        )
    ).all()

    for row in waiting:
        try:
            apply_one(db, row, rules=rules, now=now)
            applied += 1
        except ApplyProblem as problem:
            if len(problems) < MAX_REPORTED:
                problems.append(str(problem))
    return applied, problems


def run_due(db: DbSession, *, now: datetime) -> dict[str, int]:
    """Every directory that is due, one at a time.

    Mirrors `sync.run_due` on the metric side, including the part that matters:
    one organization's failure does not stop the next one's.
    """
    counted = {"directories": 0, "people": 0, "created": 0, "failed": 0}
    for connection in due(db, now=now):
        try:
            run_row = run(db, connection, now=now)
        except Exception:  # noqa: BLE001
            logger.exception("directory: run failed for org %s", connection.organization_id)
            db.rollback()
            counted["failed"] += 1
            continue
        counted["directories"] += 1
        counted["people"] += run_row.people_seen
        counted["created"] += run_row.created
        if run_row.status == "failed":
            counted["failed"] += 1
    return counted


def _describe(error: Exception) -> str:
    """An error an admin can act on.

    A `DirectoryProblem` is already written for them — Microsoft's own words about a
    bad secret are more useful than anything we would write. Anything else gets its
    type, because "it broke" with no clue is worse than a class name.
    """
    if isinstance(error, microsoft.DirectoryProblem):
        return str(error)[:2000]
    return f"{type(error).__name__}: {error}"[:2000]
