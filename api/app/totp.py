"""Two-step sign-in with an authenticator app — TOTP, RFC 6238.

The same six-digit codes Microsoft Authenticator, Google Authenticator, 1Password
and the rest produce: HMAC-SHA1 over the count of 30-second steps since the
epoch, from a secret shared once through a QR code. Written out here rather than
taken from a library because it is twenty lines of the standard and nothing else,
and a self-hosted deployment should not need a package to check six digits.

**A code is accepted once.** The step it matched is remembered, so a code read
over somebody's shoulder cannot be replayed inside its 30 seconds.

**One step either side.** A phone a few seconds out, or a code typed just as it
changed, still works — the tolerance every authenticator expects.

**Recovery codes are one-use and stored hashed.** They are random and long, so
a fast hash is right for them (unlike a password): the point is that a copy of
the database does not hand them over.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

__all__ = [
    "RECOVERY_CODES",
    "hash_recovery",
    "matching_step",
    "new_recovery_codes",
    "new_secret",
    "otpauth_uri",
]

STEP_SECONDS = 30
DIGITS = 6
#: Steps either side still accepted.
WINDOW = 1
RECOVERY_CODES = 10


def new_secret() -> str:
    """160 random bits, base32 — what every authenticator app expects."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def code_now(secret: str, *, at: float | None = None) -> str:
    """The current code — for tests, and nothing else."""
    return _code_at(secret, int((at if at is not None else time.time()) // STEP_SECONDS))


def matching_step(
    secret: str, code: str, *, after_step: int | None = None, at: float | None = None
) -> int | None:
    """The step a code matches, or None. A step at or before `after_step` —
    the last one used — does not count, which is what stops a replay."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = int((at if at is not None else time.time()) // STEP_SECONDS)
    for step in range(now - WINDOW, now + WINDOW + 1):
        if after_step is not None and step <= after_step:
            continue
        if hmac.compare_digest(_code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, *, account: str, issuer: str) -> str:
    """What the QR code holds: the standard `otpauth://totp/` link."""
    label = quote(f"{issuer}:{account}")
    query = urlencode({"secret": secret, "issuer": issuer, "digits": DIGITS, "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"


def new_recovery_codes() -> list[str]:
    """Ten `xxxx-xxxx` codes, lowercase and without look-alike characters."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return [
        "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))
        for _ in range(RECOVERY_CODES)
    ]


def hash_recovery(code: str) -> str:
    """How a recovery code is stored. Normalised first, so "ABCD EFGH" and
    "abcd-efgh" are the same code."""
    clean = "".join(ch for ch in (code or "").lower() if ch.isalnum())
    return hashlib.sha256(clean.encode()).hexdigest()
