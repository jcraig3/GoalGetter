"""Accounts that look like devices, rooms or shared mailboxes rather than people.

**Why this exists.** A directory sync brings in every account the tenant has, and
a tenant has printers ("MFP 3100"), shared mailboxes ("No Reply", "Deal Desk"),
service accounts ("OneDrive", "Device Admin") and leftovers ("dummy account 2").
Each one lands on every picker, in every "recorded nothing in 7 days" count and
at the bottom of every board, so every number a new admin sees is wrong until
somebody hides them — and nothing suggested it (review §2 #2).

**A suggestion, never a decision.** This only proposes; an admin reviews the
list and hides what it names, through the same audited bulk action the People
page uses. Getting one wrong costs a click, not a person silently vanishing.

**Two tests, both required.**

1. *Nothing says it is a person.* Never signed in, no recorded numbers, no
   photo, nobody has given it a goal, and still the default role — an admin or
   a manager was made one on purpose. Any one of those is somebody having
   treated the account as a person, and that outweighs anything about its name.
   A job title or a department counts too, *unless* the name says it is a
   stand-in ("Test User 69", "Jarvis Bot"): a test account copied from a real one
   carries the real one's title. A team on its own counts for nothing (Q2-15) —
   "Jarvis Bot" was put on a team so it could dial, not because it is somebody.
2. *Its name is shaped like a thing.* A digit ("MFP 3100", "test user8"), a word
   that names a service ("No Reply", "Scans", "Deal Desk", "FastSourcing"), the
   organization's own name ("Northwind Vegas" at northwindtax.example), a "former_"
   address, or a single word ("Krypto"). Real people with no title — common in a
   directory nobody has tidied — have two ordinary names and pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session as DbSession

from app.models import Goal, MetricFact, Organization, UserAccount

#: Words that name a service, a place or a function rather than somebody.
#: Matched as whole words in the name, and anywhere in the address's local part.
SERVICE_WORDS = frozenset(
    {
        "admin", "alerts", "billing", "bot", "calendar", "conference", "desk",
        "device", "dummy", "helpdesk", "info", "kiosk", "mailbox", "noreply",
        "onedrive", "prem", "printer", "reception", "room", "scan", "scans",
        "scanner", "service", "shared", "site", "sourcing", "success", "support",
        "team", "test", "testing", "tv",
    }
)

#: Words that say the account stands in for somebody. These outweigh a job
#: title or a department, which test accounts copy from real ones.
STAND_IN_WORDS = frozenset({"bot", "demo", "dummy", "fake", "sample", "test", "testing"})

_WORD = re.compile(r"[a-z]+")
#: "FastSourcing" is two words; "NTax" stays one.
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def words_of(name: str) -> list[str]:
    return _WORD.findall(_CAMEL.sub(" ", name).lower())


def own_name_words(email: str, org_name: str = "") -> frozenset[str]:
    """The organization's own name, as words a person is not called.

    From its name and from the address's domain ("northwindtax.example"), which is
    often the only place the real name appears. Short words ("co", "acme") are
    too common to say anything.
    """
    domain = email.split("@", 1)[1].split(".", 1)[0].lower() if "@" in email else ""
    found = {w for w in words_of(org_name) if len(w) >= 5}
    return frozenset(found | ({domain} if len(domain) >= 5 else set()))


def stands_in(full_name: str) -> bool:
    return any(w in STAND_IN_WORDS for w in words_of(full_name))


@dataclass(frozen=True)
class Candidate:
    id: int
    full_name: str
    email: str
    #: Why it was suggested, in words an admin can check at a glance.
    reason: str


def reason_for(full_name: str, email: str, org_name: str = "") -> str | None:
    """Why this name looks like a thing rather than a person, or None.

    Only the name test — the caller has already established that nothing else
    marks the account as a person.
    """
    name = full_name.strip()
    local = email.split("@", 1)[0].lower()
    words = words_of(name)
    # As typed, too: "OneDrive" is one service word, not "one" and "drive".
    whole = _WORD.findall(name.lower())

    if any(ch.isdigit() for ch in name):
        return "a number in the name"
    if "no reply" in name.lower() or "noreply" in local or "no-reply" in local:
        return "a no-reply address"
    service = next((w for w in [*whole, *words] if w in SERVICE_WORDS), None)
    if service:
        return f"“{service}” in the name"
    # A name word inside the organization's own name: "Northwind" in
    # northwindtax — a mailbox named for the company, not somebody in it.
    own = own_name_words(email, org_name)
    if any(len(w) >= 5 and any(w in o for o in own) for w in words):
        return "the organization's own name"
    if any(word in local for word in ("former_", "shared", "noreply", "printer")):
        return "a shared or former address"
    if "@" in name:
        return "an address as the name"
    if len(whole) <= 1:
        return "a single word for a name"
    return None


def candidates(db: DbSession, org_id: int) -> list[Candidate]:
    """Visible accounts in this organization that look like things."""
    org_name = db.scalar(select(Organization.name).where(Organization.id == org_id)) or ""
    unmarked = db.scalars(
        select(UserAccount)
        .where(
            UserAccount.organization_id == org_id,
            UserAccount.hidden_at.is_(None),
            UserAccount.org_role == "agent",
            UserAccount.last_login_at.is_(None),
            UserAccount.tenant_photo_image_id.is_(None),
            UserAccount.custom_photo_image_id.is_(None),
            ~exists().where(MetricFact.subject_user_id == UserAccount.id),
            ~exists().where(Goal.subject_user_id == UserAccount.id),
        )
        .order_by(UserAccount.full_name)
    ).all()

    found: list[Candidate] = []
    for user in unmarked:
        # A title or a department is a person — unless the name says stand-in.
        if (user.job_title or user.department) and not stands_in(user.full_name):
            continue
        reason = reason_for(user.full_name, user.email, org_name)
        if reason:
            found.append(Candidate(user.id, user.full_name, user.email, reason))
    return found
