"""Sign-in, lockout, sessions, and invitation acceptance.

The security-critical path. Two timing oracles were found here by hand during
development; these tests pin down the behaviour that replaced them.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import (
    DirectoryPerson,
    LoginAttempt,
    OauthClient,
    Session,
    SsoConfig,
    UserAccount,
)
from app.rate_limit import MAX_FAILURES_PER_EMAIL
from app.security import hash_password

PASSWORD = "correct horse battery staple"


@pytest.fixture
def person(db, make_user):
    user = make_user("agent", name="Person")
    user.password_hash = hash_password(PASSWORD)
    db.flush()
    return user


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ── Signing in ───────────────────────────────────────────────────────────────


def test_correct_credentials_sign_in(client, person):
    response = login(client, person.email, PASSWORD)
    assert response.status_code == 200
    assert response.json()["email"] == person.email


def test_signing_in_sets_an_http_only_cookie(client, person):
    """HttpOnly is what stops an XSS bug from stealing the session, and is the
    main reason for a cookie over localStorage."""
    response = login(client, person.email, PASSWORD)
    cookie = response.headers["set-cookie"]
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()


def test_the_session_token_is_not_stored_in_plain_text(db, client, person):
    """The database holds a SHA-256 of the token. A leaked backup therefore
    does not hand over live sessions."""
    login(client, person.email, PASSWORD)
    token = client.cookies["gg_session"]
    row = db.scalar(select(Session).where(Session.user_id == person.id))
    assert row.token_hash != token
    assert len(row.token_hash) == 64


def test_signing_in_records_last_login(db, client, person):
    assert person.last_login_at is None
    login(client, person.email, PASSWORD)
    db.refresh(person)
    assert person.last_login_at is not None


def test_email_matching_is_case_insensitive(client, person):
    assert login(client, person.email.upper(), PASSWORD).status_code == 200


@pytest.mark.parametrize("password", ["wrong", "", PASSWORD + " "])
def test_a_wrong_password_is_rejected(client, person, password):
    assert login(client, person.email, password).status_code in (401, 422)


def test_an_unknown_address_gets_the_same_message_as_a_wrong_password(client, person):
    """Distinguishing them would confirm which addresses exist, which is how an
    attacker enumerates everyone who works at the company."""
    unknown = login(client, "nobody@acme.example", "whatever")
    wrong = login(client, person.email, "wrong")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_a_suspended_account_cannot_sign_in(db, client, person):
    person.status = "suspended"
    db.flush()
    assert login(client, person.email, PASSWORD).status_code == 401


def test_a_hidden_account_cannot_sign_in(db, client, person):
    person.hidden_at = datetime.now(UTC)
    db.flush()
    assert login(client, person.email, PASSWORD).status_code == 401


def test_an_account_with_no_password_cannot_sign_in(db, client, make_user):
    """An invited account that has never set one. Without the explicit check, a
    null hash could be compared against and behave unpredictably."""
    invited = make_user("agent", status="invited")
    db.flush()
    assert login(client, invited.email, "anything").status_code == 401


# ── Rate limiting ────────────────────────────────────────────────────────────


def test_repeated_failures_lock_the_account(client, person):
    for _ in range(MAX_FAILURES_PER_EMAIL):
        assert login(client, person.email, "wrong").status_code == 401

    response = login(client, person.email, "wrong")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) > 0


def test_lockout_blocks_even_the_correct_password(client, person):
    """Otherwise the limit is trivially bypassed by whoever eventually guesses
    right — which is exactly the case it exists to stop."""
    for _ in range(MAX_FAILURES_PER_EMAIL):
        login(client, person.email, "wrong")
    assert login(client, person.email, PASSWORD).status_code == 429


def test_an_address_that_does_not_exist_locks_out_on_the_same_terms(client, person):
    """This is what makes the explicit 429 safe to show.

    If only real accounts locked out, the 429 itself would reveal which
    addresses exist — reintroducing the enumeration oracle by another route.
    """
    unknown = "ghost@acme.example"
    for _ in range(MAX_FAILURES_PER_EMAIL):
        assert login(client, unknown, "wrong").status_code == 401
    assert login(client, unknown, "wrong").status_code == 429


def test_a_successful_sign_in_clears_earlier_failures(db, client, person):
    """So an earlier typo does not count against someone who has since signed
    in successfully."""
    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        login(client, person.email, "wrong")
    assert login(client, person.email, PASSWORD).status_code == 200

    for _ in range(MAX_FAILURES_PER_EMAIL - 1):
        assert login(client, person.email, "wrong").status_code == 401


def test_a_failed_attempt_is_recorded(db, client, person):
    login(client, person.email, "wrong")
    attempts = db.scalars(
        select(LoginAttempt).where(func.lower(LoginAttempt.email) == person.email.lower())
    ).all()
    assert [a.succeeded for a in attempts] == [False]


def test_a_successful_attempt_is_recorded_and_removes_the_failures(db, client, person):
    """`clear_failures` deletes the failure rows for that address, so what
    survives is the success alone. The failures have done their job — they held
    the lockout counter — and keeping them would mean a single typo months ago
    still counted toward a future lockout."""
    login(client, person.email, "wrong")
    login(client, person.email, PASSWORD)
    attempts = db.scalars(
        select(LoginAttempt).where(func.lower(LoginAttempt.email) == person.email.lower())
    ).all()
    assert [a.succeeded for a in attempts] == [True]


# ── Sessions ─────────────────────────────────────────────────────────────────


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_capabilities_and_team(client, db, person, make_team):
    team = make_team("Enterprise")
    person.team_id = team.id
    db.flush()
    body = login(client, person.email, PASSWORD).json()
    assert body["team_id"] == team.id
    assert "teams.view" in body["capabilities"]
    assert "users.view" not in body["capabilities"]


def test_an_expired_session_is_rejected_and_deleted(db, client, person):
    login(client, person.email, PASSWORD)
    row = db.scalar(select(Session).where(Session.user_id == person.id))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    assert client.get("/api/auth/me").status_code == 401
    assert db.scalar(select(func.count()).select_from(Session).where(
        Session.user_id == person.id
    )) == 0


def test_a_forged_token_is_rejected(client, person):
    login(client, person.email, PASSWORD)
    client.cookies.set("gg_session", "not-a-real-token")
    assert client.get("/api/auth/me").status_code == 401


def test_logging_out_removes_the_session(db, client, person):
    login(client, person.email, PASSWORD)
    assert client.post("/api/auth/logout").status_code == 204
    assert db.scalar(select(func.count()).select_from(Session).where(
        Session.user_id == person.id
    )) == 0


def test_logging_out_without_a_session_still_succeeds(client):
    """Logging out should never fail, and never reveal whether the session was
    real."""
    assert client.post("/api/auth/logout").status_code == 204


def test_a_role_change_takes_effect_on_the_next_request(db, client, person):
    """Permissions are re-read from the database every request, which is the
    main reason sessions are server-side rather than JWT."""
    login(client, person.email, PASSWORD)
    assert client.get("/api/users").status_code == 403

    person.org_role = "admin"
    db.flush()
    assert client.get("/api/users").status_code == 200


# ── Required SSO, and the break-glass rule ───────────────────────────────────


@pytest.fixture
def sso_required(db, org):
    # The credential lives on the provider connection now, not here — one app
    # registration serves signing in and reading data. This fixture only needs
    # sign-on switched on and pointed at something.
    connection = OauthClient(
        organization_id=org.id,
        provider="oidc",
        client_id="client",
        client_secret_encrypted="x",
        issuer="https://login.example/tenant",
    )
    config = SsoConfig(
        organization_id=org.id,
        enabled=True,
        require_sso=True,
        provider="oidc",
        button_label="Sign in with SSO",
    )
    db.add_all([connection, config])
    db.flush()
    return config


def test_require_sso_blocks_password_sign_in_for_somebody_in_the_directory(
    db, org, client, person, sso_required
):
    """Enforced at the endpoint, not by hiding the form. Anyone can POST here
    directly, so the rule has to live where the decision is made."""
    db.add(DirectoryPerson(
        organization_id=org.id, provider="microsoft", external_id="p-1",
        email=person.email, status="approved", user_account_id=person.id,
    ))
    db.flush()
    response = login(client, person.email, PASSWORD)
    assert response.status_code == 401
    # The same words as a wrong password: nothing about who is in the directory.
    assert response.json()["detail"] == "Incorrect email or password."


def test_require_sso_lets_in_somebody_set_up_outside_the_directory(client, person, sso_required):
    """A contractor with no work account has no other way in (11.1)."""
    assert login(client, person.email, PASSWORD).status_code == 200


def test_require_sso_still_lets_an_admin_in(db, client, person, sso_required):
    """The break-glass path. Without it, a typo in the issuer URL locks
    everyone out of a self-hosted deployment with no support line, and the only
    way back is editing the database by hand."""
    person.org_role = "admin"
    db.flush()
    assert login(client, person.email, PASSWORD).status_code == 200


def test_providers_reports_what_the_login_page_should_offer(client, sso_required):
    body = client.get("/api/auth/providers").json()
    assert body == {
        # Always: people outside the directory sign in with a password (11.1).
        "local": True,
        "sso_enabled": True,
        "sso_required": True,
        # No mail server here, so "Forgot password?" says to ask an admin.
        "self_reset": False,
        "sso_button_label": "Sign in with SSO",
    }


def test_providers_is_public(client):
    """It reveals only which buttons to draw — which anyone can see by loading
    the login page anyway."""
    assert client.get("/api/auth/providers").status_code == 200


# ── Invitations ──────────────────────────────────────────────────────────────


@pytest.fixture
def invited(db, make_user):
    from app import tokens

    user = make_user("agent", status="invited")
    raw = tokens.issue(db, user.id, "invite")
    db.flush()
    return user, raw


def test_accepting_an_invite_sets_a_password_and_signs_in(db, client, invited):
    user, raw = invited
    response = client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "a long enough password"}
    )
    assert response.status_code == 200
    db.refresh(user)
    assert user.status == "active"
    assert user.password_hash
    assert client.get("/api/auth/me").status_code == 200


def test_an_invite_token_works_only_once(client, invited):
    _, raw = invited
    client.post("/api/auth/accept-invite", json={"token": raw, "password": "a long enough password"})
    second = client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "another long password"}
    )
    assert second.status_code == 400


def test_a_short_password_is_refused(client, invited):
    """Length over character-class rules — current NIST guidance, and the
    alternative mostly produces "Password1!"."""
    _, raw = invited
    assert client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "short"}
    ).status_code == 422


def test_an_unknown_invite_token_is_refused(client):
    assert client.post(
        "/api/auth/accept-invite", json={"token": "made-up", "password": "a long enough password"}
    ).status_code == 400


def test_an_expired_invite_token_is_refused(db, client, invited):
    from app.models import UserToken

    user, raw = invited
    row = db.scalar(select(UserToken).where(UserToken.user_id == user.id))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()

    assert client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "a long enough password"}
    ).status_code == 400


def test_an_invite_for_a_suspended_account_is_refused(db, client, invited):
    user, raw = invited
    user.status = "suspended"
    db.flush()
    assert client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "a long enough password"}
    ).status_code == 400


def test_every_invite_failure_gives_the_same_message(db, client, invited):
    """Distinguishing them would tell someone holding a stale link whether it
    was ever real, and whether the account exists."""
    user, raw = invited
    unknown = client.post(
        "/api/auth/accept-invite", json={"token": "made-up", "password": "a long enough password"}
    )
    user.status = "suspended"
    db.flush()
    suspended = client.post(
        "/api/auth/accept-invite", json={"token": raw, "password": "a long enough password"}
    )
    assert unknown.json()["detail"] == suspended.json()["detail"]


# ── Setup ────────────────────────────────────────────────────────────────────


def test_setup_is_required_only_while_there_are_no_users(client, db, make_user):
    assert client.get("/api/setup/status").json()["setup_required"] is True
    make_user("admin")
    assert client.get("/api/setup/status").json()["setup_required"] is False


def test_setup_creates_an_organization_an_admin_and_the_default_metrics(client, db):
    from app.metrics_seed import DEFAULT_METRICS
    from app.models import MetricDefinition

    response = client.post(
        "/api/setup",
        json={
            "organization_name": "Acme",
            "full_name": "First Admin",
            "email": "first@acme.example",
            "password": "a long enough password",
        },
    )
    assert response.status_code == 201
    org_id = response.json()["organization_id"]

    admin = db.get(UserAccount, response.json()["user_id"])
    assert admin.org_role == "admin"
    assert admin.status == "active"

    assert db.scalar(
        select(func.count()).select_from(MetricDefinition).where(
            MetricDefinition.organization_id == org_id
        )
    ) == len(DEFAULT_METRICS)


def test_setup_refuses_once_anyone_exists(client, make_user):
    """What stops this endpoint being a permanent backdoor."""
    make_user("agent")
    assert client.post(
        "/api/setup",
        json={
            "organization_name": "Acme",
            "full_name": "Sneaky",
            "email": "sneaky@acme.example",
            "password": "a long enough password",
        },
    ).status_code == 409


def test_the_session_says_whether_there_is_a_password_to_change(client, db, make_user, sign_in):
    """QA-33: somebody who only signs in with Microsoft was offered "Change
    password", which asks for a current one they do not have."""
    sso_only = sign_in(make_user("agent"))

    assert client.get("/api/auth/me").json()["has_password"] is False

    sso_only.password_hash = "x"
    db.flush()
    assert client.get("/api/auth/me").json()["has_password"] is True


# ── Limits by the real visitor (P5-1) ────────────────────────────────────────


@pytest.fixture
def behind_nginx(client):
    """Requests as nginx delivers them: from a trusted proxy address, with the
    visitor appended to X-Forwarded-For."""
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app, client=("172.18.0.5", 50000)) as proxied:
        yield proxied


def test_one_visitors_failures_do_not_lock_out_another(db, behind_nginx, person):
    """As proven in QA pass 5: 20 failures from made-up addresses locked out a
    different address, because every request looked like nginx."""
    from app.rate_limit import MAX_FAILURES_PER_IP

    for n in range(MAX_FAILURES_PER_IP):
        behind_nginx.post(
            "/api/auth/login",
            json={"email": f"nobody{n}@acme.example", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.66"},
        )

    reply = behind_nginx.post(
        "/api/auth/login",
        json={"email": person.email, "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    assert reply.status_code == 200


def test_one_visitor_is_still_limited(db, behind_nginx):
    from app.rate_limit import MAX_FAILURES_PER_IP

    for n in range(MAX_FAILURES_PER_IP):
        behind_nginx.post(
            "/api/auth/login",
            json={"email": f"nobody{n}@acme.example", "password": "wrong"},
            headers={"X-Forwarded-For": "203.0.113.66"},
        )
    reply = behind_nginx.post(
        "/api/auth/login",
        json={"email": "another@acme.example", "password": "wrong"},
        headers={"X-Forwarded-For": "203.0.113.66"},
    )
    assert reply.status_code == 429


def test_the_attempt_and_session_record_the_visitor(db, behind_nginx, person):
    behind_nginx.post(
        "/api/auth/login",
        json={"email": person.email, "password": PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.7"},
    )
    session = db.scalar(select(Session).where(Session.user_id == person.id))
    assert str(session.ip_address) == "198.51.100.7"
