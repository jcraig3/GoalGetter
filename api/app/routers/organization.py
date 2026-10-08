from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DbSession

from app import net, public_url, rate_limit
from app.appearance import Appearance, resolve
from app.db import get_db
from app.models import Organization, UserAccount
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/organization", tags=["organization"])

# Resolved once at import. available_timezones() walks the tz database, which
# is not something to repeat on every request.
_VALID_TIMEZONES = available_timezones()

# ISO 4217 codes for the currencies a sales team is plausibly measured in.
# Not the full list of 180 — a picker of everything is harder to use, and
# adding one later is a one-line change.
CURRENCIES = ("USD", "CAD", "GBP", "EUR", "AUD", "NZD", "ZAR", "INR", "SGD", "MXN")


class OrganizationRead(BaseModel):
    id: int
    name: str
    timezone: str
    week_starts_on: int
    fiscal_year_start_month: int
    currency: str

    #: What this organization has chosen, sparsely — only the fields it set.
    #: What an agent may set about themselves. See `models/organization.py`.
    self_photo: bool = True
    self_details: bool = True
    self_walkup: bool = True
    #: Colleagues can see each other's profiles (9.5). See `app/people.py`.
    profiles_public: bool = True
    #: Password sign-in needs an authenticator code too. See `app/totp.py`.
    require_mfa: bool = False
    #: Only admins and managers can sign in (Phase 28).
    sign_in_leaders_only: bool = False
    #: Where this deployment is, as an admin set it; null for the default
    #: (11.7). See `app/public_url.py`.
    public_url: str | None = None
    #: `APP_URL` from the environment: what applies while `public_url` is null.
    public_url_default: str = ""
    #: A proxy of the organization's own in front (Phase 17): `direct`,
    #: `proxy`, or null for `.env`'s TRUSTED_PROXY_HOPS.
    proxy_mode: str | None = None
    #: Wrong passwords allowed in five minutes; null for the defaults.
    sign_in_limit_account: int | None = None
    sign_in_limit_device: int | None = None

    #: Sent alongside `appearance_resolved` rather than instead of it, because
    #: an editor needs to know which values are the organization's own in order
    #: to offer "reset to default" on exactly those.
    appearance: dict = {}
    #: The same thing merged over the built-in defaults: every field filled.
    #: What a renderer reads, so nothing downstream handles a null.
    appearance_resolved: dict = {}


class OrganizationUpdate(BaseModel):
    name: Name(200) | None = None
    timezone: str | None = None
    week_starts_on: int | None = Field(default=None, ge=0, le=6)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    currency: str | None = None

    #: **Replaces the whole object rather than merging.** A PATCH that merged
    #: would have no way to express "stop setting this and go back to the
    #: default" — the absence of a key would be indistinguishable from leaving
    #: it alone, which is exactly the control this system exists to provide.
    #:
    #: Typed rather than a bare dict so FastAPI validates it as part of the
    #: body. Validating by hand inside the handler raised `ValidationError`
    #: *after* the request had been accepted, which FastAPI reports as a 500 —
    #: a font scale of nine came back as "internal server error" rather than as
    #: the field that was wrong.
    appearance: Appearance | None = None

    #: Each one is "may an agent do this for themselves". A manager and an
    #: admin are never bound by them — see the note on the model.
    self_photo: bool | None = None
    self_details: bool | None = None
    self_walkup: bool | None = None
    profiles_public: bool | None = None
    require_mfa: bool | None = None
    sign_in_leaders_only: bool | None = None
    #: Empty or null goes back to `APP_URL`.
    public_url: str | None = None
    #: `direct`, `proxy`, or null for `.env`. `proxy` only with one seen.
    proxy_mode: str | None = None
    sign_in_limit_account: int | None = None
    sign_in_limit_device: int | None = None


def _org(db: DbSession, organization_id: int) -> Organization:
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )
    return org


@router.get("", response_model=OrganizationRead)
def read_organization(
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> OrganizationRead:
    """Readable by anyone signed in, not just admins.

    Every screen that shows a date or a currency needs these — a leaderboard
    has to know which timezone "today" means. Only editing is restricted.
    """
    return _to_read(_org(db, user.organization_id))


@router.patch("", response_model=OrganizationRead)
def update_organization(
    payload: OrganizationUpdate,
    request: Request,
    user: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> OrganizationRead:
    org = _org(db, user.organization_id)
    fields = payload.model_dump(exclude_unset=True)

    if "timezone" in fields:
        # Validated against the real tz database rather than accepting any
        # string. An invalid zone would not fail here — it would fail later,
        # inside a date calculation, and present as wrong numbers rather than
        # an error.
        if fields["timezone"] not in _VALID_TIMEZONES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{fields['timezone']}' is not a recognised timezone.",
            )

    if "currency" in fields:
        code = (fields["currency"] or "").upper()
        if code not in CURRENCIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{code}' is not a supported currency.",
            )
        fields["currency"] = code

    if "public_url" in fields:
        try:
            fields["public_url"] = (
                public_url.normalise(fields["public_url"]) if fields["public_url"] else None
            )
        except ValueError as problem:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
            ) from problem

    # Only when it changes: saving the currency while `proxy` is on, from the
    # server's own browser, must not trip a check about how you connected.
    if "proxy_mode" in fields and (fields["proxy_mode"] or None) != org.proxy_mode:
        _check_proxy_mode(fields, request)
    elif "proxy_mode" in fields:
        fields["proxy_mode"] = org.proxy_mode

    for key, (low, high) in (
        ("sign_in_limit_account", rate_limit.ACCOUNT_RANGE),
        ("sign_in_limit_device", rate_limit.DEVICE_RANGE),
    ):
        value = fields.get(key)
        if value is not None and not low <= value <= high:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Choose between {low} and {high}.",
            )

    if "appearance" in fields:
        # `exclude_none` keeps the row sparse: a field nobody set stays absent,
        # which is what "inherit" looks like on disk — and means a later change
        # to the built-in default still reaches this organization.
        chosen = payload.appearance or Appearance()
        fields["appearance"] = chosen.model_dump(exclude_none=True)

    for field, value in fields.items():
        # A switch sent as null is somebody's client filling in a default it
        # did not mean; the column is NOT NULL and "leave it alone" is what
        # absence already says.
        if (field.startswith("self_") or field in ("require_mfa", "profiles_public", "sign_in_leaders_only")) and value is None:
            continue
        setattr(org, field, value)

    db.commit()
    return _to_read(org)


def _check_proxy_mode(fields: dict, request: Request) -> None:
    """`proxy` only when a proxy is passing an address along right now.

    **The safety check** (Phase 17). With `proxy`, GoalGetter believes one more
    entry of X-Forwarded-For — the one the organization's proxy adds. With no
    such proxy, that entry is whatever a visitor typed, and anybody could
    choose the address they appear to come from: every per-device limit gone.
    So it is refused unless this very request arrived with two entries, the
    proxy's and nginx's.
    """
    mode = fields["proxy_mode"]
    if mode in (None, ""):
        fields["proxy_mode"] = None
        return
    if mode not in ("direct", "proxy"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown proxy setting.")
    if mode == "proxy" and len(net.forwarded_chain(request)) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No proxy is passing your address along right now. Open GoalGetter "
                "through your proxy's address and try again — set without one, anybody "
                "could choose the address they appear to come from."
            ),
        )


def _to_read(org: Organization) -> OrganizationRead:
    read = OrganizationRead.model_validate(org, from_attributes=True)
    read.appearance_resolved = resolve(org.appearance).model_dump()
    read.public_url_default = public_url.default()
    return read
