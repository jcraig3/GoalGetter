from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app import audit, csv_export, leaderboards as service
from app import unlocks as unlock_service
from app.appearance import Appearance
from app.db import get_db
from app.models import (
    Leaderboard,
    MetricDefinition,
    Office,
    Organization,
    Team,
    UserAccount,
)
from app.models.leaderboard import (
    BOARD_PERIODS,
    ENTITY_TYPES,
    RANK_METHODS,
    SCOPE_TYPES,
    VISIBILITIES,
)
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])


def _one_of(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"Unknown {label}. Expected one of: {', '.join(allowed)}")
    return value


class LeaderboardRead(BaseModel):
    id: int
    name: str
    metric_id: int
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    direction: str
    entity_type: str
    scope_type: str
    scope_team_id: int | None
    scope_team_name: str | None
    scope_office_id: int | None
    scope_office_name: str | None
    period_type: str
    display_limit: int | None
    #: Where a race layout draws the finish line. See `app/game_boards.py`.
    finish_line: Decimal | None = None
    visibility: str
    is_tv_enabled: bool
    rank_method: str
    archived: bool
    #: What this board has chosen for itself, sparsely. Sent alongside the
    #: resolved form so an editor can offer "reset" on exactly the fields this
    #: item owns. See `app/appearance.py`.
    appearance: dict = {}
    #: Whether the viewer may change it, so the client does not re-derive the
    #: rule. Viewing and editing are different questions here: an agent can see
    #: an org-visible board and must not be offered an edit button for it.
    can_edit: bool


class LeaderboardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120)
    metric_id: int
    entity_type: str = "user"
    scope_type: str = "organization"
    scope_team_id: int | None = None
    scope_office_id: int | None = None
    period_type: str = "month"
    display_limit: int | None = Field(default=10, ge=1, le=500)
    #: Where a race layout draws the finish line, in the metric's unit.
    #: Optional — a race with none is measured against the leader.
    finish_line: Decimal | None = Field(default=None, gt=0)
    visibility: str = "org"
    is_tv_enabled: bool = False
    rank_method: str = "rank"

    @field_validator("entity_type")
    @classmethod
    def _entity(cls, v: str) -> str:
        return _one_of(v, ENTITY_TYPES, "entity_type")

    @field_validator("scope_type")
    @classmethod
    def _scope(cls, v: str) -> str:
        return _one_of(v, SCOPE_TYPES, "scope_type")

    @field_validator("period_type")
    @classmethod
    def _period(cls, v: str) -> str:
        return _one_of(v, BOARD_PERIODS, "period_type")

    @field_validator("visibility")
    @classmethod
    def _visibility(cls, v: str) -> str:
        return _one_of(v, VISIBILITIES, "visibility")

    @field_validator("rank_method")
    @classmethod
    def _rank(cls, v: str) -> str:
        return _one_of(v, RANK_METHODS, "rank_method")

    #: **Replaces rather than merges.** A merging update could not express
    #: "stop setting this and follow the default", because absence would mean
    #: "leave it alone" — which is the opposite of what a reset needs.
    appearance: Appearance | None = None


class LeaderboardUpdate(LeaderboardCreate):
    """Everything is editable, including the metric.

    Unlike a goal, a leaderboard makes no claim about the past — it is a
    question asked fresh each time it is opened. Changing which metric it ranks
    produces a different board, not a rewritten history, so there is nothing to
    protect.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name(120) | None = None
    metric_id: int | None = None
    entity_type: str | None = None
    scope_type: str | None = None
    period_type: str | None = None
    visibility: str | None = None
    rank_method: str | None = None
    is_tv_enabled: bool | None = None


class EntryRead(BaseModel):
    rank: int
    entity_id: int
    entity_name: str
    team_name: str | None
    value: Decimal
    movement: int | None
    #: The face to draw, on a board of people. Null on a team or office board.
    photo_digest: str | None = None
    #: How far along a race layout they are, 0–1, and whether they have
    #: crossed the finish line. Set on a wall slide; see `game_boards`.
    progress: float | None = None
    finished: bool = False
    #: The piece they move on a race board, or null for their own face.
    token: str | None = None
    #: The ring they have bought and are wearing, as a colour. Drawn round the
    #: face wherever it appears — which is the whole point of buying one. See
    #: `app/unlocks.py`.
    ring: str | None = None
    #: A team's own colour and short name, on a team board (6.7). Its logo,
    #: when it has one, arrives as `photo_digest`.
    colour: str | None = None
    short_name: str | None = None
    #: **This row is a team.** Said outright, because the two fields above are
    #: on every row — null on a person's — and a wall that guessed from them
    #: drew every photograph as a team logo.
    is_team: bool = False


class ResultsRead(BaseModel):
    leaderboard: LeaderboardRead
    period_label: str
    period_start: datetime
    period_end: datetime
    entries: list[EntryRead]
    viewer_entry: EntryRead | None
    total_entrants: int


def _can_edit(actor: UserAccount, board: Leaderboard) -> bool:
    """Admins, and the manager who created it.

    A manager may build boards for their own team; letting them edit anyone
    else's would make a published org board editable by everyone who can see
    it.
    """
    if actor.org_role == "admin":
        return True
    return actor.org_role == "manager" and board.created_by_user_id == actor.id


def _to_read(db: DbSession, actor: UserAccount, board: Leaderboard) -> LeaderboardRead:
    metric = db.get(MetricDefinition, board.metric_definition_id)
    team = db.get(Team, board.scope_team_id) if board.scope_team_id else None
    office = db.get(Office, board.scope_office_id) if board.scope_office_id else None
    return LeaderboardRead(
        id=board.id,
        name=board.name,
        metric_id=metric.id,
        metric_name=metric.name,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
        entity_type=board.entity_type,
        scope_type=board.scope_type,
        scope_team_id=board.scope_team_id,
        scope_team_name=team.name if team else None,
        scope_office_id=board.scope_office_id,
        scope_office_name=office.name if office else None,
        period_type=board.period_type,
        display_limit=board.display_limit,
        finish_line=board.finish_line,
        visibility=board.visibility,
        is_tv_enabled=board.is_tv_enabled,
        rank_method=board.rank_method,
        archived=board.archived_at is not None,
        can_edit=_can_edit(actor, board),
        appearance=board.appearance or {},
    )


def _validate_shape(
    db: DbSession, actor: UserAccount, scope_type: str, scope_team_id: int | None,
    scope_office_id: int | None, visibility: str, metric_id: int,
    is_tv_enabled: bool = False,
) -> None:
    """Reject combinations the CHECK constraints would refuse, with a sentence.

    The database is the guarantee; this exists so the answer is "a board
    visible to a team has to be scoped to one" rather than a constraint name.
    """
    metric = db.get(MetricDefinition, metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")

    if scope_type == "team":
        if scope_team_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A team-scoped board needs a team.",
            )
        team = db.get(Team, scope_team_id)
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
        if actor.org_role != "admin" and team.id != actor.team_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only build boards for your own team.",
            )
    elif scope_type == "office":
        if scope_office_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An office-scoped board needs an office.",
            )
        office = db.get(Office, scope_office_id)
        if office is None or office.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Office not found."
            )
        # An office spans several teams, so scoping a board to one is a
        # cross-team decision — which is what admins are for.
        if actor.org_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an admin can build an office board.",
            )
    elif scope_team_id is not None or scope_office_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An organization-wide board cannot also be scoped to a team or office.",
        )

    if visibility == "team" and scope_type != "team":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A board visible to a team has to be scoped to one, or there is "
                "no team for 'visible to the team' to mean."
            ),
        )

    # A wall screen has no audience control — anyone walking past reads it.
    # The CHECK constraint refuses this too; this exists so the answer is a
    # sentence rather than an unhandled IntegrityError.
    if is_tv_enabled and visibility != "org":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A board on a wall display has to be visible to everyone — "
                "anyone walking past the screen can read it."
            ),
        )

    # A manager publishing to the whole organization would be publishing their
    # team's numbers to everyone, which is not theirs to decide.
    if visibility == "org" and actor.org_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can publish a board to the whole organization.",
        )


@router.get("", response_model=list[LeaderboardRead])
def list_leaderboards(
    include_archived: bool = Query(default=False),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[LeaderboardRead]:
    """Boards this person may open.

    Filtered in the query: the existence of a private board, and its name, is
    itself information about what someone is tracking.
    """
    query = visible_boards(actor)
    if not include_archived:
        query = query.where(Leaderboard.archived_at.is_(None))

    rows = db.scalars(query.order_by(Leaderboard.name)).all()
    return [_to_read(db, actor, board) for board in rows]


def visible_boards(actor: UserAccount):
    """The boards this person may open, as a query — shared with search
    (6.16), so the palette can never offer a board the list would hide."""
    query = select(Leaderboard).where(Leaderboard.organization_id == actor.organization_id)
    if actor.org_role != "admin":
        query = query.where(
            or_(
                Leaderboard.visibility == "org",
                (Leaderboard.visibility == "team")
                & (Leaderboard.scope_team_id == actor.team_id)
                if actor.team_id is not None
                else (Leaderboard.visibility == "org"),
                Leaderboard.created_by_user_id == actor.id,
            )
        )
    return query


def _new_board(db: DbSession, actor: UserAccount, payload: LeaderboardCreate) -> Leaderboard:
    """A board from the form, checked — shared by saving and previewing it."""
    _validate_shape(
        db, actor, payload.scope_type, payload.scope_team_id,
        payload.scope_office_id, payload.visibility, payload.metric_id,
        payload.is_tv_enabled,
    )

    return Leaderboard(
        organization_id=actor.organization_id,
        name=payload.name,
        # Sparse on disk: a field nobody chose stays absent, so a later change
        # to the organization's default still reaches this board.
        appearance=(payload.appearance or Appearance()).model_dump(
            exclude_none=True
        ),
        metric_definition_id=payload.metric_id,
        entity_type=payload.entity_type,
        scope_type=payload.scope_type,
        scope_team_id=payload.scope_team_id,
        scope_office_id=payload.scope_office_id,
        period_type=payload.period_type,
        display_limit=payload.display_limit,
        finish_line=payload.finish_line,
        visibility=payload.visibility,
        is_tv_enabled=payload.is_tv_enabled,
        rank_method=payload.rank_method,
        created_by_user_id=actor.id,
    )


@router.post("/draft-slide")
def preview_leaderboard(
    payload: LeaderboardCreate,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> dict | None:
    """The form's board with its real standings, before it is saved (8.7).

    Added inside a savepoint that is always rolled back, and drawn by the
    TVs' renderer — so "Real numbers" in the form is what a wall would show.
    Null when there is nothing to rank yet.
    """
    from app import channels as channel_service
    from app.models import Organization

    org = db.get(Organization, actor.organization_id)
    savepoint = db.begin_nested()
    try:
        board = _new_board(db, actor, payload)
        # Who may see it is not what it shows: drawn as a public board so the
        # renderer, which only draws those, will draw it.
        board.visibility = "org"
        db.add(board)
        db.flush()
        return channel_service.draw_unsaved(
            db, org, actor, kind="leaderboard", leaderboard_id=board.id
        )
    finally:
        savepoint.rollback()


@router.post("", response_model=LeaderboardRead, status_code=status.HTTP_201_CREATED)
def create_leaderboard(
    payload: LeaderboardCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> LeaderboardRead:
    board = _new_board(db, actor, payload)
    db.add(board)
    audit.record(
        db, actor=actor, action="leaderboard.created", request=request,
        name=payload.name, visibility=payload.visibility,
    )
    db.commit()
    return _to_read(db, actor, board)


@router.patch("/{board_id}", response_model=LeaderboardRead)
def update_leaderboard(
    board_id: int,
    payload: LeaderboardUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> LeaderboardRead:
    board = _owned(db, actor, board_id)
    fields = payload.model_dump(exclude_unset=True)

    scope_type = fields.get("scope_type", board.scope_type)
    scope_team_id = fields.get("scope_team_id", board.scope_team_id)
    scope_office_id = fields.get("scope_office_id", board.scope_office_id)
    # Exactly one scope id survives a change of scope type; leaving the others
    # behind would trip the CHECK with a message nobody can act on.
    if scope_type != "team":
        scope_team_id = None
    if scope_type != "office":
        scope_office_id = None

    _validate_shape(
        db, actor, scope_type, scope_team_id, scope_office_id,
        fields.get("visibility", board.visibility),
        fields.get("metric_id", board.metric_definition_id),
        fields.get("is_tv_enabled", board.is_tv_enabled),
    )

    if "visibility" in fields and fields["visibility"] != board.visibility:
        # Who can see a board is the decision worth being able to trace later.
        audit.record(
            db, actor=actor, action="leaderboard.visibility_changed", request=request,
            name=board.name,
            visibility=audit.changed(board.visibility, fields["visibility"]),
        )

    if "metric_id" in fields:
        board.metric_definition_id = fields.pop("metric_id")
    fields.pop("scope_team_id", None)
    fields.pop("scope_office_id", None)
    if "appearance" in fields:
        fields["appearance"] = (payload.appearance or Appearance()).model_dump(
            exclude_none=True
        )
    for field, value in fields.items():
        setattr(board, field, value)
    board.scope_type = scope_type
    board.scope_team_id = scope_team_id
    board.scope_office_id = scope_office_id

    db.commit()
    return _to_read(db, actor, board)


@router.post("/{board_id}/archive", response_model=LeaderboardRead)
def archive_leaderboard(
    board_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> LeaderboardRead:
    board = _owned(db, actor, board_id, allow_archived=True)
    board.archived_at = datetime.now(UTC)
    db.commit()
    return _to_read(db, actor, board)


@router.post("/{board_id}/restore", response_model=LeaderboardRead)
def restore_leaderboard(
    board_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> LeaderboardRead:
    board = _owned(db, actor, board_id, allow_archived=True)
    board.archived_at = None
    db.commit()
    return _to_read(db, actor, board)


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_leaderboard(
    board_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    board = _owned(db, actor, board_id, allow_archived=True)
    audit.record(
        db, actor=actor, action="leaderboard.deleted", request=request, name=board.name
    )
    db.delete(board)
    db.commit()


@router.get("/{board_id}/slide")
def board_slide(
    board_id: int,
    anchor: date | None = Query(default=None, description="Any date inside the period"),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> dict:
    """The board as a wall draws it — its layout, look and faces — for its own
    page. Seen by exactly who may see its results."""
    from app import channels as channel_service
    from app.routers.display_feed import SlideRead

    board = db.get(Leaderboard, board_id)
    if board is None or not service.can_view(db, actor, board):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Leaderboard not found."
        )
    org = db.get(Organization, actor.organization_id)
    slide = channel_service.board_slide(db, org, actor, board, anchor=anchor)
    if slide is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Leaderboard not found.")
    return SlideRead(**vars(slide)).model_dump(mode="json")


@router.get("/{board_id}/results", response_model=ResultsRead)
def results(
    board_id: int,
    anchor: date | None = Query(default=None, description="Any date inside the period"),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> ResultsRead:
    """The board, computed now.

    Readable by anyone the board's visibility admits — including agents, who
    see every entrant. That is the point of a leaderboard, and the one place
    the per-person scope rule is deliberately relaxed.
    """
    board = db.get(Leaderboard, board_id)
    # 404 rather than 403 for a board they may not see: confirming a private
    # board exists tells them what someone is tracking.
    if board is None or not service.can_view(db, actor, board):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Leaderboard not found."
        )

    org = db.get(Organization, actor.organization_id)
    result = service.run(db, org, actor, board, anchor=anchor)

    # One query for the whole board, and only on a board of people: a team has
    # no face to put a ring round.
    rows = [*result.entries, *([result.viewer_entry] if result.viewer_entry else [])]
    dressed = (
        unlock_service.worn_by(db, {row.entity_id for row in rows})
        if board.entity_type == "user"
        else {}
    )

    def entry(row) -> EntryRead:
        worn = dressed.get(row.entity_id)
        return EntryRead(**vars(row), ring=worn.ring if worn else None)

    return ResultsRead(
        leaderboard=_to_read(db, actor, board),
        period_label=result.period.label,
        period_start=result.period.start,
        period_end=result.period.end,
        entries=[entry(row) for row in result.entries],
        viewer_entry=entry(result.viewer_entry) if result.viewer_entry else None,
        total_entrants=result.total_entrants,
    )


def _owned(
    db: DbSession, actor: UserAccount, board_id: int, *, allow_archived: bool = False
) -> Leaderboard:
    board = db.get(Leaderboard, board_id)
    if board is None or board.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Leaderboard not found."
        )
    if board.archived_at is not None and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Leaderboard not found."
        )
    if not _can_edit(actor, board):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only change boards you created.",
        )
    return board


@router.get("/{board_id}/results.csv")
def results_csv(
    board_id: int,
    anchor: date | None = Query(default=None),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> StreamingResponse:
    """The same board as a spreadsheet.

    Exports **every** entrant, not just the ones on screen. `display_limit` is
    a drawing decision — someone who asked for the file wants the data, and a
    truncated export is the kind of thing that gets pasted into a report
    without anyone noticing what is missing.

    Same visibility rules as the board itself: this is a different rendering of
    data they can already see, never a way around who may see it.
    """
    board = db.get(Leaderboard, board_id)
    if board is None or not service.can_view(db, actor, board):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Leaderboard not found."
        )

    org = db.get(Organization, actor.organization_id)
    result = service.run(db, org, actor, board, anchor=anchor, apply_limit=False)
    metric = db.get(MetricDefinition, board.metric_definition_id)

    header = ["Rank", "Name", "Team", metric.name, "Movement"]
    rows = (
        [
            entry.rank,
            entry.entity_name,
            entry.team_name or "",
            # A plain number, so the column sums in a spreadsheet. Formatting
            # it as "$1,234.00" here would make it text.
            entry.value,
            "" if entry.movement is None else entry.movement,
        ]
        for entry in result.entries
    )

    name = csv_export.filename(board.name, result.period.label)
    return StreamingResponse(
        csv_export.rows_to_csv(header, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
