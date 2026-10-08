from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str


class Readiness(BaseModel):
    status: str
    database: bool


@router.get("/health", response_model=Health)
def health() -> Health:
    """Liveness: is the process up?

    Deliberately touches nothing external. If this checked the database, a
    brief Postgres blip would make an orchestrator restart a perfectly healthy
    API process.
    """
    return Health(status="ok")


@router.get("/health/ready", response_model=Readiness)
def readiness(response: Response, db: Session = Depends(get_db)) -> Readiness:
    """Readiness: can the process actually serve traffic?

    Returns 503 when not, so a load balancer stops sending requests without the
    container being killed.
    """
    try:
        db.execute(text("SELECT 1"))
        database = True
    except Exception:
        database = False
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return Readiness(status="ready" if database else "not_ready", database=database)
