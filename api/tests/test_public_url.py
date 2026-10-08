"""The deployment's address, set in Settings (11.7).

Self-hosted, often on an office server: an admin sets where the app is under
Settings → General rather than editing `.env` and restarting. `APP_URL` is the
default until they do, and every link that leaves the app follows the setting.
"""

from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import get_settings
from app.models import OauthClient

ADDRESS = "https://goals.acme.example"


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def set_address(client, value):
    return client.patch("/api/organization", json={"public_url": value})


def test_unset_it_is_the_environment_default(client, admin, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_url", "http://localhost:8080")
    body = client.get("/api/organization").json()
    assert body["public_url"] is None
    assert body["public_url_default"] == "http://localhost:8080"


def test_it_is_stored_as_just_the_address(client, admin):
    assert set_address(client, "  HTTPS://Goals.Acme.Example/  ").json()["public_url"] == ADDRESS


@pytest.mark.parametrize(
    "value",
    ["goals.acme.example", "ftp://goals.acme.example", "https://goals.acme.example/app",
     "https://goals.acme.example?x=1", "https://user:pw@goals.acme.example"],
)
def test_anything_but_an_address_is_refused_with_a_sentence(client, admin, value):
    reply = set_address(client, value)
    assert reply.status_code == 400
    assert reply.json()["detail"].endswith(".")


def test_emptying_it_goes_back_to_the_default(client, admin):
    set_address(client, ADDRESS)
    assert set_address(client, "").json()["public_url"] is None


def test_only_an_admin_sets_it(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert set_address(client, ADDRESS).status_code == 403


def test_invite_links_follow_it_over_the_browser(client, admin):
    set_address(client, ADDRESS)
    body = client.post(
        "/api/users/invite",
        json={"email": "new@acme.example", "full_name": "New"},
        headers={"Origin": "http://192.168.1.20:8080"},
    ).json()
    assert body["invite_link"].startswith(f"{ADDRESS}/accept-invite?token=")


def test_tv_links_follow_it(client, admin):
    set_address(client, ADDRESS)
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    tv = client.post("/api/displays", json={"name": "Lobby", "channel_id": channel["id"]}).json()
    assert tv["url"].startswith(f"{ADDRESS}/")


@pytest.mark.parametrize(("provider", "path"), [("microsoft", "excel"), ("google", "sheets")])
def test_sign_in_redirects_follow_it(client, db, org, admin, provider, path):
    """Starting the Excel or Sheets sign-in — which had no test, and would
    have failed on the first press after this change without one."""
    db.add(OauthClient(
        organization_id=org.id, provider=provider, client_id="client",
        client_secret_encrypted="x",
    ))
    db.commit()
    set_address(client, ADDRESS)

    reply = client.post(f"/api/admin/{path}/account")

    assert reply.status_code == 200, reply.json()
    redirect = parse_qs(urlsplit(reply.json()["url"]).query)["redirect_uri"][0]
    assert redirect.startswith(f"{ADDRESS}/")
