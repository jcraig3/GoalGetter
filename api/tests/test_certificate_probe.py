"""Reading the certificate an HTTPS address serves (Phase 19)."""

import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _certificate(tmp_path, until: datetime):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GoalGetter Local Authority")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1)).not_valid_after(until)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ))
    return cert_path, key_path


def test_it_reads_what_is_served(tmp_path, monkeypatch):
    monkeypatch.undo()  # the real knock, not conftest's stand-in
    from app import certificate_probe

    until = datetime(2027, 1, 12, 12, tzinfo=UTC)
    cert_path, key_path = _certificate(tmp_path, until)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def answer():
        conn, _ = server.accept()
        try:
            with context.wrap_socket(conn, server_side=True):
                pass
        except (ssl.SSLError, OSError):
            pass

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    try:
        found = certificate_probe._knock("127.0.0.1", port, "goals.internal")
    finally:
        server.close()
    assert found is not None
    assert found.valid_until == until
    assert found.issuer == "GoalGetter Local Authority"


def test_nothing_listening_is_none(monkeypatch):
    monkeypatch.undo()
    from app import certificate_probe

    with socket.create_server(("127.0.0.1", 0)) as spare:
        port = spare.getsockname()[1]
    assert certificate_probe._knock("127.0.0.1", port, "goals.internal") is None
