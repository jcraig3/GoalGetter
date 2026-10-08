"""The Cloudflare tunnel, set up in the app (Phase 21)."""

import base64
import json
import os
import time

import pytest

from app import env_file, hosting_config


def make_token(tunnel: str = "6ff42ae2-765d-4adf-8112-31c55c1551ef") -> str:
    body = json.dumps({"a": "0123456789abcdef0123456789abcdef", "t": tunnel, "s": "c2VjcmV0LXNlY3JldC1zZWNyZXQ="})
    return base64.b64encode(body.encode()).decode().rstrip("=")


TOKEN = make_token()


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("HTTPS_HOST=\nHTTPS_FRONT_DOOR=\nCLOUDFLARE_TUNNEL_TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(env_file, "ENV_FILE_PATH", str(path))
    return path


@pytest.fixture
def tunnel_dir(tmp_path, monkeypatch):
    directory = tmp_path / "tunnel"
    directory.mkdir()
    monkeypatch.setattr(hosting_config, "TUNNEL_DIR", str(directory))
    return directory


@pytest.fixture
def caddy(monkeypatch):
    pushed = []
    monkeypatch.setattr(hosting_config, "push_to_caddy", lambda text: pushed.append(text) or None)
    hosting_config._last.clear()
    return pushed


@pytest.fixture
def nginx(tmp_path, monkeypatch):
    directory = tmp_path / "nginx"
    directory.mkdir()
    path = directory / "https.conf"
    monkeypatch.setattr(hosting_config, "NGINX_CONF", str(path))
    return path


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def connected(monkeypatch, connections: int = 4):
    class Reply:
        status_code = 200 if connections else 503

        def json(self):
            return {"status": self.status_code, "readyConnections": connections}

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: Reply())


# ── The token ────────────────────────────────────────────────────────────────


def test_the_token_is_found_in_cloudflare_s_install_command():
    assert hosting_config.tunnel_token_from(f"sudo cloudflared service install {TOKEN}") == TOKEN
    assert hosting_config.tunnel_token_from(f"cloudflared.exe tunnel run --token {TOKEN}\n") == TOKEN


def test_anything_else_is_not_a_token():
    assert hosting_config.tunnel_token_from("hello") is None
    assert hosting_config.tunnel_token_from("eyJ" + "x" * 60) is None


def test_which_tunnel_a_token_is_for():
    assert hosting_config.tunnel_id(make_token("abc-123")) == "abc-123"


# ── Through the API ──────────────────────────────────────────────────────────


def _turn_on(client, **extra):
    body = {"on": True, "host": "goalgetter.acme.com", "front_door": "cloudflare", "tunnel_token": TOKEN}
    body.update(extra)
    return client.put("/api/hosting/https", json=body)


def test_turning_the_tunnel_on_hands_it_the_token(client, admin, env, tunnel_dir, caddy):
    reply = _turn_on(client)
    assert reply.status_code == 200, reply.text
    settings = reply.json()["settings"]
    assert settings["front_door"] == "cloudflare"
    assert settings["has_tunnel_token"] is True
    assert settings["tunnel_id"] == "6ff42ae2-765d-4adf-8112-31c55c1551ef"
    assert TOKEN not in reply.text
    assert (tunnel_dir / "token").read_text() == TOKEN
    assert oct((tunnel_dir / "token").stat().st_mode & 0o777) == "0o600"
    # Cloudflare serves HTTPS, so Caddy serves nothing.
    assert "https://" not in caddy[-1]
    # And .env says so.
    written = env_file.read()
    assert written["HTTPS_FRONT_DOOR"] == "cloudflare"
    assert written["CLOUDFLARE_TUNNEL_TOKEN"] == TOKEN
    assert written["HTTPS_HOST"] == "goalgetter.acme.com"


def test_the_saved_token_is_kept_when_none_is_sent(client, admin, env, tunnel_dir, caddy):
    _turn_on(client)
    reply = _turn_on(client, host="goals.acme.com", tunnel_token=None)
    assert reply.status_code == 200
    assert (tunnel_dir / "token").read_text() == TOKEN


def test_a_tunnel_needs_a_token(client, admin, caddy):
    reply = _turn_on(client, tunnel_token=None)
    assert reply.status_code == 400
    assert "token" in reply.json()["detail"]


def test_something_that_is_not_a_token_is_refused(client, admin, caddy):
    reply = _turn_on(client, tunnel_token="my-password")
    assert reply.status_code == 400
    assert "eyJ" in reply.json()["detail"]


def test_turning_it_off_stops_the_tunnel(client, admin, env, tunnel_dir, caddy):
    _turn_on(client)
    client.put("/api/hosting/https", json={"on": False, "front_door": "cloudflare"})
    assert (tunnel_dir / "token").read_text() == ""


def test_back_to_caddy_stops_the_tunnel(client, admin, env, tunnel_dir, caddy):
    _turn_on(client)
    reply = client.put("/api/hosting/https", json={"on": True, "host": "goals.internal", "certificate": "internal"})
    assert reply.status_code == 200
    assert (tunnel_dir / "token").read_text() == ""
    assert "https://goals.internal" in caddy[-1]


def test_the_windows_front_door_is_not_changed_here(client, admin, env, caddy, db):
    env_file.write({"HTTPS_HOST": "goals.internal", "HTTPS_FRONT_DOOR": "windows"})
    hosting_config.current(db)
    db.commit()
    reply = client.put("/api/hosting/https", json={"on": True, "host": "goals.internal"})
    assert reply.status_code == 400
    assert "Windows front door" in reply.json()["detail"]


def test_a_token_edited_in_the_file_reaches_the_tunnel(db, env, tunnel_dir, caddy, org):
    hosting_config.sync(db)
    env_file.write({
        "HTTPS_HOST": "goalgetter.acme.com", "HTTPS_FRONT_DOOR": "cloudflare", "CLOUDFLARE_TUNNEL_TOKEN": TOKEN,
    })
    hosting_config.reconcile(db)
    assert (tunnel_dir / "token").read_text() == TOKEN


# ── Whether it is connected ──────────────────────────────────────────────────


def _hosting(**overrides):
    fields = dict(
        on=True, host="goalgetter.acme.com", certificate="internal", front_door="cloudflare",
        dns_provider="", dns_api_token="", acme_email="", tunnel_token=TOKEN,
        https_port=8443, http_port=80, app_port=8080, env_connected=True,
    )
    fields.update(overrides)
    return hosting_config.Hosting(**fields)


def test_through_cloudflare_the_address_has_no_port():
    assert _hosting().https_address == "https://goalgetter.acme.com"


def test_off_when_no_tunnel_should_run():
    assert hosting_config.tunnel_status(_hosting(front_door=""))["state"] == "off"
    assert hosting_config.tunnel_status(_hosting(on=False))["state"] == "off"


def test_connected_with_its_connections(monkeypatch, tunnel_dir):
    connected(monkeypatch, 4)
    assert hosting_config.tunnel_status(_hosting()) == {"state": "connected", "connections": 4, "problem": None}


def test_the_service_not_running_is_said(tunnel_dir):
    status = hosting_config.tunnel_status(_hosting())
    assert status["state"] == "problem"
    assert "isn't running" in status["problem"]


def test_cloudflared_s_own_error_is_shown(tunnel_dir):
    (tunnel_dir / "alive").touch()
    (tunnel_dir / "cloudflared.log").write_text(
        "2026-10-07T09:00:00Z INF Starting tunnel tunnelID=6ff4\n"
        '2026-10-07T09:00:01Z ERR Unable to reach the origin service error="dial tcp: lookup web" connIndex=0\n'
    )
    status = hosting_config.tunnel_status(_hosting())
    assert status == {
        "state": "problem", "connections": 0,
        "problem": "Unable to reach the origin service: dial tcp: lookup web",
    }


def test_a_token_cloudflare_refuses_is_said_plainly(tunnel_dir):
    """As cloudflared said it for a made-up token, against Cloudflare itself."""
    (tunnel_dir / "alive").touch()
    (tunnel_dir / "cloudflared.log").write_text(
        '2026-10-06T22:43:21Z ERR Register tunnel error from server side error="Failed to get tunnel" '
        "connIndex=0 event=0 ip=198.41.192.37\n"
    )
    assert "doesn't accept this token" in hosting_config.tunnel_status(_hosting())["problem"]


def test_connecting_until_it_is(tunnel_dir):
    (tunnel_dir / "alive").touch()
    (tunnel_dir / "cloudflared.log").write_text("2026-10-07T09:00:00Z INF Starting tunnel\n")
    assert hosting_config.tunnel_status(_hosting())["state"] == "connecting"


def test_a_stale_heartbeat_means_not_running(tunnel_dir):
    alive = tunnel_dir / "alive"
    alive.touch()
    old = time.time() - 120
    os.utime(alive, (old, old))
    assert "isn't running" in hosting_config.tunnel_status(_hosting())["problem"]


def test_the_tv_port_moves_to_https_only_once_connected(monkeypatch, tunnel_dir, caddy, nginx):
    """Until the tunnel works, the plain address stays a full app — nobody is
    sent to an HTTPS address that doesn't answer yet."""
    hosting_config.apply(_hosting(), force=True)
    assert nginx.read_text() == 'set $gg_https_address "";\n'
    connected(monkeypatch)
    hosting_config.apply(_hosting())
    assert 'https://goalgetter.acme.com' in nginx.read_text()


def test_the_hosting_tab_shows_the_tunnel(client, admin, env, tunnel_dir, caddy, monkeypatch):
    _turn_on(client)
    connected(monkeypatch, 4)
    body = client.get("/api/hosting").json()
    assert body["tunnel"] == {"state": "connected", "connections": 4, "problem": None}
    assert body["certificate"] == "cloudflare"
    assert client.get("/api/hosting/tunnel").json()["state"] == "connected"
