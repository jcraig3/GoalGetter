"""Sending the activity log to a SIEM, and exporting it.

**What goes out is what the activity log already holds** — who did what, to
whom, when, and from where — and nothing more. The log was written never to
contain a password, token or secret (see `models/audit_log.py`), which is what
makes it safe to hand to another system at all.

**In order, exactly once.** A stream remembers the newest entry its collector
accepted. Each pass sends the next batch after it, oldest first, and moves the
marker only on a 2xx — so a collector that is down for a day receives that day
when it comes back, and a pass that dies half-way sends nothing twice.

**A new stream starts from now.** Pointing a SIEM at a deployment that has
been running for a year should not deliver a year in one burst; the export is
the way to backfill.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import crypto
from app.models import AuditLog, AuditStream

logger = logging.getLogger(__name__)

__all__ = ["BATCH", "StreamProblem", "check_url", "entry", "push_due", "send_test"]

#: Entries per request. Splunk's HEC and most collectors take far more; this
#: keeps a backlog moving without one enormous request.
BATCH = 500
HTTP_TIMEOUT = 15.0

#: (url, headers, body) → response. Injectable for tests.
Poster = Callable[[str, dict, bytes], httpx.Response]


class StreamProblem(ValueError):
    """Why a collector address cannot be used, in words."""


def check_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise StreamProblem("A collector address starts with https://.")
    return url


def entry(row: AuditLog) -> dict:
    """One activity-log entry, as it leaves."""
    return {
        "id": row.id,
        "time": row.occurred_at.astimezone(UTC).isoformat(),
        "action": row.action,
        "actor": row.actor_email,
        "target": row.target_email,
        "ip": str(row.ip_address) if row.ip_address else None,
        "details": row.details or {},
        "source": "goalgetter",
    }


def body_for(stream_format: str, rows: list[AuditLog]) -> tuple[bytes, str]:
    events = [entry(row) for row in rows]
    if stream_format == "splunk":
        # HEC takes concatenated JSON objects, each an event with its own time.
        text = "\n".join(
            json.dumps({
                "time": row.occurred_at.timestamp(),
                "sourcetype": "goalgetter:audit",
                "event": event,
            })
            for row, event in zip(rows, events)
        )
        return text.encode(), "application/json"
    return json.dumps({"events": events}).encode(), "application/json"


def _post(url: str, headers: dict, body: bytes) -> httpx.Response:
    # No redirects: a collector that answers with one is not one to follow.
    return httpx.post(url, content=body, headers=headers, timeout=HTTP_TIMEOUT, follow_redirects=False)


def _headers(stream: AuditStream) -> dict:
    headers = {"Content-Type": "application/json"}
    if stream.header_value_encrypted:
        headers[stream.header_name or "Authorization"] = crypto.decrypt(stream.header_value_encrypted)
    return headers


def _describe(response: httpx.Response) -> str:
    if response.status_code in (401, 403):
        return f"The collector refused the credential ({response.status_code}). Check the header and its value."
    if response.status_code == 404:
        return "The collector address answered 404. Check it is the collector's own endpoint."
    return f"The collector answered {response.status_code}."


@dataclass
class PushReport:
    streams: int = 0
    sent: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"audit stream {self.streams} streams, {self.sent} entries sent, {self.failed} failed"


def push_due(db: DbSession, *, now: datetime | None = None, post: Poster | None = None) -> PushReport:
    now = now or datetime.now(UTC)
    post = post or _post
    report = PushReport()
    for stream in db.scalars(select(AuditStream).where(AuditStream.enabled.is_(True))).all():
        rows = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == stream.organization_id,
                AuditLog.id > stream.last_audit_id,
            )
            .order_by(AuditLog.id)
            .limit(BATCH)
        ).all()
        if not rows:
            continue
        report.streams += 1
        try:
            url = check_url(crypto.decrypt(stream.url_encrypted))
            body, _ = body_for(stream.format, list(rows))
            response = post(url, _headers(stream), body)
        except (ValueError, httpx.HTTPError) as problem:
            error = (
                str(problem) if isinstance(problem, StreamProblem)
                else f"Could not reach the collector: {problem.__class__.__name__}."
            )
            stream.last_error, stream.last_error_at = error[:500], now
            report.failed += 1
            continue
        if 200 <= response.status_code < 300:
            stream.last_audit_id = rows[-1].id
            stream.last_sent_at = now
            stream.last_error = None
            report.sent += len(rows)
        else:
            stream.last_error, stream.last_error_at = _describe(response)[:500], now
            report.failed += 1
    return report


def send_test(stream: AuditStream, *, post: Poster | None = None) -> str | None:
    """One made-up entry, now. None when the collector took it."""
    post = post or _post
    event = {
        "id": 0, "time": datetime.now(UTC).isoformat(), "action": "audit_stream.test",
        "actor": None, "target": None, "ip": None, "details": {"test": True}, "source": "goalgetter",
    }
    try:
        url = check_url(crypto.decrypt(stream.url_encrypted))
        if stream.format == "splunk":
            body = json.dumps({"time": datetime.now(UTC).timestamp(), "sourcetype": "goalgetter:audit", "event": event}).encode()
        else:
            body = json.dumps({"events": [event]}).encode()
        response = post(url, _headers(stream), body)
    except StreamProblem as problem:
        return str(problem)
    except (ValueError, httpx.HTTPError) as problem:
        return f"Could not reach the collector: {problem.__class__.__name__}."
    return None if 200 <= response.status_code < 300 else _describe(response)


def newest_id(db: DbSession, org_id: int) -> int:
    return int(db.scalar(select(func.max(AuditLog.id)).where(AuditLog.organization_id == org_id)) or 0)


def export_rows(db: DbSession, org_id: int, *, since: datetime | None, until: datetime | None) -> Iterator[AuditLog]:
    """Oldest first, in pages, so a large log streams rather than loads."""
    last = 0
    while True:
        query = select(AuditLog).where(AuditLog.organization_id == org_id, AuditLog.id > last)
        if since is not None:
            query = query.where(AuditLog.occurred_at >= since)
        if until is not None:
            query = query.where(AuditLog.occurred_at < until)
        page = db.scalars(query.order_by(AuditLog.id).limit(1000)).all()
        if not page:
            return
        yield from page
        last = page[-1].id
