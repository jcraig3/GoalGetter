"""Hosting settings in the app (Phase 17): the connection check, a proxy in
front, and the sign-in limits."""

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.security import hash_password

PASSWORD = "correct horse battery staple"


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


@pytest.fixture
def via_nginx(client):
    """Requests as nginx delivers them: from a trusted proxy address."""
    with TestClient(app, client=("172.18.0.5", 50000)) as proxied:
        yield proxied


def patch(client, **fields):
    return client.patch("/api/organization", json=fields)


# ── The connection check ─────────────────────────────────────────────────────


def test_settings_says_who_you_appear_as(db, via_nginx, make_user, sign_in):
    user = make_user("admin")
    user.password_hash = hash_password(PASSWORD)
    db.commit()
    via_nginx.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD},
        headers={"X-Forwarded-For": "192.168.1.55"},
    )
    body = via_nginx.get("/api/hosting", headers={"X-Forwarded-For": "192.168.1.55"}).json()
    assert body["you_appear_as"] == "192.168.1.55"
    assert body["connection"] == "visible"
    assert body["proxies_seen"] == 1
    assert (body["proxy_hops"], body["proxy_hops_from"]) == (1, "env")
    assert body["sign_in_limits"] == [5, 20]


# ── A proxy in front ─────────────────────────────────────────────────────────


def test_proxy_is_refused_with_no_proxy_in_sight(client, admin):
    """Believing one more entry with no proxy adding it would let anybody
    choose the address they appear to come from."""
    reply = patch(client, proxy_mode="proxy")
    assert reply.status_code == 400
    assert "No proxy is passing your address along" in reply.json()["detail"]


def test_proxy_is_allowed_when_one_is_passing_an_address(client, admin):
    reply = client.patch(
        "/api/organization", json={"proxy_mode": "proxy"},
        headers={"X-Forwarded-For": "192.168.1.55, 10.0.0.2"},
    )
    assert reply.status_code == 200
    assert reply.json()["proxy_mode"] == "proxy"


def test_direct_and_back_to_env_are_always_allowed(client, admin):
    assert patch(client, proxy_mode="direct").json()["proxy_mode"] == "direct"
    assert patch(client, proxy_mode="").json()["proxy_mode"] is None


def test_the_setting_decides_which_entry_is_the_visitor(db, org, via_nginx):
    """Behind the organization's proxy, nginx's entry is the proxy's address
    and the one before it is the visitor."""
    from app.net import visitor_ip

    class Fake:
        client = type("C", (), {"host": "172.18.0.5"})()
        headers = {"x-forwarded-for": "192.168.1.55, 10.0.0.2"}

    assert visitor_ip(Fake(), db) == "10.0.0.2"
    org.proxy_mode = "proxy"
    db.flush()
    assert visitor_ip(Fake(), db) == "192.168.1.55"


# ── The sign-in limits ───────────────────────────────────────────────────────


def test_a_lower_account_limit_applies(client, db, admin, make_user):
    patch(client, sign_in_limit_account=3)
    client.post("/api/auth/logout")
    person = make_user("agent")
    person.password_hash = hash_password(PASSWORD)
    db.commit()
    for _ in range(3):
        client.post("/api/auth/login", json={"email": person.email, "password": "wrong"})
    assert client.post(
        "/api/auth/login", json={"email": person.email, "password": PASSWORD}
    ).status_code == 429


@pytest.mark.parametrize(("field", "value"), [
    ("sign_in_limit_account", 2), ("sign_in_limit_account", 21),
    ("sign_in_limit_device", 9), ("sign_in_limit_device", 201),
])
def test_limits_stay_within_sense(client, admin, field, value):
    reply = patch(client, **{field: value})
    assert reply.status_code == 400
    assert "Choose between" in reply.json()["detail"]


def test_only_an_admin_changes_them(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert patch(client, sign_in_limit_account=10).status_code == 403


def test_an_unchanged_proxy_setting_is_not_checked_again(client, db, org, admin):
    """Saving the currency while `proxy` is on, from the server's own browser,
    must not trip a check about how you connected."""
    org.proxy_mode = "proxy"
    db.commit()
    reply = patch(client, proxy_mode="proxy", currency="CAD")
    assert reply.status_code == 200
    assert reply.json()["proxy_mode"] == "proxy"
