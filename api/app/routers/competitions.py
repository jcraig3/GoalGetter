"""The competition API.

Two rules here are worth reading before the code.

**Entering a contest is consent to be ranked in it.** Everywhere else in this
product, one person's numbers are hidden from another's by `visible_user_ids`.
Standings deliberately break that: a competition whose entrants cannot see each
other's positions is not a competition. The scope rule therefore governs
*seeing the contest at all* — once you are in it, you see the whole table.

**A running competition is nearly frozen.** Its name and look can change
freely. Three things can change with a reason given (6.14): the prize, a later
end, and a late entrant — each the kind of thing that really happens to a
contest (the prize got better, the floor asked for another week, the new
starter wants in), none of which takes anything from somebody who was already
winning. The reason goes in the audit log and on the contest's page, so
everybody can see what changed and why. Everything else — metric, start,
rules, an earlier end, removing an entrant — stays refused: changing the rules
mid-contest destroys the result, and the result is the only thing here anybody
will remember.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, competition_rounds as rounds, competitions as service, periods
from app.appearance import Appearance
from app.db import get_db
from app.models import (
    Competition,
    CompetitionParticipant,
    MetricDefinition,
    Organization,
    Team,
    UserAccount,
)
from app.models.competition import ENTITY_TYPES, TIE_BREAKS
from app.scope import EVERYONE, can_see_user, visible_user_ids
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/competitions", tags=["competitions"])

#: States in which the rules may still be changed.
#:
#: `scheduled` qualifies as well as `draft`: a scheduled competition is
#: published and visible, but has not started, so nobody has competed under the
#: old rules yet. Once `active`, only the label changes.
EDITABLE_STATES = ("draft", "scheduled")

#: Changes allowed while a contest runs, with a reason (6.14). See the module
#: docstring.
RUNNING_CHANGES = ("prize", "ends_at")

#: Audit actions that are a change to a running contest — what its page lists.
RUNNING_ACTIONS = ("competition.changed_while_running", "competition.joined_late")

#: Fewer entrants than this is not a contest.
#:
#: Checked at publish rather than create, because the creation flow is
#: deliberately "make the thing, then choose who is in it" — an empty draft is a
#: normal intermediate state, and a published one-horse race is not.
MIN_ENTRANTS = 2


class StandingRead(BaseModel):
    entity_id: int
    entity_name: str
    rank: int
    value: Decimal
    #: To the place immediately above; null for the leader. See app/competitions.py.
    gap_to_next: Decimal | None
    final: bool
    #: A person's face, for the head-to-head panels (8.5). Null for a team.
    photo_digest: str | None = None


class ParticipantRead(BaseModel):
    id: int
    entity_id: int
    entity_name: str


class CompetitionRead(BaseModel):
    id: int
    name: str
    prize: str | None

    metric_id: int
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    direction: str

    entity_type: str
    starts_at: datetime
    ends_at: datetime

    settlement_hours: int
    #: When the result freezes. Computed, so no client has to do date arithmetic
    #: to draw the one thing that changes what the page means.
    settles_at: datetime
    state: str
    closed_at: datetime | None

    tie_break: str
    min_participation: int | None
    #: Where a race layout draws the finish line. See `app/game_boards.py`.
    finish_line: Decimal | None = None

    entrant_count: int
    #: True for exactly two entrants — the cue to render two big numbers rather
    #: than a ranked list. Derived, never stored: see documentation/09.
    head_to_head: bool

    #: Ended, not yet frozen. Drives the "provisional — finalizing" banner.
    provisional: bool
    #: Whether the rules may still change, so the UI can lock the fields and say
    #: why rather than the server refusing a save nobody expected.
    rules_editable: bool
    #: Running: the prize, a later end and late entrants may change, each with
    #: a reason (6.14).
    running_editable: bool = False

    #: What this has chosen for itself, sparsely. Empty means it follows the
    #: organization; a channel or a single screen can still override. See
    #: `app/appearance.py`.
    appearance: dict = {}

    #: The series this round belongs to — its first round's id — and how it
    #: repeats. A one-off contest is its own series of one, with no repeat.
    series_id: int | None = None
    #: 1 for the first round, 2 for the second, and so on.
    round_number: int = 1
    repeat: str | None = None
    repeat_until: date | None = None


class RoundRead(BaseModel):
    id: int
    round_number: int
    starts_at: datetime
    ends_at: datetime
    state: str
    #: Who won it, once it is settled.
    winner: str | None = None


class RepeatWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: None stops it repeating. Rounds already made are kept.
    repeat: Literal["daily", "weekly", "monthly"] | None = None
    until: date | None = None


class CompetitionDetail(BaseModel):
    """One competition, with everything its page draws.

    Composed here for the same reason the dashboard and goal detail are: a
    client assembling it would make three round trips whose answers have to
    agree about whether the contest closed between them.
    """

    competition: CompetitionRead
    standings: list[StandingRead]
    #: The actor's own row, repeated, so the UI can pin it without searching a
    #: list it may have truncated. Null when the actor is not an entrant.
    you: StandingRead | None
    #: What changed while it ran, and why, newest first (6.14).
    changes: list["ChangeRead"] = []


class ChangeRead(BaseModel):
    at: datetime
    who: str | None
    #: "The end moved from Fri 9 Oct to Fri 16 Oct."
    what: str
    #: The reason given.
    note: str


class CompetitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120)
    metric_id: int
    entity_type: str = "user"
    starts_at: datetime
    ends_at: datetime
    prize: str | None = Field(default=None, max_length=200)
    settlement_hours: int = Field(default=24, ge=0, le=168)
    tie_break: str = "earliest_to_reach"
    min_participation: int | None = Field(default=None, ge=1)
    #: Where a race layout draws the finish line, in the metric's unit.
    #: Optional — a race with none is measured against the leader.
    finish_line: Decimal | None = Field(default=None, gt=0)
    #: Entrants may be named up front or added afterwards. Both are real flows —
    #: "Phoenix versus Dallas" is known at the moment of typing, and a
    #: forty-person sprint is not.
    entity_ids: list[int] = Field(default_factory=list)
    #: Run it again every day, week or month. See `app/competition_rounds.py`.
    repeat: Literal["daily", "weekly", "monthly"] | None = None
    repeat_until: date | None = None

    @field_validator("entity_type")
    @classmethod
    def _entity(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of: {', '.join(ENTITY_TYPES)}")
        return value

    @field_validator("tie_break")
    @classmethod
    def _tie(cls, value: str) -> str:
        if value not in TIE_BREAKS:
            raise ValueError(f"tie_break must be one of: {', '.join(TIE_BREAKS)}")
        return value

    @model_validator(mode="after")
    def _window(self) -> "CompetitionCreate":
        # Checked here as well as by the database constraint. The constraint is
        # what makes it impossible; this is what makes it legible — an
        # IntegrityError reaches the user as "something went wrong".
        if self.ends_at <= self.starts_at:
            raise ValueError("A competition has to end after it starts.")
        return self

    #: **Replaces rather than merges.** A merging update could not express "stop
    #: setting this and follow the default", because absence would mean "leave
    #: it alone" — the opposite of what a reset needs.
    appearance: Appearance | None = None


class CompetitionUpdate(BaseModel):
    """What may change, and when.

    `name` and `prize` are always editable — they are how the contest is
    described, not how it is decided. Everything else is refused once the
    competition is `active`, in the endpoint rather than here, because whether a
    field is editable depends on the row and not on the payload.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name(120) | None = None
    prize: str | None = Field(default=None, max_length=200)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    settlement_hours: int | None = Field(default=None, ge=0, le=168)
    tie_break: str | None = None
    min_participation: int | None = Field(default=None, ge=1)
    #: Where a race layout draws the finish line, in the metric's unit.
    #: Optional — a race with none is measured against the leader.
    finish_line: Decimal | None = Field(default=None, gt=0)
    #: Why, for a change to a running contest (6.14). Required then; ignored
    #: before it starts, when nobody has competed under the old terms.
    note: str | None = Field(default=None, max_length=300)

    @field_validator("tie_break")
    @classmethod
    def _tie(cls, value: str | None) -> str | None:
        if value is not None and value not in TIE_BREAKS:
            raise ValueError(f"tie_break must be one of: {', '.join(TIE_BREAKS)}")
        return value

    #: **Replaces rather than merges.** A merging update could not express "stop
    #: setting this and follow the default", because absence would mean "leave
    #: it alone" — the opposite of what a reset needs.
    appearance: Appearance | None = None


class ParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: int
    #: Why, for somebody joining a contest already running (6.14).
    note: str | None = Field(default=None, max_length=300)


def _org(db: DbSession, actor: UserAccount) -> Organization:
    return db.get(Organization, actor.organization_id)


def _entrant_ids(db: DbSession, competition: Competition) -> list[int]:
    rows = db.execute(
        select(CompetitionParticipant.user_id, CompetitionParticipant.team_id).where(
            CompetitionParticipant.competition_id == competition.id
        )
    ).all()
    return [(user_id or team_id) for user_id, team_id in rows]


def _may_see(db: DbSession, actor: UserAccount, competition: Competition) -> bool:
    """Whether this competition appears for this person at all.

    **You are in it, or you could see every entrant anyway.**

    One sentence, and it lands where it should for each role without a special
    case: an admin sees everything, a manager sees a contest confined to their
    own people, an agent sees the contests they are competing in. An agent does
    not see a manager-versus-manager contest in another office, which they have
    no stake in and would only learn other people's numbers from.

    "Every", not "any". A contest between one colleague they can see and forty
    they cannot would otherwise be a forty-name leak.
    """
    visible = visible_user_ids(db, actor)
    if visible is EVERYONE:
        return True

    ids = _entrant_ids(db, competition)
    if not ids:
        # Nobody is in it yet, so there is no entrant list to earn a place in it
        # through — and the person building it still has to be able to open it
        # and add entrants. Their own, and nobody else's.
        #
        # This branch first returned a flat False, which was right for everybody
        # except the one person standing in the middle of the creation flow: a
        # manager 404'd on the draft they had just made. Mutation testing found
        # it, by way of the mutant that made an empty draft public surviving —
        # a line whose two opposite versions both pass is a line nothing has
        # pinned down.
        return competition.created_by_user_id == actor.id

    if competition.entity_type == "team":
        # For a team contest the rule collapses to "your team is in it".
        #
        # A non-admin sees their own team plus unplaced agents, and an unplaced
        # agent is on no team — so the only entrant team whose members are *all*
        # visible to them is their own. An earlier version checked that
        # member-by-member. It looked more thorough and computed the same answer
        # in every case but one: two **empty** teams, where `all()` over no
        # members is vacuously True and would have shown that contest to the
        # entire organization. Mutation testing flagged the check as inert,
        # which is what sent me looking for the case where it was not.
        return actor.team_id is not None and actor.team_id in ids

    if actor.id in ids:
        return True
    return all(entrant in visible for entrant in ids)


def _to_read(db: DbSession, competition: Competition, *, entrants: int) -> CompetitionRead:
    metric = db.get(MetricDefinition, competition.metric_definition_id)
    root = rounds.root_of(db, competition)
    return CompetitionRead(
        series_id=root.id,
        round_number=(competition.round or 0) + 1,
        repeat=root.repeat,
        repeat_until=root.repeat_until,
        id=competition.id,
        name=competition.name,
        prize=competition.prize,
        metric_id=metric.id if metric else 0,
        metric_name=metric.name if metric else "Deleted metric",
        unit=metric.unit if metric else "number",
        decimal_places=metric.decimal_places if metric else 0,
        unit_label=metric.unit_label if metric else None,
        direction=metric.direction if metric else "higher_is_better",
        entity_type=competition.entity_type,
        starts_at=competition.starts_at,
        ends_at=competition.ends_at,
        settlement_hours=competition.settlement_hours,
        settles_at=competition.ends_at + timedelta(hours=competition.settlement_hours),
        state=competition.state,
        closed_at=competition.closed_at,
        tie_break=competition.tie_break,
        min_participation=competition.min_participation,
        finish_line=competition.finish_line,
        entrant_count=entrants,
        head_to_head=entrants == 2,
        provisional=competition.state == "ended",
        rules_editable=competition.state in EDITABLE_STATES,
        running_editable=competition.state == "active",
        appearance=competition.appearance or {},
    )


def _standing_read(row: service.Standing) -> StandingRead:
    return StandingRead(
        entity_id=row.entity_id,
        entity_name=row.entity_name,
        rank=row.rank,
        value=row.value,
        gap_to_next=row.gap_to_next,
        final=row.final,
    )


def _owned(db: DbSession, actor: UserAccount, competition_id: int) -> Competition:
    competition = db.get(Competition, competition_id)
    if competition is None or competition.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found."
        )
    # 404 rather than 403, as everywhere else: a 403 confirms the thing exists,
    # which is half of what the caller was fishing for.
    if not _may_see(db, actor, competition):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found."
        )
    return competition


def _check_entity(db: DbSession, actor: UserAccount, entity_type: str, entity_id: int) -> str:
    """Confirm an entrant exists, is in this organization, and is the actor's to
    enter. Returns their name, so the caller can put it in a message."""
    if entity_type == "team":
        team = db.get(Team, entity_id)
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )
        if actor.org_role != "admin" and team.id != actor.team_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only enter your own team.",
            )
        return team.name

    person = db.get(UserAccount, entity_id)
    if (
        person is None
        or person.organization_id != actor.organization_id
        or not can_see_user(db, actor, person.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return person.full_name


@router.get("", response_model=list[CompetitionRead])
def list_competitions(
    state: str | None = Query(default=None, description="Filter to one state"),
    mine: bool = Query(default=False, description="Only competitions you are in"),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[CompetitionRead]:
    """Competitions the actor may see, newest window first.

    Drafts are hidden from agents. A draft is being configured; an agent
    discovering one would be reading a plan, not an announcement.
    """
    query = select(Competition).where(
        Competition.organization_id == actor.organization_id
    )
    if state:
        query = query.where(Competition.state == state)
    if actor.org_role == "agent":
        query = query.where(Competition.state != "draft")

    rows = db.scalars(
        query.order_by(Competition.starts_at.desc(), Competition.id.desc())
    ).all()

    results: list[CompetitionRead] = []
    for competition in rows:
        if not _may_see(db, actor, competition):
            continue
        ids = _entrant_ids(db, competition)
        if mine:
            own = actor.team_id if competition.entity_type == "team" else actor.id
            if own is None or own not in ids:
                continue
        results.append(_to_read(db, competition, entrants=len(ids)))
    return results


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    entity_type: str = "user"
    entity_ids: list[int] = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime

    @field_validator("entity_type")
    @classmethod
    def _entity(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            raise ValueError(f"entity_type must be one of: {', '.join(ENTITY_TYPES)}")
        return value

    @model_validator(mode="after")
    def _window(self) -> "PreviewRequest":
        if self.ends_at <= self.starts_at:
            raise ValueError("A competition has to end after it starts.")
        return self


class Preview(BaseModel):
    """What this contest would have looked like last time.

    The question a person actually has when setting one up is not "what is the
    target" — a competition has no target — it is **"will this be worth
    watching?"** A field where one entrant does four times the volume of the rest
    is a walkover, and the honest moment to find that out is before anybody is
    told they are competing.

    So: the same metric, the same entrants, over the equally-long window
    immediately before this one.
    """

    #: The window that was measured, so the UI can name it rather than implying
    #: the numbers are from the future.
    starts_at: datetime
    ends_at: datetime
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None

    standings: list[StandingRead]
    #: How far the leader was ahead of last place, as a multiple. Null when the
    #: bottom of the field recorded nothing, where a ratio has no meaning.
    #:
    #: One number for "is this a contest or a coronation", which is easier to act
    #: on than reading the table and doing it in your head.
    spread: float | None


@router.post("/preview", response_model=Preview)
def preview_competition(
    payload: PreviewRequest,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> Preview:
    """A dry run over the preceding window.

    Registered above `/{competition_id}` on purpose. FastAPI matches in
    definition order, and while `competition_id: int` would reject "preview" with
    a 422 rather than mis-routing it, relying on a type coercion failure to keep
    two endpoints apart is the sort of thing that stops being true when somebody
    changes the parameter to a string.
    """
    metric = db.get(MetricDefinition, payload.metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")

    for entity_id in payload.entity_ids:
        _check_entity(db, actor, payload.entity_type, entity_id)

    # The same length, and genuinely in the past.
    #
    # Same length because "last month" against a two-week sprint is comparing a
    # number to a bigger one.
    #
    # Anchored at whichever comes first — the competition's start, or now. The
    # first version always measured backwards from `starts_at`, which is only
    # historical if the contest begins today: a contest scheduled for the first
    # of next month got a "history" running from a fortnight ago to a fortnight
    # ahead, most of it the future, and every number in it came back zero. The
    # unit test agreed with the bug because it asserted what the code did.
    # Running it against real data was what showed it.
    anchor = min(payload.starts_at, datetime.now(UTC))
    length = payload.ends_at - payload.starts_at
    org = _org(db, actor)

    # Built as an unsaved Competition so the preview goes through exactly the
    # scoring the real thing will. A second code path here would be a second
    # place for the numbers to be right in isolation and disagree in practice.
    rehearsal = Competition(
        organization_id=org.id,
        name="Preview",
        metric_definition_id=metric.id,
        entity_type=payload.entity_type,
        starts_at=anchor - length,
        ends_at=anchor,
        state="active",
    )
    rows = service.standings_for(
        db, org, rehearsal, entity_ids=list(dict.fromkeys(payload.entity_ids))
    )

    spread: float | None = None
    if len(rows) >= 2 and rows[-1].value > 0:
        spread = round(float(rows[0].value / rows[-1].value), 1)

    return Preview(
        starts_at=rehearsal.starts_at,
        ends_at=rehearsal.ends_at,
        metric_name=metric.name,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        standings=[_standing_read(row) for row in rows],
        spread=spread,
    )



@router.get("/{competition_id}", response_model=CompetitionDetail)
def read_competition(
    competition_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> CompetitionDetail:
    competition = _owned(db, actor, competition_id)
    org = _org(db, actor)

    rows = service.standings(db, org, competition)
    own_id = actor.team_id if competition.entity_type == "team" else actor.id
    mine = next((row for row in rows if row.entity_id == own_id), None)

    standings = [_standing_read(row) for row in rows]
    # Faces only where they are drawn: two people facing each other (8.5).
    if competition.entity_type == "user" and len(standings) == 2:
        from app import photos

        for standing in standings:
            person = db.get(UserAccount, standing.entity_id)
            standing.photo_digest = photos.digest_of(db, person) if person else None

    return CompetitionDetail(
        competition=_to_read(db, competition, entrants=len(_entrant_ids(db, competition))),
        standings=standings,
        you=_standing_read(mine) if mine else None,
        changes=_running_changes(db, competition),
    )


def _running_changes(db: DbSession, competition: Competition) -> list[ChangeRead]:
    """What changed while this contest ran, from the audit log.

    The log rather than a table of its own: it already records who and when,
    and a second record of the same change is a second thing to keep honest.
    """
    from app.models import AuditLog

    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == competition.organization_id,
            AuditLog.action.in_(RUNNING_ACTIONS),
            AuditLog.details["competition_id"].as_integer() == competition.id,
        )
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    ).all()
    out = []
    for row in rows:
        actor = db.get(UserAccount, row.actor_user_id) if row.actor_user_id else None
        details = row.details or {}
        out.append(
            ChangeRead(
                at=row.occurred_at,
                who=actor.full_name if actor else row.actor_email,
                what=details.get("what", ""),
                note=details.get("note", ""),
            )
        )
    return out


def _reason(note: str | None) -> str:
    """The reason for a change to a running contest, or a refusal saying so."""
    note = " ".join((note or "").split())
    if len(note) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Say why — this contest is running, and everybody in it will "
                "see what changed and the reason given."
            ),
        )
    return note


def _when(org: Organization, moment: datetime) -> str:
    """"Fri 16 Oct, 5 pm" in the organization's time — the way the pages say it
    (Q2-29)."""
    local = moment.astimezone(periods.tz(org))
    minutes = f":{local:%M}" if local.minute else ""
    noon = "am" if local.hour < 12 else "pm"
    return f"{local:%a} {local.day} {local:%b}, {local.hour % 12 or 12}{minutes} {noon}"


@router.get("/{competition_id}/participants", response_model=list[ParticipantRead])
def list_participants(
    competition_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[ParticipantRead]:
    competition = _owned(db, actor, competition_id)
    rows = db.scalars(
        select(CompetitionParticipant).where(
            CompetitionParticipant.competition_id == competition.id
        )
    ).all()
    return [
        ParticipantRead(
            id=p.id,
            entity_id=p.user_id or p.team_id,
            entity_name=service.name_of(db, competition, p.user_id or p.team_id),
        )
        for p in rows
    ]


@router.post("", response_model=CompetitionRead, status_code=status.HTTP_201_CREATED)
def create_competition(
    payload: CompetitionCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    metric = db.get(MetricDefinition, payload.metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")
    if metric.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{metric.name}' is archived. Restore it before running a "
                "competition on it."
            ),
        )

    if payload.repeat is not None:
        _check_repeat(
            _org(db, actor), payload.starts_at, payload.ends_at, payload.repeat,
            payload.repeat_until,
        )

    competition = Competition(
        repeat=payload.repeat,
        repeat_until=payload.repeat_until if payload.repeat else None,
        # Sparse on disk: a field nobody chose stays absent, so a later
        # change to the organization's default still reaches this one.
        appearance=(payload.appearance or Appearance()).model_dump(
            exclude_none=True
        ),
        organization_id=actor.organization_id,
        name=payload.name,
        prize=payload.prize,
        metric_definition_id=metric.id,
        entity_type=payload.entity_type,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        settlement_hours=payload.settlement_hours,
        tie_break=payload.tie_break,
        min_participation=payload.min_participation,
        finish_line=payload.finish_line,
        state="draft",
        created_by_user_id=actor.id,
    )
    db.add(competition)
    db.flush()

    # Duplicates are dropped rather than refused. Sending the same person twice
    # is a client bug, not something to make a person resolve.
    for entity_id in dict.fromkeys(payload.entity_ids):
        _check_entity(db, actor, payload.entity_type, entity_id)
        db.add(
            CompetitionParticipant(
                competition_id=competition.id,
                user_id=entity_id if payload.entity_type == "user" else None,
                team_id=entity_id if payload.entity_type == "team" else None,
            )
        )
    db.flush()

    audit.record(
        db,
        actor=actor,
        action="competition.created",
        request=request,
        name=competition.name,
        metric=metric.key,
        entity_type=competition.entity_type,
        entrants=len(set(payload.entity_ids)),
    )
    db.commit()
    return _to_read(db, competition, entrants=len(_entrant_ids(db, competition)))


@router.patch("/{competition_id}", response_model=CompetitionRead)
def update_competition(
    competition_id: int,
    payload: CompetitionUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    """Edit a competition. The rules are locked once it starts.

    The refusal names the fields rather than saying "not allowed", because the
    person is mid-edit and needs to know which part to undo.
    """
    competition = _owned(db, actor, competition_id)
    if competition.state in ("closed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This competition is {competition.state} and can no longer be edited.",
        )

    changes = payload.model_dump(exclude_unset=True)
    note = changes.pop("note", None)
    if "appearance" in changes:
        changes["appearance"] = (
            payload.appearance or Appearance()
        ).model_dump(exclude_none=True)

    # **What can be changed while a contest is running.** Everything else is a
    # rule, and changing a rule mid-contest makes the result meaningless.
    #
    # `appearance` belongs here: it decides what the screen looks like, not who
    # wins. Treating it as a rule would refuse to recolour a live contest —
    # which is exactly when somebody wants to, the week it is on the wall — and
    # would do it with a message reading "cannot change its appearance", which
    # sounds like a bug rather than a decision.
    # `finish_line` too: it decides where a race layout draws the flag, not
    # who wins — the standings are the same with or without it.
    cosmetic = {"name", "appearance", "finish_line"}
    # Only what actually changes counts — a form that sends the whole
    # contest back must not need a reason for a prize it left alone.
    changes = {
        field: value
        for field, value in changes.items()
        if field in cosmetic or getattr(competition, field) != value
    }
    running = competition.state not in EDITABLE_STATES
    rule_changes = sorted(set(changes) - cosmetic - (set(RUNNING_CHANGES) if running else set()))

    if rule_changes and running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A competition that has started cannot change its "
                f"{', '.join(rule_changes)}. Changing the rules mid-contest "
                "would make the result meaningless. The name, the prize and a "
                "later end can still change."
            ),
        )

    told: list[str] = []
    org = _org(db, actor)
    if running and set(changes) & set(RUNNING_CHANGES):
        if competition.state != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This competition has finished, so its prize and end are settled.",
            )
        reason = _reason(note)
        if "ends_at" in changes:
            new_end = changes["ends_at"]
            # **Later only.** An earlier end decides the contest early for
            # whoever happens to be ahead today; a later one gives everybody
            # the same extra time.
            if new_end <= competition.ends_at:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "A running competition can be extended but not cut short — "
                        "ending early hands it to whoever is ahead today."
                    ),
                )
            told.append(
                f"The end moved from {_when(org, competition.ends_at)} to {_when(org, new_end)}."
            )
        if "prize" in changes:
            before = competition.prize or "no prize"
            after = changes["prize"] or "no prize"
            told.append(f"The prize changed from “{before}” to “{after}”.")

    starts_at = changes.get("starts_at", competition.starts_at)
    ends_at = changes.get("ends_at", competition.ends_at)
    # Checked against the merged pair, not the payload: sending only a new
    # `ends_at` can invert a window whose `starts_at` was already stored.
    if ends_at <= starts_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A competition has to end after it starts.",
        )

    if competition.repeat is not None and ("starts_at" in changes or "ends_at" in changes):
        _check_repeat(_org(db, actor), starts_at, ends_at, competition.repeat, competition.repeat_until)

    for field, value in changes.items():
        setattr(competition, field, value)

    if told:
        audit.record(
            db,
            actor=actor,
            action="competition.changed_while_running",
            request=request,
            competition_id=competition.id,
            name=competition.name,
            fields=sorted(set(changes) & set(RUNNING_CHANGES)),
            what=" ".join(told),
            note=reason,
        )
    elif changes:
        audit.record(
            db,
            actor=actor,
            action="competition.updated",
            request=request,
            name=competition.name,
            fields=sorted(changes),
        )
    db.commit()
    return _to_read(db, competition, entrants=len(_entrant_ids(db, competition)))


@router.post("/{competition_id}/publish", response_model=CompetitionRead)
def publish_competition(
    competition_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    """Publish it, and start it if the clock says it has already begun.

    Publishing used to set `scheduled` and stop, leaving the lifecycle job to
    promote it. That is correct and reads terribly: publish a contest whose start
    date has passed and it sat under *Upcoming* saying "starts in now" until the
    next pass. So this runs the same state machine the job runs — `advance_one` —
    which lands it wherever the clock actually puts it, and tells the entrants if
    that is "running".

    The job's function rather than a copy of its logic, because two places that
    decide when a contest starts would eventually disagree, and one of them is the
    one that announces.
    """
    competition = _owned(db, actor, competition_id)
    if competition.state != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This competition is already {competition.state}.",
        )

    entrants = _entrant_ids(db, competition)
    if len(entrants) < MIN_ENTRANTS:
        word = "entrant" if len(entrants) == 1 else "entrants"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A competition needs at least {MIN_ENTRANTS} entrants. "
                f"This one has {len(entrants)} {word}."
            ),
        )

    competition.state = "scheduled"
    audit.record(
        db,
        actor=actor,
        action="competition.published",
        request=request,
        name=competition.name,
        entrants=len(entrants),
    )
    # Needs the flush: `advance_one` reads the state that was just set.
    db.flush()
    service.advance_one(db, _org(db, actor), competition)
    db.commit()
    return _to_read(db, competition, entrants=len(entrants))


@router.post("/{competition_id}/cancel", response_model=CompetitionRead)
def cancel_competition(
    competition_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    """Stop it with no winner.

    Kept separate from closing early, which produces one. Cancelling is the
    honest option when a contest was set up wrongly, and it leaves no result to
    be quoted later.
    """
    competition = _owned(db, actor, competition_id)
    if competition.state == "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This competition has already been settled. Cancelling it now "
                "would remove a result people have seen."
            ),
        )

    # Captured before the assignment. It was read after, so the audit log
    # recorded every cancellation as coming from `cancelled`.
    was = competition.state
    competition.state = "cancelled"
    audit.record(
        db,
        actor=actor,
        action="competition.cancelled",
        request=request,
        name=competition.name,
        was=was,
    )
    db.commit()
    return _to_read(db, competition, entrants=len(_entrant_ids(db, competition)))


#: States a competition can be pulled back to draft from.
#:
#: Everything except `draft` (already there) and `closed` — a settled result is
#: the one thing here that cannot be walked back, because somebody has been told
#: they won.
REOPENABLE_STATES = ("scheduled", "active", "ended", "cancelled")

#: States a competition can be deleted in.
#:
#: The rule is "it never produced a result and is not running". A live contest
#: should be cancelled first, which is a decision somebody can see, rather than
#: vanishing from under its entrants.
DELETABLE_STATES = ("draft", "cancelled")


@router.post("/{competition_id}/unpublish", response_model=CompetitionRead)
def unpublish_competition(
    competition_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    """Back to draft — the escape hatch from every state that has one.

    Publishing was previously a one-way door: a contest with the wrong metric or
    the wrong dates could only be cancelled, which left it sitting in Finished
    for good. Returning it to draft hides it from entrants again and unlocks the
    rules, which is what somebody who has just spotted a mistake actually wants.

    Refused from `closed`, and that is the only refusal. A frozen result has been
    announced; reopening it would make the winner provisional after the fact.
    """
    competition = _owned(db, actor, competition_id)
    if competition.state == "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This competition is already a draft.",
        )
    if competition.state not in REOPENABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This competition has been settled. Its result has already been "
                "announced, so it cannot be reopened — copy it into a new "
                "competition instead."
            ),
        )

    was = competition.state
    competition.state = "draft"
    audit.record(
        db,
        actor=actor,
        action="competition.unpublished",
        request=request,
        name=competition.name,
        was=was,
    )
    db.commit()
    return _to_read(db, competition, entrants=len(_entrant_ids(db, competition)))


@router.delete("/{competition_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_competition(
    competition_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    """Remove a competition that never produced a result.

    Draft and cancelled only. Both mean "nothing came of this", so there is no
    record to protect — entrant rows go with it through the cascade, and no
    result was ever frozen.

    A settled competition is refused outright rather than confirmed away: it is
    the record of a prize somebody received, which is the whole reason its
    numbers are stored instead of derived. A running one has to be cancelled
    first, so its entrants see a decision rather than a disappearance.
    """
    competition = _owned(db, actor, competition_id)
    if competition.state not in DELETABLE_STATES:
        detail = (
            "A settled competition is the record of a result people were given. "
            "It cannot be deleted."
            if competition.state == "closed"
            else (
                f"This competition is {competition.state}. Cancel it first — "
                "deleting a contest out from under the people competing in it "
                "leaves them wondering what happened to it."
            )
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # Both read before the delete. Attributes survive on a deleted instance
    # until the session expires it, which makes reading them afterwards work
    # right up until it does not — the same shape as the `cancel` audit bug
    # above, where the state was read after being reassigned.
    name, was = competition.name, competition.state
    # "QA2 sprint has started", linking to a contest that is gone (Q2-6).
    from app import cleanup

    cleanup.forget(db, actor.organization_id, *cleanup.about("competition", competition.id))
    db.delete(competition)
    audit.record(
        db,
        actor=actor,
        action="competition.deleted",
        request=request,
        name=name,
        was=was,
    )
    db.commit()


@router.post("/{competition_id}/close", response_model=CompetitionDetail)
def close_competition(
    competition_id: int,
    request: Request,
    # Admin only. Freezing a result early is the one action here that cannot be
    # undone and that somebody will be asked to justify.
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> CompetitionDetail:
    """Settle now, without waiting out the settlement window.

    For the case the window exists to handle going wrong: an integration that
    will not sync, or a contest everyone has moved on from. It writes the same
    columns the job would.
    """
    competition = _owned(db, actor, competition_id)
    if competition.state in ("draft", "scheduled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This competition has not started, so there is no result to settle.",
        )
    if competition.state != "active" and competition.state != "ended":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This competition is {competition.state}.",
        )

    org = _org(db, actor)
    ranked = service.close(db, org, competition)
    audit.record(
        db,
        actor=actor,
        action="competition.closed_early",
        request=request,
        name=competition.name,
        ranked=ranked,
    )
    db.commit()
    return read_competition(competition_id, actor=actor, db=db)


@router.post(
    "/{competition_id}/participants",
    response_model=ParticipantRead,
    status_code=status.HTTP_201_CREATED,
)
def add_participant(
    competition_id: int,
    payload: ParticipantCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> ParticipantRead:
    competition = _owned(db, actor, competition_id)
    late = competition.state == "active"
    if competition.state not in EDITABLE_STATES and not late:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This competition has finished, so nobody new can join it.",
        )
    # **A late entrant, with a reason** (6.14). Their numbers count from the
    # start, the same window as everyone's — joining late is less time to
    # *notice*, not less time to have scored.
    reason = _reason(payload.note) if late else None

    name = _check_entity(db, actor, competition.entity_type, payload.entity_id)
    if payload.entity_id in _entrant_ids(db, competition):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{name} is already in this competition.",
        )

    participant = CompetitionParticipant(
        competition_id=competition.id,
        user_id=payload.entity_id if competition.entity_type == "user" else None,
        team_id=payload.entity_id if competition.entity_type == "team" else None,
    )
    db.add(participant)
    db.flush()

    target = db.get(UserAccount, payload.entity_id) if competition.entity_type == "user" else None
    if late:
        audit.record(
            db,
            actor=actor,
            action="competition.joined_late",
            request=request,
            target=target,
            competition_id=competition.id,
            name=competition.name,
            entrant=name,
            what=f"{name} joined after it started.",
            note=reason,
        )
    else:
        audit.record(
            db,
            actor=actor,
            action="competition.entrant_added",
            request=request,
            target=target,
            name=competition.name,
            entrant=name,
        )
    db.commit()
    return ParticipantRead(id=participant.id, entity_id=payload.entity_id, entity_name=name)


@router.delete(
    "/{competition_id}/participants/{participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_participant(
    competition_id: int,
    participant_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    competition = _owned(db, actor, competition_id)
    if competition.state not in EDITABLE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Entrants cannot be removed from a competition that has "
                "started. Cancel it instead — taking somebody out of a contest "
                "they have been competing in rewrites what everyone else saw."
            ),
        )

    participant = db.get(CompetitionParticipant, participant_id)
    if participant is None or participant.competition_id != competition.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrant not found.")

    entity_id = participant.user_id or participant.team_id
    _check_entity(db, actor, competition.entity_type, entity_id)
    name = service.name_of(db, competition, entity_id)

    db.delete(participant)
    audit.record(
        db,
        actor=actor,
        action="competition.entrant_removed",
        request=request,
        name=competition.name,
        entrant=name,
    )
    db.commit()


@router.post(
    "/{competition_id}/duplicate",
    response_model=CompetitionRead,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_competition(
    competition_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    """Run last month's contest again, with the same people and rules.

    **The commonest competition is the last one.** A monthly sprint between the
    same fourteen people, on the same metric, for the same prize — rebuilt each
    time by retyping it and re-ticking the entrants, which is where somebody
    misses one.

    **It arrives as a draft**, whatever the original is now. A copy that
    started running the moment it was made would be a contest nobody had
    checked the dates on, and the dates are the one thing that always needs
    changing.

    **The window keeps its length, not its dates.** A copy of a contest that
    ran last March, dated last March, has already finished — so it is moved to
    start now and run for as long as the original did. Somebody duplicating a
    fortnight's sprint gets a fortnight.
    """
    original = _owned(db, actor, competition_id)

    length = original.ends_at - original.starts_at
    starts = datetime.now(UTC)

    copy = Competition(
        organization_id=actor.organization_id,
        name=_copy_name(db, actor.organization_id, original.name),
        metric_definition_id=original.metric_definition_id,
        entity_type=original.entity_type,
        starts_at=starts,
        ends_at=starts + length,
        prize=original.prize,
        settlement_hours=original.settlement_hours,
        tie_break=original.tie_break,
        min_participation=original.min_participation,
        finish_line=original.finish_line,
        appearance=dict(original.appearance or {}),
        state="draft",
        created_by_user_id=actor.id,
    )
    db.add(copy)
    db.flush()

    for participant in db.scalars(
        select(CompetitionParticipant).where(
            CompetitionParticipant.competition_id == original.id
        )
    ).all():
        db.add(
            CompetitionParticipant(
                competition_id=copy.id,
                user_id=participant.user_id,
                team_id=participant.team_id,
            )
        )

    audit.record(
        db,
        actor=actor,
        action="competition.duplicated",
        request=request,
        name=copy.name,
        copied_from=original.name,
    )
    db.commit()
    return _to_read(db, copy, entrants=len(_entrant_ids(db, copy)))


def _copy_name(db: DbSession, organization_id: int, name: str) -> str:
    """"Month-end push (copy)", and then "(copy 2)".

    Named rather than numbered from the start, because the first copy is
    usually the only one and "(copy 1)" reads like there are others.
    """
    taken = set(
        db.scalars(
            select(Competition.name).where(
                Competition.organization_id == organization_id
            )
        ).all()
    )
    stem = name[:100]
    for attempt in range(1, 50):
        suffix = " (copy)" if attempt == 1 else f" (copy {attempt})"
        candidate = f"{stem}{suffix}"
        if candidate not in taken:
            return candidate
    return f"{stem} (copy)"


# ── Repeating ────────────────────────────────────────────────────────────────


def _check_repeat(
    org: Organization, starts_at: datetime, ends_at: datetime, repeat: str, until: date | None
) -> None:
    if not rounds.fits(org, starts_at, ends_at, repeat):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A contest this long cannot repeat {repeat} — one round would still be "
                "running when the next began. Shorten it, or repeat it less often."
            ),
        )
    if until is not None and until < periods.local_date(org, starts_at):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The last round cannot start before the first one.",
        )


@router.put("/{competition_id}/repeat", response_model=CompetitionRead)
def set_repeat(
    competition_id: int,
    payload: RepeatWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionRead:
    """Make a contest repeat, change how, or stop it.

    Set on the series whichever round is opened, because repeating belongs to
    the series. **Allowed in any state**: it decides future rounds, not this
    one's rules — a contest that has already been settled can still start
    running every week from now on. Stopping keeps every round already made;
    an upcoming one can be cancelled like any other contest.
    """
    competition = _owned(db, actor, competition_id)
    root = rounds.root_of(db, competition)
    if payload.repeat is not None:
        _check_repeat(_org(db, actor), root.starts_at, root.ends_at, payload.repeat, payload.until)
    root.repeat = payload.repeat
    root.repeat_until = payload.until if payload.repeat else None
    audit.record(
        db, actor=actor, action="competition.repeat", request=request,
        name=root.name, repeat=payload.repeat or "never",
        until=payload.until.isoformat() if payload.until and payload.repeat else "",
    )
    db.flush()
    # Straight away, so the next round is on the list without waiting for the job.
    rounds.spawn_due(db)
    db.commit()
    return _to_read(db, competition, entrants=len(_entrant_ids(db, competition)))


@router.get("/{competition_id}/rounds", response_model=list[RoundRead])
def list_rounds(
    competition_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[RoundRead]:
    """Every round of this contest's series the caller may see, first first —
    so the history of a weekly sprint, and who won each week, is one list."""
    competition = _owned(db, actor, competition_id)
    root = rounds.root_of(db, competition)
    out: list[RoundRead] = []
    for row in rounds.rounds_of(db, root):
        if row.id != competition.id and not _may_see(db, actor, row):
            continue
        winner = None
        if row.state == "closed":
            first = db.scalar(
                select(CompetitionParticipant).where(
                    CompetitionParticipant.competition_id == row.id,
                    CompetitionParticipant.final_rank == 1,
                )
            )
            if first is not None:
                winner = service.name_of(db, row, first.user_id or first.team_id)
        out.append(
            RoundRead(
                id=row.id, round_number=(row.round or 0) + 1, starts_at=row.starts_at,
                ends_at=row.ends_at, state=row.state, winner=winner,
            )
        )
    return out

