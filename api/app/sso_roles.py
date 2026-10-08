"""Roles from groups: signing in with SSO sets a person's role from their groups.

"Everybody in *Sales Managers* is a manager here." Off unless an admin switches
it on, and then applied on every sign-in, so moving somebody between groups in
the identity provider moves their role here the next time they sign in.

**Where the groups come from.** The sign-in token's own `groups` (ids) and
`roles` (app role values) claims, when the identity provider sends them — and
the group names directory sync already stores for that person, when it runs. So
an Entra tenant with directory sync on needs no token configuration at all: its
group names are already here.

**The highest role any group gives.** Somebody in both *Sales* (agent) and
*Sales Managers* (manager) is a manager — the rule is "at least", which is what
membership of a managers' group means.

**Nothing matching leaves the role alone.** A rule set that forgot a group must
not quietly demote everybody in it to agent; an admin who wants a default can
write a rule for the group everyone is in.

**Never the last admin.** A group change that would leave the organization with
nobody able to administer it is skipped and logged, rather than locking
everybody out at the next sign-in.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.directory.rules import normalise
from app.models import DirectoryPerson, SsoConfig, UserAccount
from app.models.user import ORG_ROLES

logger = logging.getLogger(__name__)

__all__ = ["RANK", "apply", "check_rules", "decide", "groups_of"]

#: Higher wins.
RANK = {"agent": 0, "manager": 1, "admin": 2}

MAX_RULES = 50


def check_rules(rules: list[dict]) -> list[dict]:
    """Rules as stored, or ValueError saying what is wrong in words."""
    if len(rules) > MAX_RULES:
        raise ValueError(f"At most {MAX_RULES} group rules.")
    out: list[dict] = []
    seen: set[str] = set()
    for rule in rules:
        group = str(rule.get("group") or "").strip()[:200]
        role = str(rule.get("role") or "")
        if not group:
            raise ValueError("Each rule needs a group.")
        if role not in ORG_ROLES:
            raise ValueError(f"'{role}' is not a role.")
        key = normalise(group)
        if key in seen:
            raise ValueError(f"'{group}' has two rules. Keep one.")
        seen.add(key)
        out.append({"group": group, "role": role})
    return out


def groups_of(db: DbSession, org_id: int, claims: dict, email: str) -> set[str]:
    """Every group this person is in that we can see, normalised."""
    found: set[str] = set()
    for key in ("groups", "roles"):
        value = claims.get(key)
        if isinstance(value, list):
            found |= {normalise(str(v)) for v in value if v}
    # The directory's view, by the object id Entra puts in `oid`, or by email.
    oid = claims.get("oid")
    conditions = []
    if oid:
        conditions.append(DirectoryPerson.external_id == str(oid))
    if email:
        conditions.append(func.lower(DirectoryPerson.email) == email.lower())
    if conditions:
        row = db.scalar(
            select(DirectoryPerson).where(
                DirectoryPerson.organization_id == org_id,
                DirectoryPerson.archived_at.is_(None),
                or_(*conditions),
            )
        )
        if row is not None:
            found |= {normalise(str(g)) for g in (row.groups or []) if isinstance(g, str)}
    return found


def decide(rules: list[dict], groups: set[str]) -> str | None:
    """The role the groups give, or None when no rule matches."""
    matched = [r["role"] for r in rules if normalise(r["group"]) in groups]
    return max(matched, key=lambda role: RANK.get(role, -1)) if matched else None


def _other_admins(db: DbSession, user: UserAccount) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(UserAccount)
            .where(
                UserAccount.organization_id == user.organization_id,
                UserAccount.org_role == "admin",
                UserAccount.status == "active",
                UserAccount.id != user.id,
            )
        )
        or 0
    )


def apply(db: DbSession, config: SsoConfig, user: UserAccount, claims: dict, email: str) -> str | None:
    """Set the role the groups say, if they say one. Returns the new role when
    it changed."""
    if not config.role_sync or not config.role_rules:
        return None
    wanted = decide(config.role_rules, groups_of(db, user.organization_id, claims, email))
    if wanted is None or wanted == user.org_role:
        return None
    if user.org_role == "admin" and _other_admins(db, user) == 0:
        logger.warning(
            "sso roles: kept %s as admin — the groups say %s, and they are the last admin",
            user.email, wanted,
        )
        return None
    before = user.org_role
    user.org_role = wanted
    audit.record(
        db, actor=user, action="user.role_changed", target=user,
        role=audit.changed(before, wanted), source="sso groups",
    )
    return wanted
