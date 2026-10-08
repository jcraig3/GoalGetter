"""HTTPS in front of the app (Phase 13), as the app sees it.

Caddy terminates TLS; the app reads the same .env to know that it is there.
What has to be true: with HTTPS on, the HTTPS address is the default web
address and session cookies set over it are Secure; the plain address TVs use
keeps working; and Settings can say where the root certificate is and what
to register in Azure.
"""

import pytest

from app import public_url
from app.config import get_settings


@pytest.fixture
def https(monkeypatch):
    def _on(host="goals.internal", *, port=443, certificate="internal", profiles="https"):
        settings = get_settings()
        monkeypatch.setattr(settings, "https_host", host)
        monkeypatch.setattr(settings, "https_port", port)
        monkeypatch.setattr(settings, "https_certificate", certificate)
        monkeypatch.setattr(settings, "compose_profiles", profiles)
        monkeypatch.setattr(settings, "http_port", 80)
        monkeypatch.setattr(settings, "app_port", 8080)

    return _on


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def test_https_on_makes_its_address_the_default(https, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_url", "http://localhost:8080")
    https()
    assert public_url.default() == "https://goals.internal"


def test_a_port_other_than_443_is_part_of_the_address(https):
    https(port=8443)
    assert public_url.default() == "https://goals.internal:8443"


def test_a_host_without_the_profile_is_not_https(https, monkeypatch):
    """The app agrees with whether Caddy is actually running."""
    monkeypatch.setattr(get_settings(), "app_url", "http://localhost:8080")
    https(profiles="")
    assert public_url.default() == "http://localhost:8080"
    assert get_settings().https_on is False


def login_cookie(client, db, make_user, headers):
    from app.security import hash_password

    user = make_user("agent")
    user.password_hash = hash_password("correct horse battery staple")
    db.commit()
    reply = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "correct horse battery staple"},
        headers=headers,
    )
    assert reply.status_code == 200
    return reply.headers["set-cookie"].lower()


def test_signing_in_over_https_makes_the_cookie_secure(client, db, make_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "secure_cookies", False)
    cookie = login_cookie(client, db, make_user, {"X-Forwarded-Proto": "https"})
    assert "secure" in cookie


def test_the_plain_address_still_signs_in(client, db, make_user, monkeypatch):
    """The address TVs use. Secure there would be a cookie the browser drops."""
    monkeypatch.setattr(get_settings(), "secure_cookies", False)
    cookie = login_cookie(client, db, make_user, {})
    assert "secure" not in cookie


def test_secure_cookies_still_forces_it(client, db, make_user, monkeypatch):
    monkeypatch.setattr(get_settings(), "secure_cookies", True)
    assert "secure" in login_cookie(client, db, make_user, {})


def test_settings_says_where_the_root_certificate_is(client, admin, https):
    https()
    body = client.get("/api/hosting").json()
    # The connection check and limits have their own tests, below.
    body = {k: body[k] for k in ("https", "https_address", "certificate", "root_certificate_url", "tv_address", "sso_redirect")}
    assert body == {
        "https": True,
        "https_address": "https://goals.internal",
        "certificate": "internal",
        "root_certificate_url": "http://goals.internal/goalgetter-root.crt",
        "tv_address": "http://goals.internal:8080",
        "sso_redirect": "https://goals.internal/api/auth/sso/callback",
    }


def test_no_root_certificate_for_a_public_one(client, admin, https):
    https("goalgetter.acme.com", certificate="letsencrypt")
    body = client.get("/api/hosting").json()
    assert body["root_certificate_url"] is None
    assert body["sso_redirect"] == "https://goalgetter.acme.com/api/auth/sso/callback"


def test_off_says_off(client, admin, https):
    https(host="")
    body = client.get("/api/hosting").json()
    assert body["https"] is False
    assert body["https_address"] is None


def test_hosting_is_an_admin_page(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert client.get("/api/hosting").status_code == 403


def test_settings_says_when_addresses_are_hidden(client, admin, monkeypatch):
    """P6-1: nothing has reached GoalGetter but Docker's own address."""
    from app.routers import hosting

    monkeypatch.setattr(hosting, "visitor_ip", lambda request, db=None: None)
    assert client.get("/api/hosting").json()["addresses_visible"] is False


def test_one_real_device_lately_is_enough(client, db, admin, monkeypatch):
    """On Linux the server's own browser arrives as Docker's address while
    the office's devices do not: their sessions say addresses are visible."""
    from app.models import Session as SessionRow
    from app.routers import hosting

    monkeypatch.setattr(hosting, "visitor_ip", lambda request, db=None: None)
    db.query(SessionRow).update({SessionRow.ip_address: "192.168.1.55"})
    db.commit()
    assert client.get("/api/hosting").json()["addresses_visible"] is True


def test_through_a_cloudflare_tunnel(client, admin, https, monkeypatch):
    """Phase 18: Cloudflare holds the certificate and the name leads to it, so
    there is no root certificate to hand out and no TV address to guess."""
    https("goalgetter.company.com", profiles="cloudflare")
    monkeypatch.setattr(get_settings(), "https_front_door", "cloudflare")
    body = client.get("/api/hosting").json()
    assert body["https"] is True
    assert body["https_address"] == "https://goalgetter.company.com"
    assert body["certificate"] == "cloudflare"
    assert body["root_certificate_url"] is None
    assert body["tv_address"] is None
    assert body["sso_redirect"] == "https://goalgetter.company.com/api/auth/sso/callback"


# ── The status card (Phase 19) ───────────────────────────────────────────────


def test_the_status_card_says_where_links_point_and_why(client, db, org, admin, https):
    https(host="")
    body = client.get("/api/hosting").json()
    assert body["web_address_from"] == "env"
    https()
    assert client.get("/api/hosting").json()["web_address_from"] == "https"
    org.public_url = "https://goals.acme.example"
    db.commit()
    body = client.get("/api/hosting").json()
    assert (body["web_address"], body["web_address_from"]) == ("https://goals.acme.example", "settings")


def test_the_certificate_served_is_reported(client, admin, https, monkeypatch):
    from datetime import UTC, datetime

    from app import certificate_probe

    https()
    monkeypatch.setattr(
        certificate_probe, "served",
        lambda hosting: certificate_probe.Served(datetime(2027, 1, 12, tzinfo=UTC), "GoalGetter Local Authority - ECC Intermediate"),
    )
    body = client.get("/api/hosting").json()
    assert body["certificate_valid_until"].startswith("2027-01-12")
    assert body["certificate_issuer"].startswith("GoalGetter Local Authority")


def test_no_certificate_while_https_is_off(db, https):
    from app import certificate_probe, hosting_config

    https(host="")
    assert certificate_probe.served(hosting_config.current(db)) is None
