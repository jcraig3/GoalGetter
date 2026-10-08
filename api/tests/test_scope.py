"""Who can see whom, and who can do what.

A bug here is a data leak rather than a wrong number, so these tests assert
both directions every time: that the right people ARE visible, and that the
wrong ones are NOT.
"""

import pytest

from app.scope import (
    EVERYONE,
    _CAPABILITIES,
    can_see_user,
    capabilities_for,
    has_capability,
    visible_user_ids,
)


@pytest.fixture
def world(make_team, make_user):
    """Two teams, an unassigned agent, and one of each role."""
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin"),
        "manager": make_user("manager", enterprise),
        "teammate": make_user("agent", enterprise),
        "other_manager": make_user("manager", smb),
        "stranger": make_user("agent", smb),
        "unassigned": make_user("agent", None),
    }


# ── visible_user_ids ─────────────────────────────────────────────────────────


def test_admin_sees_everyone_without_building_a_list(db, world):
    """EVERYONE is None — "apply no filter" — not a list of every id. A
    5,000-person organization would otherwise build a 5,000-element IN clause
    on every request."""
    assert visible_user_ids(db, world["admin"]) is EVERYONE


def test_manager_sees_their_team(db, world):
    visible = visible_user_ids(db, world["manager"])
    assert world["teammate"].id in visible
    assert world["manager"].id in visible


def test_manager_sees_unassigned_agents(db, world):
    """Deliberate. Without it a manager could never pull a newly invited person
    onto their team — they would stay invisible until an admin placed them,
    which is the setup failure this product should surface, not hide."""
    assert world["unassigned"].id in visible_user_ids(db, world["manager"])


def test_manager_does_not_see_another_team(db, world):
    visible = visible_user_ids(db, world["manager"])
    assert world["stranger"].id not in visible
    assert world["other_manager"].id not in visible


def test_manager_with_no_team_sees_only_unassigned_people_and_themselves(db, make_user, world):
    """The `false()` branch. Written as a ternary this silently became "their
    team OR nothing", and a manager with no team would have seen every person
    in the organization."""
    homeless = make_user("manager", None)
    visible = visible_user_ids(db, homeless)
    assert homeless.id in visible
    assert world["unassigned"].id in visible
    assert world["teammate"].id not in visible
    assert world["stranger"].id not in visible


def test_agent_sees_only_themselves(db, world):
    assert visible_user_ids(db, world["teammate"]) == [world["teammate"].id]


def test_hidden_people_are_invisible_even_on_the_managers_own_team(db, make_user, world):
    from datetime import UTC, datetime

    departed = make_user("agent", world["enterprise"])
    departed.hidden_at = datetime.now(UTC)
    db.flush()
    assert departed.id not in visible_user_ids(db, world["manager"])


def test_scope_stops_at_the_organization_boundary(db, org, make_user, world):
    """A second organization's manager must not appear, even though they share
    the "no team" condition that lets managers see unassigned agents."""
    from app.models import Organization, UserAccount

    other_org = Organization(name="Other", timezone="UTC")
    db.add(other_org)
    db.flush()
    outsider = UserAccount(
        organization_id=other_org.id,
        email="outsider@other.example",
        full_name="Outsider",
        org_role="agent",
        status="active",
    )
    db.add(outsider)
    db.flush()

    assert outsider.id not in visible_user_ids(db, world["manager"])


# ── can_see_user ─────────────────────────────────────────────────────────────


def test_can_see_user_agrees_with_visible_user_ids(db, world):
    """The two must never disagree — one is used to filter lists and the other
    to guard single-record endpoints, and a gap between them is a hole."""
    for actor_name in ("admin", "manager", "teammate"):
        actor = world[actor_name]
        visible = visible_user_ids(db, actor)
        for subject_name in ("admin", "manager", "teammate", "stranger", "unassigned"):
            subject = world[subject_name]
            expected = visible is EVERYONE or subject.id in visible
            assert can_see_user(db, actor, subject.id) is expected, (
                f"{actor_name} -> {subject_name}"
            )


def test_everyone_can_see_themselves(db, world):
    for name in ("admin", "manager", "teammate", "unassigned"):
        actor = world[name]
        assert can_see_user(db, actor, actor.id)


def test_nobody_can_see_a_user_that_does_not_exist(db, world):
    assert not can_see_user(db, world["manager"], 999_999)
    # An admin's EVERYONE is "no filter", so this returns True — the endpoints
    # that use it always load the row separately and 404 on a missing one.
    assert can_see_user(db, world["admin"], 999_999)


# ── Capabilities ─────────────────────────────────────────────────────────────


def test_admin_holds_every_capability_any_role_holds(db, world):
    """An admin unable to do something a manager can would be a support
    nightmare, and the kind of gap nobody notices until it matters."""
    admin = set(capabilities_for("admin"))
    for role in _CAPABILITIES:
        assert set(capabilities_for(role)) <= admin, f"{role} holds something admin does not"


def test_only_an_admin_can_manage_roles_or_settings():
    for capability in ("users.manage_roles", "users.suspend", "org.settings.edit",
                       "integrations.manage", "teams.manage", "metrics.manage"):
        holders = {role for role in _CAPABILITIES if capability in _CAPABILITIES[role]}
        assert holders == {"admin"}, f"{capability} held by {holders}"


def test_an_agent_cannot_view_the_user_list():
    assert "users.view" not in capabilities_for("agent")


def test_capabilities_are_sorted_and_unique():
    """The client compares this list; a stable order keeps it diffable and
    keeps a React key from changing between requests."""
    for role in _CAPABILITIES:
        capabilities = capabilities_for(role)
        assert capabilities == sorted(capabilities)
        assert len(capabilities) == len(set(capabilities))


def test_an_unknown_role_holds_nothing(db, world):
    """Fail closed. A role added to the database but not to the map must deny
    everything rather than default to allowing it."""
    assert capabilities_for("superuser") == []
    world["admin"].org_role = "superuser"
    assert not has_capability(world["admin"], "users.view")


def test_has_capability_matches_capabilities_for(db, world):
    for name in ("admin", "manager", "teammate"):
        actor = world[name]
        listed = set(capabilities_for(actor.org_role))
        for capability in {c for caps in _CAPABILITIES.values() for c in caps}:
            assert has_capability(actor, capability) is (capability in listed)


# ── Regression: unplaced privileged accounts ─────────────────────────────────
#
# Found by a test asserting the exact membership of a manager's visible set.
# The docstring had always said "agents on no team"; the query said "anyone on
# no team", and an admin has no team by default.


def test_a_manager_cannot_see_an_admin_who_has_no_team(db, make_user, world):
    unplaced_admin = make_user("admin", None)
    assert unplaced_admin.id not in visible_user_ids(db, world["manager"])
    assert not can_see_user(db, world["manager"], unplaced_admin.id)


def test_a_manager_cannot_see_another_manager_who_has_no_team(db, make_user, world):
    unplaced_manager = make_user("manager", None)
    assert unplaced_manager.id not in visible_user_ids(db, world["manager"])


def test_the_unassigned_rule_admits_agents_only(db, make_user, world):
    """Both directions in one assertion: the agent IS admitted, the privileged
    accounts are NOT. Asserting only the exclusions would still pass if the
    whole branch were deleted."""
    agent = make_user("agent", None)
    visible = visible_user_ids(db, world["manager"])
    assert agent.id in visible
    assert make_user("admin", None).id not in visible
    assert make_user("manager", None).id not in visible
