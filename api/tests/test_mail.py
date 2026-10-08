"""Sending mail, and the rule that governs all of it.

**Email is an enhancement, never a dependency.** Every flow that sends one also
produces a link an admin can hand over, and that stays true with a mail server
configured — because a server that is down, misconfigured, or refusing the
from-address must not swallow an invitation. Nobody should be unable to join
because a relay was unhappy.

Most of what follows is that sentence, stated in a way that can fail.
"""

import smtplib

import pytest

from app import mail
from app.crypto import encrypt
from app.models import SmtpConfig


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


@pytest.fixture
def server(db, org):
    """A configured mail server, without one existing."""

    def _server(**kwargs):
        defaults = dict(
            organization_id=org.id,
            enabled=True,
            host="smtp.acme.test",
            port=587,
            security="starttls",
            username="bot@acme.com",
            password_encrypted=encrypt("shhh"),
            from_address="goalgetter@acme.com",
            from_name="GoalGetter",
        )
        defaults.update(kwargs)
        row = db.query(SmtpConfig).filter_by(organization_id=org.id).one_or_none()
        if row is None:
            row = SmtpConfig(**defaults)
            db.add(row)
        else:
            for key, value in defaults.items():
                setattr(row, key, value)
        db.flush()
        db.commit()
        return row

    return _server


@pytest.fixture
def relay(monkeypatch):
    """Stand in for a mail server, so the message can be inspected."""

    class Relay:
        def __init__(self, explode=None):
            self.explode = explode
            self.sent = []
            self.logged_in = None
            self.started_tls = False

        def __call__(self, host, port, timeout=None, context=None):
            self.host, self.port = host, port
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            self.started_tls = True

        def login(self, username, password):
            self.logged_in = (username, password)

        def send_message(self, message):
            if self.explode:
                raise self.explode
            self.sent.append(message)

    def _install(explode=None, ssl=False):
        made = Relay(explode)
        monkeypatch.setattr(mail.smtplib, "SMTP_SSL" if ssl else "SMTP", made)
        return made

    return _install


# ── Whether there is anything to try ─────────────────────────────────────────


def test_a_deployment_with_no_mail_server_says_it_did_not_try(db, org):
    """**Distinct from a failure, on purpose.** "We have not set this up" and "it
    did not work" need different words and lead to different pages."""
    result = mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert result.ok is False
    assert result.attempted is False
    assert "No mail server" in result.detail


def test_a_server_switched_off_is_not_used(db, org, server, relay):
    sent = relay()
    server(enabled=False)

    result = mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert result.attempted is False
    assert sent.sent == []


def test_a_relay_needing_no_password_is_usable(db, org, server):
    """**An internal relay that accepts anything from inside the network is a
    normal setup**, and demanding credentials it does not want would make the one
    configuration most likely to work impossible to save."""
    config = server(username="", password_encrypted=None, security="none")

    assert mail.usable(config) is True


def test_a_server_with_no_host_is_not_usable(db, org, server):
    assert mail.usable(server(host="")) is False


def test_a_server_with_no_from_address_is_not_usable(db, org, server):
    """Every server rejects a message with no sender, so this would fail once per
    invited person rather than once at save time."""
    assert mail.usable(server(from_address="")) is False


# ── The message ──────────────────────────────────────────────────────────────


def test_the_message_carries_the_from_name_and_address(db, org, server, relay):
    sent = relay()
    server()

    mail.send(db, org.id, to="sam@acme.com", subject="Hi", body="Hello")

    assert sent.sent[0]["From"] == "GoalGetter <goalgetter@acme.com>"
    assert sent.sent[0]["To"] == "sam@acme.com"
    assert sent.sent[0]["Subject"] == "Hi"


def test_a_display_name_with_a_comma_is_quoted(db, org, server, relay):
    """`formataddr` rather than an f-string. A comma in a display name splits the
    header into two recipients, which some servers reject and others deliver
    looking broken."""
    sent = relay()
    server(from_name="Acme, Inc.")

    mail.send(db, org.id, to="sam@acme.com", subject="Hi", body="Hello")

    assert sent.sent[0]["From"] == '"Acme, Inc." <goalgetter@acme.com>'


def test_a_display_name_that_is_not_ascii_is_encoded(db, org, server, relay):
    """RFC 2047, which `formataddr` does and an f-string does not. Raw bytes in a
    header are what some servers reject and others deliver as mojibake.

    **Asserted against the serialised message, not the header attribute.**
    `EmailMessage` decodes headers on read, so `message["From"]` hands back
    `Ünité <…>` however it is stored — which is exactly the sort of check that
    passes whether or not the encoding happened. What goes over SMTP is the bytes.
    """
    sent = relay()
    server(from_name="Ünité")

    mail.send(db, org.id, to="sam@acme.com", subject="Hi", body="Hello")

    headers = sent.sent[0].as_bytes().split(b"\n\n", 1)[0]

    # The property, not a particular encoding. Which of base64 or quoted-printable
    # the library picks is its business and has changed before; what must hold is
    # that the header is ASCII and the address survived intact.
    headers.decode("ascii")
    assert "Ünité".encode() not in headers
    assert b"<goalgetter@acme.com>" in headers


def test_no_display_name_sends_a_bare_address(db, org, server, relay):
    sent = relay()
    server(from_name="")

    mail.send(db, org.id, to="sam@acme.com", subject="Hi", body="Hello")

    assert sent.sent[0]["From"] == "goalgetter@acme.com"


# ── Connecting ───────────────────────────────────────────────────────────────


def test_starttls_upgrades_the_connection(db, org, server, relay):
    sent = relay()
    server(security="starttls")

    mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert sent.started_tls is True


def test_an_unencrypted_relay_is_not_upgraded(db, org, server, relay):
    """Named plainly rather than hidden, because somebody choosing it should have
    to choose it — but it has to actually work for an internal relay."""
    sent = relay()
    server(security="none")

    mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert sent.started_tls is False


def test_signing_in_only_happens_when_there_is_something_to_sign_in_with(
    db, org, server, relay
):
    """An empty AUTH is rejected outright by a relay that wants none."""
    sent = relay()
    server(username="", password_encrypted=None)

    mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert sent.logged_in is None


def test_the_stored_password_is_decrypted_before_use(db, org, server, relay):
    sent = relay()
    server()

    mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert sent.logged_in == ("bot@acme.com", "shhh")


# ── When it fails ────────────────────────────────────────────────────────────


def test_a_failure_is_reported_rather_than_raised(db, org, server, relay):
    """**The rule this module exists to keep.** A caller is in the middle of
    creating an invitation, and neither the invitation nor the request should fail
    because a relay refused a connection."""
    relay(explode=OSError("connection refused"))
    server()

    result = mail.send(db, org.id, to="a@b.com", subject="Hi", body="Hello")

    assert result.ok is False
    assert result.attempted is True


@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        (smtplib.SMTPAuthenticationError(535, b"nope"), "username or password"),
        (smtplib.SMTPSenderRefused(550, b"no", "x@y.com"), "from-address"),
        (smtplib.SMTPRecipientsRefused({}), "recipient"),
        (OSError("unreachable"), "Could not reach"),
    ],
)
def test_each_common_failure_says_what_to_fix(db, org, server, relay, problem, expected):
    """Three of these actually happen, and each has a different fix. The raw
    exception says so only to somebody who already knows."""
    relay(explode=problem)
    server()

    assert expected in mail.send(db, org.id, to="a@b.com", subject="Hi", body="H").detail


def test_an_unexpected_failure_still_says_something(db, org, server, relay):
    relay(explode=RuntimeError("something odd"))
    server()

    assert "RuntimeError" in mail.send(db, org.id, to="a@b.com", subject="H", body="H").detail


# ── Address sanity ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["a@b.com", "Name <a@b.co.uk>", "x.y+z@sub.acme.io"])
def test_a_plausible_address_passes(value):
    assert mail.looks_like_an_address(value) is True


@pytest.mark.parametrize("value", ["", "   ", "GoalGetter", "a@b", "@b.com"])
def test_something_that_is_not_an_address_is_caught(value):
    """Deliberately loose — the purpose is to catch a from-address somebody left
    blank or typed as a name. Deciding what a valid address *is* belongs to the
    mail server, which will say so."""
    assert mail.looks_like_an_address(value) is False


# ── The settings endpoint ────────────────────────────────────────────────────


def save(client, **changes):
    payload = {
        "enabled": False,
        "host": "smtp.acme.test",
        "port": 587,
        "security": "starttls",
        "username": "bot@acme.com",
        "from_address": "goalgetter@acme.com",
        "from_name": "GoalGetter",
    }
    payload.update(changes)
    return client.put("/api/admin/smtp", json=payload)


def test_the_password_is_never_returned(signed_in):
    body = signed_in.get("/api/admin/smtp").json()

    assert "password" not in body
    assert body["password_set"] is False


def test_saving_without_a_password_keeps_the_stored_one(signed_in, db, org, server):
    server()

    save(signed_in, host="smtp.new.test")

    db.expire_all()
    row = db.query(SmtpConfig).filter_by(organization_id=org.id).one()
    assert row.host == "smtp.new.test"
    assert row.password_encrypted is not None


def test_an_empty_password_clears_it(signed_in, db, org, server):
    """Which is how a relay wanting no authentication is configured after one that
    did — otherwise the old password would be sent to a server that rejects AUTH."""
    server()

    save(signed_in, password="")

    db.expire_all()
    assert db.query(SmtpConfig).filter_by(organization_id=org.id).one().password_encrypted is None


def test_it_cannot_be_switched_on_without_a_host(signed_in):
    response = save(signed_in, enabled=True, host="")

    assert response.status_code == 400
    assert "host" in response.json()["detail"]


def test_it_cannot_be_switched_on_without_a_real_from_address(signed_in):
    """**Refused at save time rather than once per invited person.** A blank sender
    produces a message every server rejects."""
    response = save(signed_in, enabled=True, from_address="GoalGetter")

    assert response.status_code == 400
    assert "from-address" in response.json()["detail"]


def test_a_connection_type_that_is_not_one_is_refused_by_name(signed_in):
    response = save(signed_in, security="carrier-pigeon")

    assert response.status_code == 400
    assert "carrier-pigeon" in response.json()["detail"]


def test_the_test_button_sends_to_the_admin_pressing_it(signed_in, admin, server, relay):
    """To *them*, not an address they type: the question is "does mail from here
    arrive", and their own inbox is the one they can go and check."""
    sent = relay()
    server()

    response = signed_in.post("/api/admin/smtp/test")

    assert response.json()["ok"] is True
    assert sent.sent[0]["To"] == admin.email


def test_the_test_button_says_so_when_nothing_is_configured(signed_in):
    response = signed_in.post("/api/admin/smtp/test")

    assert response.json()["ok"] is False
    assert "No mail server" in response.json()["detail"]


def test_only_an_admin_can_see_or_change_the_mail_settings(client, db, make_user, sign_in):
    agent = make_user("agent")
    sign_in(agent)
    db.commit()

    assert client.get("/api/admin/smtp").status_code == 403
    assert client.post("/api/admin/smtp/test").status_code == 403


# ── The two flows that use it ────────────────────────────────────────────────


def test_an_invitation_is_emailed_when_there_is_a_server(signed_in, server, relay):
    sent = relay()
    server()

    response = signed_in.post(
        "/api/users/invite",
        json={"email": "new@acme.com", "full_name": "New Person", "org_role": "agent"},
    )

    assert response.json()["emailed"] is True
    assert sent.sent[0]["To"] == "new@acme.com"
    # And the message carries the link, not just a mention of one.
    assert response.json()["invite_link"] in sent.sent[0].get_content()


def test_the_link_comes_back_even_when_the_mail_server_is_broken(
    signed_in, server, relay
):
    """**The rule, end to end.** An invitation must not be swallowed by a relay
    having a bad afternoon — the admin gets the link and can paste it into Slack,
    exactly as they would with no mail server at all."""
    relay(explode=OSError("connection refused"))
    server()

    response = signed_in.post(
        "/api/users/invite",
        json={"email": "new@acme.com", "full_name": "New Person", "org_role": "agent"},
    )

    assert response.status_code == 201
    assert response.json()["invite_link"].startswith("http")
    assert response.json()["emailed"] is False
    assert "Could not reach" in response.json()["email_detail"]


def test_a_deployment_with_no_mail_server_is_not_told_off_every_invitation(signed_in):
    """The normal case, not a problem to report. A red message on every invitation
    for a deployment that has deliberately never configured mail is noise that
    trains somebody to ignore the field."""
    response = signed_in.post(
        "/api/users/invite",
        json={"email": "new@acme.com", "full_name": "New Person", "org_role": "agent"},
    )

    assert response.json()["emailed"] is False
    assert response.json()["email_detail"] is None
    assert response.json()["invite_link"].startswith("http")


def test_a_reset_link_is_emailed_and_still_returned(signed_in, make_user, db, server, relay):
    sent = relay()
    server()
    person = make_user("agent")
    person.status = "active"
    db.commit()

    response = signed_in.post(f"/api/users/{person.id}/reset-password")

    assert response.json()["emailed"] is True
    assert response.json()["reset_link"].startswith("http")
    assert sent.sent[0]["To"] == person.email
