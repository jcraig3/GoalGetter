"""User management endpoints.

The permission matrix, in both directions: what each role may do, and what it
must not. A gap here is a privilege escalation, not a wrong number.
"""

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Organization, Session, Team, UserAccount


@pytest.fixture
def world(make_team, make_user):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "unassigned": make_user("agent", None, name="Unassigned"),
    }


def audit_count(db) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0


# ── Listing ──────────────────────────────────────────────────────────────────


def test_admin_lists_everyone(client, db, world, sign_in):
    sign_in(world["admin"])
    names = {u["full_name"] for u in client.get("/api/users").json()}
    assert names == {"Admin", "Manager", "Teammate", "Stranger", "Unassigned"}


def test_manager_lists_their_team_and_unassigned_only(client, db, world, sign_in):
    sign_in(world["manager"])
    names = {u["full_name"] for u in client.get("/api/users").json()}
    assert names == {"Manager", "Teammate", "Unassigned"}
    assert "Stranger" not in names


def test_an_agent_cannot_list_users(client, db, world, sign_in):
    """403, not an empty list: the capability itself is absent, so the honest
    answer is "you may not do this" rather than "there is nobody"."""
    sign_in(world["teammate"])
    assert client.get("/api/users").status_code == 403


# ── Assigning teams ──────────────────────────────────────────────────────────


def test_admin_can_move_anyone(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.patch(
        f"/api/users/{world['stranger'].id}", json={"team_id": world["enterprise"].id}
    )
    assert response.status_code == 200
    assert response.json()["team_name"] == "Enterprise"


def test_manager_can_recruit_an_unassigned_agent(client, db, world, sign_in):
    """The reason managers see unassigned people at all — otherwise a newly
    invited person is invisible until an admin places them."""
    sign_in(world["manager"])
    response = client.patch(
        f"/api/users/{world['unassigned'].id}", json={"team_id": world["enterprise"].id}
    )
    assert response.status_code == 200


def test_manager_cannot_push_someone_onto_a_team_they_do_not_manage(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.patch(
        f"/api/users/{world['unassigned'].id}", json={"team_id": world["smb"].id}
    )
    assert response.status_code == 403
    assert "your own team" in response.json()["detail"]


def test_manager_acting_on_someone_outside_their_scope_gets_404(client, db, world, sign_in):
    """404 and not 403: for a user they may not see, confirming the account
    exists is itself information they are not entitled to."""
    sign_in(world["manager"])
    response = client.patch(
        f"/api/users/{world['stranger'].id}", json={"team_id": world["enterprise"].id}
    )
    assert response.status_code == 404


def test_explicit_null_unassigns_while_an_omitted_field_does_not(client, db, world, sign_in):
    """`{"team_id": null}` means "remove them"; `{}` means "leave it alone".
    Without model_fields_set the two are indistinguishable, and saving a name
    would silently clear the team."""
    sign_in(world["admin"])
    target = world["teammate"].id

    assert client.patch(f"/api/users/{target}", json={"full_name": "Renamed"}).json()["team_id"]
    assert client.patch(f"/api/users/{target}", json={"team_id": None}).json()["team_id"] is None


def test_moving_to_a_nonexistent_team_is_a_404(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.patch(
        f"/api/users/{world['teammate'].id}", json={"team_id": 999999}
    ).status_code == 404


# ── Roles ────────────────────────────────────────────────────────────────────


def test_only_an_admin_can_change_a_role(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.patch(f"/api/users/{world['teammate'].id}", json={"org_role": "manager"})
    assert response.status_code == 403
    assert "admin" in response.json()["detail"]


def test_admin_can_change_a_role(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.patch(f"/api/users/{world['teammate'].id}", json={"org_role": "manager"})
    assert response.status_code == 200
    assert response.json()["org_role"] == "manager"


def test_an_unknown_role_is_rejected(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.patch(
        f"/api/users/{world['teammate'].id}", json={"org_role": "superuser"}
    ).status_code == 400


def test_the_database_rejects_an_unknown_role_too(db, org):
    from sqlalchemy.exc import IntegrityError

    db.add(
        UserAccount(
            organization_id=org.id, email="x@acme.example", full_name="X",
            org_role="superuser", status="active",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# ── The last-admin guard ─────────────────────────────────────────────────────
#
# Without this, one click permanently locks everyone out of a self-hosted
# deployment with no support line to call.


def test_the_only_admin_cannot_be_demoted(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.patch(f"/api/users/{world['admin'].id}", json={"org_role": "agent"})
    assert response.status_code == 409
    assert "only active admin" in response.json()["detail"]


def test_the_only_admin_cannot_be_suspended_or_archived(client, db, world, make_user, sign_in):
    second = make_user("admin", name="Second Admin")
    sign_in(second)
    for action in ("suspend", "hide"):
        assert client.post(f"/api/users/{world['admin'].id}/{action}").status_code != 409

    # Now only `second` remains; a third admin signs in to try to remove them.
    third = make_user("admin", name="Third Admin")
    sign_in(third)
    client.post(f"/api/users/{second.id}/suspend")
    # `third` is now the only active admin and cannot remove themselves...
    assert client.post(f"/api/users/{third.id}/suspend").status_code == 409


def test_an_admin_cannot_suspend_themselves(client, db, world, make_user, sign_in):
    """Blocked because it is almost always a misclick, and the consequence is
    signing yourself out of an account you may be the only admin for."""
    make_user("admin")  # so the last-admin guard is not what refuses
    sign_in(world["admin"])
    response = client.post(f"/api/users/{world['admin'].id}/suspend")
    assert response.status_code == 409
    assert "your own account" in response.json()["detail"]


def test_a_second_admin_makes_demotion_possible(client, db, world, make_user, sign_in):
    make_user("admin", name="Backup")
    sign_in(world["admin"])
    assert client.patch(
        f"/api/users/{world['admin'].id}", json={"org_role": "agent"}
    ).status_code == 200


# ── Suspension ends sessions ─────────────────────────────────────────────────


def test_suspending_deletes_every_session(client, db, world, sign_in):
    """`current_user` already rejects a suspended account on its next request,
    so this is belt and braces — but it also means a reactivated account starts
    clean rather than resuming a session issued before the suspension."""
    sign_in(world["teammate"])  # gives them a session row
    sessions_before = db.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == world["teammate"].id)
    )
    assert sessions_before == 1

    sign_in(world["admin"])
    client.post(f"/api/users/{world['teammate'].id}/suspend")

    assert db.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == world["teammate"].id)
    ) == 0


def test_a_suspended_user_cannot_use_an_existing_session(client, db, world, sign_in):
    sign_in(world["teammate"])
    world["teammate"].status = "suspended"
    db.flush()
    assert client.get("/api/auth/me").status_code == 401


def test_reactivating_someone_who_never_accepted_their_invite_returns_them_to_invited(
    client, db, world, make_user, sign_in
):
    """"active" would be a lie — they still have no password."""
    invited = make_user("agent", status="invited")
    sign_in(world["admin"])
    client.post(f"/api/users/{invited.id}/suspend")
    assert client.post(f"/api/users/{invited.id}/reactivate").json()["status"] == "invited"


# ── Invitations ──────────────────────────────────────────────────────────────


def test_a_manager_can_invite_an_agent(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/users/invite",
        json={"email": "new@acme.example", "full_name": "New", "org_role": "agent"},
    )
    assert response.status_code == 201
    assert response.json()["invite_link"]


def test_a_manager_cannot_mint_an_admin(client, db, world, sign_in):
    sign_in(world["manager"])
    for role in ("admin", "manager"):
        response = client.post(
            "/api/users/invite",
            json={"email": f"{role}@acme.example", "full_name": "X", "org_role": role},
        )
        assert response.status_code == 403


def test_inviting_an_existing_address_is_a_conflict(client, db, world, sign_in):
    """409 rather than silently reissuing — an admin who typed an address that
    already exists needs to know, not to accidentally reset someone."""
    sign_in(world["admin"])
    response = client.post(
        "/api/users/invite",
        json={"email": world["teammate"].email, "full_name": "Dup", "org_role": "agent"},
    )
    assert response.status_code == 409


def test_a_manager_cannot_resend_an_invite_outside_their_scope(client, db, world, make_user, sign_in):
    """The hole found by applying the scope rule to every handler rather than
    only the one being written: that link sets a password."""
    from app.models import Team

    theirs = db.get(Team, world["smb"].id)
    invited = make_user("admin", theirs, status="invited")
    sign_in(world["manager"])
    assert client.post(f"/api/users/{invited.id}/resend-invite").status_code == 404


def test_resending_for_an_activated_account_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post(f"/api/users/{world['teammate'].id}/resend-invite")
    assert response.status_code == 409


# ── Audit ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("suspend", "user.suspended"),
        ("reactivate", "user.reactivated"),
        ("hide", "user.hidden"),
    ],
)
def test_privileged_actions_are_recorded(client, db, world, sign_in, action, expected):
    sign_in(world["admin"])
    client.post(f"/api/users/{world['teammate'].id}/{action}")
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == expected
    assert latest.actor_email == world["admin"].email
    assert latest.target_email == world["teammate"].email


def test_a_role_change_records_both_sides(client, db, world, sign_in):
    sign_in(world["admin"])
    client.patch(f"/api/users/{world['teammate'].id}", json={"org_role": "manager"})
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.details == {"org_role": {"from": "agent", "to": "manager"}}


def test_a_no_op_change_records_nothing(client, db, world, sign_in):
    """Setting a field to the value it already has is not a change. Recording
    it would bury the entries that matter."""
    sign_in(world["admin"])
    before = audit_count(db)
    client.patch(f"/api/users/{world['teammate'].id}", json={"org_role": "agent"})
    client.patch(f"/api/users/{world['teammate'].id}", json={"team_id": world["enterprise"].id})
    assert audit_count(db) == before


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("patch", "/api/users/{stranger}", {"team_id": "{enterprise}"}),  # out of scope
        ("patch", "/api/users/{teammate}", {"org_role": "admin"}),  # manager, forbidden
        ("post", "/api/users/{teammate}/suspend", None),  # manager, forbidden
    ],
)
def test_a_refused_action_writes_no_audit_row(client, db, world, sign_in, method, path, body):
    """The direction that actually matters. An audit row for something that
    never happened is worse than a missing one — it is a false record."""
    sign_in(world["manager"])
    before = audit_count(db)

    resolved = path.format(stranger=world["stranger"].id, teammate=world["teammate"].id)
    if body:
        body = {k: (world["enterprise"].id if v == "{enterprise}" else v) for k, v in body.items()}

    response = getattr(client, method)(resolved, json=body) if body else getattr(client, method)(resolved)
    assert response.status_code >= 400
    assert audit_count(db) == before


def test_a_refused_action_changes_nothing(client, db, world, sign_in):
    sign_in(world["manager"])
    client.patch(f"/api/users/{world['stranger'].id}", json={"team_id": world["enterprise"].id})
    db.refresh(world["stranger"])
    assert world["stranger"].team_id == world["smb"].id


def test_the_audit_log_is_admin_only(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.get("/api/audit").status_code == 403
    sign_in(world["admin"])
    assert client.get("/api/audit").status_code == 200


def test_the_audit_log_is_newest_first(client, db, world, sign_in):
    sign_in(world["admin"])
    client.post(f"/api/users/{world['teammate'].id}/suspend")
    client.post(f"/api/users/{world['teammate'].id}/reactivate")
    actions = [row["action"] for row in client.get("/api/audit").json()]
    assert actions[:2] == ["user.reactivated", "user.suspended"]


def test_the_audit_limit_is_capped(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.get("/api/audit?limit=100000").status_code == 422
    assert client.get("/api/audit?limit=0").status_code == 422


def test_audit_rows_do_not_cross_organizations(client, db, org, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        AuditLog(
            organization_id=other.id, action="user.suspended",
            actor_email="them@other.example", occurred_at=func.now(),
        )
    )
    db.flush()

    sign_in(world["admin"])
    assert all(r["actor_email"] != "them@other.example" for r in client.get("/api/audit").json())


def test_a_manager_cannot_reissue_an_unplaced_admins_invite(client, db, world, make_user, sign_in):
    """The escalation this closes.

    An admin has no team by default. While the "unassigned" rule admitted
    anyone rather than only agents, a manager could see an admin account that
    had not yet accepted its invitation, POST resend-invite, receive the link,
    and set that admin's password.
    """
    pending_admin = make_user("admin", None, status="invited")
    sign_in(world["manager"])

    assert client.post(f"/api/users/{pending_admin.id}/resend-invite").status_code == 404
    assert client.patch(
        f"/api/users/{pending_admin.id}", json={"team_id": world["enterprise"].id}
    ).status_code == 404
    assert pending_admin.full_name not in [
        u["full_name"] for u in client.get("/api/users").json()
    ]


# ── Restoring, and doing it to many at once ──────────────────────────────────


def test_hidden_people_are_absent_until_asked_for(client, db, world, sign_in, make_user):
    """Otherwise "who works here" stops being a question the list answers."""
    sign_in(world["admin"])
    gone = make_user("agent", name="Gone Person")
    db.commit()
    client.post(f"/api/users/{gone.id}/hide")

    listed = client.get("/api/users").json()
    assert not any(u["id"] == gone.id for u in listed)

    with_archived = client.get("/api/users?roster=all").json()
    row = next(u for u in with_archived if u["id"] == gone.id)
    assert row["hidden"] is True


def test_unhiding_brings_somebody_back_suspended(client, db, world, sign_in, make_user):
    """**Not active.** Archiving ended their sessions and took away access;
    restoring is a decision to put them back in the list, which is not the same
    as a decision to let them straight back in. Two steps, neither by accident."""
    sign_in(world["admin"])
    gone = make_user("agent")
    db.commit()
    client.post(f"/api/users/{gone.id}/hide")

    body = client.post(f"/api/users/{gone.id}/unhide").json()

    assert body["hidden"] is False
    assert body["status"] == "suspended"


def test_unhiding_somebody_who_was_never_hidden_is_harmless(client, db, world, sign_in, make_user):
    """A second press, or two admins at once. Failing would be reporting a
    problem that does not exist."""
    sign_in(world["admin"])
    here = make_user("agent")
    db.commit()

    assert client.post(f"/api/users/{here.id}/unhide").status_code == 200


def test_a_bulk_hide_changes_everybody_selected(client, db, world, sign_in, make_user):
    sign_in(world["admin"])
    people = [make_user("agent") for _ in range(3)]
    db.commit()

    body = client.post(
        "/api/users/bulk",
        json={"ids": [p.id for p in people], "action": "hide"},
    ).json()

    assert body["changed"] == 3
    assert body["skipped"] == []
    # Gone from the roster, and findable again only by asking for the archived.
    listed = {u["id"] for u in client.get("/api/users").json()}
    assert listed.isdisjoint({p.id for p in people})
    with_archived = {u["id"] for u in client.get("/api/users?roster=all").json()}
    assert {p.id for p in people} <= with_archived


def test_a_bulk_hide_skips_the_protected_and_keeps_going(client, db, world, sign_in, make_user):
    """**Partial success is the normal case, not an edge one.** A selection of two
    hundred will contain the actor themselves. Refusing the whole batch would make
    the feature useless for the other hundred and ninety-nine; reporting "done"
    would hide that somebody was left behind."""
    sign_in(world["admin"])
    other = make_user("agent")
    db.commit()

    body = client.post(
        "/api/users/bulk",
        json={"ids": [world["admin"].id, other.id], "action": "hide"},
    ).json()

    assert body["changed"] == 1
    assert len(body["skipped"]) == 1
    # Named, and with the reason, because a count alone is not something anybody
    # can act on.
    assert "your own account" in body["skipped"][0]


def test_a_bulk_unhide_puts_them_all_back(client, db, world, sign_in, make_user):
    sign_in(world["admin"])
    people = [make_user("agent") for _ in range(2)]
    db.commit()
    client.post(
        "/api/users/bulk", json={"ids": [p.id for p in people], "action": "hide"}
    )

    body = client.post(
        "/api/users/bulk",
        json={"ids": [p.id for p in people], "action": "unhide"},
    ).json()

    assert body["changed"] == 2
    listed = {u["id"] for u in client.get("/api/users").json()}
    assert {p.id for p in people} <= listed


def test_a_bulk_action_ignores_ids_from_another_organization(client, db, world, sign_in, make_user):
    """The scoping rule this whole router is built on, asserted where it would be
    easiest to forget it — a new endpoint taking a list of ids from a client."""
    sign_in(world["admin"])
    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = UserAccount(
        organization_id=other.id, email="them@other.com", full_name="Them",
        org_role="agent", status="active",
    )
    db.add(theirs)
    db.commit()

    body = client.post(
        "/api/users/bulk", json={"ids": [theirs.id], "action": "hide"}
    ).json()

    assert body["changed"] == 0
    db.expire_all()
    assert db.get(UserAccount, theirs.id).hidden_at is None


def test_an_agent_cannot_bulk_archive_anybody(client, db, make_user, sign_in):
    sign_in(make_user("agent"))
    db.commit()

    response = client.post("/api/users/bulk", json={"ids": [1], "action": "hide"})

    assert response.status_code == 403


# ── Bulk team and role ───────────────────────────────────────────────────────


def test_a_bulk_team_assignment_moves_everybody(client, db, world, sign_in, make_user, make_team):
    sign_in(world["admin"])
    target = make_team("Phoenix Sales")
    people = [make_user("agent") for _ in range(3)]
    db.commit()

    body = client.post(
        "/api/users/bulk",
        json={"ids": [p.id for p in people], "action": "assign_team", "team_id": target.id},
    ).json()

    assert body["changed"] == 3
    db.expire_all()
    assert all(db.get(UserAccount, p.id).team_id == target.id for p in people)


def test_a_bulk_team_assignment_can_unassign(client, db, world, sign_in, make_user, make_team):
    """Null is a real thing to want in bulk — a team being dissolved is exactly
    when somebody reaches for this."""
    sign_in(world["admin"])
    team = make_team("Going Away")
    person = make_user("agent", team=team)
    db.commit()

    body = client.post(
        "/api/users/bulk",
        json={"ids": [person.id], "action": "assign_team", "team_id": None},
    ).json()

    assert body["changed"] == 1
    db.expire_all()
    assert db.get(UserAccount, person.id).team_id is None


def test_a_bulk_team_assignment_refuses_a_team_that_is_not_yours(
    client, db, world, sign_in, make_user
):
    """Wrong about the *request*, not about a person — so a 404 rather than two
    hundred identical skips."""
    sign_in(world["admin"])
    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = Team(organization_id=other.id, name="Theirs")
    db.add(theirs)
    db.commit()

    response = client.post(
        "/api/users/bulk",
        json={"ids": [world["teammate"].id], "action": "assign_team", "team_id": theirs.id},
    )

    assert response.status_code == 404


def test_a_bulk_role_change_works_and_skips_your_own(client, db, world, sign_in, make_user):
    """**Your own role is never in a bulk change.** Demoting yourself by way of a
    select-all is a lockout nobody intended, and the single-user path is where a
    deliberate one belongs."""
    sign_in(world["admin"])
    other = make_user("agent")
    db.commit()

    body = client.post(
        "/api/users/bulk",
        json={"ids": [world["admin"].id, other.id], "action": "set_role", "role": "manager"},
    ).json()

    assert body["changed"] == 1
    assert any("your own role" in s for s in body["skipped"])
    db.expire_all()
    assert db.get(UserAccount, other.id).org_role == "manager"
    assert db.get(UserAccount, world["admin"].id).org_role == "admin"


def test_a_bulk_role_change_refuses_an_unknown_role(client, db, world, sign_in):
    sign_in(world["admin"])

    response = client.post(
        "/api/users/bulk",
        json={"ids": [world["teammate"].id], "action": "set_role", "role": "wizard"},
    )

    assert response.status_code == 400


def test_a_bulk_action_leaves_hidden_people_out(client, db, world, sign_in, make_user, make_team):
    """They are finished business. Re-teaming somebody who left is a change
    nobody asked for, and it would quietly resurrect them in reports."""
    sign_in(world["admin"])
    team = make_team("Somewhere")
    gone = make_user("agent", name="Gone")
    db.commit()
    client.post(f"/api/users/{gone.id}/hide")

    body = client.post(
        "/api/users/bulk",
        json={"ids": [gone.id], "action": "assign_team", "team_id": team.id},
    ).json()

    assert body["changed"] == 0
    assert any("hidden" in s for s in body["skipped"])


def test_a_manager_cannot_bulk_anything(client, db, world, sign_in):
    """A manager may re-team one person they can see. Select-all over a filtered
    list is a different act with different scope rules — so rather than
    approximate them, it is not offered."""
    sign_in(world["manager"])

    response = client.post(
        "/api/users/bulk",
        json={"ids": [world["teammate"].id], "action": "assign_team", "team_id": None},
    )

    assert response.status_code == 403


# ── One person (P4-16) ───────────────────────────────────────────────────────


def test_one_person_is_read_on_their_own(client, db, make_user, sign_in):
    from datetime import UTC, datetime

    sign_in(make_user("admin"))
    hidden = make_user("agent", name="Hidden Person")
    hidden.hidden_at = datetime.now(UTC)
    db.commit()
    body = client.get(f"/api/users/{hidden.id}").json()
    assert body["full_name"] == "Hidden Person"
    assert body["hidden"] is True


def test_one_person_outside_a_managers_scope_is_not_found(client, make_team, make_user, sign_in):
    mine, theirs = make_team("Mine"), make_team("Theirs")
    sign_in(make_user("manager", mine))
    stranger = make_user("agent", theirs)
    assert client.get(f"/api/users/{stranger.id}").status_code == 404


def test_an_agent_cannot_read_people(client, make_user, sign_in):
    sign_in(make_user("agent"))
    other = make_user("agent")
    assert client.get(f"/api/users/{other.id}").status_code == 403
