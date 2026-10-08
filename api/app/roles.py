"""Custom roles: a built-in role, narrowed.

**Enforced in one place, by route.** Every endpoint already goes through
`require_role`, which now also asks: does this person have a custom role, and
does it take away the capability this request needs? The request's method and
path decide the capability, from `ROUTE_RULES` below — so a removed capability
is refused by the server, not just hidden in the interface, without 200 call
sites each learning about custom roles.

**Only what the table enforces can be removed.** `REMOVABLE` is derived from
`ROUTE_RULES`, so the role editor never offers a switch the server would not
honour.

**A custom role applies only while its base matches.** If somebody's built-in
role changes — an admin edit, SSO groups — a custom role based on the old one
simply stops applying, rather than narrowing a role it was never about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import CustomRole, UserAccount

__all__ = [
    "LABELS",
    "REMOVABLE",
    "applies",
    "capability_for",
    "effective",
    "removed_for",
]


@dataclass(frozen=True)
class Rule:
    capability: str
    #: None means every method.
    methods: frozenset[str] | None
    path: re.Pattern


WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _rule(capability: str, pattern: str, methods: frozenset[str] | None = WRITES) -> Rule:
    return Rule(capability=capability, methods=methods, path=re.compile(pattern))


#: First match wins, so the specific ones come first.
ROUTE_RULES: tuple[Rule, ...] = (
    _rule("users.reset_password", r"^/api/users/\d+/(reset-password|temporary-password)$"),
    _rule("users.suspend", r"^/api/users/\d+/(suspend|reactivate|hide|unhide)$"),
    _rule("users.invite", r"^/api/users/(invite|\d+/resend-invite)$"),
    _rule("wheel.hand_over", r"^/api/points/wheel/spins/\d+/given$"),
    _rule("recognition.send", r"^/api/recognition$", frozenset({"POST"})),
    _rule("announcements.send", r"^/api/tv-announcements(/|$)"),
    _rule("reporting.view", r"^/api/reporting(/|$)", None),
    _rule("goals.manage", r"^/api/goals(/|$)"),
    _rule("leaderboards.manage", r"^/api/leaderboards(/|$)"),
    _rule("competitions.manage", r"^/api/competitions(/|$)"),
    _rule("metrics.correct", r"^/api/metric-facts(/|$)"),
    _rule("metrics.manage", r"^/api/metrics(/|$)"),
    _rule("teams.manage", r"^/api/teams(/|$)"),
    _rule("offices.manage", r"^/api/offices(/|$)"),
    # Roles themselves are settings: otherwise somebody in a narrowed admin
    # role could edit their own role and lift the restriction.
    _rule("org.settings.edit", r"^/api/(organization|backgrounds|channels|displays|roles)(/|$)"),
    _rule(
        "integrations.manage",
        r"^/api/(admin|data-sources|integrations|announcements|connectors|audit/stream)(/|$)",
        None,
    ),
)

#: What each removable capability is called in the role editor.
LABELS: dict[str, str] = {
    "users.invite": "Invite people",
    "users.suspend": "Suspend and hide people",
    "users.reset_password": "Issue reset links and set temporary passwords",
    "teams.manage": "Create and edit teams",
    "offices.manage": "Create and edit offices",
    "org.settings.edit": "Change organization settings, roles, channels and screens",
    "integrations.manage": "Manage integrations, data sources, directory sync and sign-in",
    "metrics.manage": "Create and edit metrics",
    "metrics.correct": "Correct data",
    "goals.manage": "Set goals",
    "leaderboards.manage": "Build leaderboards",
    "competitions.manage": "Run competitions",
    "reporting.view": "See the reporting tab",
    "recognition.send": "Send recognition",
    "announcements.send": "Make and send announcements to the TVs",
    "wheel.hand_over": "Hand over prize-wheel prizes",
}

REMOVABLE: tuple[str, ...] = tuple(dict.fromkeys(rule.capability for rule in ROUTE_RULES))
assert set(REMOVABLE) == set(LABELS), "every removable capability needs a label"


def capability_for(method: str, path: str) -> str | None:
    """The capability a request needs, as far as custom roles are concerned."""
    for rule in ROUTE_RULES:
        if (rule.methods is None or method.upper() in rule.methods) and rule.path.search(path):
            return rule.capability
    return None


def applies(user: UserAccount, role: CustomRole | None) -> bool:
    return role is not None and role.base_role == user.org_role


def removed_for(user: UserAccount) -> set[str]:
    role = getattr(user, "custom_role", None)
    return set(role.removed or []) if applies(user, role) else set()


def effective(user: UserAccount, base: set[str]) -> set[str]:
    """The base role's capabilities, less what a custom role takes away."""
    return base - removed_for(user)
