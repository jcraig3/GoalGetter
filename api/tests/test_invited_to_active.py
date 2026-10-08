"""Invited becomes active the moment there is a way in.

Setting a password, signing in with a work account, or being found in the
directory all end an invitation. Two of those used to leave the account
"invited", which the People list showed in yellow and the SSO sign-in refused.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app import tokens
from app.directory.apply import apply
from app.directory.reconcile import _reactivate_account
from app.models import DirectoryPerson, SsoConfig, UserToken
from app.routers.sso import _resolve_user
from app.security import hash_password

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def invite_links(db, user) -> int:
    return db.scalar(
        select(func.count()).select_from(UserToken).where(
            UserToken.user_id == user.id, UserToken.purpose == "invite"
        )
    )


def test_signing_in_with_a_work_account_accepts_the_invitation(db, org, make_user):
    invited = make_user("agent", name="Sam", status="invited")
    tokens.issue(db, invited.id, "invite")
    config = SsoConfig(organization_id=org.id, enabled=True, provider="oidc", button_label="SSO")
    db.add(config)
    db.flush()

    found = _resolve_user(db, config, subject="sub-1", claims={}, email=invited.email.lower())

    # It was refused: only `active` got past the check.
    assert found is invited
    assert invited.status == "active"
    assert invite_links(db, invited) == 0


def test_found_in_the_directory_ends_the_invitation(db, org, make_user):
    invited = make_user("agent", name="Sam", status="invited")
    tokens.issue(db, invited.id, "invite")
    row = DirectoryPerson(
        organization_id=org.id, provider="microsoft", external_id="e1",
        email=invited.email.upper(), display_name="Sam", status="approved",
    )
    db.add(row)
    db.flush()

    assert apply(db, row, now=NOW) is invited
    assert invited.status == "active"
    assert invite_links(db, invited) == 0


def test_back_in_the_directory_is_active_without_a_password(db, org, make_user):
    """They sign in with the work account the directory holds."""
    account = make_user("agent", name="Returner")
    account.status = "deactivated"
    row = DirectoryPerson(
        organization_id=org.id, provider="microsoft", external_id="e2",
        email=account.email, status="approved", user_account_id=account.id,
    )
    row.account = account
    db.add(row)
    db.flush()

    assert _reactivate_account(row) is True
    assert account.status == "active"


def test_reactivated_by_hand_from_the_directory_is_active(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))
    account = make_user("agent", name="Returner")
    account.status = "deactivated"
    db.add(DirectoryPerson(
        organization_id=org.id, provider="microsoft", external_id="e3",
        email=account.email, status="approved", user_account_id=account.id,
    ))
    db.commit()

    assert client.post(f"/api/users/{account.id}/reactivate").json()["status"] == "active"


def test_a_temporary_password_shows_invited_until_first_sign_in(client, db, make_user, sign_in):
    admin = sign_in(make_user("admin"))
    person = make_user("agent", name="Contractor")
    client.post(f"/api/users/{person.id}/temporary-password", json={"password": "a temporary one"})

    row = next(u for u in client.get("/api/users").json() if u["id"] == person.id)
    assert row["awaiting_first_sign_in"] is True

    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": person.email, "password": "a temporary one"})
    client.post("/api/auth/choose-password", json={"password": "my very own passphrase"})
    client.post("/api/auth/logout")
    admin.password_hash = hash_password("the admin password")
    db.commit()
    client.post("/api/auth/login", json={"email": admin.email, "password": "the admin password"})

    row = next(u for u in client.get("/api/users").json() if u["id"] == person.id)
    assert row["awaiting_first_sign_in"] is False
    assert row["status"] == "active"
