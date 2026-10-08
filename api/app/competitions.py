"""Running a contest, and freezing its result.

Scoring is the same `aggregate` query as everything else — a competition is not
a new way to measure. What it adds is a **defined entrant set**, a **defined
end**, and a **result that stops changing**.

That last one is the only place this product stores a computed number, and it
inverts the rule the rest of it follows. Everything else is derived because
derived numbers stay correct: correct an August fact and August's leaderboard
updates, which is what you want. A competition result is the opposite — a prize
was handed over on the strength of it — so at close it is written down and read
from there forever after.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, events, notifications, periods, points
from app.models import (
    Competition,
    CompetitionParticipant,
    MetricDefinition,
    MetricFact,
    Organization,
    Team,
    UserAccount,
)
from app.periods import Period
from app.scope import EVERYONE


@dataclass
class Standing:
    """One row of a competition table, live or frozen."""

    entity_id: int
    entity_name: str
    rank: int
    value: Decimal
    #: How far behind the entrant immediately above. None for the leader.
    #:
    #: The gap that matters is to the *next* place, not to first: "$4,100
    #: behind 6th" is something somebody can do today, and "$45,300 behind 1st"
    #: is a reason to stop trying.
    gap_to_next: Decimal | None = None
    #: True once the result is frozen, so a caller cannot mistake a settled
    #: table for a live one.
    final: bool = False


#: No viewer, deliberately.
#:
#: A competition's standings are the same for everybody who can see it — the
#: entrant set *is* the scope, so there is no per-person narrowing to apply.
#: `aggregate` reads its actor for exactly one purpose: working out `visible`
#: when the caller did not say. This module always says, so the actor is never
#: read.
#:
#: An earlier version passed a fake admin here. Mutation testing proved it
#: inert — flipping it to `agent` changed no answer, because nothing looks at
#: it. Worse than useless: it would have quietly handed admin-wide visibility
#: to any future call that stopped passing `visible`, where `None` raises
#: instead. Fifth piece of my own dead code found this way.
NO_ACTOR = None


def window(competition: Competition) -> Period:
    """The competition's window, as the aggregation engine wants it.

    Absolute instants rather than a period type: a competition is an event
    somebody scheduled, and re-resolving a period later could give a different
    answer if the organization's timezone changed. For a settled result that
    would be rewriting history.
    """
    return Period(
        type="custom",
        start=competition.starts_at,
        end=competition.ends_at,
        label=competition.name,
    )


def _entrants(db: DbSession, competition: Competition) -> list[CompetitionParticipant]:
    return list(
        db.scalars(
            select(CompetitionParticipant).where(
                CompetitionParticipant.competition_id == competition.id
            )
        ).all()
    )


def name_of(db: DbSession, competition: Competition, entity_id: int) -> str:
    if competition.entity_type == "team":
        team = db.get(Team, entity_id)
        return team.name if team else "Deleted team"
    person = db.get(UserAccount, entity_id)
    return person.full_name if person else "Deleted user"


def _with_gaps(standings: list[Standing]) -> list[Standing]:
    """Fill in how far each entrant is behind the one above."""
    for above, row in zip(standings, standings[1:]):
        row.gap_to_next = abs(above.value - row.value)
    return standings


def standings(db: DbSession, org: Organization, competition: Competition) -> list[Standing]:
    """The table, live or frozen depending on whether it has closed.

    One function for both so that no caller has to remember which — a page that
    recomputed a settled competition would quietly disagree with the trophy.
    """
    if competition.is_settled:
        return _frozen(db, competition)
    return _live(db, org, competition)


def _frozen(db: DbSession, competition: Competition) -> list[Standing]:
    rows = [
        Standing(
            entity_id=p.user_id or p.team_id or 0,
            entity_name=name_of(db, competition, p.user_id or p.team_id or 0),
            rank=p.final_rank,
            value=p.final_value if p.final_value is not None else Decimal(0),
            final=True,
        )
        for p in _entrants(db, competition)
        # An unranked entrant — below `min_participation` — has no place in
        # the table. They were in the contest and did not qualify, which is
        # different from finishing last.
        if p.final_rank is not None
    ]
    rows.sort(key=lambda r: (r.rank, r.entity_name))
    return _with_gaps(rows)


def standings_for(
    db: DbSession,
    org: Organization,
    competition: Competition,
    *,
    entity_ids: list[int],
) -> list[Standing]:
    """Score a named entrant set over this competition's window.

    Split out from `_live` so the creation flow can rehearse a contest that does
    not exist yet — an unsaved `Competition` has no participant rows to read, and
    the preview must go through exactly this scoring rather than a second copy of
    it. Two code paths here would be two places for the numbers to be right in
    isolation and disagree in practice.
    """
    metric = db.get(MetricDefinition, competition.metric_definition_id)
    ids = [i for i in dict.fromkeys(entity_ids) if i is not None]
    if metric is None or not ids:
        return []

    # Ranked *within the entrants*. Ranking against the whole organization and
    # hiding the rest would give a different, wrong number — second of two is
    # not the same as second of forty.
    rows = aggregate.run(
        db,
        org.id,
        NO_ACTOR,
        metric,
        window(competition),
        group_by=competition.entity_type,
        visible=ids if competition.entity_type == "user" else EVERYONE,
        team_ids=ids if competition.entity_type == "team" else None,
    )

    scored = {row.subject_id: row for row in rows}
    standings_rows = [
        Standing(
            entity_id=entity_id,
            entity_name=name_of(db, competition, entity_id),
            rank=scored[entity_id].rank if entity_id in scored else len(scored) + 1,
            value=scored[entity_id].value if entity_id in scored else Decimal(0),
        )
        for entity_id in ids
    ]
    standings_rows.sort(key=lambda r: (r.rank, r.entity_name))
    return _with_gaps(standings_rows)


def _live(db: DbSession, org: Organization, competition: Competition) -> list[Standing]:
    """The stored entrants, scored."""
    return standings_for(
        db, org, competition, entity_ids=_entrant_ids_of(db, competition)
    )


def _reached_at(
    db: DbSession, competition: Competition, entity_id: int
) -> datetime | None:
    """When this entrant last added to their total inside the window.

    Used only for `earliest_to_reach`. The entrant who got to the number first
    wins the tie, which is how a sales contest is settled in practice — and it
    is worth one extra query at close to avoid a disputed dead heat.
    """
    column = (
        MetricFact.subject_team_id
        if competition.entity_type == "team"
        else MetricFact.subject_user_id
    )
    from app import derived

    metric = db.get(MetricDefinition, competition.metric_definition_id)
    # For a derived metric, whichever of its parts they last added to.
    ids = derived.fact_metric_ids(db, metric) if metric else [competition.metric_definition_id]
    return db.scalar(
        select(func.max(MetricFact.occurred_at)).where(
            MetricFact.organization_id == competition.organization_id,
            MetricFact.metric_definition_id.in_(ids),
            MetricFact.occurred_at >= competition.starts_at,
            MetricFact.occurred_at < competition.ends_at,
            column == entity_id,
        )
    )


def close(db: DbSession, org: Organization, competition: Competition) -> int:
    """Write the result down. Returns how many entrants were ranked.

    After this the standings come from these columns and nothing recomputes
    them — which is the point, and the single most important behaviour in the
    feature. A correction that lands tomorrow changes the leaderboard for that
    period and leaves the trophy alone.
    """
    metric = db.get(MetricDefinition, competition.metric_definition_id)
    live = _live(db, org, competition)
    by_entity = {row.entity_id: row for row in live}

    #: How many facts each entrant contributed, for `min_participation`.
    counts: dict[int, int] = {}
    # Facts behind the score: for a derived metric, the denominator's — a
    # close rate over two deals is the thing a participation floor exists
    # to keep off the podium.
    counted = (
        metric.denominator_metric_id
        if metric is not None and metric.aggregation == "ratio"
        else competition.metric_definition_id
    )
    if competition.min_participation:
        column = (
            MetricFact.subject_team_id
            if competition.entity_type == "team"
            else MetricFact.subject_user_id
        )
        counts = dict(
            db.execute(
                select(column, func.count())
                .where(
                    MetricFact.organization_id == competition.organization_id,
                    MetricFact.metric_definition_id == counted,
                    MetricFact.occurred_at >= competition.starts_at,
                    MetricFact.occurred_at < competition.ends_at,
                )
                .group_by(column)
            ).all()
        )

    qualified: list[tuple[CompetitionParticipant, Standing, datetime | None]] = []
    for participant in _entrants(db, competition):
        entity_id = participant.team_id or participant.user_id
        row = by_entity.get(entity_id)
        if row is None:
            continue
        if competition.min_participation and counts.get(entity_id, 0) < competition.min_participation:
            # In the contest, did not qualify. Left unranked rather than placed
            # last, because those mean different things.
            continue
        qualified.append(
            (participant, row, _reached_at(db, competition, entity_id))
        )

    higher_wins = metric is None or metric.direction != "lower_is_better"
    # Sorted by value, then — for `earliest_to_reach` — by who got there first.
    # `datetime.max` puts an entrant with no facts behind anyone who has some.
    qualified.sort(
        key=lambda item: (
            -item[1].value if higher_wins else item[1].value,
            item[2] or datetime.max.replace(tzinfo=UTC)
            if competition.tie_break == "earliest_to_reach"
            else datetime.min.replace(tzinfo=UTC),
        )
    )

    rank = 0
    previous: tuple | None = None
    for index, (participant, row, reached) in enumerate(qualified):
        key = (row.value,) if competition.tie_break == "shared_rank" else (row.value, reached)
        # `shared_rank` gives 1, 2, 2, 4 — the honest default when two entrants
        # genuinely finished level. `earliest_to_reach` never ties, because the
        # timestamp is part of the key.
        if previous is None or key != previous:
            rank = index + 1
            previous = key
        participant.final_rank = rank
        participant.final_value = row.value
        participant.reached_at = reached

    competition.state = "closed"
    competition.closed_at = datetime.now(UTC)

    # Announced here rather than in the job, so settling early through the API
    # produces exactly what the clock would have. Needs the flush: the frozen
    # columns above are what `announce_result` reads back.
    db.flush()
    announce_result(db, competition)
    return len(qualified)


def _people(
    db: DbSession, competition: Competition, entity_ids: list[int]
) -> list[int]:
    """Who to actually notify, for these entrants.

    A notification goes to a **person**. For a user contest that is the entrants
    themselves; for a team contest it is everybody *on* those teams, because
    "Enterprise won" is news to the twelve people who made that happen and not to
    a row in a table.

    Archived and non-active accounts are left out, the same as everywhere else
    that picks recipients.

    **One function for both announcements**, and it was not always. `audience()`
    applied this filter and the per-entrant lookup did not, so somebody still on
    an unaccepted invitation was told they finished third in a contest nothing had
    ever told them had started. Two places computing the same thing is the shape
    of bug this codebase keeps finding; live data found this one.
    """
    if not entity_ids:
        return []

    query = select(UserAccount.id).where(
        # The organization clause cannot change an answer today: every id here
        # comes from one competition's participants, and those are validated
        # against the caller's organization when they are added. A mutation
        # removing it survives, and no honest test can kill it — team and user ids
        # are globally unique, so an out-of-org id simply matches nothing.
        #
        # It stays because this query decides who receives a notification, and the
        # cost of the clause is nothing against the cost of a future caller
        # passing ids it has not checked. Stated rather than pretended: seventh
        # piece of redundant defence found this way, and the first kept on
        # purpose.
        UserAccount.organization_id == competition.organization_id,
        UserAccount.hidden_at.is_(None),
        UserAccount.status == "active",
    )
    if competition.entity_type == "team":
        query = query.where(UserAccount.team_id.in_(entity_ids))
    else:
        query = query.where(UserAccount.id.in_(entity_ids))
    return list(db.scalars(query).all())


def audience(db: DbSession, competition: Competition) -> list[int]:
    """Everybody with a stake in this competition."""
    return _people(db, competition, _entrant_ids_of(db, competition))


def _entrant_ids_of(db: DbSession, competition: Competition) -> list[int]:
    entrants = _entrants(db, competition)
    ids = [
        p.team_id if competition.entity_type == "team" else p.user_id for p in entrants
    ]
    return [i for i in ids if i is not None]


def announce_start(db: DbSession, competition: Competition) -> int:
    """Tell the entrants it has begun. Returns how many were told.

    Idempotent through the unique index on `notification`, so a job restarted
    mid-pass cannot tell anybody twice. What makes it unique is
    `subject_id` — the competition — not the anchor: a mutation setting
    `period_anchor` to None changed no behaviour, because `NULLS NOT DISTINCT`
    still collapses the duplicates. The anchor is carried because it is true and
    useful to read, not because anything depends on it.
    """
    anchor = competition.starts_at.date()
    told = 0
    for user_id in audience(db, competition):
        if notifications.emit(
            db,
            org_id=competition.organization_id,
            user_id=user_id,
            event=events.COMPETITION_STARTED,
            subject_type="competition",
            subject_id=competition.id,
            period_anchor=anchor,
            title=f"{competition.name} has started",
            body=_start_body(db, competition),
            link_url=f"/competitions/{competition.id}",
        ):
            told += 1
    return told


def _start_body(db: DbSession, competition: Competition) -> str:
    # **The organization's day, not UTC's.** Stored in UTC, a contest ending at
    # 7pm on the 2nd in New York ends on the 3rd, and said so (QA-14).
    org = db.get(Organization, competition.organization_id)
    prize = f" {competition.prize} is on the line." if competition.prize else ""
    return f"Runs until {until(org, competition.ends_at)}.{prize}"


def until(org: Organization, ends_at: datetime) -> str:
    """"Fri 14 Aug, 8 pm" in the organization's time — the app's date style
    (P3-14), where it said only "14 August" and left the hour to guess.

    **Midnight closes the day before**: a contest ending at 00:00 on the 16th
    runs "until the end of Sat 15 Aug". `.day` rather than `%-d`, which is
    glibc-only and prints a literal "%-d" on somebody's Mac.
    """
    local = ends_at.astimezone(periods.tz(org))
    if local.hour == 0 and local.minute == 0:
        day = periods.last_day(org, ends_at)
        return f"the end of {day:%a} {day.day} {day:%b}"
    minutes = f":{local:%M}" if local.minute else ""
    noon = "am" if local.hour < 12 else "pm"
    return f"{local:%a} {local.day} {local:%b}, {local.hour % 12 or 12}{minutes} {noon}"


def announce_result(db: DbSession, competition: Competition) -> int:
    """Announce the winner, and tell everybody else where they came.

    Two events on purpose. The win is public and celebrated — it is the moment a
    prize is handed over, and the entire point is that other people see it.
    Finishing fifth is private, for the same reason `goal.period_ending` is: a
    permanent display in front of the floor is not the place for it.

    Called from `close()` rather than from the job, so settling early through the
    API announces exactly the same way the clock would have.
    """
    table = _frozen(db, competition)
    if not table:
        return 0

    org = db.get(Organization, competition.organization_id)
    anchor = competition.starts_at.date()
    winners = [row for row in table if row.rank == 1]
    winner_names = ", ".join(row.entity_name for row in winners)
    told = 0

    # The public announcement is addressed to each winner, so it lands in their
    # bell as well as on the wall. A shared rank means two of them, which is why
    # this is a loop rather than `table[0]`.
    for row in winners:
        for user_id in _people(db, competition, [row.entity_id]):
            if notifications.emit(
                db,
                org_id=competition.organization_id,
                user_id=user_id,
                event=events.COMPETITION_WON,
                subject_type="competition",
                subject_id=competition.id,
                period_anchor=anchor,
                title=f"{row.entity_name} won {competition.name}",
                body=(
                    f"{competition.prize}" if competition.prize else None
                ),
                about_name=row.entity_name,
                about_user_id=row.entity_id if competition.entity_type == "user" else None,
                about_team_id=row.entity_id if competition.entity_type == "team" else None,
                figure=_winning_figure(db, org, competition, row.value),
                **_win_media(db, competition, row.entity_id),
            ):
                told += 1
            _pay(db, org, competition, user_id, events.COMPETITION_WON.key,
                 f"Won {competition.name}")

    placed = {row.entity_id: row for row in table}
    for row in table:
        if row.rank == 1:
            continue
        for user_id in _people(db, competition, [row.entity_id]):
            if notifications.emit(
                db,
                org_id=competition.organization_id,
                user_id=user_id,
                event=events.COMPETITION_FINISHED,
                subject_type="competition",
                subject_id=competition.id,
                period_anchor=anchor,
                title=f"{competition.name} is over",
                body=(
                    f"{row.entity_name} finished {_place(row.rank)} of "
                    f"{len(placed)}. {winner_names} won."
                ),
                link_url=f"/competitions/{competition.id}",
            ):
                told += 1
            # **The podium pays, the rest of the field does not.** Entering a
            # contest and finishing third should beat not entering; paying
            # everyone who was named in one would make entry itself the
            # income, and then the winner's award is a rounding error on a
            # number everybody got.
            if row.rank <= PAID_PLACES:
                _pay(db, org, competition, user_id, PLACED,
                     f"{_place(row.rank)} in {competition.name}")
    return told


def _winning_figure(
    db: DbSession, org: Organization | None, competition: Competition, value: Decimal
) -> str | None:
    """The winning score as the metric says it, "$12,400" (7.9)."""
    metric = db.get(MetricDefinition, competition.metric_definition_id)
    if metric is None:
        return None
    return notifications.format_value(value, metric, org.currency if org else "USD")


def _win_media(db: DbSession, competition: Competition, entity_id: int) -> dict:
    """Personal walk-up media for a win, and never for a team.

    A win is a celebration, so it gets what an achievement gets. But
    `walkup_for()` takes a **user** id, and a team's id comes from a different
    sequence that also starts at 1 — so handing it a team id would look up
    whichever *person* happens to share that number and play their song for their
    team's victory. Nothing would raise; it would simply be the wrong music.

    Its own function because that cannot be caught by a natural test: the shared
    test database has run its sequences far apart, so team and user ids never
    collide there, while in a fresh organization they overlap completely. Pulled
    out, the branch can be asserted directly — see
    test_competition_announcements.py.
    """
    if competition.entity_type != "user":
        return {}
    return notifications.walkup_for(db, entity_id)





#: How far down the table an award reaches.
PAID_PLACES = 3

#: What finishing on the podium without winning is worth. Not an event anybody
#: is notified about — `competition.finished` is deliberately private — so it
#: is a ledger key of its own rather than one from the catalogue.
PLACED = "competition.placed"


def _pay(
    db: DbSession,
    org: Organization,
    competition: Competition,
    user_id: int,
    event_key: str,
    reason: str,
) -> None:
    """Award points for where somebody finished.

    Keyed on the competition and its start date, so settling the same contest
    twice — which `close` already refuses, but which a future path might not —
    cannot pay twice.
    """
    points.award_for(
        db,
        org=org,
        user_id=user_id,
        event_key=event_key,
        subject_type="competition",
        subject_id=competition.id,
        period_anchor=competition.starts_at.date(),
        reason=reason,
    )


def _place(rank: int) -> str:
    """1st, 2nd, 3rd — including the 11th/12th/13th exceptions.

    The web app has its own copy in `competitionClock.ts`, because a notification
    body is written here and read there; sharing it would mean shipping a
    formatting rule over HTTP.
    """
    if rank % 100 in (11, 12, 13):
        return f"{rank}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def advance_one(
    db: DbSession,
    org: Organization,
    competition: Competition,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Move **one** competition to the state the clock says it should be in.

    Split out from `advance()` so publishing can use it. Publishing used to set
    `scheduled` and stop, leaving the job to promote it — so a contest whose start
    date had already passed sat under *Upcoming* saying "starts in now" until the
    next pass. Running the same state machine here means publish lands it wherever
    the clock actually puts it.

    The same function rather than a second copy, because the alternative is two
    places that agree today and drift later — and one of them would be the one
    that announces to entrants.
    """
    now = now or datetime.now(UTC)
    moved = {"started": 0, "ended": 0, "closed": 0}

    if competition.state == "scheduled" and now >= competition.starts_at:
        competition.state = "active"
        moved["started"] += 1
        announce_start(db, competition)

    if competition.state == "active" and now >= competition.ends_at:
        competition.state = "ended"
        moved["ended"] += 1

    if competition.state == "ended":
        # The settlement window. A deal closed at 4:55pm that syncs at 5:10pm
        # still counts, and announcing a winner and then changing it is far worse
        # than a day's delay.
        settles_at = competition.ends_at + timedelta(
            hours=competition.settlement_hours
        )
        if now >= settles_at:
            close(db, org, competition)
            moved["closed"] += 1

    return moved


def advance(db: DbSession, *, now: datetime | None = None) -> dict[str, int]:
    """Move every competition to the state the clock says it should be in.

    A job rather than something computed on read, because the transitions have
    consequences — closing writes the result down and announces it, and starting
    tells the entrants. Neither should depend on somebody happening to load a
    page.
    """
    now = now or datetime.now(UTC)
    moved = {"started": 0, "ended": 0, "closed": 0}

    orgs = {o.id: o for o in db.scalars(select(Organization)).all()}

    # This filter is an index seek, not a guard. `draft`, `closed` and
    # `cancelled` match none of the branches in `advance_one`, so widening it
    # changes no answer — mutation testing confirmed that, and there is no test
    # to write for a line that cannot change a result. It stays because
    # `ix_competition_org_state` makes it cheap and the intent is worth
    # stating; the branches there are what actually keeps a draft from going
    # live behind its author's back.
    for competition in db.scalars(
        select(Competition).where(
            Competition.state.in_(["scheduled", "active", "ended"])
        )
    ).all():
        org = orgs.get(competition.organization_id)
        if org is None:
            continue
        for key, count in advance_one(db, org, competition, now=now).items():
            moved[key] += count

    return moved
