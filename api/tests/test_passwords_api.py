"""Changing and resetting passwords."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import tokens
from app.models import AuditLog, Session, UserToken
from app.rate_limit import MAX_FAILURES_PER_EMAIL
from app.security import hash_password, verify_password

OLD = "the old password here"
NEW = "a brand new password"


@pytest.fixture
def person(db, make_user):
    user = make_user("agent", name="Person")
    user.password_hash = hash_password(OLD)
    db.flush()
    return user


@pytest.fixture
def admin(db, make_user):
    user = make_user("admin", name="Admin")
    user.password_hash = hash_password(OLD)
    db.flush()
    return user


def session_count(db, user_id) -> int:
    return db.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == user_id)
    ) or 0


# ── Changing your own password ───────────────────────────────────────────────


def test_changing_with_the_correct_current_password(client, db, person, sign_in):
    sign_in(person)
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": OLD, "new_password": NEW},
    )
    assert response.status_code == 204
    db.refresh(person)
    assert verify_password(NEW, person.password_hash)


def test_the_old_password_stops_working(client, db, person, sign_in):
    sign_in(person)
    client.post("/api/auth/change-password", json={"current_password": OLD, "new_password": NEW})
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": OLD}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": NEW}
    ).status_code == 200


def test_a_wrong_current_password_is_refused(client, db, person, sign_in):
    sign_in(person)
    response = client.post(
        "/api/auth/change-password",
        json={"current_password": "not it", "new_password": NEW},
    )
    assert response.status_code == 400
    db.refresh(person)
    assert verify_password(OLD, person.password_hash)


def test_the_new_password_must_differ(client, db, person, sign_in):
    sign_in(person)
    assert client.post(
        "/api/auth/change-password", json={"current_password": OLD, "new_password": OLD}
    ).status_code == 400


def test_a_short_new_password_is_refused(client, db, person, sign_in):
    sign_in(person)
    assert client.post(
        "/api/auth/change-password", json={"current_password": OLD, "new_password": "short"}
    ).status_code == 422


def test_changing_keeps_your_own_session_but_ends_the_others(client, db, person, sign_in):
    """A password change is the standard response to "someone else may have my
    password". Other sessions surviving would defeat exactly that."""
    from app.models import Session as SessionRow

    # A second session, as if signed in on another device.
    db.add(
        SessionRow(
            user_id=person.id,
            token_hash="other-device",
            created_at=datetime.now(UTC),
            last_used_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    db.flush()

    sign_in(person)
    assert session_count(db, person.id) == 2

    client.post("/api/auth/change-password", json={"current_password": OLD, "new_password": NEW})

    assert session_count(db, person.id) == 1
    # And the caller is still signed in — no surprise logout mid-task.
    assert client.get("/api/auth/me").status_code == 200


def test_guessing_the_current_password_is_rate_limited(client, db, person, sign_in):
    """The check is a guessing oracle against a session left open on a shared
    machine, so it shares sign-in's counter."""
    sign_in(person)
    for _ in range(MAX_FAILURES_PER_EMAIL):
        client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": NEW},
        )
    response = client.post(
        "/api/auth/change-password", json={"current_password": OLD, "new_password": NEW}
    )
    assert response.status_code == 429


def test_a_successful_change_clears_the_failure_counter(client, db, person, sign_in):
    sign_in(person)
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        client.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": NEW},
        )
    assert client.post(
        "/api/auth/change-password", json={"current_password": OLD, "new_password": NEW}
    ).status_code == 204
    # Sign-in is not locked out afterwards.
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": NEW}
    ).status_code == 200


def test_changing_requires_a_session(client, person):
    assert client.post(
        "/api/auth/change-password", json={"current_password": OLD, "new_password": NEW}
    ).status_code == 401


def test_a_change_is_audited_without_recording_any_password(client, db, person, sign_in):
    sign_in(person)
    client.post("/api/auth/change-password", json={"current_password": OLD, "new_password": NEW})
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == "password.changed"
    assert latest.target_email == person.email
    # Nothing password-shaped anywhere in the row.
    assert NEW not in str(latest.details or "")
    assert OLD not in str(latest.details or "")


# ── Admin-issued reset links ─────────────────────────────────────────────────


def test_an_admin_can_issue_a_reset_link(client, db, admin, person, sign_in):
    sign_in(admin)
    response = client.post(f"/api/users/{person.id}/reset-password")
    assert response.status_code == 200
    assert response.json()["reset_link"].endswith(tuple("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"))
    assert "/reset-password?token=" in response.json()["reset_link"]


def test_issuing_a_link_invalidates_the_previous_one(client, db, admin, person, sign_in):
    """Otherwise an admin who issued two links would leave both working, and
    revoking one would not revoke the other."""
    sign_in(admin)
    first = client.post(f"/api/users/{person.id}/reset-password").json()["reset_link"]
    client.post(f"/api/users/{person.id}/reset-password")

    token = first.split("token=")[1]
    assert client.post(
        "/api/auth/reset-password", json={"token": token, "password": NEW}
    ).status_code == 400


def test_a_manager_cannot_issue_a_reset_link(client, db, make_user, make_team, person, sign_in):
    """Narrower than invitations on purpose: inviting creates an account nobody
    was using, while resetting takes over one somebody is."""
    manager = make_user("manager", make_team("Enterprise"))
    sign_in(manager)
    assert client.post(f"/api/users/{person.id}/reset-password").status_code == 403


def test_an_agent_cannot_issue_a_reset_link(client, db, person, make_user, sign_in):
    sign_in(make_user("agent"))
    assert client.post(f"/api/users/{person.id}/reset-password").status_code == 403


def test_resetting_an_unactivated_account_points_at_the_invitation_instead(
    client, db, admin, make_user, sign_in
):
    invited = make_user("agent", status="invited")
    sign_in(admin)
    response = client.post(f"/api/users/{invited.id}/reset-password")
    assert response.status_code == 409
    assert "invitation" in response.json()["detail"]


def test_an_unknown_or_hidden_user_is_a_404(client, db, admin, person, sign_in):
    sign_in(admin)
    assert client.post("/api/users/999999/reset-password").status_code == 404
    person.hidden_at = datetime.now(UTC)
    db.flush()
    assert client.post(f"/api/users/{person.id}/reset-password").status_code == 404


def test_another_organizations_user_is_a_404(client, db, admin, sign_in):
    from app.models import Organization, UserAccount

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = UserAccount(
        organization_id=other.id, email="them@other.example", full_name="Them",
        org_role="agent", status="active", password_hash=hash_password(OLD),
    )
    db.add(theirs)
    db.flush()

    sign_in(admin)
    assert client.post(f"/api/users/{theirs.id}/reset-password").status_code == 404


# ── Consuming a reset link ───────────────────────────────────────────────────


@pytest.fixture
def reset_token(db, person):
    raw = tokens.issue(db, person.id, "password_reset")
    db.flush()
    return raw


def test_resetting_sets_the_new_password(client, db, person, reset_token):
    assert client.post(
        "/api/auth/reset-password", json={"token": reset_token, "password": NEW}
    ).status_code == 204
    db.refresh(person)
    assert verify_password(NEW, person.password_hash)


def test_resetting_does_not_sign_them_in(client, db, person, reset_token):
    """Unlike accepting an invitation. A reset answers a possible compromise,
    and the link may have been read by someone other than its owner — signing
    in with the new password proves you are the one who chose it."""
    client.post("/api/auth/reset-password", json={"token": reset_token, "password": NEW})
    assert client.get("/api/auth/me").status_code == 401


def test_resetting_ends_every_existing_session(client, db, person, reset_token, sign_in):
    """Including any an attacker holds — which is the entire point."""
    sign_in(person)
    assert session_count(db, person.id) == 1
    client.post("/api/auth/reset-password", json={"token": reset_token, "password": NEW})
    assert session_count(db, person.id) == 0


def test_a_reset_link_works_only_once(client, db, person, reset_token):
    client.post("/api/auth/reset-password", json={"token": reset_token, "password": NEW})
    assert client.post(
        "/api/auth/reset-password", json={"token": reset_token, "password": "another password"}
    ).status_code == 400


def test_an_expired_reset_link_is_refused(client, db, person, reset_token):
    row = db.scalar(select(UserToken).where(UserToken.user_id == person.id))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert client.post(
        "/api/auth/reset-password", json={"token": reset_token, "password": NEW}
    ).status_code == 400


def test_an_invite_token_cannot_be_used_to_reset(client, db, person):
    """Purposes are not interchangeable. An invite link lives for 7 days and a
    reset for 2 hours, so accepting either for either would silently give the
    long-lived token the short-lived one's power."""
    raw = tokens.issue(db, person.id, "invite")
    db.flush()
    assert client.post(
        "/api/auth/reset-password", json={"token": raw, "password": NEW}
    ).status_code == 400


def test_a_reset_token_cannot_be_used_to_accept_an_invite(client, db, person, reset_token):
    assert client.post(
        "/api/auth/accept-invite", json={"token": reset_token, "password": NEW}
    ).status_code == 400


def test_resetting_a_suspended_account_is_refused(client, db, person, reset_token):
    person.status = "suspended"
    db.flush()
    assert client.post(
        "/api/auth/reset-password", json={"token": reset_token, "password": NEW}
    ).status_code == 400


def test_every_reset_failure_gives_the_same_message(client, db, person, reset_token):
    unknown = client.post(
        "/api/auth/reset-password", json={"token": "made-up", "password": NEW}
    )
    person.status = "suspended"
    db.flush()
    suspended = client.post(
        "/api/auth/reset-password", json={"token": reset_token, "password": NEW}
    )
    assert unknown.json()["detail"] == suspended.json()["detail"]


def test_a_short_reset_password_is_refused(client, db, person, reset_token):
    assert client.post(
        "/api/auth/reset-password", json={"token": reset_token, "password": "short"}
    ).status_code == 422


def test_resetting_clears_a_lockout(client, db, person, reset_token):
    """Someone locked out by an attacker's guessing must be able to use their
    new password immediately, not wait for the window to expire."""
    for _ in range(MAX_FAILURES_PER_EMAIL):
        client.post("/api/auth/login", json={"email": person.email, "password": "wrong"})
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": OLD}
    ).status_code == 429

    client.post("/api/auth/reset-password", json={"token": reset_token, "password": NEW})
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": NEW}
    ).status_code == 200


def test_both_halves_of_a_reset_are_audited(client, db, admin, person, sign_in):
    sign_in(admin)
    link = client.post(f"/api/users/{person.id}/reset-password").json()["reset_link"]
    issued = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert issued.action == "password.reset_issued"
    assert issued.actor_email == admin.email

    client.post(
        "/api/auth/reset-password",
        json={"token": link.split("token=")[1], "password": NEW},
    )
    completed = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert completed.action == "password.reset_completed"


def test_self_service_never_hands_back_the_link(client, db, person):
    """Why there was once no self-service at all: with no mail server the link
    could only come back in the response, and anybody could request one for the
    admin and be handed it. Self-service exists now (Phase 14) only by email —
    with or without a mail server, the response never carries a token."""
    reply = client.post("/api/auth/forgot-password", json={"email": person.email})
    assert reply.status_code == 202
    assert "token" not in reply.text
    assert "reset-password" not in reply.text


def test_an_unknown_token_purpose_fails_at_the_call_site(db, person):
    """The bug that produced this test: `tokens.issue(db, id, "reset")` — a
    purpose the CHECK constraint does not allow. It surfaced as a
    CheckViolation from deep inside a commit, naming neither the caller nor the
    valid values. Now it raises immediately and says what is allowed."""
    with pytest.raises(ValueError, match="Unknown token purpose"):
        tokens.issue(db, person.id, "reset")


def test_the_two_purposes_have_different_lifetimes(db, person):
    """An invitation is handed over deliberately and may sit over a weekend; a
    reset answers a possible compromise and should not outlive the incident."""
    assert tokens.TTL["invite"] > tokens.TTL["password_reset"]


def test_a_reset_link_can_be_checked_without_spending_it(client, db, make_user):
    """QA-29: the page now asks when it opens, rather than after somebody has
    typed a new password twice into a dead link."""
    from app import tokens

    user = make_user("agent")
    raw = tokens.issue(db, user.id, "password_reset")
    db.commit()

    assert client.post("/api/auth/reset-password/check", json={"token": raw}).status_code == 204
    # Still usable: checking spent nothing.
    assert client.post("/api/auth/reset-password/check", json={"token": raw}).status_code == 204
    assert client.post("/api/auth/reset-password/check", json={"token": "nope"}).status_code == 400
