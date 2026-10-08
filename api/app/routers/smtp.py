"""The mail server settings, and a button that proves them.

Beside `/api/admin/sso` and `/api/admin/directory`, because it is the same kind of
thing: a once-per-deployment connection an admin sets up and then forgets about.

**The password is absent from every response, not masked.** Same rule as the SSO
client secret and every connector credential: a masked value still travelled over
the network and sat in a browser's memory.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, mail
from app.crypto import encrypt
from app.db import get_db
from app.models import SmtpConfig, UserAccount
from app.models.smtp_config import SMTP_SECURITY
from app.sessions import require_role

router = APIRouter(prefix="/admin/smtp", tags=["admin"])


class SmtpSettings(BaseModel):
    enabled: bool
    host: str
    port: int
    security: str
    username: str
    #: Whether a password is stored. Never the password.
    password_set: bool
    from_address: str
    from_name: str
    #: Whether there is enough here to attempt a send. Reported rather than left
    #: to the page to work out, so the page and the sender cannot disagree about
    #: what "configured" means.
    usable: bool


class SmtpWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: str = Field(default="starttls", max_length=20)
    username: str = Field(default="", max_length=320)
    #: Omit to keep the stored one — so fixing a typo in the host does not mean
    #: going to find the password again. `""` clears it, which is how a relay that
    #: wants no authentication is configured after one that did.
    password: str | None = Field(default=None, max_length=1000)
    from_address: str = Field(default="", max_length=320)
    from_name: str = Field(default="GoalGetter", max_length=200)


class TestResult(BaseModel):
    ok: bool
    detail: str


def _get_or_create(db: DbSession, organization_id: int) -> SmtpConfig:
    config = db.scalar(
        select(SmtpConfig).where(SmtpConfig.organization_id == organization_id)
    )
    if config is None:
        config = SmtpConfig(organization_id=organization_id)
        db.add(config)
        db.flush()
    return config


def _to_settings(config: SmtpConfig) -> SmtpSettings:
    return SmtpSettings(
        enabled=config.enabled,
        host=config.host,
        port=config.port,
        security=config.security,
        username=config.username,
        password_set=bool(config.password_encrypted),
        from_address=config.from_address,
        from_name=config.from_name,
        usable=mail.usable(config),
    )


@router.get("", response_model=SmtpSettings)
def get_smtp(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SmtpSettings:
    config = _get_or_create(db, actor.organization_id)
    db.commit()
    return _to_settings(config)


@router.put("", response_model=SmtpSettings)
def update_smtp(
    payload: SmtpWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SmtpSettings:
    if payload.security not in SMTP_SECURITY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{payload.security!r} is not a connection type. "
            f"Known: {', '.join(SMTP_SECURITY)}.",
        )

    config = _get_or_create(db, actor.organization_id)
    config.host = payload.host.strip()
    config.port = payload.port
    config.security = payload.security
    config.username = payload.username.strip()
    config.from_address = payload.from_address.strip()
    config.from_name = payload.from_name.strip()

    if payload.password is not None:
        config.password_encrypted = encrypt(payload.password) if payload.password else None

    # **Refused at save time rather than discovered per invitation.** A from-address
    # somebody left blank produces a message every server rejects, and the failure
    # would otherwise surface once per invited person rather than once here.
    if payload.enabled:
        if not config.host:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A mail server needs a host before it can be switched on.",
            )
        if not mail.looks_like_an_address(config.from_address):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The from-address has to be an email address — it is what "
                    "recipients see, and the server has to be allowed to send as it."
                ),
            )

    config.enabled = payload.enabled
    audit.record(
        db,
        actor=actor,
        action="smtp.saved",
        request=request,
        enabled=payload.enabled,
        # Whether the password was touched, never the password.
        password_changed=payload.password is not None,
    )
    db.commit()
    return _to_settings(config)


@router.post("/test", response_model=TestResult)
def test_smtp(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TestResult:
    """Send a real message to the admin pressing the button.

    To *them*, not to an address they type: the question this answers is "does mail
    from here arrive", and an address they choose could be one the server happens to
    treat differently. Their own is the one they can go and check.
    """
    result = mail.send(
        db,
        actor.organization_id,
        to=actor.email,
        subject="GoalGetter test message",
        body=(
            "This is a test from GoalGetter.\n\n"
            "If you are reading it, invitations and password reset links will "
            "reach people from this address.\n"
        ),
    )
    return TestResult(ok=result.ok, detail=result.detail)
