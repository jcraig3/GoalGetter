from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.metrics_seed import seed_default_metrics
from app.models import Organization, UserAccount
from app.security import NewPassword, hash_password

router = APIRouter(prefix="/setup", tags=["setup"])


class SetupStatus(BaseModel):
    setup_required: bool


class SetupRequest(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: NewPassword


class SetupResult(BaseModel):
    organization_id: int
    user_id: int
    email: str


def _setup_required(db: Session) -> bool:
    """Setup is available only while the deployment has no users at all.

    This is what stops the endpoint being a permanent backdoor: once anyone
    exists, it refuses forever.
    """
    return db.scalar(select(func.count()).select_from(UserAccount)) == 0


@router.get("/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db)) -> SetupStatus:
    """Tells the UI whether to show the setup screen. Safe to call publicly —
    it reveals only whether the app has been initialised."""
    return SetupStatus(setup_required=_setup_required(db))


@router.post("", response_model=SetupResult, status_code=status.HTTP_201_CREATED)
def run_setup(payload: SetupRequest, db: Session = Depends(get_db)) -> SetupResult:
    """Create the organization and the first admin.

    Password is hashed before the row is written; the plaintext exists only for
    the life of this request and is never logged or stored.
    """
    # Serialises concurrent setup attempts. Without it, two requests arriving
    # together could both see zero users and both create an admin. The lock is
    # held until this transaction ends.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('goalgetter.setup'))"))

    if not _setup_required(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This deployment has already been set up.",
        )

    organization = Organization(name=payload.organization_name)
    db.add(organization)
    db.flush()  # assigns organization.id without ending the transaction

    # Same transaction as the organization, so a failed setup leaves no
    # orphaned metrics behind. A fresh install has something to measure rather
    # than an empty configuration screen.
    seed_default_metrics(db, organization.id)

    user = UserAccount(
        organization_id=organization.id,
        email=payload.email.lower(),
        full_name=payload.full_name,
        org_role="admin",
        status="active",
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()

    return SetupResult(
        organization_id=organization.id, user_id=user.id, email=user.email
    )
