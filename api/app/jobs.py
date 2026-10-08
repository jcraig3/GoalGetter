"""Scheduled work.

    docker compose exec api python -m app.jobs          # run everything once
    docker compose exec api python -m app.jobs --dry-run

Every job here is **idempotent**: running it twice changes nothing the second
time. That is the property that makes scheduling boring — a missed run catches
up on the next one, a double run is harmless, and a container restarting
mid-job leaves nothing half-done.

Idempotency is enforced by the database wherever possible, not by the job
checking first. A check-then-insert is a race: two workers, or one worker
restarted between the check and the insert, both see nothing and both write.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import periods
from app.db import SessionFactory, SessionLocal, engine
from app.models import Goal, Organization

logger = logging.getLogger(__name__)

# Serialises concurrent runs. The unique index is what actually guarantees
# correctness; this only stops two replicas doing the same work and filling the
# log with rollbacks.
LOCK_KEY = "goalgetter.jobs.spawn_goals"

# Serialises the announcing passes, which run from the scheduled job and also
# straight after a number arrives outside it. Unlike everything else here they
# are not all protected by a unique index: two `announcements.deliver` passes
# at once could both post the same queued card to Teams.
ANNOUNCE_LOCK_KEY = "goalgetter.jobs.announce"


@contextmanager
def _held(key: str, *, wait: bool) -> Iterator[bool]:
    """A Postgres advisory lock, held on a connection of its own.

    **Not on the caller's session.** A session hands its connection back to the
    pool at every commit and may be given a different one for the next
    statement, and the jobs commit after every pass. A session-level lock taken
    on one connection and released on another is never released: it stays on
    the first connection, idle in the pool, and a later run finding it held
    skips its work while nothing is running at all.

    Committed as soon as it is taken, because advisory locks outlive their
    transaction, and a transaction left open for the length of a job holds back
    vacuum for no reason.
    """
    with engine.connect() as conn:
        if wait:
            conn.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": key})
            acquired = True
        else:
            acquired = bool(
                conn.scalar(text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": key})
            )
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})
                conn.commit()


@dataclass
class SpawnReport:
    created: int = 0
    skipped: int = 0
    ended: int = 0
    details: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"created={self.created} skipped={self.skipped} ended={self.ended}"


def _normalise(org: Organization, period_type: str, anchor: date) -> date:
    """The canonical date for the period containing `anchor` — its start.

    Any date inside a period names that period, so "13 August" and "1 August"
    both mean August 2026. Comparing the raw values would call them different
    periods, which is precisely how a recurring goal created on the 13th
    spawned a duplicate of itself for the month it was already covering.
    """
    period = periods.resolve(org, period_type, anchor)
    return period.start.astimezone(ZoneInfo(org.timezone)).date()


def _current_anchor(org: Organization, goal: Goal, now: datetime) -> date:
    """The canonical anchor for the period the goal should exist for *today*.

    The period's own start date, not today's: running the job on the 5th and
    again on the 20th must produce the same value, or the second run would
    spawn a second September goal.
    """
    return _normalise(org, goal.period_type, now.astimezone(ZoneInfo(org.timezone)).date())


def spawn_due_goals(
    db: DbSession, now: datetime | None = None, *, dry_run: bool = False
) -> SpawnReport:
    """Give every recurring goal an instance for the current period.

    Only the current one. A goal that recurred monthly and was not run for six
    months does not produce six back-dated goals nobody saw — targets for
    periods that already closed are noise, and the history of what was actually
    asked for should not be invented after the fact.
    """
    now = now or datetime.now(UTC)
    report = SpawnReport()

    roots = db.scalars(
        select(Goal).where(
            Goal.recurring.is_(True),
            # An archived original stops producing. Archiving is how you turn a
            # recurring goal off without deleting its history.
            Goal.archived_at.is_(None),
        )
    ).all()

    for root in roots:
        org = db.get(Organization, root.organization_id)
        today = now.astimezone(ZoneInfo(org.timezone)).date()

        if root.recurrence_ends_on is not None and today > root.recurrence_ends_on:
            report.ended += 1
            continue

        anchor = _current_anchor(org, root, now)

        # The original already covers this period — nothing to spawn yet.
        #
        # Both sides normalised, so a root anchored mid-period still matches.
        # Rows written before anchors were canonical are handled here too.
        if _normalise(org, root.period_type, root.period_anchor) == anchor:
            report.skipped += 1
            continue

        if dry_run:
            report.details.append(f"would spawn goal {root.id} for {anchor}")
            report.created += 1
            continue

        child = Goal(
            organization_id=root.organization_id,
            metric_definition_id=root.metric_definition_id,
            subject_type=root.subject_type,
            subject_user_id=root.subject_user_id,
            subject_team_id=root.subject_team_id,
            # The target is copied, not referenced. Raising next month's target
            # must not silently rewrite what last month was judged against.
            target_value=root.target_value,
            # Copied with the target, for the same reason.
            stretch_targets=list(root.stretch_targets or []),
            period_type=root.period_type,
            period_anchor=anchor,
            name=root.name,
            created_by_user_id=root.created_by_user_id,
            recurring=False,
            spawned_from_goal_id=root.id,
        )
        db.add(child)

        try:
            # Committed one at a time so a single conflict cannot roll back the
            # goals already spawned in this run.
            db.commit()
            report.created += 1
            report.details.append(f"spawned goal {child.id} from {root.id} for {anchor}")
        except IntegrityError:
            # The unique index did its job — another run got there first. This
            # is the expected outcome of a double run, not an error.
            db.rollback()
            report.skipped += 1

    return report


def run_all(db: DbSession, *, dry_run: bool = False) -> SpawnReport:
    """Every scheduled job, under one advisory lock."""
    if dry_run:
        return spawn_due_goals(db, dry_run=True)

    # Non-blocking: if another replica holds it, this run does nothing rather
    # than queueing up behind it. The next tick will catch up.
    with _held(LOCK_KEY, wait=False) as acquired:
        if not acquired:
            logger.info("jobs: another run holds the lock, skipping")
            return SpawnReport()
        return _run_all_locked(db)


def _run_all_locked(db: DbSession) -> SpawnReport:
    report = spawn_due_goals(db)
    logger.info("jobs: spawn_due_goals %s", report)

    # **First in the pass, and deliberately.** Everything below reads
    # `metric_fact`: a goal detects as achieved, an announcement rule
    # fires, a competition settles. Syncing first means all of that sees
    # the numbers that arrived since the last tick, rather than
    # celebrating them an hour late.
    # **Before the metric sync, deliberately.** A person approved from
    # the directory becomes an account here, and the sync below matches
    # rows to people by email — so somebody who joined today has an
    # account to match against on their first sync rather than spending a
    # pass in quarantine for no reason.
    from app.directory import sync as directory_sync

    people = directory_sync.run_due(db, now=datetime.now(UTC))
    db.commit()
    if people["directories"]:
        logger.info("jobs: directory %s", people)

    from app import sync as sync_service

    synced = sync_service.run_due(db)
    db.commit()
    if synced["sources"]:
        logger.info("jobs: sync %s", synced)

    # Deliberately after spawning and syncing, and in the same pass: a goal the
    # recurrence job just created for this period should announce itself now
    # rather than sitting silent until the next tick.
    announce(db)

    # Imported here rather than at module scope because `notifications`
    # imports `goals`, which would close a cycle back to this module.
    from app import notifications

    # Its own pass: goals are a question about a target and these are a
    # question about a calendar. See `detect_occasions`.
    occasions_marked = notifications.detect_occasions(db)
    db.commit()
    if occasions_marked.emitted:
        logger.info("jobs: occasions %s", occasions_marked)

    from app import competition_rounds, competitions

    # Rounds first, so a round that should already be running starts
    # on this same pass rather than the next.
    rounds = competition_rounds.spawn_due(db)
    db.commit()
    if rounds:
        logger.info("jobs: competition rounds made=%s", rounds)

    moved = competitions.advance(db)
    db.commit()
    if any(moved.values()):
        logger.info("jobs: competitions %s", moved)

    # After everything that moves a number, so a digest describes
    # this pass's standings rather than the last one's.
    from app import report_delivery

    reports = report_delivery.deliver_due(db)
    db.commit()
    if reports.schedules:
        logger.info("jobs: %s", reports)

    # Last, so everything this pass recorded goes out on this pass.
    from app import audit_stream

    streamed = audit_stream.push_due(db)
    db.commit()
    if streamed.streams:
        logger.info("jobs: %s", streamed)

    pruned = notifications.prune(db)
    db.commit()
    if pruned:
        logger.info("jobs: pruned %d expired notifications", pruned)

    return report


def announce(db: DbSession) -> None:
    """Turn new numbers into announcements: goals hit, rules fired, badges
    earned, and the Teams and Slack posts for all three.

    Run by the scheduled job straight after its sync, and by `announce_now`
    straight after a number arrives any other way. Waits for a pass already
    running rather than skipping, because the caller has a number that pass
    may have started too early to see.
    """
    with _held(ANNOUNCE_LOCK_KEY, wait=True):
        _announce_locked(db)


def _announce_locked(db: DbSession) -> None:
    # Imported here rather than at module scope because `notifications`
    # imports `goals`, which would close a cycle back to this module.
    from app import announcements, badges, notifications

    detected = notifications.detect(db)
    db.commit()
    logger.info("jobs: notifications %s", detected)

    rules = notifications.detect_rules(db)
    db.commit()
    logger.info("jobs: achievement rules %s", rules)

    # After the rules, not with them. A badge counts how often a rule has
    # fired, so it has to run against a settled picture — folding the two
    # together would mean a badge seeing a half-finished pass and coming up
    # one short until the next cycle.
    earned = badges.detect(db)
    db.commit()
    if earned.awarded or earned.skipped:
        logger.info("jobs: badges %s", earned)

    # Last of the announcing passes, so it posts everything the passes above
    # have just written — a goal hit this cycle reaches the Teams channel this
    # cycle, not the next one.
    posted = announcements.deliver(db)
    db.commit()
    if posted.queued or posted.sent or posted.failed:
        logger.info("jobs: %s", posted)


#: Held by the one request thread in this process that is waiting to announce.
_queued = threading.Lock()


def announce_now(sessions: SessionFactory) -> None:
    """Announce what a correction, a webhook or "Sync now" just recorded.

    Run as a background task, after the response, so the person pressing the
    button is not kept waiting on a Teams post. Before this, only the hourly
    job looked for wins, so a rule promising "the moment it happens" fired up
    to an hour late (QA-2).

    **At most one waiting per process.** A pass announces everything new,
    not just the number that asked for it, so a second request arriving while
    one is already queued has nothing to add: the queued pass starts after
    both numbers were committed and sees them both. Without this, a burst of
    webhooks would park one thread each on the lock, and those are the same
    threads that serve requests.

    A failure is logged and dropped. Nothing is lost by it: every pass is
    idempotent, and the hourly job announces whatever this one did not.
    """
    if not _queued.acquire(blocking=False):
        return
    queued = True
    try:
        with _held(ANNOUNCE_LOCK_KEY, wait=True):
            # Running now: the next number to arrive needs a pass of its own.
            _queued.release()
            queued = False
            with sessions() as db:
                _announce_locked(db)
    except Exception:  # noqa: BLE001 — the hourly job is the safety net
        logger.exception("jobs: announcing straight away failed; the hourly job will")
    finally:
        if queued:
            _queued.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobs", description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would happen, change nothing"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        report = run_all(db, dry_run=args.dry_run)
        for line in report.details:
            print(f"  {line}")
        print(report)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
