"""Where this deployment is, for every link that leaves the app.

**Set in Settings, not only in a file** (decided 6 Oct). GoalGetter is hosted
by whoever runs it, often on an office server, and asking them to edit `.env`
and restart a container to change an address was the wrong door. So an admin
sets it under Settings → General, where the page offers the address their
browser is using; `APP_URL` from the environment is only the default until
they do.

One deployment is one organization (setup refuses a second), so the address
is that organization's and is read from its row.

**What follows it:** Microsoft and Google redirect addresses (which must match
what is registered with them, so changing this means updating them there),
TV links, webhook URLs, scheduled emails, and invite and reset links. Those
last two follow the admin's own browser when nothing is set — see
`tokens.base_url`.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import get_settings
from app.models import Organization


def default(db: DbSession | None = None) -> str:
    """What applies until an admin sets one: the HTTPS address when HTTPS is
    on (Phase 13), else `APP_URL`.

    HTTPS on means Caddy is answering at the HTTPS name, so that is where the
    app is — making somebody also change `APP_URL` to match would be a second
    place to forget. `APP_URL` is read from `.env` as it is now (Phase 23).
    """
    from app import hosting_config

    return https_address(db) or hosting_config.app_url()


def https_address(db: DbSession | None = None) -> str | None:
    """https://<name>, with the port when it is not 443; None when off.

    From the app's hosting settings where a session is to hand (Phase 20),
    else the environment it was started with.
    """
    if db is not None:
        from app import hosting_config

        return hosting_config.current(db, sync_first=False).https_address
    settings = get_settings()
    if not settings.https_on:
        return None
    port = "" if settings.https_port == 443 else f":{settings.https_port}"
    return f"https://{settings.https_host}{port}"


def chosen(db: DbSession) -> str | None:
    """What an admin set in Settings, or None."""
    value = db.scalar(select(Organization.public_url).order_by(Organization.id).limit(1))
    return value or None


def get(db: DbSession) -> str:
    """The address to build links from: the admin's choice, else `APP_URL`."""
    return chosen(db) or default(db)


def is_https(db: DbSession) -> bool:
    """For a cookie's Secure flag."""
    return get(db).startswith("https")


def normalise(value: str) -> str:
    """An address as stored: scheme and host (and port), nothing after.

    Raises ValueError with a sentence for the admin. A path is refused rather
    than kept: the app is served from the root, and a path here would put
    every link one directory off.
    """
    text = value.strip().rstrip("/")
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("Enter the full address, starting with http:// or https://.")
    if parts.path or parts.query or parts.fragment:
        raise ValueError("Just the address, with nothing after it — like https://goals.example.com.")
    if parts.username or parts.password:
        raise ValueError("The address cannot contain a username or password.")
    return f"{parts.scheme}://{parts.netloc.lower()}"
