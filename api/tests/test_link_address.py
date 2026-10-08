"""Invite and reset links point where the admin is using the app.

From the browser's Origin — the admin's address bar — so a link made on the
office server's address carries that address with nothing to configure.
APP_URL when there is no usable Origin, or when the admin is on localhost and
APP_URL names a real address.
"""

import pytest

from app.config import get_settings
from app.tokens import base_url, is_local


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def invite(client, origin=None):
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/api/users/invite",
        json={"email": "new@acme.example", "full_name": "New"},
        headers=headers,
    ).json()


@pytest.fixture
def app_url(monkeypatch):
    def _set(value):
        monkeypatch.setattr(get_settings(), "app_url", value)

    return _set


def test_the_link_is_the_address_the_admin_is_using(client, admin, app_url):
    app_url("http://localhost:8080")
    body = invite(client, "http://192.168.1.20:8080")
    assert body["invite_link"].startswith("http://192.168.1.20:8080/accept-invite?token=")
    assert body["link_is_local"] is False


def test_no_origin_falls_back_to_app_url(client, admin, app_url):
    app_url("https://goals.acme.example")
    assert invite(client)["invite_link"].startswith("https://goals.acme.example/accept-invite")


def test_localhost_gives_way_to_a_real_app_url(client, admin, app_url):
    """A link to localhost opens on nobody's computer but the admin's."""
    app_url("https://goals.acme.example")
    assert invite(client, "http://localhost:8080")["invite_link"].startswith(
        "https://goals.acme.example/"
    )


def test_localhost_both_ways_is_said_to_be_local(client, admin, app_url):
    app_url("http://localhost:8080")
    body = invite(client, "http://localhost:8080")
    assert body["link_is_local"] is True


def test_the_reset_link_follows_the_same_rule(client, admin, make_user, app_url):
    app_url("http://localhost:8080")
    person = make_user("agent")
    person.password_hash = "x"
    body = client.post(
        f"/api/users/{person.id}/reset-password", headers={"Origin": "https://10.0.0.5"}
    ).json()
    assert body["reset_link"].startswith("https://10.0.0.5/reset-password?token=")


@pytest.mark.parametrize("origin", ["null", "javascript:alert(1)", "http://x.example/path", "ftp://x"])
def test_anything_but_a_plain_origin_is_ignored(origin, app_url):
    app_url("https://goals.acme.example")

    class Fake:
        headers = {"origin": origin}

    assert base_url(Fake()) == "https://goals.acme.example"


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://localhost:8080", True),
        ("http://127.0.0.1", True),
        ("http://[::1]:8080", True),
        ("http://app.localhost", True),
        ("http://192.168.1.20:8080", False),
        ("https://goals.acme.example", False),
    ],
)
def test_what_counts_as_local(url, local):
    assert is_local(url) is local
