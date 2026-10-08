"""One notice, put away in both places (P4-9).

"No new numbers from Excel" is an Inbox item for each quiet source and, for
the same sources, one banner on Home. Putting it away in one place left it
showing in the other, which read as the dismissal not having worked.

So the two follow each other:

- putting Home's banner away puts away each of its sources in the Inbox;
- putting a source away in the Inbox puts Home's banner away once every quiet
  source it speaks for is put away — while one is still showing in the Inbox,
  the banner still has something true to say;
- bringing either back brings back the other.

Each side still keeps its own dismissal with its own fingerprint, so each
still comes back by itself when what it is about changes (`app/dismissals.py`).
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app import dismissals, periods
from app.models import Organization, UserAccount

BANNER = "data_stale"
ITEM = "source_quiet"


def _quiet_items(db: DbSession, org: Organization):
    from app import inbox

    return [item for item in inbox.build(db, org).items if item.kind == ITEM]


def put_away_together(
    db: DbSession, org: Organization, user: UserAccount, surface: str, key: str
) -> None:
    """After `key` was put away on `surface`: put away its twin, if it has one."""
    from app import dashboard

    if surface == "home" and key == BANNER:
        for item in _quiet_items(db, org):
            dismissals.dismiss(db, org, user, "inbox", item.mark())
    elif surface == "inbox" and key.startswith(f"{ITEM}:"):
        banner = next((a for a in dashboard.attention(db, org, user) if a.kind == BANNER), None)
        if banner is None:
            return
        db.flush()
        found = dismissals.current(db, user, "inbox")
        today = periods.today(org)
        if all(dismissals.holds(found.get(i.key), i.mark(), today) for i in _quiet_items(db, org)):
            dismissals.dismiss(db, org, user, "home", banner.mark())


def bring_back_together(db: DbSession, user: UserAccount, surface: str, key: str) -> None:
    """After `key` was brought back on `surface`: bring back its twin."""
    if surface == "home" and key == BANNER:
        dismissals.restore_matching(db, user, "inbox", f"{ITEM}:%")
    elif surface == "inbox" and key.startswith(f"{ITEM}:"):
        dismissals.restore(db, user, "home", BANNER)
