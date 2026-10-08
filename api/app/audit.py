"""Recording privileged actions.

One function, called from the handlers that change access. It only adds a row
to the session — the caller's existing `db.commit()` writes it.

That is deliberate: the audit row and the change it describes commit in the
same transaction, so they cannot disagree. If the role change is rolled back,
the record of it is rolled back too, and a change can never be applied without
being recorded.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session as DbSession

from app.models import AuditLog, UserAccount
from app.net import visitor_ip


def record(
    db: DbSession,
    *,
    actor: UserAccount,
    action: str,
    request: Request | None = None,
    target: UserAccount | None = None,
    **details: Any,
) -> None:
    """Note that `actor` performed `action`, optionally against `target`.

    Keyword-only after `db` on purpose: a positional call like
    `record(db, actor, target, "suspend")` reads fine and is easy to get in the
    wrong order, and swapped actor/target is a mistake nobody notices until the
    log is needed.
    """
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            actor_email=actor.email,
            action=action,
            target_user_id=target.id if target else None,
            target_email=target.email if target else None,
            # Empty dict would be noise; None reads as "nothing to add".
            details=details or None,
            # Who it was, not nginx (P5-1): the socket peer is always the
            # proxy. Read by position, so a client cannot write it.
            ip_address=visitor_ip(request, db),
            occurred_at=datetime.now(UTC),
        )
    )


def record_system(db: DbSession, *, organization_id: int, action: str, **details: Any) -> None:
    """Note something GoalGetter did by itself, or saw done outside the app —
    a hosting change undone because nobody kept it, an edit in `.env`. Shown
    in Activity as done by "GoalGetter"."""
    db.add(
        AuditLog(
            organization_id=organization_id,
            actor_user_id=None,
            actor_email=SYSTEM,
            action=action,
            details=details or None,
            occurred_at=datetime.now(UTC),
        )
    )


#: Who a system entry says did it.
SYSTEM = "GoalGetter"


def changed(before: Any, after: Any) -> dict[str, Any]:
    """Shorthand for the usual details payload: {"from": x, "to": y}."""
    return {"from": before, "to": after}
