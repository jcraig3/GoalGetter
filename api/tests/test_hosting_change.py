"""A hosting change: checked, tried beside the old setup, then kept or undone
(Phase 22)."""

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import certificate_probe, env_file, hosting_checks, hosting_config
from app.models import HostingConfig

TOKEN = base64.b64encode(
    json.dumps({"a": "0123456789abcdef0123456789abcdef", "t": "6ff42ae2-765d-4adf", "s": "c2VjcmV0"}).encode()
).decode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("HTTPS_HOST=\nHTTPS_CERTIFICATE=internal\n", encoding="utf-8")
    monkeypatch.setattr(env_file, "ENV_FILE_PATH", str(path))
    return path


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
def tunnel_dir(tmp_path, monkeypatch):
    directory = tmp_path / "tunnel"
    directory.mkdir()
    monkeypatch.setattr(hosting_config, "TUNNEL_DIR", str(directory))
    return directory


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def put(client, **body):
    return client.put("/api/hosting/https", json=body)


def on_internal(client, host="goals.internal", trial=False):
    return put(client, on=True, host=host, certificate="internal", trial=trial)


# ── Undo ─────────────────────────────────────────────────────────────────────


def test_undo_goes_back_and_undo_again_comes_back(client, admin, env, caddy):
    on_internal(client, "first.internal")
    on_internal(client, "second.internal")
    reply = client.post("/api/hosting/undo")
    assert reply.status_code == 200
    assert reply.json()["settings"]["host"] == "first.internal"
    assert env_file.read()["HTTPS_HOST"] == "first.internal"
    assert client.post("/api/hosting/undo").json()["settings"]["host"] == "second.internal"


def test_what_undo_goes_back_to_is_shown(client, admin, env, caddy):
    on_internal(client, "first.internal")
    put(client, on=True, host="goals.acme.com", front_door="cloudflare", tunnel_token=TOKEN)
    undo_to = client.get("/api/hosting/https").json()["undo_to"]
    assert undo_to == {"on": True, "host": "first.internal", "choice": "internal", "redo": False}


def test_undo_can_be_tried_like_any_change(client, admin, env, caddy):
    on_internal(client, "first.internal")
    on_internal(client, "second.internal")
    reply = client.post("/api/hosting/undo", json={"trial": True})
    settings = reply.json()["settings"]
    assert settings["host"] == "first.internal"
    assert settings["trial_until"] is not None
    assert "https://second.internal" in caddy[-1] and "https://first.internal" in caddy[-1]


def test_nothing_to_undo_is_said(client, admin):
    assert client.post("/api/hosting/undo").status_code == 400


def test_an_edit_in_the_file_can_be_undone(db, env, org):
    hosting_config.save(db, https_on=True, https_host="goals.internal")
    env_file.write({"HTTPS_HOST": "edited.internal"})
    assert hosting_config.current(db).host == "edited.internal"
    assert hosting_config.undo(db).host == "goals.internal"
    assert env_file.read()["HTTPS_HOST"] == "goals.internal"


# ── A trial ──────────────────────────────────────────────────────────────────


def test_a_trial_serves_the_old_name_and_the_new(client, admin, env, caddy, nginx):
    on_internal(client, "old.internal")
    reply = on_internal(client, "new.internal", trial=True)
    assert reply.json()["settings"]["trial_until"] is not None
    assert "https://old.internal" in caddy[-1]
    assert "https://new.internal" in caddy[-1]
    # The old HTTPS name is the way back in, so the plain port stays TVs only.
    assert nginx.read_text() == 'set $gg_https_address "https://old.internal";\n'


def test_from_plain_http_the_plain_port_is_the_way_back_in(client, admin, env, caddy, nginx):
    on_internal(client, "new.internal", trial=True)
    assert nginx.read_text() == 'set $gg_https_address "";\n'


def test_keeping_it_drops_the_old_name(client, admin, env, caddy, nginx):
    on_internal(client, "old.internal")
    on_internal(client, "new.internal", trial=True)
    reply = client.post("/api/hosting/keep")
    assert reply.status_code == 200
    assert reply.json()["settings"]["trial_until"] is None
    assert "https://old.internal" not in caddy[-1]
    assert "https://new.internal" in caddy[-1]
    assert nginx.read_text() == 'set $gg_https_address "https://new.internal";\n'
    # Undo still goes back after keeping.
    assert reply.json()["settings"]["undo_to"]["host"] == "old.internal"


def test_undoing_a_trial_puts_the_old_setup_back(client, admin, env, caddy, nginx):
    on_internal(client, "old.internal")
    on_internal(client, "new.internal", trial=True)
    reply = client.post("/api/hosting/undo")
    assert reply.json()["settings"]["host"] == "old.internal"
    assert reply.json()["settings"]["trial_until"] is None
    assert "https://new.internal" not in caddy[-1]
    assert env_file.read()["HTTPS_HOST"] == "old.internal"
    assert nginx.read_text() == 'set $gg_https_address "https://old.internal";\n'


def test_one_name_has_one_certificate_the_new_one(client, admin, env, caddy, monkeypatch, tmp_path):
    on_internal(client, "goals.acme.com")
    put(
        client, on=True, host="goals.acme.com", certificate="letsencrypt",
        dns_provider="cloudflare", dns_api_token="tok_1", trial=True,
    )
    assert caddy[-1].count("https://goals.acme.com {") == 1
    assert "dns cloudflare tok_1" in caddy[-1]


def test_turning_https_off_on_trial_keeps_it_answering(client, admin, env, caddy, nginx):
    on_internal(client, "goals.internal")
    put(client, on=False, trial=True)
    assert "https://goals.internal" in caddy[-1]
    assert nginx.read_text() == 'set $gg_https_address "https://goals.internal";\n'
    client.post("/api/hosting/keep")
    assert "https://goals.internal" not in caddy[-1]


def test_a_tunnel_on_trial_runs_beside_caddy(client, admin, env, caddy, tunnel_dir):
    on_internal(client, "goals.internal")
    put(client, on=True, host="goals.acme.com", front_door="cloudflare", tunnel_token=TOKEN, trial=True)
    assert (tunnel_dir / "token").read_text() == TOKEN
    assert "https://goals.internal" in caddy[-1]
    client.post("/api/hosting/keep")
    assert "https://goals.internal" not in caddy[-1]


def test_leaving_a_tunnel_on_trial_keeps_it_running(client, admin, env, caddy, tunnel_dir):
    put(client, on=True, host="goals.acme.com", front_door="cloudflare", tunnel_token=TOKEN)
    on_internal(client, "goals.internal", trial=True)
    assert (tunnel_dir / "token").read_text() == TOKEN
    client.post("/api/hosting/keep")
    assert (tunnel_dir / "token").read_text() == ""


def test_changed_again_on_trial_it_is_still_a_trial_of_the_same_start(client, admin, env, caddy):
    on_internal(client, "old.internal")
    on_internal(client, "try1.internal", trial=True)
    on_internal(client, "try2.internal", trial=True)
    undo_to = client.get("/api/hosting/https").json()["undo_to"]
    assert undo_to["host"] == "old.internal"


def test_back_to_where_it_started_ends_the_trial(client, admin, env, caddy):
    on_internal(client, "old.internal")
    on_internal(client, "new.internal", trial=True)
    reply = on_internal(client, "old.internal", trial=True)
    assert reply.json()["settings"]["trial_until"] is None


def test_a_trial_nobody_keeps_is_undone_by_itself(db, env, caddy, org):
    hosting_config.save(db, https_on=True, https_host="old.internal")
    hosting_config.save(db, trial=True, https_host="new.internal")
    row = db.scalar(select(HostingConfig))
    row.trial_until = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    hosting_config.reconcile(db)
    current = hosting_config.current(db)
    assert current.host == "old.internal"
    assert not current.on_trial
    assert "https://new.internal" not in caddy[-1]


def test_an_edit_in_the_file_during_a_trial_is_a_new_trial(db, env, org):
    """P7-4: from the same start, so the old name stays up."""
    hosting_config.save(db, https_on=True, https_host="old.internal")
    hosting_config.save(db, trial=True, https_host="new.internal")
    env_file.write({"HTTPS_HOST": "file.internal"})
    current = hosting_config.current(db)
    assert current.host == "file.internal"
    assert current.on_trial
    assert current.undo_to.host == "old.internal"
    assert "https://old.internal" in hosting_config.caddyfile(current)


def test_edited_back_to_the_start_in_the_file_ends_the_trial(db, env, org):
    hosting_config.save(db, https_on=True, https_host="old.internal")
    hosting_config.save(db, trial=True, https_host="new.internal")
    env_file.write({"HTTPS_HOST": "old.internal"})
    assert not hosting_config.current(db).on_trial


def test_an_edit_in_the_file_is_in_activity(db, env, org):
    from app.models import AuditLog

    hosting_config.sync(db)
    env_file.write({"HTTPS_HOST": "file.internal"})
    hosting_config.current(db)
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "hosting.changed_in_env"))
    assert entry.actor_email == "GoalGetter"
    assert entry.details["host"] == "file.internal"


def test_a_trial_nobody_keeps_is_in_activity_and_the_inbox(db, env, caddy, org):
    from app import inbox
    from app.models import AuditLog

    hosting_config.save(db, https_on=True, https_host="old.internal")
    hosting_config.save(db, trial=True, https_host="new.internal")
    row = db.scalar(select(HostingConfig))
    row.trial_until = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    hosting_config.reconcile(db)
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "hosting.change_expired"))
    assert entry.details == {"tried": "new.internal", "back_to": "old.internal"}
    items = [i for i in inbox.build(db, org).items if i.kind == "hosting_change_undone"]
    assert len(items) == 1
    assert "new.internal" in items[0].title
    # The next change clears it.
    hosting_config.save(db, https_host="next.internal")
    assert not [i for i in inbox.build(db, org).items if i.kind == "hosting_change_undone"]


def test_after_an_undo_going_back_is_a_redo(client, admin, env, caddy):
    on_internal(client, "first.internal")
    on_internal(client, "second.internal")
    assert client.get("/api/hosting/https").json()["undo_to"]["redo"] is False
    client.post("/api/hosting/undo")
    assert client.get("/api/hosting/https").json()["undo_to"]["redo"] is True


def test_undo_is_refused_while_the_windows_front_door_is_set(client, admin, env, caddy, db):
    on_internal(client, "goals.internal")
    env_file.write({"HTTPS_FRONT_DOOR": "windows"})
    hosting_config.current(db)
    db.commit()
    reply = client.post("/api/hosting/undo")
    assert reply.status_code == 400
    assert "Windows front door" in reply.json()["detail"]


def test_the_front_door_not_answering_keeps_the_plain_port_open(monkeypatch, nginx, caddy, db, env, org):
    """P7-3: HTTPS_FRONT_DOOR=windows before the front door runs."""
    monkeypatch.setattr(certificate_probe, "served", lambda hosting, fresh=False: None)
    env_file.write({"HTTPS_HOST": "goals.internal", "HTTPS_FRONT_DOOR": "windows"})
    hosting_config.reconcile(db)
    assert nginx.read_text() == 'set $gg_https_address "";\n'
    monkeypatch.setattr(
        certificate_probe, "served",
        lambda hosting, fresh=False: certificate_probe.Served(valid_until=datetime.now(UTC), issuer="x"),
    )
    hosting_config.reconcile(db)
    assert nginx.read_text() == 'set $gg_https_address "https://goals.internal";\n'


def test_caddy_s_redirect_is_not_remembered_for_good():
    hosting = hosting_config.Hosting(
        on=True, host="goals.internal", certificate="internal", front_door="", dns_provider="",
        dns_api_token="", acme_email="", tunnel_token="", https_port=443, http_port=80, app_port=8080,
        env_connected=True,
    )
    assert "{uri} temporary" in hosting_config.caddyfile(hosting)


def test_keep_without_a_trial_is_said(client, admin):
    assert client.post("/api/hosting/keep").status_code == 400


def test_only_an_admin_keeps_or_undoes(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert client.post("/api/hosting/keep").status_code == 403
    assert client.post("/api/hosting/undo").status_code == 403
    assert client.post("/api/hosting/check", json={"on": False}).status_code == 403


# ── Checks before switching over ─────────────────────────────────────────────


@pytest.fixture
def dns(monkeypatch):
    table: dict[str, list[str]] = {}
    monkeypatch.setattr(hosting_checks, "resolve", lambda name: table.get(name))
    return table


def check(client, **body):
    reply = client.post("/api/hosting/check", json=body)
    assert reply.status_code == 200, reply.text
    return {c["key"]: c for c in reply.json()["checks"]}


def test_the_name_points_at_the_address_you_are_on(client, admin, dns):
    dns["goals.internal"] = ["192.168.1.5"]
    dns["192.168.1.5"] = ["192.168.1.5"]
    found = check(client, on=True, host="goals.internal", seen_at="192.168.1.5")["dns"]
    assert found["state"] == "ok"
    assert found["label"] == "goals.internal → 192.168.1.5"
    assert found["detail"] == "The address you're on"


def test_a_name_pointing_elsewhere_is_a_warning(client, admin, dns):
    dns["goals.internal"] = ["10.0.99.9"]
    dns["192.168.1.5"] = ["192.168.1.5"]
    found = check(client, on=True, host="goals.internal", seen_at="192.168.1.5")["dns"]
    assert found["state"] == "warn"
    assert "You're on 192.168.1.5" in found["detail"]


def test_a_name_not_in_dns_yet(client, admin, dns):
    found = check(client, on=True, host="goals.internal", seen_at="localhost")["dns"]
    assert found["state"] == "warn"
    assert "isn't in DNS yet" in found["label"]


def test_cloudflare_s_answer_on_the_token(client, admin, dns, monkeypatch):
    class Reply:
        def __init__(self, ok):
            self.status_code = 200 if ok else 401
            self.ok = ok

        def json(self):
            return {"success": self.ok, "result": {"status": "active"} if self.ok else None}

    monkeypatch.setattr("httpx.get", lambda *a, **k: Reply(True))
    body = dict(on=True, host="goals.acme.com", certificate="letsencrypt", dns_provider="cloudflare", dns_api_token="t")
    assert check(client, **body)["token"]["state"] == "ok"
    monkeypatch.setattr("httpx.get", lambda *a, **k: Reply(False))
    assert check(client, **body)["token"]["state"] == "fail"


def test_cloudflare_out_of_reach_is_only_a_warning(client, admin, dns, monkeypatch):
    import httpx

    def unreachable(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr("httpx.get", unreachable)
    body = dict(on=True, host="goals.acme.com", certificate="letsencrypt", dns_provider="cloudflare", dns_api_token="t")
    assert check(client, **body)["token"]["state"] == "warn"


def test_duckdns_names_end_in_duckdns(client, admin, dns):
    body = dict(on=True, host="goals.acme.com", certificate="letsencrypt", dns_provider="duckdns", dns_api_token="t")
    assert check(client, **body)["token"]["state"] == "fail"


def test_duckdns_checks_the_token_without_moving_the_name(client, admin, dns, monkeypatch):
    asked = {}

    class Reply:
        text = "OK"

    def get(url, params=None, **kwargs):
        asked.update(params)
        return Reply()

    monkeypatch.setattr("httpx.get", get)
    body = dict(on=True, host="acme.duckdns.org", certificate="letsencrypt", dns_provider="duckdns", dns_api_token="t")
    assert check(client, **body)["token"]["state"] == "ok"
    assert asked["domains"] == "acme" and asked["clear"] == "true" and "ip" not in asked


def test_certificate_files_must_cover_the_name(client, admin, dns, tmp_path, monkeypatch):
    from tests.test_hosting_config import _pem_pair

    monkeypatch.setattr(hosting_config, "CERTS_DIR", str(tmp_path))
    cert, _ = _pem_pair(name="*.acme.com")
    (tmp_path / "cert.pem").write_text(cert)
    assert check(client, on=True, host="goals.acme.com", certificate="files")["files"]["state"] == "ok"
    found = check(client, on=True, host="goals.internal", certificate="files")["files"]
    assert found["state"] == "fail" and "*.acme.com" in found["detail"]


def test_a_tunnel_token_is_checked(client, admin, dns):
    assert check(client, on=True, host="goals.acme.com", front_door="cloudflare", tunnel_token=TOKEN)[
        "tunnel_token"
    ]["state"] == "ok"
    assert check(client, on=True, host="goals.acme.com", front_door="cloudflare")["tunnel_token"]["state"] == "fail"


def test_off_has_nothing_to_check(client, admin):
    assert client.post("/api/hosting/check", json={"on": False}).json()["checks"] == []


def test_checking_changes_nothing(client, admin, db, dns, env, caddy):
    check(client, on=True, host="goals.internal")
    assert caddy == []
    assert env_file.read()["HTTPS_HOST"] == ""


# ── While it is tried ────────────────────────────────────────────────────────


def test_waiting_then_answering(client, admin, env, caddy, monkeypatch):
    on_internal(client, "old.internal")
    on_internal(client, "new.internal", trial=True)
    monkeypatch.setattr(certificate_probe, "served", lambda hosting, fresh=False: None)
    body = client.get("/api/hosting/trial").json()
    assert body["checks"][0]["state"] == "wait"
    assert body["trial_until"] is not None
    monkeypatch.setattr(
        certificate_probe, "served",
        lambda hosting, fresh=False: certificate_probe.Served(
            valid_until=datetime(2027, 1, 12, tzinfo=UTC), issuer="GoalGetter Local Authority"
        ),
    )
    found = client.get("/api/hosting/trial").json()["checks"][0]
    assert found == {
        "key": "served", "state": "ok",
        "label": "HTTPS answers · GoalGetter Local Authority", "detail": None,
    }


def test_a_tunnel_on_trial_says_whether_it_connected(client, admin, env, caddy, tunnel_dir, monkeypatch):
    put(client, on=True, host="goals.acme.com", front_door="cloudflare", tunnel_token=TOKEN, trial=True)
    monkeypatch.setattr(
        hosting_config, "tunnel_status", lambda h: {"state": "problem", "connections": 0, "problem": "nope"}
    )
    found = client.get("/api/hosting/trial").json()["checks"][0]
    assert (found["state"], found["detail"]) == ("fail", "nope")


def test_caddy_s_suffix_is_left_off_the_issuer():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GoalGetter Local Authority - ECC Intermediate")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(issuer).issuer_name(issuer).public_key(key.public_key())
        .serial_number(1).not_valid_before(now).not_valid_after(now + timedelta(hours=12))
        .sign(key, hashes.SHA256())
    )
    assert certificate_probe._issuer(cert) == "GoalGetter Local Authority"
