"""Symmetric encryption for secrets that must be stored and read back.

Used for values the app has to *use* later — an OIDC client secret, a Snowflake
password. That is fundamentally different from a password, which is only ever
compared and so gets a one-way hash instead. If you can decrypt it, it is not a
password; if you can only compare it, it must not be encrypted.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


@lru_cache
def _cipher() -> Fernet:
    """Fernet, keyed by a hash of ENCRYPTION_KEY.

    Fernet rather than raw AES because it is authenticated (AES-128-CBC plus
    HMAC) and has no options to get wrong — no IV to reuse, no mode to pick
    badly. Hand-rolled AES is where encryption bugs live.

    The env var is hashed to derive the key so operators can supply any
    sufficiently long random string instead of having to produce Fernet's
    exact 32-byte urlsafe-base64 format. SHA-256 is fine here: the input is
    already high-entropy random, so there is nothing to brute-force.
    """
    raw = get_settings().encryption_key.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt(plaintext: str) -> str:
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Raises ValueError if the value was not encrypted with the current key.

    That happens when ENCRYPTION_KEY is rotated or lost. Failing loudly is
    correct — silently treating an unreadable secret as absent would make the
    app look misconfigured rather than mis-keyed.
    """
    try:
        return _cipher().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Could not decrypt. ENCRYPTION_KEY does not match the value used "
            "to store this secret."
        ) from exc
