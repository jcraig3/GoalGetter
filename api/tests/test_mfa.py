"""Two-step sign-in with an authenticator app.

What has to be true: codes follow RFC 6238; a code works once; a correct
password with two-step sign-in on gives a challenge, not a session; the
challenge becomes a session only with a code or a recovery code, each used
once; wrong codes are rate-limited; requiring it walks somebody without it
through setup before they are in; SSO is untouched; and an admin can reset it.
"""

import pytest
from sqlalchemy import select

from app import crypto, mfa, totp
from app.models import AuditLog
from app.security import hash_password

PASSWORD = "correct horse battery"


# ── The codes ───────────────────────────────────────────────────────────────


def test_the_rfc_6238_test_vector():
    """RFC 6238 appendix B, SHA-1, secret "12345678901234567890", T=59."""
    import base64

    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp.code_now(secret, at=59) == "287082"
    assert totp.code_now(secret, at=1111111109) == "081804"


def test_a_code_either_side_of_now_is_accepted():
    secret = totp.new_secret()
    earlier = totp.code_now(secret, at=1_000_000 - 30)

    assert totp.matching_step(secret, earlier, at=1_000_000) is not None
    assert totp.matching_step(secret, totp.code_now(secret, at=1_000_000 - 90), at=1_000_000) is None


def test_a_used_step_is_not_accepted_again():
    secret = totp.new_secret()
    code = totp.code_now(secret, at=1_000_000)
    step = totp.matching_step(secret, code, at=1_000_000)

    assert totp.matching_step(secret, code, after_step=step, at=1_000_000) is None


def test_the_qr_link_is_what_authenticators_read():
    uri = totp.otpauth_uri("ABC", account="peter@acme.example", issuer="GoalGetter")

    assert uri.startswith("otpauth://totp/GoalGetter%3Apeter%40acme.example?")
    assert "secret=ABC" in uri and "issuer=GoalGetter" in uri


# ── Signing in ──────────────────────────────────────────────────────────────


@pytest.fixture
def peter(db, make_user):
    user = make_user("agent", name="Peter Parker")
    user.password_hash = hash_password(PASSWORD)
    db.flush()
    return user


def with_authenticator(db, user):
    secret = totp.new_secret()
    user.mfa_secret_encrypted = crypto.encrypt(secret)
    user.mfa_recovery_hashes = [totp.hash_recovery("abcd-efgh")]
    db.flush()
    return secret


def login(client, user):
    return client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})


def test_without_it_a_password_signs_in(client, peter):
    reply = login(client, peter)

    assert reply.status_code == 200
    assert reply.json()["email"] == peter.email


def test_with_it_a_password_gives_a_challenge_not_a_session(client, db, peter):
    with_authenticator(db, peter)

    reply = login(client, peter)

    assert reply.status_code == 202
    assert reply.json()["mfa"] == "code"
    assert client.get("/api/auth/me").status_code == 401


def test_the_code_finishes_signing_in(client, db, peter):
    secret = with_authenticator(db, peter)
    challenge = login(client, peter).json()["challenge"]

    reply = client.post(
        "/api/auth/login/mfa", json={"challenge": challenge, "code": totp.code_now(secret)}
    )

    assert reply.status_code == 200
    assert client.get("/api/auth/me").json()["email"] == peter.email


def test_the_same_code_cannot_be_used_twice(client, db, peter):
    secret = with_authenticator(db, peter)
    code = totp.code_now(secret)
    client.post("/api/auth/login/mfa", json={"challenge": login(client, peter).json()["challenge"], "code": code})
    client.cookies.clear()

    again = client.post(
        "/api/auth/login/mfa", json={"challenge": login(client, peter).json()["challenge"], "code": code}
    )

    assert again.status_code == 401


def test_a_recovery_code_works_once(client, db, peter):
    with_authenticator(db, peter)

    first = client.post(
        "/api/auth/login/mfa", json={"challenge": login(client, peter).json()["challenge"], "code": "ABCD EFGH"}
    )
    client.cookies.clear()
    second = client.post(
        "/api/auth/login/mfa", json={"challenge": login(client, peter).json()["challenge"], "code": "abcd-efgh"}
    )

    assert first.status_code == 200
    assert second.status_code == 401


def test_wrong_codes_are_rate_limited(client, db, peter):
    with_authenticator(db, peter)
    challenge = login(client, peter).json()["challenge"]

    replies = [
        client.post("/api/auth/login/mfa", json={"challenge": challenge, "code": "000000"}).status_code
        for _ in range(7)
    ]

    assert replies[-1] == 429


def test_a_forged_challenge_signs_nobody_in(client, peter):
    reply = client.post("/api/auth/login/mfa", json={"challenge": "nonsense", "code": "123456"})

    assert reply.status_code == 401


# ── Requiring it ────────────────────────────────────────────────────────────


def test_required_and_not_set_up_is_walked_through_setup(client, db, org, peter):
    org.require_mfa = True
    db.flush()

    first = login(client, peter)
    assert first.status_code == 202 and first.json()["mfa"] == "setup"
    challenge = first.json()["challenge"]

    setup = client.post("/api/auth/login/mfa/setup", json={"challenge": challenge}).json()
    enabled = client.post(
        "/api/auth/login/mfa/enable",
        json={"challenge": challenge, "code": totp.code_now(setup["secret"])},
    )

    assert enabled.status_code == 200
    assert len(enabled.json()["recovery_codes"]) == totp.RECOVERY_CODES
    assert client.get("/api/auth/me").status_code == 200
    db.refresh(peter)
    assert mfa.is_enabled(peter)


def test_a_setup_challenge_cannot_skip_to_a_session(client, db, org, peter):
    org.require_mfa = True
    db.flush()
    challenge = login(client, peter).json()["challenge"]

    reply = client.post("/api/auth/login/mfa", json={"challenge": challenge, "code": "123456"})

    assert reply.status_code == 401


def test_required_cannot_be_turned_off_by_the_person(client, db, org, peter, sign_in):
    secret = with_authenticator(db, peter)
    org.require_mfa = True
    db.flush()
    sign_in(peter)

    reply = client.post("/api/auth/mfa/disable", json={"code": totp.code_now(secret)})

    assert reply.status_code == 409


def test_the_settings_switch(client, db, org, sign_in, make_user):
    sign_in(make_user("admin"))

    reply = client.patch("/api/organization", json={"require_mfa": True})

    assert reply.json()["require_mfa"] is True


# ── Your own account ────────────────────────────────────────────────────────


def test_setting_it_up_from_the_account_page(client, db, peter, sign_in):
    sign_in(peter)

    setup = client.post("/api/auth/mfa/setup").json()
    wrong = client.post("/api/auth/mfa/enable", json={"code": "000000"})
    right = client.post("/api/auth/mfa/enable", json={"code": totp.code_now(setup["secret"])})

    assert wrong.status_code == 400
    assert right.status_code == 200
    assert client.get("/api/auth/mfa").json()["enabled"] is True


def test_starting_setup_again_does_not_break_a_working_authenticator(client, db, peter, sign_in):
    secret = with_authenticator(db, peter)
    sign_in(peter)

    client.post("/api/auth/mfa/setup")

    db.refresh(peter)
    assert crypto.decrypt(peter.mfa_secret_encrypted) == secret


def test_turning_it_off_needs_a_code(client, db, peter, sign_in):
    secret = with_authenticator(db, peter)
    sign_in(peter)

    assert client.post("/api/auth/mfa/disable", json={"code": "000000"}).status_code == 400
    assert client.post("/api/auth/mfa/disable", json={"code": totp.code_now(secret)}).status_code == 204


def test_an_admin_resets_somebody_who_lost_their_phone(client, db, peter, sign_in, make_user):
    with_authenticator(db, peter)
    sign_in(make_user("admin"))

    reply = client.post(f"/api/auth/mfa/{peter.id}/reset")

    assert reply.status_code == 204
    db.refresh(peter)
    assert not mfa.is_enabled(peter)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "mfa.reset")) is not None


def test_only_an_admin_resets(client, db, peter, sign_in, make_user):
    sign_in(make_user("manager"))

    assert client.post(f"/api/auth/mfa/{peter.id}/reset").status_code == 403


def test_the_people_list_says_who_has_it(client, db, peter, sign_in, make_user):
    with_authenticator(db, peter)
    sign_in(make_user("admin"))

    people = client.get("/api/users").json()

    assert next(p for p in people if p["id"] == peter.id)["mfa_enabled"] is True


def test_settings_lists_who_signs_in_with_a_password_and_has_not_set_it_up(
    client, db, peter, sign_in, make_user
):
    """QA-32: "required" asks at the next password sign-in, so until then an
    admin cannot see who is still without it. Somebody with no password —
    Microsoft only — has nothing this applies to, and is not listed."""
    ready = make_user("agent", name="Wanda Maximoff")
    ready.password_hash = hash_password(PASSWORD)
    with_authenticator(db, ready)
    make_user("agent", name="Sso Only")
    sign_in(make_user("admin"))

    listed = client.get("/api/auth/mfa/unenrolled").json()

    assert [p["full_name"] for p in listed] == ["Peter Parker"]


def test_only_an_admin_sees_who_is_unenrolled(client, peter, sign_in, make_user):
    sign_in(make_user("manager"))

    assert client.get("/api/auth/mfa/unenrolled").status_code == 403
