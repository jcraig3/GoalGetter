from datetime import UTC, date, datetime
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession, object_session

from app import audit, images, mail, photo_bulk, photos, sign_in, tokens
from app.db import get_db
from app.models import Organization, Session, Team, UserAccount
# Imported rather than redeclared, so the API and the database CHECK constraint
# can never disagree about what a valid role is.
from app.models.user import ORG_ROLES
from app.routers import passwords
from app.scope import EVERYONE, can_see_user, has_capability, visible_user_ids
from app.security import NewPassword
from app.sessions import current_user, require_role

router = APIRouter(prefix="/users", tags=["users"])

ACCEPT_INVITE_PATH = "/accept-invite"


class UserRead(BaseModel):
    id: int
    email: str
    full_name: str
    org_role: str
    status: str
    last_login_at: datetime | None
    # True when the account has never set a password and has no SSO identity —
    # i.e. the invitation is still outstanding.
    invite_pending: bool
    team_id: int | None
    # Embedded rather than made the client fetch teams and join by hand: a name
    # is always needed to render a row, so a second request is guaranteed waste.
    team_name: str | None
    #: Archived people are absent unless asked for, so this is how a page that
    #: asked tells them apart.
    #: An admin hid them. Off every board, out of the roster, one click back.
    hidden: bool
    #: The image to draw, or null for initials. A content hash, so the client
    #: builds `/api/images/{digest}` and may cache it forever.
    photo_digest: str | None = None
    #: Whether "use the default" would change anything.
    has_custom_photo: bool = False
    #: The directory reported their account turned off. Set and cleared by the
    #: sync, so this is a fact about Entra rather than a decision anybody made.
    deactivated: bool
    #: Two-step sign-in is set up. Read-only here — an admin resets it through
    #: `/auth/mfa/{id}/reset`; nothing about editing a person changes.
    mfa_enabled: bool = False
    #: In the directory with SSO required (11.1): a password would be refused,
    #: so the person page offers no reset link or temporary password.
    must_use_sso: bool = False
    #: Signed in with a password an admin set, and not yet replaced it (11.2).
    must_change_password: bool = False
    #: Set up with a temporary password and never signed in: shown as invited,
    #: though the account is active so that the password works.
    awaiting_first_sign_in: bool = False
    #: Whether a reset link would have anything to reset (P4-5).
    has_password: bool = False
    #: Why `must_use_sso`, in a word the page can explain (P4-6): `signed_in`
    #: — they have signed in with Microsoft — or `directory`. Null otherwise.
    sso_reason: str | None = None

    #: What the directory said this person does. Empty for anybody invited by
    #: hand — which is also what "any" means to the filters on the People list,
    #: so neither side needs a special case.
    #: What people actually call them. Empty when they have not set one, which
    #: is almost everybody.
    nickname: str

    #: A month and a day, and deliberately no year. Both or neither.
    birthday_month: int | None = None
    birthday_day: int | None = None
    #: When they started, year and all — "three years today" is the point.
    started_on: date | None = None

    job_title: str
    department: str
    office_location: str


class UserUpdate(BaseModel):
    # None is ambiguous in JSON — it can mean "unassign" or "not supplied" —
    # so the endpoint uses model_fields_set to tell them apart.
    team_id: int | None = None
    org_role: str | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    #: **Here rather than on the profile, and the split is the point.** A
    #: birthday is theirs and they may set it; a start date is a company fact
    #: about when somebody joined, and an agent inventing their own would be a
    #: number on a wall nobody checked.
    started_on: date | None = None


def _count_active_admins(db: DbSession, organization_id: int, *, excluding: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(UserAccount)
            .where(
                UserAccount.organization_id == organization_id,
                UserAccount.org_role == "admin",
                UserAccount.status == "active",
                UserAccount.hidden_at.is_(None),
                UserAccount.id != excluding,
            )
        )
        or 0
    )


def _is_last_admin(db: DbSession, user: UserAccount) -> bool:
    """Whether removing this person would leave nobody able to administer.

    Split out of the guard below so a bulk action can *skip* where a single-user
    action *refuses* — a selection of two hundred containing the last admin
    should archive the other hundred and ninety-nine and say why it did not
    archive them, rather than failing whole.
    """
    if user.org_role != "admin" or user.status != "active":
        return False
    return _count_active_admins(db, user.organization_id, excluding=user.id) == 0


def _guard_last_admin(db: DbSession, user: UserAccount, action: str) -> None:
    """Refuse anything that would leave the organization with no admin.

    Without this, one click permanently locks everyone out of a self-hosted
    deployment — no support line to call, and the only way back is editing the
    database by hand. The same reasoning as the SSO break-glass rule.
    """
    if _is_last_admin(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This is the only active admin, so they cannot be {action}. "
                "Make someone else an admin first."
            ),
        )


def _end_sessions(db: DbSession, user_id: int) -> None:
    """Sign someone out everywhere, immediately.

    `current_user` already rejects a suspended account on its next request, so
    this is belt and braces — but it also clears the rows, so a reactivated
    account starts clean rather than resuming an old session.
    """
    db.query(Session).filter(Session.user_id == user_id).delete(
        synchronize_session=False
    )


class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    org_role: str = Field(default="agent")
    #: Set up with a password an admin chose, instead of a link (11.2) — they
    #: replace it the moment they sign in. Admin only.
    temporary_password: NewPassword | None = None


class InviteResult(BaseModel):
    user: UserRead
    # Returned so an admin can copy it. Deliberately not only emailed: many
    # internal deployments have no SMTP on day one, and the tool must be fully
    # usable without it — paste the link into Slack or Teams instead.
    #: None when they were given a temporary password instead (11.2).
    invite_link: str | None

    #: Whether the link was also emailed, and what happened if not.
    #:
    #: **The link is returned either way**, which is the rule this whole flow was
    #: built on: many internal deployments have no mail server, and a mail server
    #: that exists can still be down or refuse the from-address. An invitation must
    #: not be swallowed by a relay having a bad afternoon.
    emailed: bool = False
    email_detail: str | None = None
    #: The link uses localhost, so it opens only on the computer that made it.
    link_is_local: bool = False


class BulkPhotoOutcome(BaseModel):
    filename: str
    #: `matched`, `unmatched`, `ambiguous` or `rejected`.
    status: str
    detail: str
    user_id: int | None = None
    user_name: str | None = None


class BulkPhotoReport(BaseModel):
    matched: int
    unresolved: int
    outcomes: list[BulkPhotoOutcome]


def _to_read(
    user: UserAccount, team_name: str | None = None, must_use_sso: bool | None = None
) -> UserRead:
    # Asked one at a time unless a list worked them out together.
    if must_use_sso is None:
        db = object_session(user)
        must_use_sso = db is not None and sign_in.must_use_sso(db, user)
    return UserRead(
        must_use_sso=must_use_sso,
        must_change_password=user.must_change_password,
        has_password=user.password_hash is not None,
        sso_reason=(
            ("signed_in" if user.external_subject_id else "directory") if must_use_sso else None
        ),
        # Only while they could sign in: suspended outranks it (P4-2).
        awaiting_first_sign_in=(
            user.must_change_password and user.last_login_at is None and user.status == "active"
        ),
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        org_role=user.org_role,
        status=user.status,
        last_login_at=user.last_login_at,
        invite_pending=user.status == "invited",
        team_id=user.team_id,
        team_name=team_name,
        hidden=user.hidden_at is not None,
        deactivated=user.status == "deactivated",
        mfa_enabled=bool(user.mfa_secret_encrypted),
        nickname=user.nickname,
        birthday_month=user.birthday_month,
        birthday_day=user.birthday_day,
        started_on=user.started_on,
        job_title=user.job_title,
        department=user.department,
        office_location=user.office_location,
        photo_digest=user.photo_digest,
        has_custom_photo=user.custom_photo_image_id is not None,
    )


@router.get("", response_model=list[UserRead])
def list_users(
    roster: Literal["active", "hidden", "deactivated", "all"] = "active",
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[UserRead]:
    """The people this actor may see, on one of three rosters.

    An admin sees everyone; a manager sees their own team plus unassigned
    agents. See app/scope.py.

    **Three rosters, because there are three reasons somebody is not on the
    active one** and lumping them together loses the only thing you would want to
    know. `hidden` is a decision an admin made and can undo. `deactivated` is the
    directory reporting the account turned off, which reverses itself when the
    directory changes its mind. `all` is for looking up one person by id — the
    detail page has to render somebody whichever roster they are on.

    A parameter rather than three endpoints: the scope rules, the team join and
    the ordering are the same for all of them, and three copies of that is three
    places for a scope filter to go missing.
    """
    # One query with an outer join, not a query per user to fetch their team.
    # LEFT so unassigned people are still returned — they are exactly who an
    # admin needs to see.
    query = (
        select(UserAccount, Team.name)
        .outerjoin(Team, Team.id == UserAccount.team_id)
        .where(UserAccount.organization_id == actor.organization_id)
    )
    # **Each roster is a WHERE clause, never a filter on the results.** Same
    # reasoning as the scope rule below it, and the same failure if ignored:
    # counting rows you then drop makes every total on the page a lie.
    #
    # Hidden wins over deactivated when somebody is both. An admin hid them on
    # purpose, and that decision is what should be shown and undone — a person
    # sitting only on the Deactivated tab could be un-deactivated by the
    # directory and quietly reappear on a board they were hidden from.
    if roster == "active":
        query = query.where(
            UserAccount.hidden_at.is_(None), UserAccount.status != "deactivated"
        )
    elif roster == "hidden":
        query = query.where(UserAccount.hidden_at.is_not(None))
    elif roster == "deactivated":
        query = query.where(
            UserAccount.hidden_at.is_(None), UserAccount.status == "deactivated"
        )

    # Scope filters the QUERY, never the result.
    #
    # Fetching everyone and then dropping rows in Python makes counts,
    # pagination, and "no results" states all subtly wrong, and any code path
    # that forgets the filter leaks silently. Pushing it into the WHERE clause
    # makes the safe version the default one.
    visible = visible_user_ids(db, actor)
    if visible is not EVERYONE:
        query = query.where(UserAccount.id.in_(visible))

    rows = db.execute(query.order_by(func.lower(UserAccount.full_name))).all()
    sso_only = sign_in.must_use_sso_among(db, actor.organization_id, [u for u, _ in rows])
    return [_to_read(user, team_name, user.id in sso_only) for user, team_name in rows]


class NonPerson(BaseModel):
    id: int
    full_name: str
    email: str
    reason: str


@router.get("/non-people", response_model=list[NonPerson])
def non_people(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[NonPerson]:
    """Accounts that look like printers, rooms or shared mailboxes.

    Suggestions for an admin to review and hide with the bulk action — never
    hidden here. See `app/directory/non_people.py` for what counts.
    """
    from app.directory import non_people as detector

    return [
        NonPerson(id=c.id, full_name=c.full_name, email=c.email, reason=c.reason)
        for c in detector.candidates(db, actor.organization_id)
    ]


@router.get("/{user_id}", response_model=UserRead)
def read_user(
    user_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """One person, on whichever roster — for their page (P4-16), which loaded
    all 480 to show one. Same scope as the list: outside it is a 404."""
    user = _owned_user(db, user_id, actor.organization_id)
    if not can_see_user(db, actor, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return _with_team(db, user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Update someone's team, name, or role.

    A manager may act only on people they can see — their own team, plus agents
    on no team so they can recruit. They cannot change roles.
    """
    user = _owned_user(db, user_id, actor.organization_id)
    if user.hidden_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # 404, not 403: for someone outside the actor's scope, confirming the
    # account exists is itself information they are not entitled to.
    if not can_see_user(db, actor, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    fields = payload.model_fields_set

    if "started_on" in fields:
        user.started_on = payload.started_on

    # "team_id" present with a null value means unassign; absent means leave it
    # alone. Checking model_fields_set is what distinguishes the two.
    if "team_id" in fields:
        # A manager may only move someone onto their own team, or off a team
        # entirely. Without this they could see an unassigned agent and post
        # them into a team they have nothing to do with.
        if actor.org_role != "admin" and payload.team_id not in (None, actor.team_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only move people onto your own team.",
            )
        if payload.team_id is not None:
            team = db.get(Team, payload.team_id)
            if (
                team is None
                or team.organization_id != actor.organization_id
                or team.archived_at is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
                )
        if payload.team_id != user.team_id:
            audit.record(
                db,
                actor=actor,
                action="user.team_changed",
                request=request,
                target=user,
                team_id=audit.changed(user.team_id, payload.team_id),
            )
        user.team_id = payload.team_id

    if "full_name" in fields and payload.full_name:
        user.full_name = payload.full_name

    if "org_role" in fields and payload.org_role != user.org_role:
        if actor.org_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an admin can change someone's role.",
            )
        if payload.org_role not in ORG_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role."
            )
        # Demoting the last admin is the same lockout as suspending them.
        if payload.org_role != "admin":
            _guard_last_admin(db, user, "given a different role")
        audit.record(
            db,
            actor=actor,
            action="user.role_changed",
            request=request,
            target=user,
            org_role=audit.changed(user.org_role, payload.org_role),
        )
        user.org_role = payload.org_role
        # Permissions are read fresh on every request, so the change takes
        # effect immediately — no need to end their sessions.

    db.commit()
    team = db.get(Team, user.team_id) if user.team_id else None
    return _to_read(user, team.name if team else None)


@router.post("/{user_id}/suspend", response_model=UserRead)
def suspend_user(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Revoke access without deleting anything.

    Their goals, history, and past leaderboard positions stay intact — this is
    "they have left" or "something is wrong", not "they never existed".
    """
    user = _owned_user(db, user_id, actor.organization_id)
    if user.id == actor.id:
        # Blocked because it is almost always a misclick, and the consequence
        # is signing yourself out of an account you may be the only admin for.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot suspend your own account.",
        )
    _guard_last_admin(db, user, "suspended")

    user.status = "suspended"
    _end_sessions(db, user.id)
    audit.record(db, actor=actor, action="user.suspended", request=request, target=user)
    db.commit()
    return _with_team(db, user)


@router.post("/{user_id}/reactivate", response_model=UserRead)
def reactivate_user(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> UserRead:
    user = _owned_user(db, user_id, actor.organization_id)
    # An account that never accepted its invitation goes back to "invited", not
    # "active" — it still has no password, so "active" would be a lie.
    user.status = sign_in.ready_status(db, user)
    audit.record(
        db, actor=actor, action="user.reactivated", request=request, target=user,
        status=user.status,
    )
    db.commit()
    return _with_team(db, user)


@router.post("/{user_id}/hide", response_model=UserRead)
def hide_user(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Take somebody off the boards without deleting them.

    Users are never removed outright: their metric history and past leaderboard
    positions are part of the company's record, and deleting the row would make
    last quarter's results reference nobody.

    **Their facts keep counting toward their team.** Only the person disappears —
    from the roster, from every leaderboard, dashboard and goal. The totals do
    not move, because `aggregate._scored` groups team and office numbers on
    columns held by the fact itself rather than by joining to whoever is still
    around. A board somebody screenshotted last week still adds up.

    **The sync will not undo this.** Nothing in `app/directory/` writes
    `hidden_at`, which is the same promise `directory.DECIDED` makes about a
    declined person: a decision an admin made outranks anything the directory
    later reports.
    """
    user = _owned_user(db, user_id, actor.organization_id)
    if user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot hide your own account.",
        )
    _guard_last_admin(db, user, "hidden")

    user.hidden_at = datetime.now(UTC)
    user.status = "suspended"
    _end_sessions(db, user.id)
    audit.record(db, actor=actor, action="user.hidden", request=request, target=user)
    db.commit()
    return _with_team(db, user)


def _owned_user(db: DbSession, user_id: int, organization_id: int) -> UserAccount:
    user = db.get(UserAccount, user_id)
    if user is None or user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _with_team(db: DbSession, user: UserAccount) -> UserRead:
    team = db.get(Team, user.team_id) if user.team_id else None
    return _to_read(user, team.name if team else None)


@router.post("/{user_id}/unhide", response_model=UserRead)
def unhide_user(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Undo a hide.

    **Comes back suspended, not active.** Hiding ends their sessions and takes
    away access; unhiding is a decision to put somebody back in the list, which
    is not the same as a decision to let them straight back in. Two steps, so
    neither is taken by accident — and the second one is one click away.
    """
    user = _owned_user(db, user_id, actor.organization_id)
    if user.hidden_at is None:
        # Not an error worth failing on: a second press, or two admins at once.
        return _with_team(db, user)

    user.hidden_at = None
    user.status = "suspended"
    audit.record(db, actor=actor, action="user.unhidden", request=request, target=user)
    db.commit()
    return _with_team(db, user)


class BulkWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Capped, because this arrives from a "select all shown" on a list that has
    #: no pagination — a tenant of six hundred is one press away.
    ids: list[int] = Field(min_length=1, max_length=1000)
    #: **One action per roster.** The list you
    #: are looking at decides what you can do to a selection — Hide from Active,
    #: Unhide from Hidden, Reactivate from Deactivated — so a bulk menu never
    #: offers something that would be a no-op for everything selected.
    action: Literal[
        "hide", "unhide", "reactivate", "assign_team", "set_role"
    ]
    #: For `assign_team`. Null unassigns, which is a real thing to want in bulk —
    #: a team being dissolved is exactly when you reach for this.
    team_id: int | None = None
    #: For `set_role`.
    role: str | None = None


class BulkResult(BaseModel):
    """What actually happened, per outcome rather than as one number.

    **Partial success is the normal case here**, not an edge one: a selection of
    two hundred will contain the actor themselves, and may contain the last
    admin. Reporting "done" would hide that; refusing the whole batch would make
    the feature useless for the other hundred and ninety-eight.
    """

    changed: int
    #: People deliberately left alone, and why — one sentence each, for a list
    #: somebody reads rather than a code they look up.
    skipped: list[str] = []


@router.post("/bulk", response_model=BulkResult)
def bulk(
    payload: BulkWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> BulkResult:
    """Archive, restore, re-team or re-role several people at once.

    One endpoint rather than the page looping: two hundred requests is two
    hundred audit commits and a progress bar nobody asked for, and a batch that
    fails halfway leaves a selection in a state nobody can describe.

    **The guards are the same ones the single-user endpoints apply**, checked per
    person rather than up front — so one protected account does not refuse the
    other hundred and ninety-nine. The exceptions are the things that are wrong
    about the *request* rather than about a person: an unknown team or role is a
    400, not two hundred identical skips.

    **Admin-only, including for the team assignment** that a manager may do one
    person at a time. A manager moving people onto their own team is a
    recruitment decision made while looking at somebody; select-all over a
    filtered list is a different act, and the scope rules for it are not the same
    ones — so rather than approximate them, it is not offered.
    """
    changed = 0
    skipped: list[str] = []

    # Validated once, not per person: a team that does not exist is a bad request
    # rather than two hundred individual skips saying the same thing.
    team: Team | None = None
    if payload.action == "assign_team" and payload.team_id is not None:
        team = db.get(Team, payload.team_id)
        if (
            team is None
            or team.organization_id != actor.organization_id
            or team.archived_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )
    if payload.action == "set_role" and payload.role not in ORG_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role."
        )

    for user_id in dict.fromkeys(payload.ids):  # de-duplicated, order kept
        user = db.get(UserAccount, user_id)
        if user is None or user.organization_id != actor.organization_id:
            continue

        if payload.action == "assign_team":
            if user.hidden_at is not None:
                skipped.append(f"{user.full_name} — hidden")
                continue
            if user.team_id == payload.team_id:
                continue
            audit.record(
                db,
                actor=actor,
                action="user.team_changed",
                request=request,
                target=user,
                team_id=audit.changed(user.team_id, payload.team_id),
            )
            user.team_id = payload.team_id
            changed += 1
            continue

        if payload.action == "set_role":
            if user.hidden_at is not None:
                skipped.append(f"{user.full_name} — hidden")
                continue
            if user.id == actor.id:
                # **Your own role is never in a bulk change.** Demoting yourself
                # by way of a select-all is a lockout nobody intended, and the
                # single-user path is where a deliberate one belongs.
                skipped.append(f"{user.full_name} — you cannot change your own role")
                continue
            if user.org_role == payload.role:
                continue
            if payload.role != "admin" and _is_last_admin(db, user):
                skipped.append(
                    f"{user.full_name} — the last admin cannot be demoted"
                )
                continue
            audit.record(
                db,
                actor=actor,
                action="user.role_changed",
                request=request,
                target=user,
                org_role=audit.changed(user.org_role, payload.role),
            )
            user.org_role = str(payload.role)
            changed += 1
            continue

        if payload.action == "hide":
            if user.id == actor.id:
                skipped.append(f"{user.full_name} — you cannot hide your own account")
                continue
            if _is_last_admin(db, user):
                skipped.append(f"{user.full_name} — the last admin cannot be hidden")
                continue
            if user.hidden_at is not None:
                continue
            user.hidden_at = datetime.now(UTC)
            user.status = "suspended"
            _end_sessions(db, user.id)
            audit.record(
                db, actor=actor, action="user.hidden", request=request, target=user
            )
        elif payload.action == "unhide":
            if user.hidden_at is None:
                continue
            user.hidden_at = None
            user.status = "suspended"
            audit.record(
                db, actor=actor, action="user.unhidden", request=request, target=user
            )
        else:
            # **Reactivate: undoing what the directory did, not what an admin
            # did.** Restricted to `deactivated` on purpose — letting it clear a
            # suspension would turn a bulk sweep of ex-employees into a way to
            # hand access back to somebody an admin had shut out, and the two
            # states look identical from a list.
            if user.status != "deactivated":
                skipped.append(f"{user.full_name} — not deactivated")
                continue
            user.status = sign_in.ready_status(db, user)
            audit.record(
                db,
                actor=actor,
                action="user.reactivated",
                request=request,
                target=user,
                status=user.status,
            )
        changed += 1

    db.commit()
    return BulkResult(changed=changed, skipped=skipped)


@router.post("/invite", response_model=InviteResult, status_code=status.HTTP_201_CREATED)
def invite_user(
    payload: InviteRequest,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> InviteResult:
    # A manager must not be able to mint an admin. Checked here rather than in
    # the UI, because the UI only decides what to draw.
    if actor.org_role != "admin" and payload.org_role != "agent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can invite managers or admins.",
        )
    if payload.org_role not in ORG_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role."
        )
    # Admin only (decided 5 Oct): a password you chose for somebody is a way to
    # be them, which a team lead inviting an agent has no need of. Asked as the
    # capability, so a custom role that takes reset links away takes this too.
    if payload.temporary_password is not None and not has_capability(
        actor, "users.reset_password"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an admin can set somebody's password. Send them a link instead.",
        )

    email = payload.email.lower()
    existing = db.scalar(
        select(UserAccount).where(
            UserAccount.organization_id == actor.organization_id,
            func.lower(UserAccount.email) == email,
        )
    )
    if existing is not None:
        # 409 rather than silently reissuing: an admin who typed an address that
        # already exists needs to know, not to accidentally reset someone.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Someone with that email already exists.",
        )

    user = UserAccount(
        organization_id=actor.organization_id,
        email=email,
        full_name=payload.full_name,
        org_role=payload.org_role,
        status="invited",
        # No password_hash: the invitee sets their own. An admin never chooses
        # someone else's password, so there is no moment where a shared secret
        # exists in a chat message.
    )
    db.add(user)
    db.flush()

    if payload.temporary_password is not None:
        # **The other way in** (11.2): no link and no email. They are handed the
        # password, and choose their own the moment they sign in.
        passwords.set_temporary(db, user, payload.temporary_password)
        audit.record(
            db, actor=actor, action="user.invited", request=request, target=user,
            org_role=user.org_role, how="temporary password",
        )
        db.commit()
        return InviteResult(user=_to_read(user), invite_link=None)

    raw = tokens.issue(db, user.id, "invite")
    audit.record(
        db, actor=actor, action="user.invited", request=request, target=user,
        org_role=user.org_role,
    )
    db.commit()

    return _invite_result(db, user, raw, request)


def _invite_result(
    db: DbSession, user: UserAccount, raw: str, request: Request | None = None
) -> InviteResult:
    """The link, and the email if there is anywhere to send one.

    Sent *after* the commit that created the token, so a message can never
    describe an invitation that then failed to save.
    """
    link = tokens.link(raw, ACCEPT_INVITE_PATH, request, db)
    sent = mail.send(
        db,
        user.organization_id,
        to=user.email,
        subject="You have been invited to GoalGetter",
        body=(
            f"Hello {user.full_name},\n\n"
            "You have been invited to GoalGetter. Open this link to set your "
            f"password and sign in:\n\n{link}\n\n"
            "The link works once and expires in seven days.\n"
        ),
    )
    return InviteResult(
        user=_to_read(user),
        invite_link=link,
        emailed=sent.ok,
        # Silent when there was nothing to try. A deployment with no mail server
        # is the normal case, not a problem to report on every invitation.
        email_detail=None if sent.ok or not sent.attempted else sent.detail,
        link_is_local=tokens.is_local(link),
    )


@router.post("/{user_id}/resend-invite", response_model=InviteResult)
def resend_invite(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> InviteResult:
    user = db.get(UserAccount, user_id)
    if (
        user is None
        or user.organization_id != actor.organization_id
        or user.hidden_at is not None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    # Same scope rule as update_user. Without this a manager could reissue an
    # invitation link for anyone in the organization, including an admin — and
    # that link sets a password.
    if not can_see_user(db, actor, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    if user.status != "invited":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That account has already been activated.",
        )

    # issue() deletes the previous token, so the old link stops working.
    raw = tokens.issue(db, user.id, "invite")
    audit.record(db, actor=actor, action="user.invite_resent", request=request, target=user)
    db.commit()
    return _invite_result(db, user, raw, request)


# ── Photographs ──────────────────────────────────────────────────────────────


def _may_change_profile(
    db: DbSession, actor: UserAccount, user: UserAccount, what: str, *, allowed: str
) -> None:
    """Yourself, or anybody if you run the place or a team in it.

    **Widened from admin-only deliberately.** The first version reasoned that a
    face is the one personal part of a profile and that letting a colleague
    change it invents a prank. True of colleagues; not true of the person who
    manages the roster. Most people here will never sign in — the accounts exist
    because a directory sync created them — so "they can upload their own" is not
    an answer for the majority, and somebody has to be able to do it for them.

    Agents still cannot touch each other's.

    **And an organization can close the self half.** `allowed` names the switch
    on `organization` — see the note there. It binds agents only: a manager and
    an admin can already do this for anybody, and locking an admin out of their
    own photograph would be a support call rather than a policy.
    """
    if actor.org_role in ("admin", "manager"):
        return

    if actor.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Only a manager or an admin can change somebody else's {what}.",
        )

    org = db.get(Organization, actor.organization_id)
    if org is not None and not getattr(org, allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Your organization has turned off changing your own {what}. "
                "Ask a manager or an administrator."
            ),
        )


class ProfileUpdate(BaseModel):
    """The parts of a profile that belong to the person rather than the roster.

    Separate from `UserUpdate`, which is team, role and name — decisions about
    where somebody sits that only a manager makes. These are decisions about
    *them*, and the rule is the one a photograph already has: your own, or
    anybody's if you run the place.
    """

    model_config = ConfigDict(extra="forbid")

    #: Empty clears it. Trimmed, so a name that is only spaces is no name.
    nickname: str = Field(default="", max_length=40)

    #: Null clears it. Both halves or neither — the CHECK on the column says so
    #: and this says it earlier, with a sentence instead of a constraint name.
    birthday_month: int | None = Field(default=None, ge=1, le=12)
    birthday_day: int | None = Field(default=None, ge=1, le=31)


@router.patch("/{user_id}/profile", response_model=UserRead)
def update_profile(
    user_id: int,
    payload: ProfileUpdate,
    request: Request,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Set what people actually call somebody.

    **Most people here will never sign in.** The accounts exist because a
    directory sync created them, so "they can set their own" is not an answer
    for the majority — somebody has to be able to do it for them, which is the
    same reasoning that widened photographs beyond admins.
    """
    user = _owned_user(db, user_id, actor.organization_id)
    _may_change_profile(db, actor, user, "details", allowed="self_details")

    if (payload.birthday_month is None) != (payload.birthday_day is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A birthday needs both a month and a day, or neither.",
        )

    user.nickname = payload.nickname.strip()
    user.birthday_month = payload.birthday_month
    user.birthday_day = payload.birthday_day
    audit.record(
        db, actor=actor, action="user.profile_set", request=request, name=user.email
    )
    db.commit()
    db.refresh(user)
    return _with_team(db, user)


@router.post("/{user_id}/photo", response_model=UserRead)
async def upload_photo(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Replace the directory's photograph with a chosen one.

    **The directory's copy is kept.** It goes in a different column, so the next
    sync does not fight this and "use the default again" has something to fall
    back to — see `models/user.py`.

    **The image is the body, not a multipart form.** A `File` upload would add a
    dependency to parse an envelope around a single file, and the browser sends
    a `File` as a body just as happily. Nothing here trusts the declared content
    type either way: the bytes are decoded to find out what they are.
    """
    user = _owned_user(db, user_id, actor.organization_id)
    _may_change_profile(db, actor, user, "photo", allowed="self_photo")

    # **Checked before reading, not after.** `await request.body()` pulls the
    # whole thing into memory, so a refusal that happens afterwards has already
    # paid for the attack it is refusing.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > images.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"The largest photo accepted is "
                f"{images.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )

    raw = await request.body()
    try:
        photos.set_custom(db, user, raw)
    except images.ImageProblem as problem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
        ) from None

    audit.record(
        db, actor=actor, action="user.photo_set", request=request, name=user.email
    )
    db.commit()
    db.refresh(user)
    return _with_team(db, user)


class PhotoFromLibrary(BaseModel):
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/{user_id}/photo/from-library", response_model=UserRead)
def photo_from_library(
    user_id: int,
    payload: PhotoFromLibrary,
    request: Request,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """A picture already in the asset library, as somebody's photograph
    (Phase 27): cropped to a square like any upload, so the library's copy is
    left as it was."""
    from app.models import StoredAsset

    user = _owned_user(db, user_id, actor.organization_id)
    _may_change_profile(db, actor, user, "photo", allowed="self_photo")
    row = db.scalar(
        select(StoredAsset).where(
            StoredAsset.organization_id == actor.organization_id, StoredAsset.sha256 == payload.digest
        )
    )
    if row is None or not row.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That picture isn't in the library.")
    try:
        photos.set_custom(db, user, row.data)
    except images.ImageProblem as problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)) from None
    audit.record(db, actor=actor, action="user.photo_set", request=request, name=user.email)
    db.commit()
    db.refresh(user)
    return _with_team(db, user)


@router.delete("/{user_id}/photo", response_model=UserRead)
def revert_photo(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> UserRead:
    """Back to whatever the directory has, or to initials.

    Not a delete of the image: it is content-addressed and may be somebody
    else's photograph too. See `photos.forget_custom`.
    """
    user = _owned_user(db, user_id, actor.organization_id)
    _may_change_profile(db, actor, user, "photo", allowed="self_photo")

    photos.forget_custom(db, user)
    audit.record(
        db, actor=actor, action="user.photo_reverted", request=request, name=user.email
    )
    db.commit()
    db.refresh(user)
    return _with_team(db, user)


@router.post("/photos/bulk", response_model=BulkPhotoReport)
async def bulk_photos(
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> BulkPhotoReport:
    """A zip of headshots, matched to people by filename.

    **Every file gets a line back, including the ones that worked.** A bulk
    action reporting "312 updated" and nothing else leaves the other eighty-eight
    to be discovered by noticing they are missing.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > photo_bulk.MAX_ARCHIVE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"The largest archive accepted is "
                f"{photo_bulk.MAX_ARCHIVE_BYTES // (1024 * 1024)} MB."
            ),
        )

    report = photo_bulk.apply_archive(db, actor.organization_id, await request.body())
    audit.record(
        db,
        actor=actor,
        action="user.photos_bulk",
        request=request,
        name=f"{report.matched} set, {report.unresolved} unresolved",
    )
    db.commit()
    return BulkPhotoReport(
        matched=report.matched,
        unresolved=report.unresolved,
        outcomes=[
            BulkPhotoOutcome(
                filename=o.filename,
                status=o.status,
                detail=o.detail,
                user_id=o.user_id,
                user_name=o.user_name,
            )
            for o in report.outcomes
        ],
    )


@router.post("/photos/one", response_model=BulkPhotoOutcome)
async def one_photo(
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> BulkPhotoOutcome:
    """One photograph, matched to its person by its file name.

    **The other half of the bulk upload**, for photos dropped as files rather
    than zipped: the page sends them one at a time, so it can count them off
    as they go and no single request has to carry four hundred. Matched by
    `photo_bulk.place`, exactly as the same file inside a zip would be. The
    name travels in `X-File-Name`, the image is the body.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > images.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"The largest photo accepted is "
                f"{images.MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )
    filename = unquote(request.headers.get("x-file-name") or "").strip()
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Send the file's name in X-File-Name — it is what says whose photo it is.",
        )
    outcome = photo_bulk.place(db, actor.organization_id, filename, await request.body())
    if outcome.status == "matched":
        audit.record(
            db, actor=actor, action="user.photo_matched", request=request,
            name=outcome.user_name,
        )
    db.commit()
    return BulkPhotoOutcome(
        filename=outcome.filename,
        status=outcome.status,
        detail=outcome.detail,
        user_id=outcome.user_id,
        user_name=outcome.user_name,
    )
