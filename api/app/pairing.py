"""Codes a person can read off a television and type with a remote.

**The alphabet is the interesting part.** A pairing code is read across a room,
possibly at an angle, by somebody who then types it on an on-screen keyboard
with four arrow keys. Every character that can be misread is a support call:
`0` and `O`, `1` and `I` and `l`, `5` and `S`, `8` and `B`. They are all gone,
and the remainder is upper case only so nobody wonders whether case matters.

That leaves 27 characters and 531,441 four-character codes, which is plenty:
codes live for ten minutes and are unique among the ones currently waiting, so
the question is never "can this be guessed" — it is "can two screens in one
building show the same four characters", and they cannot.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

__all__ = [
    "ALPHABET",
    "CODE_LENGTH",
    "LIFETIME",
    "MAX_WAITING",
    "new_code",
    "new_secret",
    "expired_before",
    "normalise",
]

#: No `0O 1IL 5S 8B`, and upper case only. See the note above.
ALPHABET = "ACDEFGHJKMNPQRTUVWXYZ234679"

CODE_LENGTH = 4

#: How long a code is good for.
#:
#: Long enough to walk from the television to a laptop and sign in; short
#: enough that a screen left on a pairing page overnight is not still offering
#: itself in the morning.
LIFETIME = timedelta(minutes=10)

#: How many pairings may be waiting at once, across the whole deployment.
#:
#: **A bound rather than a rate limit.** Asking for a code needs no account —
#: a television has none — so the endpoint is open, and the failure worth
#: preventing is somebody filling the code space so that the four characters an
#: admin reads belong to a screen they do not own. A cap makes that impossible
#: rather than merely slow, and no honest deployment has fifty televisions
#: being set up in the same ten minutes.
MAX_WAITING = 50


def new_code() -> str:
    """Four characters somebody can read and type."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def new_secret() -> str:
    """What the screen polls with. Never displayed, never typed."""
    return secrets.token_urlsafe(32)


def expired_before(now: datetime) -> datetime:
    """The cutoff: anything created before this has expired."""
    return now - LIFETIME


def normalise(code: str) -> str:
    """What somebody typed, as the code they meant.

    Upper-cased and stripped of spaces, because a person reading four
    characters aloud says them in pairs and types them that way.
    """
    return "".join(code.split()).upper()
