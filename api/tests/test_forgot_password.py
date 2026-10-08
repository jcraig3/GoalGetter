"""Forgot password, from the sign-in page (Phase 14).

Open to the world, so what has to be true is mostly what it must NOT do: say
which addresses have accounts, hand back the link, build the link from a
request a stranger controls, or let one person fill another's inbox.
"""

import pytest
from sqlalchemy import func, select

from app import mail, tokens
from app.config import get_settings
from app.models import AuditLog, DirectoryPerson, OauthClient, SsoConfig, UserToken
from app.routers.passwords import FORGOT_ANSWER, FORGOT_PER_EMAIL
from app.security import hash_password

PASSWORD = "correct horse battery staple"


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(mail, "can_send", lambda db, org_id: True)
    monkeypatch.setattr(
        mail, "send",
        lambda db, org_id, *, to, subject, body: sent.append(
            {"to": to, "subject": subject, "body": body}
        ),
    )
    return sent


@pytest.fixture
def person(db, make_user):
    user = make_user("agent", name="Pat")
    user.password_hash = hash_password(PASSWORD)
    db.commit()
    return user


def forgot(client, email, **headers):
    return client.post("/api/auth/forgot-password", json={"email": email}, headers=headers)


def link_in(message) -> str:
    return next(word for word in message["body"].split() if "token=" in word)


def test_a_link_is_emailed_and_never_returned(client, person, outbox):
    reply = forgot(client, person.email.upper())

    assert reply.status_code == 202
    assert reply.json() == {"detail": FORGOT_ANSWER}
    assert "token" not in reply.text
    assert [m["to"] for m in outbox] == [person.email]
    assert "/reset-password?token=" in link_in(outbox[0])


def test_the_link_works(client, db, person, outbox):
    forgot(client, person.email)
    raw = link_in(outbox[0]).split("token=")[1]
    assert client.post(
        "/api/auth/reset-password", json={"token": raw, "password": "a brand new password"}
    ).status_code == 204


def test_an_unknown_address_gets_the_same_answer_and_no_email(client, outbox):
    reply = forgot(client, "nobody@acme.example")
    assert reply.status_code == 202
    assert reply.json() == {"detail": FORGOT_ANSWER}
    assert outbox == []


def test_the_link_ignores_where_the_request_says_it_came_from(client, db, person, outbox, monkeypatch):
    """Password reset poisoning: a stranger's Origin must not be the link."""
    monkeypatch.setattr(get_settings(), "app_url", "https://goals.acme.example")
    forgot(client, person.email, Origin="https://evil.example")
    assert link_in(outbox[0]).startswith("https://goals.acme.example/reset-password?token=")


@pytest.mark.parametrize("state", ["suspended", "hidden"])
def test_a_closed_account_gets_nothing(client, db, person, outbox, state):
    if state == "hidden":
        from datetime import UTC, datetime

        person.hidden_at = datetime.now(UTC)
    else:
        person.status = "suspended"
    db.commit()
    assert forgot(client, person.email).json() == {"detail": FORGOT_ANSWER}
    assert outbox == []


def test_somebody_who_must_use_microsoft_gets_nothing(client, db, org, person, outbox):
    db.add(OauthClient(organization_id=org.id, provider="oidc", client_id="c",
                       client_secret_encrypted="x", issuer="https://login.example"))
    db.add(SsoConfig(organization_id=org.id, enabled=True, require_sso=True,
                     provider="oidc", button_label="SSO"))
    db.add(DirectoryPerson(organization_id=org.id, provider="microsoft", external_id="p",
                           email=person.email, status="approved", user_account_id=person.id))
    db.commit()
    forgot(client, person.email)
    assert outbox == []


def test_nothing_is_sent_with_nowhere_to_send_from(client, person, monkeypatch):
    monkeypatch.setattr(mail, "can_send", lambda db, org_id: False)
    sent = []
    monkeypatch.setattr(mail, "send", lambda *a, **k: sent.append(1))
    assert forgot(client, person.email).status_code == 202
    assert sent == []


def test_somebody_still_invited_gets_their_invitation_again(client, db, make_user, outbox):
    invited = make_user("agent", name="New", status="invited")
    db.commit()
    forgot(client, invited.email)
    assert "/accept-invite?token=" in link_in(outbox[0])
    assert outbox[0]["subject"] == "Your GoalGetter invitation"


def test_one_inbox_cannot_be_flooded(client, person, outbox):
    for _ in range(FORGOT_PER_EMAIL + 3):
        assert forgot(client, person.email).status_code == 202
    assert len(outbox) == FORGOT_PER_EMAIL


def test_asking_never_locks_anybody_out_of_signing_in(client, person, outbox):
    for _ in range(FORGOT_PER_EMAIL + 3):
        forgot(client, person.email)
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": PASSWORD}
    ).status_code == 200


def test_it_is_in_the_activity_log(client, db, person, outbox):
    forgot(client, person.email)
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "password.reset_requested"))
    assert entry.target_user_id == person.id


def test_the_sign_in_page_is_told_whether_it_can_offer_this(client, monkeypatch, org):
    monkeypatch.setattr(mail, "can_send", lambda db, org_id: True)
    assert client.get("/api/auth/providers").json()["self_reset"] is True
    monkeypatch.setattr(mail, "can_send", lambda db, org_id: False)
    assert client.get("/api/auth/providers").json()["self_reset"] is False


def test_a_dead_link_says_how_to_get_another(client):
    reply = client.post("/api/auth/reset-password/check", json={"token": "nope"})
    assert "Forgot password?" in reply.json()["detail"]


def test_an_old_reset_link_dies_when_a_new_one_is_asked_for(client, db, person, outbox):
    old = tokens.issue(db, person.id, "password_reset")
    db.commit()
    forgot(client, person.email)
    assert db.scalar(
        select(func.count()).select_from(UserToken).where(UserToken.user_id == person.id)
    ) == 1
    assert client.post(
        "/api/auth/reset-password", json={"token": old, "password": "a brand new password"}
    ).status_code == 400


@pytest.mark.parametrize("email", ["not an address", "@acme.example", "pat@", ""])
def test_a_malformed_address_gets_the_same_answer(client, outbox, email):
    """P5-13: pydantic's own 422 is not the app's words — and is a different answer."""
    reply = forgot(client, email)
    assert reply.status_code == 202
    assert reply.json() == {"detail": FORGOT_ANSWER}
    assert outbox == []
