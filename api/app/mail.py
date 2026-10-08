"""Sending mail, when a deployment has somewhere to send it from.

**Email is an enhancement, never a dependency**, and that rule shapes everything
here. Every flow that sends a message also produces a link an admin can hand over,
and it keeps producing one with a mail server configured — because a mail server
that is down, misconfigured, or rejecting the from-address must not swallow an
invitation. Nobody should be unable to join because a relay was unhappy.

So `send` **reports** rather than raises. The caller records what happened and shows
the link either way.

## What is worth testing without a server

Building the message and deciding whether a configuration can be used at all — both
pure, both easy to get subtly wrong, and both here as functions rather than buried
inside the send. The socket work is the part a unit test cannot prove anything
about; the part that decides whether an address is malformed, or whether a display
name needs encoding, is not.
"""

from __future__ import annotations

import logging
import smtplib
import ssl as ssl_module
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import mail_graph as graph
from app.crypto import decrypt
from app.models import SmtpConfig

logger = logging.getLogger(__name__)

#: How long to wait on a mail server.
#:
#: Short, because somebody is usually watching: this runs inside the request that
#: creates an invitation, and a relay that takes half a minute to answer has already
#: failed as far as that person is concerned. The invitation still exists either way.
TIMEOUT = 10.0


@dataclass(frozen=True)
class Sent:
    """What happened, phrased for the admin who pressed the button."""

    ok: bool
    detail: str

    #: False when there was nothing to try — no mail server configured. Distinct
    #: from a failure on purpose: "we have not set this up" and "it did not work"
    #: need different words and lead to different pages.
    attempted: bool = True


def config_for(db: DbSession, organization_id: int) -> SmtpConfig | None:
    """The mail settings, read fresh.

    Deliberately not cached, like the SSO settings and for the same reason: an
    admin who has just fixed a host expects the next invitation to use it.
    """
    return db.scalar(
        select(SmtpConfig).where(SmtpConfig.organization_id == organization_id)
    )


def can_send(db: DbSession, organization_id: int) -> bool:
    """Whether anything is set up to send mail: Microsoft or SMTP.

    For a page deciding what to offer — "Forgot password?" emails a link, so
    with nowhere to send from it says to ask an admin instead.
    """
    if graph.configured(db, organization_id) is not None:
        return True
    return usable(config_for(db, organization_id))


def usable(config: SmtpConfig | None) -> bool:
    """Whether there is enough here to attempt a send.

    A host and a from-address, and switched on. **A username and password are not
    required**: an internal relay that accepts anything from inside the network is a
    normal and correct setup, and demanding credentials it does not want would make
    the one configuration most likely to work impossible to save.
    """
    return bool(
        config
        and config.enabled
        and config.host.strip()
        and config.from_address.strip()
    )


def build(config: SmtpConfig, *, to: str, subject: str, body: str) -> EmailMessage:
    """One message, ready to send.

    `formataddr` rather than an f-string: a display name containing a comma or a
    non-ASCII character has to be quoted and encoded, and getting that wrong
    produces a header some servers reject and others deliver looking broken.
    """
    message = EmailMessage()
    message["From"] = formataddr((config.from_name.strip() or None, config.from_address.strip()))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    return message


def looks_like_an_address(value: str) -> bool:
    """A cheap sanity check, not validation.

    Deliberately loose. The purpose is to catch a from-address somebody left blank
    or typed as a name, which is a mistake worth refusing at save time. Deciding
    what a valid address *is* belongs to the mail server, which will say so.
    """
    _, address = parseaddr(value or "")
    local, _, domain = address.rpartition("@")
    # A local part is required, not just an `@` somewhere: `@acme.com` parses
    # happily and is nobody's address. Caught by a test written for the opposite
    # case.
    return bool(local) and "." in domain


def send(
    db: DbSession, organization_id: int, *, to: str, subject: str, body: str
) -> Sent:
    """Send one message, and say what happened.

    **Never raises.** The caller is in the middle of creating an invitation or a
    reset link, and neither should fail because a relay refused a connection — the
    link exists and works regardless.

    **Microsoft first, when it is switched on.** A deployment that has connected a
    tenant account has already told us which mailbox to send as, and going through
    Graph avoids asking an Exchange admin for SMTP AUTH — which Microsoft now
    disables by default and many tenants will not re-enable. SMTP stays as the
    path for everyone else, and as the fallback for a Microsoft send that fails.
    """
    through_graph = graph.configured(db, organization_id)
    if through_graph is not None:
        sent = graph.send(db, through_graph, to=to, subject=subject, body=body)
        if sent.ok:
            return sent
        # Fall through rather than stopping. A tenant that has both configured has
        # said twice that it wants mail out, and refusing to try the second one
        # because the first failed would be a worse reading of that.
        logger.info("mail: Microsoft send failed, trying SMTP: %s", sent.detail)

    config = config_for(db, organization_id)
    if not usable(config):
        return Sent(
            ok=False,
            attempted=False,
            detail=(
                "No mail server is configured and no Microsoft account is set to "
                "send, so nothing was sent."
            ),
        )
    assert config is not None

    try:
        _deliver(config, build(config, to=to, subject=subject, body=body))
    except Exception as problem:  # noqa: BLE001 — reported, never raised
        # Logged in full, reported in a sentence. An SMTP error can quote the
        # recipient and the whole envelope, which is more than belongs on a page
        # somebody else might be looking at.
        logger.warning("mail: send to %s failed", to, exc_info=problem)
        return Sent(ok=False, detail=_describe(problem))

    return Sent(ok=True, detail=f"Sent to {to}.")


def _deliver(config: SmtpConfig, message: EmailMessage) -> None:
    password = decrypt(config.password_encrypted) if config.password_encrypted else ""
    host, port = config.host.strip(), config.port

    if config.security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            host, port, timeout=TIMEOUT, context=ssl_module.create_default_context()
        )
    else:
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)

    with server:
        if config.security == "starttls":
            server.starttls(context=ssl_module.create_default_context())
        # Only when there is something to log in with. An internal relay that
        # accepts unauthenticated mail rejects an empty AUTH outright.
        if config.username.strip() and password:
            server.login(config.username.strip(), password)
        server.send_message(message)


def _describe(problem: Exception) -> str:
    """A mail failure, in words an admin can act on.

    The three that actually happen get their own sentence, because each has a
    different fix and the raw exception says so only to somebody who already knows.
    """
    if isinstance(problem, smtplib.SMTPAuthenticationError):
        return "The mail server rejected the username or password."
    if isinstance(problem, smtplib.SMTPSenderRefused):
        return (
            "The mail server refused the from-address. It usually has to be an "
            "address that server is allowed to send as."
        )
    if isinstance(problem, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the recipient's address."
    if isinstance(problem, TimeoutError | OSError):
        return (
            "Could not reach the mail server. Check the host, the port, and "
            "whether this server is allowed to connect to it."
        )
    return f"The mail server refused the message ({type(problem).__name__})."
