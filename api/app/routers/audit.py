import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import audit, audit_stream, crypto, csv_export
from app.db import get_db
from app.models import AuditLog, AuditStream, UserAccount
from app.sessions import require_role

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEntry(BaseModel):
    id: int
    action: str
    actor_email: str | None
    target_email: str | None
    #: Who, by name (P3-19) — the log read as a list of addresses. Null when
    #: the account is gone; the address stays as it was written.
    actor_name: str | None = None
    target_name: str | None = None
    details: dict[str, Any] | None
    occurred_at: datetime


@router.get("", response_model=list[AuditEntry])
def list_audit(
    # Admin only. A manager can see who is on their team, but not the record of
    # who granted whom what — that is organization-level oversight.
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
    # Capped in the signature rather than trusted from the query string: this
    # table grows without bound, and "?limit=1000000" should not be a way to
    # make the API read every row it has ever written.
    limit: int = Query(default=50, ge=1, le=200),
    person: str | None = Query(default=None, max_length=320),
    kind: str | None = Query(default=None, max_length=64),
    since: date | None = None,
    until: date | None = None,
) -> list[AuditEntry]:
    """The organization's recent privileged actions, newest first.

    Narrowed by who (either side of it, by address), what kind of thing
    (`competition`, `user`…) and when (8.4) — fifty rows of everything was
    the only view.
    """
    query = select(AuditLog).where(AuditLog.organization_id == actor.organization_id)
    if person and person.strip():
        like = f"%{person.strip()}%"
        query = query.where(
            or_(AuditLog.actor_email.ilike(like), AuditLog.target_email.ilike(like))
        )
    if kind:
        query = query.where(AuditLog.action.startswith(f"{kind}."))
    if since is not None:
        query = query.where(AuditLog.occurred_at >= _day(since))
    if until is not None:
        query = query.where(AuditLog.occurred_at < _day(until, end=True))
    rows = db.scalars(
        # id as the tiebreaker: two actions in the same transaction share a
        # timestamp to the microsecond, and without it their order flips
        # between requests.
        query.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit)
    ).all()
    ids = {row.actor_user_id for row in rows} | {row.target_user_id for row in rows}
    names = dict(
        db.execute(
            select(UserAccount.id, UserAccount.full_name).where(
                UserAccount.id.in_({i for i in ids if i is not None}),
                UserAccount.organization_id == actor.organization_id,
            )
        ).all()
    )
    out = []
    for row in rows:
        entry = AuditEntry.model_validate(row, from_attributes=True)
        entry.actor_name = names.get(row.actor_user_id)
        entry.target_name = names.get(row.target_user_id)
        out.append(entry)
    return out


@router.get("/kinds", response_model=list[str])
def list_kinds(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[str]:
    """The kinds of thing the log has entries for — what the filter offers."""
    prefix = func.split_part(AuditLog.action, ".", 1)
    return list(
        db.scalars(
            select(prefix)
            .where(AuditLog.organization_id == actor.organization_id)
            .group_by(prefix)
            .order_by(prefix)
        ).all()
    )


# ── Export and streaming ────────────────────────────────────────────────────


def _day(value: date | None, *, end: bool = False) -> datetime | None:
    """The start of a day in UTC — or of the day after, for an inclusive end."""
    if value is None:
        return None
    return datetime.combine(value + timedelta(days=1) if end else value, time.min, tzinfo=UTC)


@router.get("/export")
def export_audit(
    format: Literal["csv", "jsonl"] = "csv",
    since: date | None = None,
    until: date | None = None,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StreamingResponse:
    """The activity log, oldest first, as CSV or JSON Lines — for an audit, or
    to load a SIEM with what came before its stream began. `until` includes
    the whole of that day."""
    rows = audit_stream.export_rows(
        db, actor.organization_id, since=_day(since), until=_day(until, end=True)
    )
    if format == "jsonl":
        lines = (json.dumps(audit_stream.entry(row)) + "\n" for row in rows)
        return StreamingResponse(
            lines, media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="goalgetter-activity.jsonl"'},
        )
    table = (
        (e["id"], e["time"], e["action"], e["actor"] or "", e["target"] or "", e["ip"] or "", json.dumps(e["details"]))
        for e in (audit_stream.entry(row) for row in rows)
    )
    return StreamingResponse(
        csv_export.rows_to_csv(["id", "time", "action", "actor", "target", "ip", "details"], table),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="goalgetter-activity.csv"'},
    )


class StreamRead(BaseModel):
    enabled: bool
    format: str
    #: Enough of the address to recognise it by.
    url_hint: str
    header_name: str
    header_set: bool
    last_sent_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None


class StreamWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    format: Literal["json", "splunk"] = "json"
    #: Required the first time; absent keeps the stored one.
    url: str | None = Field(default=None, max_length=2000)
    header_name: str = Field(default="Authorization", min_length=1, max_length=100)
    #: Absent keeps the stored one; an empty string removes it.
    header_value: str | None = Field(default=None, max_length=2000)


def _stream_read(row: AuditStream) -> StreamRead:
    try:
        parsed = crypto.decrypt(row.url_encrypted)
        hint = f"{parsed.split('/')[2]}/…{parsed[-6:]}" if "://" in parsed else "(unreadable)"
    except ValueError:
        hint = "(unreadable — save it again)"
    return StreamRead(
        enabled=row.enabled, format=row.format, url_hint=hint, header_name=row.header_name,
        header_set=bool(row.header_value_encrypted), last_sent_at=row.last_sent_at,
        last_error=row.last_error, last_error_at=row.last_error_at,
    )


def _stream(db: DbSession, org_id: int) -> AuditStream | None:
    return db.scalar(select(AuditStream).where(AuditStream.organization_id == org_id))


@router.get("/stream", response_model=StreamRead | None)
def read_stream(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StreamRead | None:
    row = _stream(db, actor.organization_id)
    return _stream_read(row) if row else None


@router.put("/stream", response_model=StreamRead)
def save_stream(
    payload: StreamWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StreamRead:
    """Send the activity log to a SIEM as it grows, starting from now."""
    row = _stream(db, actor.organization_id)
    if row is None and not payload.url:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Paste the collector's address.")
    if payload.url:
        try:
            url = audit_stream.check_url(payload.url)
        except audit_stream.StreamProblem as problem:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(problem)) from None
    if row is None:
        row = AuditStream(
            organization_id=actor.organization_id,
            last_audit_id=audit_stream.newest_id(db, actor.organization_id),
        )
        db.add(row)
    if payload.url:
        row.url_encrypted = crypto.encrypt(url)
        row.last_error = row.last_error_at = None
    if payload.header_value is not None:
        row.header_value_encrypted = crypto.encrypt(payload.header_value) if payload.header_value else None
    if not row.enabled and payload.enabled:
        # Switched back on: from now, like a new stream. The export covers the gap.
        row.last_audit_id = audit_stream.newest_id(db, actor.organization_id)
    row.enabled = payload.enabled
    row.format = payload.format
    row.header_name = payload.header_name.strip()
    # Recorded without the address or the credential.
    audit.record(db, actor=actor, action="audit_stream.saved", request=request, format=row.format, on=str(row.enabled))
    db.commit()
    return _stream_read(row)


@router.delete("/stream", status_code=status.HTTP_204_NO_CONTENT)
def delete_stream(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    row = _stream(db, actor.organization_id)
    if row is not None:
        audit.record(db, actor=actor, action="audit_stream.removed", request=request)
        db.delete(row)
        db.commit()


class TestRead(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/stream/test", response_model=TestRead)
def test_stream(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TestRead:
    row = _stream(db, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Set up the stream first.")
    error = audit_stream.send_test(row)
    return TestRead(ok=error is None, error=error)

