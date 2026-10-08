"""Who may use a password, and setting somebody up with one (Phase 11).

"Require single sign-on" binds people in the directory and never an admin;
everybody else — a contractor, an agency's closer — signs in with a password.
An admin can set that password by hand, and the person replaces it the moment
they sign in.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app import tokens
from app.models import AuditLog, DirectoryPerson, OauthClient, Session, SsoConfig, UserToken
from app.security import hash_password, verify_password

PASSWORD = "correct horse battery staple"
TEMPORARY = "a temporary one for now"
OWN = "my very own passphrase"


@pytest.fixture
def person(db, make_user):
    user = make_user("agent", name="Person")
    user.password_hash = hash_password(PASSWORD)
    db.flush()
    return user


@pytest.fixture
def admin(make_user):
    return make_user("admin", name="Admin")


@pytest.fixture
def sso_required(db, org):
    db.add(OauthClient(
        organization_id=org.id, provider="oidc", client_id="client",
        client_secret_encrypted="x", issuer="https://login.example/tenant",
    ))
    config = SsoConfig(
        organization_id=org.id, enabled=True, require_sso=True,
        provider="oidc", button_label="Sign in with Microsoft",
    )
    db.add(config)
    db.flush()
    return config


def in_directory(db, org, user, *, archived=False):
    db.add(DirectoryPerson(
        organization_id=org.id, provider="microsoft", external_id=f"x-{user.id}",
        email=user.email, status="approved", user_account_id=user.id,
        archived_at=datetime.now(UTC) if archived else None,
    ))
    db.flush()


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ── 11.1 Who must use SSO ────────────────────────────────────────────────────


def test_an_admin_in_the_directory_keeps_their_password(db, org, client, person, sso_required):
    """The break-glass path, whichever list they are on."""
    person.org_role = "admin"
    in_directory(db, org, person)
    assert login(client, person.email, PASSWORD).status_code == 200


def test_somebody_who_signed_in_with_sso_before_must_again(db, client, person, sso_required):
    """Signing in with the work account proves they have one."""
    person.external_subject_id = "sub-123"
    db.flush()
    assert login(client, person.email, PASSWORD).status_code == 401


def test_somebody_gone_from_the_directory_may_use_a_password(db, org, client, person, sso_required):
    """Whoever kept them on did so on purpose, and they need a way in."""
    in_directory(db, org, person, archived=True)
    assert login(client, person.email, PASSWORD).status_code == 200


def test_nobody_is_bound_while_sso_is_only_offered(db, org, client, person, sso_required):
    sso_required.require_sso = False
    in_directory(db, org, person)
    assert login(client, person.email, PASSWORD).status_code == 200


def test_the_people_list_says_who_must_use_sso(db, org, client, sign_in, admin, person, make_user, sso_required):
    outsider = make_user("agent", name="Outsider")
    in_directory(db, org, person)
    sign_in(admin)
    rows = {r["id"]: r for r in client.get("/api/users").json()}
    assert rows[person.id]["must_use_sso"] is True
    assert rows[outsider.id]["must_use_sso"] is False
    assert rows[admin.id]["must_use_sso"] is False


# ── 11.3 No reset link that cannot work ──────────────────────────────────────


def test_no_reset_link_for_somebody_who_must_use_sso(db, org, client, sign_in, admin, person, sso_required):
    in_directory(db, org, person)
    sign_in(admin)
    response = client.post(f"/api/users/{person.id}/reset-password")
    assert response.status_code == 409
    assert "work account" in response.json()["detail"]
    assert db.scalar(select(func.count()).select_from(UserToken).where(
        UserToken.user_id == person.id)) == 0


# ── 11.2 Temporary passwords ─────────────────────────────────────────────────


def test_an_admin_sets_a_temporary_password(db, client, sign_in, admin, person):
    sign_in(person)  # a session that must end
    tokens.issue(db, person.id, "password_reset")
    sign_in(admin)

    response = client.post(
        f"/api/users/{person.id}/temporary-password", json={"password": TEMPORARY}
    )

    assert response.status_code == 204
    db.refresh(person)
    assert verify_password(TEMPORARY, person.password_hash)
    assert person.must_change_password is True
    assert db.scalar(select(func.count()).select_from(Session).where(
        Session.user_id == person.id)) == 0
    # A reset link would be a second way in, set by nobody now looking at it.
    assert db.scalar(select(func.count()).select_from(UserToken).where(
        UserToken.user_id == person.id)) == 0
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "password.temporary_set"))
    assert entry.target_user_id == person.id
    # Never the password, in any form.
    assert TEMPORARY not in str(entry.details)


def test_a_manager_cannot_set_one(client, sign_in, make_user, person):
    sign_in(make_user("manager"))
    assert client.post(
        f"/api/users/{person.id}/temporary-password", json={"password": TEMPORARY}
    ).status_code == 403


def test_not_for_somebody_who_must_use_sso(db, org, client, sign_in, admin, person, sso_required):
    in_directory(db, org, person)
    sign_in(admin)
    assert client.post(
        f"/api/users/{person.id}/temporary-password", json={"password": TEMPORARY}
    ).status_code == 409


def test_it_activates_an_outstanding_invitation(db, client, sign_in, admin, make_user):
    invited = make_user("agent", name="Invited", status="invited")
    tokens.issue(db, invited.id, "invite")
    sign_in(admin)
    client.post(f"/api/users/{invited.id}/temporary-password", json={"password": TEMPORARY})
    db.refresh(invited)
    assert invited.status == "active"
    assert db.scalar(select(func.count()).select_from(UserToken).where(
        UserToken.user_id == invited.id)) == 0


def test_signing_in_with_it_opens_one_door(db, client, sign_in, admin, person):
    sign_in(admin)
    client.post(f"/api/users/{person.id}/temporary-password", json={"password": TEMPORARY})
    client.post("/api/auth/logout")

    signed_in = login(client, person.email, TEMPORARY)
    assert signed_in.status_code == 200
    assert signed_in.json()["must_change_password"] is True

    # Who they are, yes; anything else, no — enforced by the server, not the page.
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    refused = client.get("/api/goals")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Choose your own password first."
    assert client.post(
        "/api/auth/change-password",
        json={"current_password": TEMPORARY, "new_password": OWN},
    ).status_code == 403


def test_choosing_their_own_opens_the_rest(db, client, sign_in, person):
    person.password_hash = hash_password(TEMPORARY)
    person.must_change_password = True
    db.flush()
    sign_in(person)

    assert client.post(
        "/api/auth/choose-password", json={"password": OWN}
    ).status_code == 204

    db.refresh(person)
    assert person.must_change_password is False
    assert verify_password(OWN, person.password_hash)
    assert client.get("/api/goals").status_code == 200
    assert db.scalar(select(AuditLog).where(AuditLog.action == "password.chosen")) is not None


def test_the_one_they_were_given_is_not_their_own(db, client, sign_in, person):
    person.password_hash = hash_password(TEMPORARY)
    person.must_change_password = True
    db.flush()
    sign_in(person)
    assert client.post(
        "/api/auth/choose-password", json={"password": TEMPORARY}
    ).status_code == 400


def test_choosing_is_only_for_a_password_somebody_else_set(client, sign_in, person):
    """Otherwise it is "change password" without the proof that one asks for."""
    sign_in(person)
    assert client.post(
        "/api/auth/choose-password", json={"password": OWN}
    ).status_code == 409


# ── Inviting with one ────────────────────────────────────────────────────────


def test_an_admin_invites_with_a_temporary_password(db, client, sign_in, admin):
    sign_in(admin)
    response = client.post("/api/users/invite", json={
        "email": "closer@agency.example", "full_name": "Agency Closer",
        "temporary_password": TEMPORARY,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["invite_link"] is None
    assert body["user"]["status"] == "active"
    assert body["user"]["must_change_password"] is True
    client.post("/api/auth/logout")
    assert login(client, "closer@agency.example", TEMPORARY).json()["must_change_password"] is True


def test_a_manager_invites_with_a_link_only(client, sign_in, make_user):
    sign_in(make_user("manager"))
    assert client.post("/api/users/invite", json={
        "email": "new@acme.example", "full_name": "New", "temporary_password": TEMPORARY,
    }).status_code == 403
    assert client.post("/api/users/invite", json={
        "email": "new@acme.example", "full_name": "New",
    }).json()["invite_link"]


# ── 11.4 One password rule ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "password",
    [
        "eleven char",  # one short of twelve
        "é" * 40,  # 40 characters, 80 bytes: bcrypt would refuse it with a 500
    ],
)
def test_the_rule_is_the_same_everywhere(client, sign_in, admin, person, password):
    sign_in(admin)
    assert client.post(
        f"/api/users/{person.id}/temporary-password", json={"password": password}
    ).status_code == 422
    assert client.post("/api/users/invite", json={
        "email": "x@acme.example", "full_name": "X", "temporary_password": password,
    }).status_code == 422
