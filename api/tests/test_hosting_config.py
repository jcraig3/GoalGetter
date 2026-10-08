"""HTTPS set up in the app, with `.env` kept in step both ways (Phase 20)."""

import pytest
from sqlalchemy import select

from app import env_file, hosting_config
from app.models import HostingConfig

ENV = """# GoalGetter settings
COMPOSE_PATH_SEPARATOR=:
POSTGRES_PASSWORD=never-touched
APP_URL=http://localhost:8080
HTTPS_HOST=
HTTPS_CERTIFICATE=internal
DNS_PROVIDER=
DNS_API_TOKEN=
ACME_EMAIL=
TRUSTED_PROXY_HOPS=1
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(ENV, encoding="utf-8", newline="\n")
    monkeypatch.setattr(env_file, "ENV_FILE_PATH", str(path))
    return path


@pytest.fixture
def caddy(monkeypatch):
    pushed = []
    monkeypatch.setattr(hosting_config, "push_to_caddy", lambda text: pushed.append(text) or None)
    hosting_config._last.clear()
    return pushed


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def lines(path) -> dict[str, str]:
    return env_file.read(str(path))


# ── The file itself ──────────────────────────────────────────────────────────


def test_only_the_named_lines_change(env):
    env_file.write({"HTTPS_HOST": "goals.internal", "NEW_ONE": "x"})
    text = env.read_text(encoding="utf-8")
    assert "HTTPS_HOST=goals.internal\n" in text
    assert "POSTGRES_PASSWORD=never-touched" in text
    assert text.startswith("# GoalGetter settings\n")
    assert text.endswith("NEW_ONE=x\n")


def test_windows_line_endings_are_kept(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"A=1\r\nHTTPS_HOST=\r\n")
    env_file.write({"HTTPS_HOST": "goals.internal"}, str(path))
    assert path.read_bytes() == b"A=1\r\nHTTPS_HOST=goals.internal\r\n"


def test_a_line_break_is_refused(env):
    with pytest.raises(ValueError):
        env_file.write({"HTTPS_HOST": "a\nPOSTGRES_PASSWORD=stolen"})


# ── Both ways ────────────────────────────────────────────────────────────────


def test_saved_in_the_app_is_written_to_the_file(db, env, org):
    hosting_config.save(db, https_on=True, https_host="goals.internal", certificate="internal")
    assert lines(env)["HTTPS_HOST"] == "goals.internal"
    assert lines(env)["POSTGRES_PASSWORD"] == "never-touched"


def test_edited_in_the_file_shows_up_in_the_app(db, env, org):
    hosting_config.sync(db)  # agree once
    env_file.write({"HTTPS_HOST": "goals.internal", "HTTPS_CERTIFICATE": "letsencrypt"})
    current = hosting_config.current(db)
    assert (current.on, current.host, current.certificate) == (True, "goals.internal", "letsencrypt")


def test_whichever_changed_last_wins(db, env, org):
    hosting_config.save(db, https_on=True, https_host="first.internal")
    env_file.write({"HTTPS_HOST": "second.internal"})
    assert hosting_config.current(db).host == "second.internal"
    hosting_config.save(db, https_host="third.internal")
    assert lines(env)["HTTPS_HOST"] == "third.internal"
    assert hosting_config.current(db).host == "third.internal"


def test_emptying_the_name_in_the_file_turns_https_off_and_keeps_the_name(db, env, org):
    hosting_config.save(db, https_on=True, https_host="goals.internal")
    env_file.write({"HTTPS_HOST": ""})
    current = hosting_config.current(db)
    assert current.on is False
    assert db.scalar(select(HostingConfig)).https_host == "goals.internal"


def test_nonsense_in_the_file_is_ignored_not_saved(db, env, org):
    hosting_config.sync(db)
    env_file.write({"HTTPS_HOST": "not a name!", "HTTPS_CERTIFICATE": "whatever"})
    current = hosting_config.current(db)
    assert current.host == ""
    assert current.certificate == "internal"


def test_the_web_address_and_proxy_follow_too(db, env, org):
    hosting_config.sync(db)
    env_file.write({"WEB_ADDRESS": "https://goals.acme.example", "TRUSTED_PROXY_HOPS": "2"})
    hosting_config.current(db)
    db.refresh(org)
    assert org.public_url == "https://goals.acme.example"
    assert org.proxy_mode == "proxy"


def test_app_url_is_the_fallback_never_an_override(db, env, org):
    """P7-1: APP_URL moved with APP_PORT must not beat HTTPS."""
    from app import public_url

    env_file.write({"APP_URL": "http://localhost:8090"})
    hosting_config.sync(db)
    db.refresh(org)
    assert org.public_url is None
    assert public_url.get(db) == "http://localhost:8090"
    hosting_config.save(db, https_on=True, https_host="goals.internal")
    assert public_url.get(db) == "https://goals.internal"
    assert "WEB_ADDRESS" not in lines(env) or lines(env)["WEB_ADDRESS"] == ""


def test_an_install_from_before_has_its_copied_address_cleared(db, env, org):
    """Phases 20–22 copied APP_URL onto the Advanced address. Once."""
    env_file.write({"APP_URL": "http://localhost:8090"})
    org.public_url = "http://localhost:8090"
    row = hosting_config._row(db)
    row.env_snapshot = {"APP_URL": "http://localhost:8090", "HTTPS_HOST": ""}
    db.flush()
    hosting_config.sync(db)
    db.refresh(org)
    assert org.public_url is None
    assert "APP_URL" not in hosting_config._row(db).env_snapshot


def test_an_address_an_admin_chose_is_kept_across_that(db, env, org):
    env_file.write({"APP_URL": "http://localhost:8090"})
    org.public_url = "https://goals.acme.example"
    row = hosting_config._row(db)
    row.env_snapshot = {"APP_URL": "http://localhost:8090", "HTTPS_HOST": ""}
    db.flush()
    hosting_config.sync(db)
    db.refresh(org)
    assert org.public_url == "https://goals.acme.example"
    assert lines(env)["WEB_ADDRESS"] == "https://goals.acme.example"


def test_app_url_edited_needs_no_restart(env):
    env_file.write({"APP_URL": "http://server:8090"})
    assert hosting_config.app_url() == "http://server:8090"


def test_the_token_is_stored_encrypted(db, env, org):
    hosting_config.save(db, dns_api_token="cf-token-123")
    row = db.scalar(select(HostingConfig))
    assert "cf-token-123" not in (row.dns_api_token_encrypted or "")
    assert lines(env)["DNS_API_TOKEN"] == "cf-token-123"


def test_without_the_file_the_app_works_alone(db, org):
    current = hosting_config.save(db, https_on=True, https_host="goals.internal")
    assert current.https_address == "https://goals.internal"
    assert current.env_connected is False


def test_before_the_first_sign_in_the_web_address_stays_the_file_s(db, env):
    """A fresh install has no organisation yet: nowhere to keep WEB_ADDRESS."""
    env_file.write({"WEB_ADDRESS": "https://goals.acme.example", "APP_URL": "http://localhost:8090"})
    hosting_config.sync(db)
    assert lines(env)["WEB_ADDRESS"] == "https://goals.acme.example"
    from app.models import Organization

    org = Organization(name="Acme")
    db.add(org)
    db.flush()
    hosting_config.sync(db)
    db.refresh(org)
    assert org.public_url == "https://goals.acme.example"
    assert lines(env)["APP_URL"] == "http://localhost:8090"


# ── A .env the app can read but not write (P7-2) ─────────────────────────────


@pytest.fixture
def read_only(env, monkeypatch):
    monkeypatch.setattr(env_file, "writable", lambda path=None: False)
    return env


def test_a_read_only_file_is_still_followed(db, read_only, org, caddy):
    """The documented way out — empty HTTPS_HOST= — works."""
    hosting_config.save(db, https_on=True, https_host="goals.internal")
    hosting_config.sync(db)
    env_file.write({"HTTPS_HOST": "other.internal"}, str(read_only))
    assert hosting_config.current(db).host == "other.internal"
    env_file.write({"HTTPS_HOST": ""}, str(read_only))
    assert hosting_config.current(db).https_on is False


def test_the_app_s_changes_stand_while_the_file_can_t_be_written(db, read_only, org):
    hosting_config.sync(db)
    hosting_config.save(db, https_on=True, https_host="goals.internal")
    current = hosting_config.current(db)
    assert current.host == "goals.internal"
    assert lines(read_only)["HTTPS_HOST"] == ""
    assert (current.env_readable, current.env_connected) == (True, False)


def test_the_first_meeting_keeps_what_the_file_set(db, env, org):
    """An install that set HTTPS in .env before Phase 20 keeps it."""
    env_file.write({"HTTPS_HOST": "goals.internal"})
    assert hosting_config.current(db).host == "goals.internal"


# ── Caddy's configuration ────────────────────────────────────────────────────


def _hosting(**overrides):
    fields = dict(
        on=True, host="goals.internal", certificate="internal", front_door="",
        dns_provider="", dns_api_token="", acme_email="", tunnel_token="",
        https_port=443, http_port=80, app_port=8080, env_connected=True,
    )
    fields.update(overrides)
    return hosting_config.Hosting(**fields)


def test_it_always_keeps_the_admin_socket():
    """Without it Caddy's admin would move back to its default, out of reach."""
    for hosting in (_hosting(), _hosting(on=False)):
        assert "admin unix/" in hosting_config.caddyfile(hosting)


def test_off_serves_nothing():
    assert "https://" not in hosting_config.caddyfile(_hosting(on=False))


def test_a_front_door_outside_docker_means_caddy_serves_nothing():
    assert "https://" not in hosting_config.caddyfile(_hosting(front_door="windows"))


@pytest.mark.parametrize(
    ("certificate", "expected"),
    [
        ("internal", "tls internal"),
        ("files", "tls /certs/cert.pem /certs/key.pem"),
    ],
)
def test_the_certificate_line(certificate, expected):
    assert expected in hosting_config.caddyfile(_hosting(certificate=certificate))


def test_lets_encrypt_carries_the_provider_and_token():
    text = hosting_config.caddyfile(
        _hosting(certificate="letsencrypt", dns_provider="cloudflare", dns_api_token="tok_1", acme_email="it@acme.com")
    )
    assert "tls it@acme.com {" in text
    assert "dns cloudflare tok_1" in text


def test_a_port_other_than_443_is_in_the_redirect():
    assert "redir https://goals.internal:8443{uri}" in hosting_config.caddyfile(_hosting(https_port=8443))


def test_nginx_is_told_the_https_address():
    assert hosting_config.nginx_conf(_hosting()) == 'set $gg_https_address "https://goals.internal";\n'
    assert hosting_config.nginx_conf(_hosting(on=False)) == 'set $gg_https_address "";\n'


# ── Through the API ──────────────────────────────────────────────────────────


def test_turning_https_on_applies_it(client, db, env, admin, caddy):
    reply = client.put("/api/hosting/https", json={"on": True, "host": "goals.internal", "certificate": "internal"})
    assert reply.status_code == 200
    assert reply.json()["problem"] is None
    assert reply.json()["settings"]["host"] == "goals.internal"
    assert "https://goals.internal" in caddy[-1]
    assert lines(env)["HTTPS_HOST"] == "goals.internal"


@pytest.mark.parametrize("host", ["https://goals.internal", "goals.internal:8443", "goals internal", ""])
def test_a_bad_name_is_refused_in_words(client, admin, caddy, host):
    reply = client.put("/api/hosting/https", json={"on": True, "host": host})
    assert reply.status_code == 400
    assert caddy == []


def test_lets_encrypt_needs_a_provider_and_a_token(client, admin, caddy):
    reply = client.put("/api/hosting/https", json={
        "on": True, "host": "goalgetter.acme.com", "certificate": "letsencrypt", "dns_provider": "cloudflare",
    })
    assert reply.status_code == 400
    assert "token" in reply.json()["detail"]


def test_the_token_is_never_sent_back(client, admin, caddy):
    client.put("/api/hosting/https", json={
        "on": True, "host": "goalgetter.acme.com", "certificate": "letsencrypt",
        "dns_provider": "cloudflare", "dns_api_token": "tok_1",
    })
    body = client.get("/api/hosting/https").json()
    assert body["has_dns_api_token"] is True
    assert "tok_1" not in str(body)


def test_caddy_s_refusal_is_said(client, admin, monkeypatch):
    monkeypatch.setattr(hosting_config, "push_to_caddy", lambda text: "adapting config: bad thing")
    reply = client.put("/api/hosting/https", json={"on": True, "host": "goals.internal"})
    assert reply.json()["problem"] == "adapting config: bad thing"


def test_only_an_admin_sets_https(client, make_user, sign_in):
    sign_in(make_user("manager"))
    assert client.put("/api/hosting/https", json={"on": False}).status_code == 403


# ── Certificate files uploaded in the browser ────────────────────────────────


def _pem_pair(*, days: int = 90, name: str = "goals.acme.com") -> tuple[str, str]:
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=200))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM).decode(),
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
    )


@pytest.fixture
def certs_dir(tmp_path, monkeypatch):
    directory = tmp_path / "certs"
    monkeypatch.setattr(hosting_config, "CERTS_DIR", str(directory))
    return directory


def test_a_certificate_and_its_key_are_saved(client, admin, caddy, certs_dir):
    cert, key = _pem_pair()
    reply = client.post("/api/hosting/certificate", json={"certificate": cert, "key": key})
    assert reply.status_code == 200
    assert reply.json()["files"]["names"] == ["goals.acme.com"]
    assert (certs_dir / "cert.pem").read_text() == cert
    assert (certs_dir / "key.pem").stat().st_mode & 0o077 == 0
    # And now "files" can be chosen.
    reply = client.put("/api/hosting/https", json={"on": True, "host": "goals.acme.com", "certificate": "files"})
    assert reply.status_code == 200
    assert "tls /certs/cert.pem /certs/key.pem" in caddy[-1]


def test_files_cannot_be_chosen_before_they_are_uploaded(client, admin, caddy, certs_dir):
    reply = client.put("/api/hosting/https", json={"on": True, "host": "goals.acme.com", "certificate": "files"})
    assert reply.status_code == 400


def test_someone_else_s_key_is_refused(client, admin, certs_dir):
    cert, _ = _pem_pair()
    _, other_key = _pem_pair()
    reply = client.post("/api/hosting/certificate", json={"certificate": cert, "key": other_key})
    assert reply.status_code == 400
    assert "belong" in reply.json()["detail"]
    assert not certs_dir.exists()


def test_an_expired_certificate_is_refused(client, admin, certs_dir):
    cert, key = _pem_pair(days=-1)
    reply = client.post("/api/hosting/certificate", json={"certificate": cert, "key": key})
    assert reply.status_code == 400
    assert "expired" in reply.json()["detail"]


def test_not_a_certificate_is_refused(client, admin, certs_dir):
    _, key = _pem_pair()
    reply = client.post("/api/hosting/certificate", json={"certificate": "hello", "key": key})
    assert reply.status_code == 400
