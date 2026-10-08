"""Balances, seasons, and what each thing is worth.

**Everybody can see the season table**, deliberately, and that is the one
scoping decision here worth arguing about. Every other ranked thing in this
product narrows to what the viewer may see; a points table that did the same
would show an agent a league of four people and call it a league. The economy
only works if there is one board everybody is on — which is exactly the
argument a published leaderboard already makes, and the same deliberate hole,
spelled out at the call site rather than hidden behind a flag.

What stays narrow is everything *behind* the number: a statement is your own,
and awarding points by hand is scoped like any other write.
"""

import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import audit, badges as badge_service, points as service
from app import unlocks as unlock_service
from app import seasons as season_service, tiers as tier_service
from app.models import badge as badge_model
from app.db import get_db
from app.models import (
    AchievementRule,
    Badge,
    BadgeAward,
    Organization,
    PointValue,
    Season,
    StoredAsset,
    Tier,
    UserAccount,
)
from app.scope import can_see_user
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/points", tags=["points"])


class SeasonRead(BaseModel):
    id: int
    name: str
    starts_on: date
    ends_on: date
    closed_at: datetime | None


def _season_read(season: Season) -> SeasonRead:
    return SeasonRead(
        id=season.id,
        name=season.name,
        starts_on=season.starts_on,
        ends_on=season.ends_on,
        closed_at=season.closed_at,
    )


class AwardRead(BaseModel):
    id: int
    points: int
    event_key: str
    subject_type: str
    subject_id: int
    reason: str
    created_at: datetime


def _award_read(row) -> AwardRead:
    """Read the columns by name.

    Not `vars(row)`: a SQLAlchemy instance's `__dict__` holds only what is
    currently loaded, and every attribute expires on commit — so the shorthand
    returns an empty dict at exactly the moment a freshly written row is being
    returned to the caller.
    """
    return AwardRead(
        id=row.id,
        points=row.points,
        event_key=row.event_key,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        reason=row.reason,
        created_at=row.created_at,
    )


class MeRead(BaseModel):
    """What one person has, and where it came from."""

    #: Null when nothing has ever been awarded here. The page says so rather
    #: than showing a zero, which would look like a balance somebody spent.
    season: SeasonRead | None
    points: int
    rank: int | None
    #: Every season added together. A fact about somebody's history, and
    #: deliberately not what anything ranks on — see `points.lifetime`.
    lifetime: int
    statement: list[AwardRead]

    #: The rung they hold now, and the one after it. Null when no ladder has
    #: been set up, which is the ordinary state — tiers are optional in a way
    #: seasons are not.
    tier: str | None = None
    next_tier: str | None = None
    #: Points from here to the next rung. **The only part of a ladder that
    #: changes behaviour** — the badge rewards what already happened, the
    #: distance is the reason to do something this week.
    to_next_tier: int | None = None

    #: What can be spent: earned in every season, less what was spent. A
    #: different number from `points` on purpose — see `points.WALLET_PREFIX`.
    wallet: int = 0
    #: What they have on, if anything. See `app/unlocks.py`.
    ring: str | None = None
    title: str | None = None


@router.get("/me", response_model=MeRead)
def me(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> MeRead:
    org = db.get(Organization, actor.organization_id)
    season = season_service.current(db, org)

    if season is None:
        worn = unlock_service.worn_by(db, {actor.id}).get(actor.id)
        return MeRead(
            season=None, points=0, rank=None,
            lifetime=service.lifetime(db, org.id, actor.id), statement=[],
            wallet=service.wallet(db, org.id, actor.id),
            ring=worn.ring if worn else None,
            title=worn.title if worn else None,
        )

    mine = next(
        (
            row
            for row in service.standings(db, season)
            if row.user_id == actor.id
        ),
        None,
    )
    points_now = mine.points if mine else 0
    worn = unlock_service.worn_by(db, {actor.id}).get(actor.id)
    reached = tier_service.standing_for(
        points_now, tier_service.ladder(db, org.id)
    )
    return MeRead(
        season=_season_read(season),
        points=points_now,
        rank=mine.rank if mine else None,
        tier=reached.current.name if reached.current else None,
        next_tier=reached.next.name if reached.next else None,
        to_next_tier=reached.to_next,
        wallet=service.wallet(db, org.id, actor.id),
        ring=worn.ring if worn else None,
        title=worn.title if worn else None,
        lifetime=service.lifetime(db, org.id, actor.id),
        statement=[
            _award_read(row)
            for row in service.statement(db, org.id, actor.id, season_id=season.id)
        ],
    )


class StandingRead(BaseModel):
    user_id: int
    name: str
    points: int
    rank: int
    #: The rung this balance reaches. Resolved from a ladder fetched once for
    #: the whole table rather than once per row.
    tier: str | None = None
    #: What they have on. One query for the whole table — see `worn_by`.
    ring: str | None = None
    title: str | None = None


class TableRead(BaseModel):
    season: SeasonRead | None
    standings: list[StandingRead]


@router.get("/standings", response_model=TableRead)
def standings(
    season_id: int | None = None,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> TableRead:
    """The season table. Everybody sees the whole of it — see the module note."""
    org = db.get(Organization, actor.organization_id)

    if season_id is None:
        season = season_service.current(db, org)
    else:
        season = db.get(Season, season_id)
        if season is None or season.organization_id != org.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Season not found."
            )

    if season is None:
        return TableRead(season=None, standings=[])

    rungs = tier_service.ladder(db, org.id)
    table = service.standings(db, season)
    dressed = unlock_service.worn_by(db, {row.user_id for row in table})
    return TableRead(
        season=_season_read(season),
        standings=[
            StandingRead(
                **vars(row),
                tier=(
                    held.name
                    if (held := tier_service.tier_for(row.points, rungs))
                    else None
                ),
                ring=dressed[row.user_id].ring if row.user_id in dressed else None,
                title=dressed[row.user_id].title if row.user_id in dressed else None,
            )
            for row in table
        ],
    )


@router.get("/seasons", response_model=list[SeasonRead])
def list_seasons(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[SeasonRead]:
    """Every season, newest first. Readable by everybody: which seasons exist
    is the shape of the game, not a setting."""
    rows = db.scalars(
        select(Season)
        .where(Season.organization_id == actor.organization_id)
        .order_by(Season.starts_on.desc())
    ).all()
    return [_season_read(row) for row in rows]


class SeasonWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(80)
    starts_on: date
    ends_on: date


@router.post("/seasons", response_model=SeasonRead, status_code=status.HTTP_201_CREATED)
def create_season(
    payload: SeasonWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SeasonRead:
    """Set up a season.

    Overlaps are refused by the database, and the message says which rule was
    broken rather than surfacing a constraint name — an admin drawing up next
    year's calendar will hit this, and "seasons cannot overlap" is the whole
    of what they need to know.
    """
    if payload.ends_on < payload.starts_on:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A season cannot end before it starts.",
        )

    season = Season(
        organization_id=actor.organization_id,
        name=payload.name,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
    )
    db.add(season)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Seasons cannot overlap. Another season already covers some of "
                "those dates."
            ),
        ) from None

    audit.record(
        db, actor=actor, action="season.created", request=request,
        name=payload.name,
    )
    db.commit()
    return _season_read(season)


@router.patch("/seasons/{season_id}", response_model=SeasonRead)
def update_season(
    season_id: int,
    payload: SeasonWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SeasonRead:
    """Rename or reshape a season.

    **Reshaping one moves awards between seasons**, because an award's season
    is resolved at the moment it is written and then fixed. That is the honest
    behaviour — a row that said "Q1" does not silently become "Q2" — but it
    means shrinking a season strands the awards outside its new dates, where
    they count toward no table. Refused rather than silently orphaning them.
    """
    season = db.get(Season, season_id)
    if season is None or season.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Season not found."
        )
    if payload.ends_on < payload.starts_on:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A season cannot end before it starts.",
        )

    if _would_strand_awards(db, season, payload):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Points have already been awarded outside those dates. Widen "
                "the season, or leave its dates alone."
            ),
        )

    season.name = payload.name
    season.starts_on = payload.starts_on
    season.ends_on = payload.ends_on
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Seasons cannot overlap.",
        ) from None

    audit.record(
        db, actor=actor, action="season.updated", request=request,
        name=payload.name,
    )
    db.commit()
    return _season_read(season)


def _would_strand_awards(
    db: DbSession, season: Season, payload: SeasonWrite
) -> bool:
    """Whether shrinking this season leaves awards outside its new dates."""
    from app.models import PointAward
    from sqlalchemy import func

    if payload.starts_on <= season.starts_on and payload.ends_on >= season.ends_on:
        return False

    earliest, latest = db.execute(
        select(
            func.min(func.date(PointAward.created_at)),
            func.max(func.date(PointAward.created_at)),
        ).where(PointAward.season_id == season.id)
    ).one()
    if earliest is None:
        return False
    return earliest < payload.starts_on or latest > payload.ends_on


class ValuesRead(BaseModel):
    """What each catalogue event is worth here, defaults filled in."""

    values: dict[str, int]


@router.get("/values", response_model=ValuesRead)
def read_values(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ValuesRead:
    return ValuesRead(values=service.values_for(db, actor.organization_id))


class ValuesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, int]


@router.put("/values", response_model=ValuesRead)
def write_values(
    payload: ValuesWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ValuesRead:
    """Set what things are worth.

    **Changes nothing that has already been awarded.** A ledger row records
    what was paid at the time, and re-pricing history would mean somebody's
    balance moving overnight for work they did last month — which is the
    fastest way to stop people believing the number.
    """
    unknown = set(payload.values) - set(service.DEFAULTS)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Not something that can be priced: {sorted(unknown)[0]}",
        )
    if any(amount < 0 for amount in payload.values.values()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Points cannot be negative.",
        )

    existing = {
        row.event_key: row
        for row in db.scalars(
            select(PointValue).where(
                PointValue.organization_id == actor.organization_id
            )
        ).all()
    }
    for event_key, amount in payload.values.items():
        if event_key in existing:
            existing[event_key].points = amount
        else:
            db.add(
                PointValue(
                    organization_id=actor.organization_id,
                    event_key=event_key,
                    points=amount,
                )
            )

    audit.record(db, actor=actor, action="point_values.updated", request=request)
    db.commit()
    return ValuesRead(values=service.values_for(db, actor.organization_id))


class AwardWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    #: Negative is allowed, and is how a mistake is corrected: a ledger row is
    #: never edited, so the fix is the opposite row.
    points: int = Field(ge=-10_000, le=10_000)
    reason: str = Field(min_length=1, max_length=200)


@router.post("/awards", response_model=AwardRead, status_code=status.HTTP_201_CREATED)
def award(
    payload: AwardWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> AwardRead:
    """Hand somebody points by hand, or take some back.

    Scoped like every other write: a manager may do this for people they can
    already see. Audited, because it is the one award with no rule behind it
    and "who gave them 500 points" needs an answer that does not depend on the
    ledger row still being there.

    Never latches — see `point_award`. A manager who does this twice meant to.
    """
    if payload.points == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An award of zero points would say nothing.",
        )

    recipient = db.get(UserAccount, payload.user_id)
    if (
        recipient is None
        or recipient.organization_id != actor.organization_id
        or not can_see_user(db, actor, recipient.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Person not found."
        )

    org = db.get(Organization, actor.organization_id)
    row = service.award(
        db,
        org=org,
        user_id=recipient.id,
        points=payload.points,
        event_key=service.MANUAL,
        subject_type="user",
        subject_id=actor.id,
        reason=payload.reason,
        awarded_by_user_id=actor.id,
    )
    audit.record(
        db, actor=actor, action="points.awarded", request=request,
        recipient=recipient.full_name, points=str(payload.points),
        reason=payload.reason,
    )
    db.commit()
    return _award_read(row)


class TierRead(BaseModel):
    id: int
    name: str
    threshold: int


class SuggestionRead(BaseModel):
    name: str
    threshold: int
    #: How many people currently on the board would hold this or better. The
    #: number that tells an admin whether the rung is worth anything, which is
    #: the whole reason the suggestion exists.
    would_hold: int


class LadderRead(BaseModel):
    tiers: list[TierRead]


@router.get("/tiers", response_model=LadderRead)
def read_tiers(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> LadderRead:
    """The ladder, lowest rung first. Readable by everybody: what the rungs
    are is the shape of the game, not a setting."""
    return LadderRead(
        tiers=[
            TierRead(id=row.id, name=row.name, threshold=row.threshold)
            for row in tier_service.ladder(db, actor.organization_id)
        ]
    )


class SuggestRead(BaseModel):
    suggestions: list[SuggestionRead]
    #: How many people have scored this season. Sent so the page can say *why*
    #: there is nothing to suggest rather than showing an empty list, which
    #: reads as "no ladder needed".
    scoring_people: int
    minimum: int


@router.get("/tiers/suggest", response_model=SuggestRead)
def suggest_tiers(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SuggestRead:
    """Rungs drawn from what people have actually scored this season.

    **Setting a threshold by hand is guessing**, and the two ways of guessing
    wrong look nothing alike from inside the form: too high and nobody aims at
    it, too low and holding it says nothing. Both are obvious the moment you
    look at the real distribution.
    """
    org = db.get(Organization, actor.organization_id)
    season = season_service.current(db, org)

    if season is None:
        return SuggestRead(
            suggestions=[], scoring_people=0, minimum=tier_service.MIN_SAMPLE
        )

    scoring = len(service.standings(db, season))
    return SuggestRead(
        suggestions=[
            SuggestionRead(**vars(row)) for row in tier_service.suggest(db, season)
        ],
        scoring_people=scoring,
        minimum=tier_service.MIN_SAMPLE,
    )


class TierWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(40)
    threshold: int = Field(gt=0)


class LadderWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers: list[TierWrite] = Field(max_length=10)


@router.put("/tiers", response_model=LadderRead)
def write_tiers(
    payload: LadderWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> LadderRead:
    """Replace the ladder.

    **Wholesale rather than row by row**, because a ladder is one shape and
    editing it a rung at a time means passing through states it forbids — two
    rungs briefly at the same height while you shuffle them, which the unique
    index refuses and which would leave an admin stuck halfway through a
    sensible edit.

    Nothing about anybody's points changes. A tier is read from a balance at
    the moment somebody looks, so moving a rung moves who is standing on it
    immediately and rewrites no history.
    """
    names = [row.name.strip() for row in payload.tiers]
    if len(set(names)) != len(names):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Two rungs cannot share a name.",
        )
    thresholds = [row.threshold for row in payload.tiers]
    if len(set(thresholds)) != len(thresholds):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Two rungs cannot sit at the same number of points — one of "
                "them would never be reachable on its own."
            ),
        )

    for row in db.scalars(
        select(Tier).where(Tier.organization_id == actor.organization_id)
    ).all():
        db.delete(row)
    # Before the inserts, or the unique index sees the old rows and the new
    # ones at once — the same autoflush hazard the channel screens hit.
    db.flush()

    for row in payload.tiers:
        db.add(
            Tier(
                organization_id=actor.organization_id,
                name=row.name.strip(),
                threshold=row.threshold,
            )
        )

    audit.record(
        db, actor=actor, action="tiers.updated", request=request,
        rungs=str(len(payload.tiers)),
    )
    db.commit()
    return LadderRead(
        tiers=[
            TierRead(id=row.id, name=row.name, threshold=row.threshold)
            for row in tier_service.ladder(db, actor.organization_id)
        ]
    )


# -- Badges ------------------------------------------------------------------


class BadgeRead(BaseModel):
    id: int
    name: str
    description: str
    kind: str
    icon: str
    points: int
    achievement_rule_id: int | None
    achievement_rule_name: str | None
    threshold: int | None
    counted_over: str | None
    #: How many people hold it. Shown beside the delete button, because
    #: deleting a badge takes every award of it with it.
    holders: int = 0


def _badge_read(db: DbSession, badge: Badge) -> BadgeRead:
    rule = (
        db.get(AchievementRule, badge.achievement_rule_id)
        if badge.achievement_rule_id
        else None
    )
    holders = db.scalar(
        select(func.count(func.distinct(BadgeAward.user_id))).where(
            BadgeAward.badge_id == badge.id
        )
    )
    return BadgeRead(
        id=badge.id,
        name=badge.name,
        description=badge.description or "",
        kind=badge.kind,
        icon=badge.icon,
        points=badge.points,
        achievement_rule_id=badge.achievement_rule_id,
        achievement_rule_name=rule.name if rule else None,
        threshold=badge.threshold,
        counted_over=badge.counted_over,
        holders=holders or 0,
    )


@router.get("/badges", response_model=list[BadgeRead])
def list_badges(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[BadgeRead]:
    """Every badge that exists here.

    Readable by everybody: what can be earned is the shape of the game, and a
    badge nobody can see the terms of is a badge nobody aims at.
    """
    rows = db.scalars(
        select(Badge)
        .where(Badge.organization_id == actor.organization_id)
        .order_by(Badge.name)
    ).all()
    return [_badge_read(db, row) for row in rows]


class HeldRead(BaseModel):
    badge_id: int
    name: str
    description: str
    icon: str
    reason: str
    earned_at: datetime
    #: How many times over. Somebody who earned it in four different months
    #: holds one badge four times, not four badges.
    times: int


class ProgressRead(BaseModel):
    badge_id: int
    name: str
    description: str
    icon: str
    have: int
    need: int
    remaining: int
    counted_over: str


class MyBadgesRead(BaseModel):
    held: list[HeldRead]
    #: Counted badges partway earned this window. **The half that changes
    #: behaviour** — the badge rewards what already happened, "one more this
    #: month" is the reason to do something today.
    progress: list[ProgressRead]


@router.get("/badges/mine", response_model=MyBadgesRead)
def my_badges(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> MyBadgesRead:
    org = db.get(Organization, actor.organization_id)
    return MyBadgesRead(
        held=[
            HeldRead(**vars(row))
            for row in badge_service.held_by(db, org.id, actor.id)
        ],
        progress=[
            ProgressRead(**vars(row), remaining=row.remaining)
            for row in badge_service.progress_for(db, org, actor.id)
        ],
    )


@router.get("/badges/user/{user_id}", response_model=list[HeldRead])
def badges_of(
    user_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[HeldRead]:
    """What somebody holds.

    Scoped like any other read about a person — unlike the season table, which
    everybody sees whole. A badge is about one person's history rather than
    about where everybody stands, so it follows the ordinary rule.
    """
    person = db.get(UserAccount, user_id)
    if (
        person is None
        or person.organization_id != actor.organization_id
        or not can_see_user(db, actor, person.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Person not found."
        )
    return [
        HeldRead(**vars(row))
        for row in badge_service.held_by(db, actor.organization_id, person.id)
    ]


class BadgeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(60)
    description: str = Field(default="", max_length=200)
    kind: str = "manual"
    #: A drawn key ("rocket"), or "asset:<sha256>" for one of the
    #: organization's own pictures (6.5).
    icon: str = Field(default="medal", max_length=80)
    points: int = Field(default=0, ge=0, le=10_000)
    achievement_rule_id: int | None = None
    threshold: int | None = Field(default=None, gt=0)
    counted_over: str | None = None


#: A drawn key: the shape `badgeMarks.tsx` uses. Unknown ones draw the medal,
#: so a key from a newer build is kept rather than refused.
_ART_KEY = re.compile(r"^[a-z][a-z_]{0,31}$")


def _badge_art(db: DbSession, actor: UserAccount, icon: str) -> str:
    """A drawn key, or a picture this organization actually holds."""
    if icon.startswith("asset:"):
        digest = icon[len("asset:"):]
        held = db.scalar(
            select(StoredAsset.id).where(
                StoredAsset.organization_id == actor.organization_id,
                StoredAsset.sha256 == digest,
                StoredAsset.content_type.like("image/%"),
            )
        )
        if held is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That picture is not in your Assets.",
            )
        return icon
    if not _ART_KEY.fullmatch(icon):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose the badge's art from the set, or a picture from Assets.",
        )
    return icon


def _apply_badge(
    db: DbSession, actor: UserAccount, badge: Badge, payload: BadgeWrite
) -> None:
    """Validate and copy, with the shape rules said in words.

    The CHECK constraint says the same things and says them as a 500. These
    are the messages somebody can act on.
    """
    if payload.kind not in badge_model.KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A badge is either given by hand or counted.",
        )

    if payload.kind == "count":
        if payload.counted_over not in badge_model.WINDOWS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Count it over a week, a month, or a season.",
            )
        if payload.threshold is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Say how many times it has to happen.",
            )
        rule = db.get(AchievementRule, payload.achievement_rule_id or 0)
        if rule is None or rule.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Choose an achievement rule to count.",
            )
        badge.achievement_rule_id = rule.id
        badge.threshold = payload.threshold
        badge.counted_over = payload.counted_over
    else:
        # Cleared rather than left behind: a manual badge carrying a stale
        # threshold is a row the CHECK refuses, and editing from counted to
        # manual is exactly how somebody would get there.
        badge.achievement_rule_id = None
        badge.threshold = None
        badge.counted_over = None

    badge.name = payload.name.strip()
    badge.description = payload.description.strip()
    badge.kind = payload.kind
    badge.icon = _badge_art(db, actor, payload.icon)
    badge.points = payload.points


@router.post("/badges", response_model=BadgeRead, status_code=status.HTTP_201_CREATED)
def create_badge(
    payload: BadgeWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> BadgeRead:
    badge = Badge(organization_id=actor.organization_id)
    _apply_badge(db, actor, badge, payload)
    db.add(badge)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A badge with that name already exists.",
        ) from None

    audit.record(
        db, actor=actor, action="badge.created", request=request, name=payload.name
    )
    db.commit()
    return _badge_read(db, badge)


@router.patch("/badges/{badge_id}", response_model=BadgeRead)
def update_badge(
    badge_id: int,
    payload: BadgeWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> BadgeRead:
    """Edit a badge.

    **Nothing already earned changes.** An award stores what it was given for,
    so renaming a badge does not rewrite what somebody was told they had — the
    same rule a notification's title follows.
    """
    badge = db.get(Badge, badge_id)
    if badge is None or badge.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found."
        )
    _apply_badge(db, actor, badge, payload)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A badge with that name already exists.",
        ) from None

    audit.record(
        db, actor=actor, action="badge.updated", request=request, name=payload.name
    )
    db.commit()
    return _badge_read(db, badge)


@router.delete("/badges/{badge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_badge(
    badge_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Delete a badge, and with it every award of it.

    **This really deletes, and it takes history with it** — the awards
    cascade. That is the honest behaviour for a badge somebody created by
    mistake, and it is why the list shows how many people hold each one. A
    badge you want to stop awarding without erasing what people earned is one
    you switch to "given by hand" and stop pinning on.
    """
    badge = db.get(Badge, badge_id)
    if badge is None or badge.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found."
        )

    audit.record(
        db, actor=actor, action="badge.deleted", request=request, name=badge.name
    )
    db.delete(badge)
    db.commit()


class GiveBadge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    reason: str = Field(default="", max_length=200)


@router.post(
    "/badges/{badge_id}/award",
    response_model=HeldRead,
    status_code=status.HTTP_201_CREATED,
)
def give_badge(
    badge_id: int,
    payload: GiveBadge,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> HeldRead:
    """Pin a badge on somebody.

    Scoped like every other write about a person: a manager may do this for
    people they can already see. Audited, because it is a public statement
    about somebody that outlives the season it was made in.

    A counted badge can be given by hand too — somebody who did the work while
    a connector was down should not lose it to a gap in the data.
    """
    badge = db.get(Badge, badge_id)
    if badge is None or badge.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found."
        )

    recipient = db.get(UserAccount, payload.user_id)
    if (
        recipient is None
        or recipient.organization_id != actor.organization_id
        or not can_see_user(db, actor, recipient.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Person not found."
        )

    org = db.get(Organization, actor.organization_id)
    badge_service.earn(
        db, org, badge, recipient.id,
        period_anchor=None,
        reason=payload.reason.strip() or badge.name,
        awarded_by_user_id=actor.id,
    )
    audit.record(
        db, actor=actor, action="badge.awarded", request=request,
        name=badge.name, recipient=recipient.full_name,
    )
    db.commit()

    held = badge_service.held_by(db, org.id, recipient.id)
    mine = next(row for row in held if row.badge_id == badge.id)
    return HeldRead(**vars(mine))
