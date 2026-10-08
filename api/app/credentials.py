"""Reading and writing a source's secrets.

The only module that touches `connector_credential.secrets_encrypted`. Everything
else asks for a dict and gets one, or hands over a dict and forgets about it —
which is the point: a secret that only exists in plaintext inside one small module
is a secret with one place to audit.

**Secrets are never returned to a client.** Not masked, not partially shown — the
API answers "a secret is set" with a boolean, the same way `sso_config` reports
`client_secret_set`. There is no legitimate reason for a browser to receive a
token back, and every mechanism that offers to show one is a mechanism that can
be made to.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import crypto
from app.models import ConnectorCredential, DataSource


def put(
    db: DbSession,
    source: DataSource,
    secrets: dict[str, object],
    *,
    expires_at: datetime | None = None,
) -> ConnectorCredential:
    """Store this source's secrets, replacing whatever was there.

    Replace rather than merge. A token refresh that merged would leave a stale
    `refresh_token` behind when a provider rotates it, and the failure mode of
    that is an integration which works until the access token expires and then
    cannot renew — days later, with nothing in the logs from the day it broke.

    `expires_at` is stored in the clear on purpose: the scheduler asks "does this
    need refreshing before I use it?" every pass, and decrypting every credential
    to answer that would be both slow and needless exposure.
    """
    row = db.scalar(
        select(ConnectorCredential).where(
            ConnectorCredential.data_source_id == source.id
        )
    )
    blob = crypto.encrypt(json.dumps(secrets))

    if row is None:
        row = ConnectorCredential(
            data_source_id=source.id, secrets_encrypted=blob, expires_at=expires_at
        )
        db.add(row)
    else:
        row.secrets_encrypted = blob
        row.expires_at = expires_at
    db.flush()
    return row


def get(db: DbSession, source: DataSource) -> dict[str, object]:
    """This source's secrets, decrypted. `{}` when none are stored.

    An empty dict rather than None for the no-credential case, so a connector
    that needs no secrets — a public sheet, an inbound webhook — reads the same
    as one whose secrets are missing. A connector that *does* need them fails on
    the missing key, in its own `test_connection`, with a message naming what is
    absent.

    A `ValueError` from here means `ENCRYPTION_KEY` no longer matches what stored
    the value. That is deliberately not caught: an unreadable secret treated as
    absent would present a mis-keyed deployment as a misconfigured integration,
    and somebody would spend an afternoon re-entering credentials that were fine.
    """
    row = db.scalar(
        select(ConnectorCredential).where(
            ConnectorCredential.data_source_id == source.id
        )
    )
    if row is None:
        return {}
    return json.loads(crypto.decrypt(row.secrets_encrypted))


def expires_at(db: DbSession, source: DataSource) -> datetime | None:
    """When this source's stored credential lapses, or None if it does not.

    Read **without decrypting anything** — which is the whole reason `expires_at`
    lives in the clear beside the ciphertext. The scheduler asks this on every
    pass, and decrypting every credential to find out whether it needs renewing
    would be both slow and needless exposure.

    None covers two cases that behave the same: no credential at all, and a
    credential the provider gave no lifetime for. Neither is due for renewal.
    """
    return db.scalar(
        select(ConnectorCredential.expires_at).where(
            ConnectorCredential.data_source_id == source.id
        )
    )


def has_secrets(db: DbSession, source: DataSource) -> bool:
    """Whether anything is stored, without decrypting it.

    What the API reports instead of the secret itself. Deliberately does not
    verify that the ciphertext is readable — that would mean decrypting on every
    page load, and an unreadable secret is a key problem that surfaces the moment
    a sync runs, with a much better error than a boolean could carry.
    """
    return (
        db.scalar(
            select(ConnectorCredential.id).where(
                ConnectorCredential.data_source_id == source.id
            )
        )
        is not None
    )


def forget(db: DbSession, source: DataSource) -> bool:
    """Remove this source's secrets. Returns whether there were any.

    Used when disconnecting an account without deleting the source and the facts
    it collected — the source stays, disabled, with its history intact and no
    usable credential left behind.
    """
    row = db.scalar(
        select(ConnectorCredential).where(
            ConnectorCredential.data_source_id == source.id
        )
    )
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
