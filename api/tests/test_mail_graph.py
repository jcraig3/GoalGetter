"""Sending mail as a mailbox in the customer's own tenant.

**Nothing signs in for this.** Client credentials, like the directory sync — so
the application registration and its consent are the whole setup, which is the
property the whole integration is built around.

What is worth pinning is what it refuses to pretend:

* the mailbox is **nominated, never defaulted** — an application has no mailbox of
  its own, so guessing would mean a first invitation failing on an address nobody
  chose;
* mail stays an enhancement, so a failure is reported and the caller carries on
  producing a link somebody can hand over;
* a 403 gets its own sentence, because Graph's `ErrorAccessDenied` names neither
  the mailbox nor the Application Access Policy refusing it.

**The permission is broad and the tests say so rather than hiding it.**
`Mail.Send` as an application permission can send as any mailbox in the tenant.
Exchange is where that gets narrowed — see the panel, which generates the policy.
"""

import httpx
import pytest

from app import mail, mail_graph
from app.crypto import encrypt
from app.models import OauthClient, SmtpConfig

REAL_CLIENT = httpx.Client


@pytest.fixture
def connection(db, org):
    def _connect(**kwargs):
        defaults = dict(
            organization_id=org.id,
            provider="microsoft",
            client_id="the-app",
            client_secret_encrypted=encrypt("shhh"),
            tenant_id="contoso.onmicrosoft.com",
            mail_enabled=True,
            mail_from="bookings@acme.com",
        )
        defaults.update(kwargs)
        row = OauthClient(**defaults)
        db.add(row)
        db.flush()
        return row

    return _connect


@pytest.fixture
def graph(monkeypatch):
    """Graph and the token endpoint, both answering."""

    def _install(status=202):
        asked: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            asked.append(request)
            if request.url.path.endswith("/oauth2/v2.0/token"):
                return httpx.Response(200, json={"access_token": "fresh"})
            return httpx.Response(status, json={} if status < 300 else {"error": {}})

        transport = httpx.MockTransport(handle)

        class Shim:
            Response = httpx.Response
            RequestError = httpx.RequestError

            @staticmethod
            def post(url, **kw):
                with REAL_CLIENT(transport=transport) as talker:
                    return talker.post(url, **kw)

        monkeypatch.setattr(mail_graph, "httpx", Shim)
        return asked

    return _install


def mail_request(asked):
    return next(r for r in asked if "sendMail" in str(r.url))


# ── Sending ──────────────────────────────────────────────────────────────────


def test_it_sends_as_the_nominated_mailbox(db, connection, graph):
    """**The mailbox is in the URL, and that is the security boundary.** Exchange
    decides whether the connected account may send as this address and answers 403
    when it may not — so the restriction is the customer's own configuration
    rather than a promise we make."""
    row = connection(mail_from="bookings@acme.com")
    asked = graph()

    sent = mail_graph.send(db, row, to="new@acme.com", subject="Hi", body="Link")

    assert sent.ok is True
    assert "sendMail" in str(mail_request(asked).url)
    assert "bookings@acme.com" in str(mail_request(asked).url)


def test_no_mailbox_named_refuses_rather_than_guessing(db, connection, graph):
    """An application has no mailbox of its own, so there is nothing sensible to
    fall back to. Reported rather than raised, because the caller is part-way
    through creating an invitation whose link works regardless."""
    row = connection(mail_from="")
    graph()

    sent = mail_graph.send(db, row, to="a@b.com", subject="s", body="b")

    assert sent.ok is False
    assert sent.attempted is False

def test_a_403_names_the_mailbox_and_the_policy(db, connection, graph):
    """Graph's own word for this is `ErrorAccessDenied`, which names neither the
    mailbox nor the Application Access Policy that is refusing it."""
    row = connection(mail_from="ceo@acme.com")
    graph(status=403)

    sent = mail_graph.send(db, row, to="a@b.com", subject="s", body="b")

    assert sent.ok is False
    assert "ceo@acme.com" in sent.detail
    # The policy that would be refusing it, which is the half to act on.
    assert "Application Access Policy" in sent.detail


def test_nothing_is_sent_when_the_switch_is_off(db, org, connection):
    """Three separate decisions — an application registered, an account connected,
    and somebody choosing to send this way. A connection existing says nothing
    about the third."""
    connection(mail_enabled=False)

    assert mail_graph.configured(db, org.id) is None


def test_nothing_is_sent_without_a_nominated_mailbox(db, org, connection):
    """An application has no mailbox of its own, so there is nothing to fall back
    to — and a send attempted against a guess fails on an address nobody chose."""
    connection(mail_enabled=True, mail_from="")

    assert mail_graph.configured(db, org.id) is None


def test_a_connection_ready_to_send_is_found(db, org, connection):
    """The positive half, so the two refusals above cannot pass by returning None
    for a reason nobody intended — which is exactly what they did while they asked
    about organization 1 instead of this one."""
    row = connection(mail_enabled=True)

    assert mail_graph.configured(db, org.id) is row


# ── How `mail.send` chooses ──────────────────────────────────────────────────


def test_microsoft_is_preferred_when_it_is_configured(db, org, connection, graph):
    """A deployment that has connected an account has already said which mailbox to
    send as, and Graph avoids needing SMTP AUTH at all."""
    connection(mail_from="bookings@acme.com")
    asked = graph()

    sent = mail.send(db, org.id, to="a@b.com", subject="s", body="b")

    assert sent.ok is True
    assert any("sendMail" in str(r.url) for r in asked)


def test_smtp_is_tried_when_microsoft_refuses(db, org, connection, graph):
    """**Falls through rather than stopping.** A tenant with both configured has
    said twice that it wants mail out, and refusing the second because the first
    failed would be a worse reading of that."""
    connection(mail_from="ceo@acme.com")
    graph(status=403)
    db.add(
        SmtpConfig(
            organization_id=org.id,
            enabled=True,
            host="smtp.acme.com",
            port=587,
            security="starttls",
            username="u",
            from_address="noreply@acme.com",
            from_name="Acme",
        )
    )
    db.flush()

    sent = mail.send(db, org.id, to="a@b.com", subject="s", body="b")

    # SMTP is unreachable in a test, so this is not `ok` — the point is that it
    # was *attempted*, which is what falling through means.
    assert sent.attempted is True
    assert "Application Access Policy" not in sent.detail


def test_neither_configured_says_so_without_raising(db, org):
    """Mail is an enhancement, never a dependency: the caller is part-way through
    creating an invitation whose link works regardless."""
    sent = mail.send(db, org.id, to="a@b.com", subject="s", body="b")

    assert sent.ok is False
    assert sent.attempted is False
    assert "Microsoft" in sent.detail
