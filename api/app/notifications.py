"""Noticing that something happened, and recording it once.

**Detection is a job, not a write-time check.** Goal progress is a query over
`metric_fact`, so there is no moment in a write where "you just hit your
target" is observable — a bulk import writing four hundred rows would have to
re-evaluate every affected goal four hundred times to find out. A job that
looks every few minutes costs one pass, and also catches achievements caused by
a connector sync, which has no user request to hang a check on.

The price is a few minutes between hitting a number and seeing the
celebration, which nobody notices.

**Firing once needs no stored state.** The obvious implementation remembers
what it has already announced, which means a `last_status` column — derived
state, wrong the moment a connector backfills, needing invalidation from every
write path. Instead the notification row *is* that record: emit inserts with ON
CONFLICT DO NOTHING against a unique index, so a second announcement is
impossible rather than merely unlikely. See `models/notification.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession

from app import achievements, events, goal_tiers, goals as goal_service, merge_tags, occasions, pace as pace_service, periods, points, units
from app.events import EventType
from app.models import (
    AchievementRule,
    Goal,
    MetricFact,
    MetricDefinition,
    Notification,
    Organization,
    Team,
    UserAccount,
    WalkupMedia,
)


@dataclass
class RuleReport:
    """What an achievement-rule pass emitted."""

    rules: int = 0
    facts: int = 0
    emitted: int = 0

    def __str__(self) -> str:
        return f"{self.rules} rules, {self.facts} new facts, {self.emitted} emitted"


@dataclass
class DetectReport:
    """What a pass emitted, for the log and for tests."""

    considered: int = 0
    emitted: int = 0
    suppressed: int = 0

    def __str__(self) -> str:
        return (
            f"{self.considered} goals considered, {self.emitted} emitted, "
            f"{self.suppressed} already known"
        )


class _System:
    """Stands in for the signed-in user a background job does not have.

    `current_value` resolves scope from an actor, and an agent's scope is
    themselves — so evaluating a team goal as one of its members would compute
    that member's contribution and announce it as the team's number. Silently,
    and low, which is the worst direction for a congratulation to be wrong in.

    A job is not a viewer. It evaluates the goal as the organization, which is
    whose number a goal is. Nothing leaks by doing so: the recipients of a team
    goal's events are the team, who can already see the team's total.

    A distinct object rather than a real admin account, so this cannot quietly
    become "whichever admin is first in the table" and then break when that
    account is archived.
    """

    org_role = "admin"
    team_id = None
    id = None

    def __init__(self, organization_id: int) -> None:
        self.organization_id = organization_id


def emit(
    db: DbSession,
    *,
    org_id: int,
    user_id: int,
    event: EventType,
    subject_type: str,
    subject_id: int,
    title: str,
    period_anchor: date | None = None,
    body: str | None = None,
    link_url: str | None = None,
    created_by_user_id: int | None = None,
    about_name: str | None = None,
    about_user_id: int | None = None,
    media_url: str | None = None,
    media_start_seconds: int | None = None,
    media_end_seconds: int | None = None,
    about_team_id: int | None = None,
    about_office_id: int | None = None,
    quiet: bool = False,
    figure: str | None = None,
) -> bool:
    """Record one notification. Returns whether it was new.

    `quiet` records it without announcing it — see `Notification.quiet`.

    Idempotent for detected events by the unique index, so callers do not check
    first — a check-then-insert is a race, and this runs on a loop that can be
    restarted mid-pass.

    Does not commit. The caller owns the transaction boundary, so one pass over
    many goals is one commit rather than hundreds.
    """
    if _at_daily_cap(db, user_id):
        return False

    statement = (
        insert(Notification)
        .values(
            organization_id=org_id,
            user_id=user_id,
            event_key=event.key,
            subject_type=subject_type,
            subject_id=subject_id,
            period_anchor=period_anchor,
            title=title,
            body=body,
            link_url=link_url,
            created_by_user_id=created_by_user_id,
            about_name=about_name,
            about_user_id=about_user_id,
            media_url=media_url,
            media_start_seconds=media_start_seconds,
            media_end_seconds=media_end_seconds,
            about_team_id=about_team_id,
            about_office_id=about_office_id,
            quiet=quiet,
            celebrated_at=datetime.now(UTC) if quiet else None,
            figure=figure,
        )
        # Untargeted on purpose. Naming the arbiter index would mean repeating
        # its partial WHERE clause here — two copies of a predicate that must
        # agree forever. `notification` has exactly one unique index besides
        # the primary key, so "any unique violation" and "that index" are the
        # same statement, and only one of them can rot.
        .on_conflict_do_nothing()
        .returning(Notification.id)
    )
    return db.scalar(statement) is not None


def _at_daily_cap(db: DbSession, user_id: int) -> bool:
    """A backstop against burying somebody, not a rate limit.

    Every detected event fires once per subject per period, so ordinary volume
    is bounded by how many goals a person has. This is here for the day an
    import goes wrong and creates four hundred of them.
    """
    since = datetime.now(UTC) - timedelta(days=1)
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.created_at >= since)
    )
    return (count or 0) >= events.DAILY_CAP


def _recipients(db: DbSession, goal: Goal) -> list[int]:
    """Who a goal's events are addressed to.

    A personal goal reaches the person and whoever manages them. A team goal
    reaches everyone on the team — a target set for a team is one every member
    is working toward, and telling only the manager would make it the manager's
    goal.

    Managers are resolved from the team the goal is about rather than from the
    recipient's own scope: a notification must never introduce somebody to a
    person they could not already see.
    """
    if goal.subject_type == "organization":
        # **Everybody, because it is everybody's.** A target the whole floor is
        # pulling toward that only reaches managers is a target the floor
        # learns about from a wall.
        return list(
            db.scalars(
                select(UserAccount.id).where(
                    UserAccount.organization_id == goal.organization_id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.status == "active",
                )
            ).all()
        )

    if goal.subject_type == "team":
        return list(
            db.scalars(
                select(UserAccount.id).where(
                    UserAccount.team_id == goal.subject_team_id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.status == "active",
                )
            ).all()
        )

    subject = db.get(UserAccount, goal.subject_user_id)
    if subject is None or subject.hidden_at is not None or subject.status != "active":
        return []

    recipients = [subject.id]
    if subject.team_id is not None:
        recipients.extend(
            db.scalars(
                select(UserAccount.id).where(
                    UserAccount.team_id == subject.team_id,
                    UserAccount.org_role == "manager",
                    UserAccount.hidden_at.is_(None),
                    UserAccount.status == "active",
                    UserAccount.id != subject.id,
                )
            ).all()
        )
    return recipients


def _earners(db: DbSession, goal: Goal) -> list[int]:
    """Who is *paid* for a goal, as opposed to who is told about it.

    **The two lists are deliberately different, and the difference is the
    whole design.** `_recipients` includes the manager of the person whose
    goal it is, because they should hear about it. Paying them for it would
    put every manager at the top of a scoreboard made of other people's work.

    An organization goal pays nobody. Everybody pulling toward one shared
    number is the point of that goal shape, and handing the entire company the
    same award for it moves every balance by the same amount — which changes no
    ranking and teaches people the number is weather rather than something they
    did.

    A team goal pays every member, because a balance somebody can spend has to
    belong to a person, and the alternative — paying the team lead — is the
    manager problem again.
    """
    if goal.subject_type == "organization":
        return []

    if goal.subject_type == "team":
        return list(
            db.scalars(
                select(UserAccount.id).where(
                    UserAccount.team_id == goal.subject_team_id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.status == "active",
                )
            ).all()
        )

    subject = db.get(UserAccount, goal.subject_user_id)
    if subject is None or subject.hidden_at is not None or subject.status != "active":
        return []
    return [subject.id]


def _pay_for_goal(
    db: DbSession,
    org: Organization,
    goal: Goal,
    *,
    anchor: date,
    label: str,
    now: datetime | None = None,
    event_key: str | None = None,
    reason: str | None = None,
) -> None:
    """Award points for a goal that has just been met — or a stretch level on it.

    Keyed on the goal and its period anchor, so a recurring goal pays once per
    period and re-running the detection pass pays nothing — the same latch the
    announcement itself uses.
    """
    for user_id in _earners(db, goal):
        points.award_for(
            db,
            org=org,
            user_id=user_id,
            event_key=event_key or events.GOAL_ACHIEVED.key,
            subject_type="goal",
            subject_id=goal.id,
            period_anchor=anchor,
            reason=reason or f"Hit {label}",
            now=now,
        )


def walkup_for(db: DbSession, user_id: int | None) -> dict[str, int | str | None]:
    """The clip that should play when this person is celebrated.

    Returned as emit's keyword arguments so a caller cannot half-apply it —
    a URL without its offsets would play a whole song on a wall.

    Resolved at emit and then frozen on the row. Changing your walk-up music
    should soundtrack your next win, not retroactively re-score every one you
    have already had.
    """
    if user_id is None:
        return {}
    media = db.get(WalkupMedia, user_id)
    if media is None:
        return {}
    return {
        "media_url": media.url,
        "media_start_seconds": media.start_seconds,
        "media_end_seconds": media.end_seconds,
    }


def where_of(db: DbSession, user_id: int | None, team_id: int | None = None) -> dict:
    """Where somebody sat when this happened, for filtering a wall.

    Snapshotted at emit like `metric_fact.subject_team_id`: a win belongs to
    the office the person was in when they earned it, so a transfer must not
    move last month's news onto a different floor.
    """
    if team_id is None and user_id is not None:
        person = db.get(UserAccount, user_id)
        team_id = person.team_id if person else None
    team = db.get(Team, team_id) if team_id else None
    return {
        "about_team_id": team_id,
        "about_office_id": team.office_id if team else None,
    }


def _about(db: DbSession, goal: Goal) -> tuple[str | None, int | None]:
    """Who the goal is about, for the public feed.

    Distinct from who its notifications are addressed to: a team goal reaches
    four people and is about one team. Resolved once per goal here rather than
    once per recipient, and stored on each row so the feed never has to join
    back to work it out.
    """
    if goal.subject_type == "organization":
        org = db.get(Organization, goal.organization_id)
        # The company's own name. `about_user_id` stays null, which is what
        # keeps `display_name` away from it — "Acme" becoming "A." would be the
        # team-name bug in a different hat.
        return (org.name if org else None), None

    if goal.subject_type == "team":
        team = db.get(Team, goal.subject_team_id)
        return (team.name if team else None), None

    subject = db.get(UserAccount, goal.subject_user_id)
    return (subject.full_name if subject else None), (subject.id if subject else None)


def _anchor(goal: Goal) -> date:
    """Which period an event belongs to.

    August's "you hit your goal" and September's are different events about the
    same goal, and this is what tells them apart. A custom goal does not recur,
    so its own start date is a stable answer.
    """
    return goal.period_anchor or goal.period_start


def _emit_all(
    db: DbSession, report: DetectReport, recipients: list[int], **fields
) -> None:
    """Emit one event to everyone it concerns, keeping the tally honest.

    A helper rather than three copies of the same loop: the counting is the
    part a new event would forget, and a report that undercounts is worse than
    no report because it reads as "nothing happened".
    """
    for user_id in recipients:
        if emit(db, user_id=user_id, **fields):
            report.emitted += 1
        else:
            report.suppressed += 1


def detect(db: DbSession, *, now: datetime | None = None) -> DetectReport:
    """One pass over every live goal, emitting what has become true.

    Almost entirely reads. The only writes are notifications that did not
    already exist, which the unique index decides — so running this twice in a
    row is indistinguishable from running it once.

    `now` is injectable because half of what this decides is "how far into the
    period are we", and a test that cannot pin that can only assert what today
    happens to make true. `pace.compute` already takes one for the same reason.
    """
    report = DetectReport()
    now = now or datetime.now(UTC)
    orgs = {org.id: org for org in db.scalars(select(Organization)).all()}

    for goal in db.scalars(select(Goal).where(Goal.archived_at.is_(None))).all():
        org = orgs.get(goal.organization_id)
        metric = db.get(MetricDefinition, goal.metric_definition_id)
        if org is None or metric is None:
            continue

        recipients = _recipients(db, goal)
        if not recipients:
            continue

        report.considered += 1
        anchor = _anchor(goal)
        label = goal.name or metric.name
        link = f"/goals/{goal.id}"
        period = goal_service.resolve_period(org, goal)

        about_name, about_user_id = _about(db, goal)
        common = {
            **walkup_for(db, about_user_id),
            **where_of(db, about_user_id, goal.subject_team_id),
            "org_id": org.id,
            "subject_type": "goal",
            "subject_id": goal.id,
            "period_anchor": anchor,
            "link_url": link,
            "about_name": about_name,
            "about_user_id": about_user_id,
        }

        # **Only while the period is still running** (P4-1). Finished goals
        # stay in this loop so a late number can still count as a hit — but
        # announcing them as new, or as running out of time, is news about
        # nothing. Nobody saw it until somebody became active late: detection
        # keeps no memory, so to a person activated today every event they
        # never received looked new, and Tony was told about September's goal
        # on 5 October, "100% of September gone".
        still_running = now < period.end

        # Assignment first: true from the moment the goal exists. Running it
        # through the same idempotent path as everything else means a goal
        # spawned by the recurrence job announces itself, without that job
        # knowing anything about notifications.
        if still_running:
            _emit_all(
                db, report, recipients,
                event=events.GOAL_ASSIGNED,
                title=f"New goal: {label}",
                body=period.label,
                **common,
            )

        # Evaluated as the organization, not as a recipient — see `_System`.
        actor = _System(org.id)
        current, has_data = goal_service.current_value(db, org, actor, goal, metric)
        progress = goal_service.progress(
            current, goal.target_value, metric.direction, has_data=has_data
        )
        pace = pace_service.compute(
            period=period,
            now=now,
            timezone=org.timezone,
            aggregation=metric.aggregation,
            percent=progress.percent,
            attained=progress.attained,
            current=progress.current,
        )

        if progress.attained:
            # **Met by numbers it was set over, not by new work** (Q2-11): no
            # number for its metric has arrived since the goal was made. Then
            # it is recorded quietly — true, paid, on the feed, but never a
            # takeover. Once a number arrives after it, a hit is news again.
            already_met = not db.scalar(
                select(MetricFact.id)
                .where(
                    MetricFact.organization_id == org.id,
                    MetricFact.metric_definition_id == metric.id,
                    MetricFact.created_at > goal.created_at,
                    MetricFact.occurred_at >= period.start,
                    MetricFact.occurred_at < period.end,
                )
                .limit(1)
            )
            _emit_all(
                db, report, recipients,
                event=events.GOAL_ACHIEVED,
                title=f"{label} achieved",
                body=period.label,
                quiet=already_met,
                figure=format_value(progress.current, metric, org.currency),
                **common,
            )
            _pay_for_goal(db, org, goal, anchor=anchor, label=label, now=now)

            # Each stretch level crossed, once per period — the same latch as
            # the target, one event key per level so none suppresses another.
            for level in goal_tiers.levels_of(goal.stretch_targets):
                reached = goal_service.progress(
                    current, level.value, metric.direction, has_data=has_data
                ).attained
                if not reached:
                    # Levels are ordered hardest-last, so nothing past this
                    # one can have been reached either.
                    break
                event = events.GOAL_STRETCH[level.level - 1]
                _emit_all(
                    db, report, recipients,
                    event=event,
                    title=f"{label}: {level.label} reached",
                    body=period.label,
                    figure=format_value(progress.current, metric, org.currency),
                    **common,
                )
                _pay_for_goal(
                    db, org, goal, anchor=anchor, label=label, now=now,
                    event_key=event.key, reason=f"{level.label} on {label}",
                )
        elif still_running and pace.elapsed_percent >= events.PERIOD_ENDING_ELAPSED:
            # Only while it is still losable. `attained` above is what stops
            # this firing at somebody who already hit their number, which would
            # be the most irritating notification in the product.
            _emit_all(
                db, report, recipients,
                event=events.GOAL_PERIOD_ENDING,
                title=f"{label} is running out of time",
                body=f"{round(pace.elapsed_percent)}% of {period.label} gone",
                **common,
            )

    return report


def prune(db: DbSession, *, now: datetime | None = None) -> int:
    """Delete notifications older than the retention window. Returns the count.

    Notifications are a feed, not a record. The audit log is what answers "what
    happened and who did it" — this table answers "what should I look at", and a
    two-year-old "you hit your August target" answers nothing. Left unpruned it
    would grow forever to hold rows nobody will ever scroll to.

    Deletes read and unread alike. An unread notification from three months ago
    is not a message somebody is about to act on; keeping it would leave a badge
    that can never be cleared by anything except reading rows nobody wants.
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=events.RETENTION_DAYS)
    result = db.execute(delete(Notification).where(Notification.created_at < cutoff))
    return result.rowcount or 0


@dataclass
class OccasionReport:
    """What a pass over birthdays and anniversaries emitted."""

    people: int = 0
    emitted: int = 0

    def __str__(self) -> str:
        return f"{self.people} to mark, {self.emitted} emitted"


def detect_occasions(
    db: DbSession, *, now: datetime | None = None
) -> OccasionReport:
    """Birthdays and work anniversaries falling on today, per organization.

    **Its own pass rather than a branch inside `detect`.** That one walks
    goals, and everything it does is a question about a target; this walks
    people and asks a question about a calendar. Sharing a loop would mean one
    of the two carrying a subject it has no use for.

    **Today in the organization's timezone, not the server's.** A birthday is a
    date, and a deployment in Phoenix reading a UTC clock marks half of them a
    day early for seven hours every evening.
    """
    report = OccasionReport()
    now = now or datetime.now(UTC)

    for org in db.scalars(select(Organization)).all():
        today = now.astimezone(periods.tz(org)).date()

        people = db.scalars(
            select(UserAccount).where(
                UserAccount.organization_id == org.id,
                UserAccount.status == "active",
                UserAccount.hidden_at.is_(None),
                or_(
                    UserAccount.birthday_month.is_not(None),
                    UserAccount.started_on.is_not(None),
                ),
            )
        ).all()

        for person in people:
            report.people += 1
            if _mark_birthday(db, org, person, today):
                report.emitted += 1
            if _mark_anniversary(db, org, person, today):
                report.emitted += 1

    return report


def _mark_birthday(
    db: DbSession, org: Organization, person: UserAccount, today: date
) -> bool:
    if person.birthday_month is None or person.birthday_day is None:
        return False
    if occasions.marked_on(person.birthday_month, person.birthday_day, today.year) != today:
        return False

    # **Anchored on the year, not on the day it is marked.** A birthday moved
    # off a weekend lands on a different date in different years, and anchoring
    # on that would let the same birthday fire twice as the rule shifted.
    return emit(
        db,
        org_id=org.id,
        user_id=person.id,
        event=events.BIRTHDAY,
        subject_type="user",
        subject_id=person.id,
        period_anchor=date(today.year, 1, 1),
        title="Happy birthday",
        body=person.full_name,
        about_name=person.full_name,
        about_user_id=person.id,
        **walkup_for(db, person.id),
        **where_of(db, person.id),
    )


def _mark_anniversary(
    db: DbSession, org: Organization, person: UserAccount, today: date
) -> bool:
    started = person.started_on
    if started is None:
        return False
    if occasions.marked_on(started.month, started.day, today.year) != today:
        return False

    years = occasions.years_since(started, today)
    # **Nothing on the day itself.** "Zero years today" is a sentence about
    # somebody's first morning, and they have enough happening.
    if years < 1:
        return False

    return emit(
        db,
        org_id=org.id,
        user_id=person.id,
        event=events.WORK_ANNIVERSARY,
        subject_type="user",
        subject_id=person.id,
        period_anchor=date(today.year, 1, 1),
        title=f"{years} {'year' if years == 1 else 'years'} today",
        body=person.full_name,
        about_name=person.full_name,
        about_user_id=person.id,
        **walkup_for(db, person.id),
        **where_of(db, person.id),
    )


def detect_rules(db: DbSession, *, now: datetime | None = None) -> RuleReport:
    """Celebrate individual pieces of work, rather than goals being completed.

    A goal is a target over a period. "Closed a deal over $5,000" is neither,
    and it is most of what a sales floor actually celebrates — so this fires
    off a single fact instead.

    **Two guards stop a backfill flooding the wall.** A connector syncing six
    months of history inserts thousands of rows with fresh ids and old
    timestamps, and announcing every one would be catastrophic in a way that is
    obvious only after it happens:

      * `last_fact_id` — a high-water mark, so a pass never re-examines what it
        has already seen. An optimisation, not a correctness guarantee.
      * `occurred_at >= rule.created_at` — the real protection, and Spinify's
        stated rule: an achievement is never applied retroactively. Work done
        before the rule existed is not celebrated by it.

    The unique index on `notification` is the backstop if either is wrong.
    """
    report = RuleReport()
    now = now or datetime.now(UTC)

    rules = db.scalars(
        select(AchievementRule).where(AchievementRule.enabled.is_(True))
    ).all()

    for rule in rules:
        report.rules += 1
        metric = db.get(MetricDefinition, rule.metric_definition_id)
        org = db.get(Organization, rule.organization_id)
        if metric is None or org is None:
            continue

        # **Defined in one place**, because the badge pass counts the same
        # facts — and a badge saying ten while the wall announced eight is
        # worse than either being wrong alone. See `app/achievements.py`,
        # which also explains why "looked at" and "qualified" are two
        # predicates rather than one.
        #
        # The watermark is this pass's own: it means "already examined", not
        # "not a match", which is why it is added here rather than living with
        # the predicate.
        considered = [
            *achievements.considered(rule),
            MetricFact.id > rule.last_fact_id,
        ]
        comparison = achievements.bar(rule)

        # The watermark moves past everything *examined*, not just what
        # matched — and the difference is a flood.
        #
        # An admin sets the bar at $50,000, sees nothing for a week, and lowers
        # it to $5,000. If the watermark had only advanced past matches, every
        # deal from that week would suddenly qualify and announce at once. That
        # is the same failure a backfill causes, arrived at from the other
        # direction, and "the rule existed but the bar was higher" is not work
        # anybody expects to be celebrated retroactively.
        highest = db.scalar(
            select(func.max(MetricFact.id)).where(*considered)
        )

        for fact in db.scalars(
            select(MetricFact).where(*considered, comparison).order_by(MetricFact.id)
        ).all():
            report.facts += 1

            person = db.get(UserAccount, fact.subject_user_id)
            if person is None or person.hidden_at is not None:
                continue

            value = format_value(fact.value, metric, org.currency)
            if emit(
                db,
                org_id=rule.organization_id,
                user_id=person.id,
                event=events.achievement(rule.event_key),
                # Keyed on the FACT, so one rule announces each piece of work
                # exactly once and no anchor is needed.
                subject_type="metric_fact",
                subject_id=fact.id,
                period_anchor=None,
                title=rule.name,
                # **Rendered once, here, and stored on the row.** The message
                # is what was said at the moment somebody earned it; filling
                # the tags in again at read time would let a transfer or a
                # rename quietly rewrite last month's announcement.
                body=merge_tags.render(
                    rule.message,
                    # Seeded by the fact, so this win always reads the same
                    # way and the next one probably does not.
                    seed=fact.id,
                    name=person.full_name,
                    first_name=person.full_name.split(" ")[0],
                    value=value,
                    metric=metric.name,
                )
                or f"{person.full_name} — {value}",
                about_name=person.full_name,
                about_user_id=person.id,
                figure=value,
                # From the fact, not from the person: they may have moved since,
                # and the win belongs to the team they were on at the time.
                **where_of(db, person.id, fact.subject_team_id),
                **rule_media(db, rule, person.id),
            ):
                report.emitted += 1
                # Paid only when the announcement was new. The emit above is
                # the thing that decides whether this fact has been seen
                # before, so hanging the award off its answer means the two
                # can never disagree about what happened.
                points.award(
                    db,
                    org=org,
                    user_id=person.id,
                    points=rule.points,
                    event_key=points.rule_key(rule.id),
                    subject_type="metric_fact",
                    subject_id=fact.id,
                    reason=rule.name,
                    now=now,
                )

        if highest is not None:
            # No `max()` guard: the query above already filters
            # `id > last_fact_id`, so anything it returns is larger by
            # construction and the watermark cannot move backwards. A mutation
            # proved the guard could be deleted without changing a result —
            # the third piece of redundant defence found that way this session.
            rule.last_fact_id = highest

    return report


def rule_media(db: DbSession, rule: AchievementRule, user_id: int) -> dict:
    """What plays for this win: their music, or the rule's.

    **Theirs wins by default**, and the rule's clip is the fallback. Most people
    never open their settings, so a rule with media is how a floor gets sound at
    all — and the few who have chosen their own should still get it. The
    earlier version had this the other way round, which meant setting a rule's
    media silently overwrote everybody's choice.

    `allow_personal_media = False` forces the rule's clip on everybody, for the
    win that should always sound the same. With no media set that is a
    deliberate silence: the announcement still appears, it just plays nothing.
    """
    rule_clip = {
        "media_url": rule.media_url,
        "media_start_seconds": rule.media_start_seconds,
        "media_end_seconds": rule.media_end_seconds,
    }
    if not rule.allow_personal_media:
        return rule_clip
    return walkup_for(db, user_id) or (rule_clip if rule.media_url else {})


#: Symbols for the currencies an organization is likely to set. Anything else
#: is written with its code ("CHF 500"), which is how a currency without a
#: well-known symbol is written anyway.
CURRENCY_SYMBOLS = {
    "USD": "$", "CAD": "$", "AUD": "$", "NZD": "$", "MXN": "$",
    "GBP": "£", "EUR": "€", "JPY": "¥", "INR": "₹",
}


def format_value(value: Decimal, metric: MetricDefinition, currency: str = "USD") -> str:
    """The number as the metric would show it, for the announcement body.

    **Money says it is money** (Q2-2): "$500", not "500.00" — the wall said
    "just closed 500.00!" while the rule form's own sample said "$6,200". And
    whole amounts drop the cents in a sentence: "$500", as somebody would say
    it; "$499.50" keeps them.
    """
    quantised = round(value, metric.decimal_places)
    if metric.unit == "currency":
        whole = quantised == quantised.to_integral_value()
        figure = f"{quantised:,.0f}" if whole else f"{quantised:,.{metric.decimal_places}f}"
        symbol = CURRENCY_SYMBOLS.get(currency)
        sign, digits = ("-", figure[1:]) if figure.startswith("-") else ("", figure)
        return f"{sign}{symbol}{digits}" if symbol else f"{currency} {figure}"
    text = f"{quantised:,.{metric.decimal_places}f}".rstrip(".")
    return units.with_noun(text, quantised, metric.unit, metric.unit_label)
