"""Emailing the coaching digest on a schedule.

**The reporting page, as a message.** The same `reporting.overview` the page
opens with — how many goals are on pace, behind and hit, and the worst gaps
with what closing each would take — written as plain text a manager can read on
a phone before stand-up. No second calculation, so the email and the page
cannot disagree.

**Worked out per recipient, with their own scope.** A manager on an admin's
schedule is sent their team, not the organization — the same answer the page
gives them.

**One send per slot, never a backlog.** A schedule remembers the slot it last
delivered for. A pass sends only the most recent slot that has passed, so a
server that was down over a long weekend sends Tuesday's digest on Tuesday, not
four of them at once.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import mail, periods, public_url, reporting, units
from app.models import Organization, ReportSchedule, UserAccount

logger = logging.getLogger(__name__)

__all__ = ["DeliveryReport", "digest", "due_slot", "deliver_due", "send_now"]

#: (db, organization_id, to, subject, body) → Sent. Injectable for tests.
Sender = Callable[..., mail.Sent]

#: What a recipient must be. A digest is a list of people to talk to, which is
#: a manager's job — see `routers/reporting.py`.
RECIPIENT_ROLES = ("admin", "manager")

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _send(db: DbSession, organization_id: int, *, to: str, subject: str, body: str) -> mail.Sent:
    return mail.send(db, organization_id, to=to, subject=subject, body=body)


def _matches(schedule: ReportSchedule, day) -> bool:
    if schedule.cadence == "weekdays":
        return day.weekday() < 5
    if schedule.cadence == "weekly":
        return day.weekday() == (schedule.weekday or 0)
    return day.day == 1


def due_slot(org: Organization, schedule: ReportSchedule, now: datetime) -> datetime | None:
    """The most recent slot at or before `now`, in UTC — or None if there has
    not been one in the last month and a half."""
    zone = periods.tz(org)
    today = now.astimezone(zone).date()
    for back in range(0, 45):
        day = today - timedelta(days=back)
        if not _matches(schedule, day):
            continue
        slot = datetime.combine(day, time(schedule.hour)).replace(tzinfo=zone).astimezone(UTC)
        if slot <= now:
            return slot
    return None


def _money(value, unit: str, places: int, label: str | None = None) -> str:
    text = f"{value:,.{places}f}"
    if unit == "currency":
        # No ".00" on a whole amount (P3-7), as everywhere a person reads it.
        rounded = round(Decimal(str(value)), places)
        if rounded == rounded.to_integral_value():
            text = f"{rounded:,.0f}"
        return f"${text}"
    if unit == "percent":
        return f"{text}%"
    return units.with_noun(text, value, unit, label)


def digest(db: DbSession, org: Organization, recipient: UserAccount, *, now: datetime) -> tuple[str, str]:
    """(subject, body) for one recipient, in their own scope."""
    found = reporting.overview(db, org, recipient, now=now)
    local = now.astimezone(periods.tz(org))
    when = f"{WEEKDAYS[local.weekday()]} {local.day} {local.strftime('%B')}"
    subject = f"Coaching digest — {when}"

    lines = [f"Coaching digest for {org.name} · {when}", ""]
    if found.total == 0:
        lines.append("No goals are running for the people you look after right now.")
    else:
        lines.append(
            f"{found.total} {'goal' if found.total == 1 else 'goals'} running: "
            f"{found.on_pace_percent:g}% on pace or hit — {found.hit} hit, "
            f"{found.on_pace} on pace, {found.behind} behind."
        )
        if found.gaps:
            lines += ["", "Behind, worst first:"]
            for gap in found.gaps:
                line = (
                    f"• {gap.subject_name} — {gap.goal_name}: "
                    f"{_money(gap.current, gap.unit, gap.decimal_places)} of "
                    f"{_money(gap.target, gap.unit, gap.decimal_places, gap.unit_label)}, "
                    f"{gap.behind_by:g}% behind pace"
                )
                if gap.rate_needed is not None:
                    line += (
                        f". Needs {_money(gap.rate_needed, gap.unit, 1, gap.unit_label)} a working day "
                        f"for {gap.days_left} {'day' if gap.days_left == 1 else 'days'}"
                    )
                    if gap.rate_so_far is not None:
                        line += f" (has averaged {_money(gap.rate_so_far, gap.unit, 1, gap.unit_label)})"
                lines.append(line + ".")
        else:
            lines += ["", "Nobody is behind. Worth saying so at stand-up."]
    lines += [
        "",
        f"Open the reporting page: {public_url.get(db)}/reporting",
        "",
        "You are getting this because you are on a GoalGetter report schedule.",
    ]
    return subject, "\n".join(lines)


def _recipients(db: DbSession, schedule: ReportSchedule) -> list[UserAccount]:
    ids = [i for i in (schedule.recipient_ids or []) if isinstance(i, int)]
    if not ids:
        return []
    return list(
        db.scalars(
            select(UserAccount).where(
                UserAccount.id.in_(ids),
                UserAccount.organization_id == schedule.organization_id,
                # Somebody demoted, hidden or gone since they were added stops
                # receiving a list of other people's numbers.
                UserAccount.org_role.in_(RECIPIENT_ROLES),
                UserAccount.hidden_at.is_(None),
                UserAccount.status == "active",
            )
        ).all()
    )


def _deliver(db, org, schedule, recipients, *, now, send) -> str | None:
    """Send to each recipient. None when everybody got it, else why not."""
    problems: list[str] = []
    for person in recipients:
        subject, body = digest(db, org, person, now=now)
        sent = send(db, org.id, to=person.email, subject=subject, body=body)
        if not sent.ok:
            problems.append(sent.detail)
    return problems[0][:500] if problems else None


@dataclass
class DeliveryReport:
    schedules: int = 0
    sent: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"reports {self.schedules} schedules, {self.sent} sent, {self.failed} failed"


def deliver_due(
    db: DbSession, *, now: datetime | None = None, send: Sender | None = None
) -> DeliveryReport:
    """Every schedule whose slot has come round since it last sent."""
    now = now or datetime.now(UTC)
    send = send or _send
    report = DeliveryReport()
    orgs = {o.id: o for o in db.scalars(select(Organization)).all()}

    for schedule in db.scalars(
        select(ReportSchedule).where(ReportSchedule.enabled.is_(True))
    ).all():
        org = orgs.get(schedule.organization_id)
        if org is None:
            continue
        slot = due_slot(org, schedule, now)
        if slot is None or (schedule.last_slot_at is not None and slot <= schedule.last_slot_at):
            continue
        # Claimed before sending: a pass that dies mid-send must not send the
        # same digest again on the next one.
        schedule.last_slot_at = slot
        report.schedules += 1
        recipients = _recipients(db, schedule)
        if not recipients:
            schedule.last_error = "Nobody on this schedule can receive it — add an admin or a manager."
            report.failed += 1
            continue
        error = _deliver(db, org, schedule, recipients, now=now, send=send)
        schedule.last_error = error
        if error is None:
            schedule.last_sent_at = now
            report.sent += 1
        else:
            report.failed += 1
    return report


def send_now(
    db: DbSession, org: Organization, schedule: ReportSchedule, to: UserAccount, *,
    now: datetime | None = None, send: Sender | None = None,
) -> str | None:
    """The digest, to one person, right now — the test button. Changes nothing
    about when the schedule next sends."""
    now = now or datetime.now(UTC)
    return _deliver(db, org, schedule, [to], now=now, send=send or _send)
