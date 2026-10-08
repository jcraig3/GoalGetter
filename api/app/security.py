from typing import Annotated

import bcrypt
from pydantic import AfterValidator, Field

# Deliberately slow. SHA-256 is designed to be fast, which is exactly wrong for
# passwords — it makes brute-forcing a stolen hash dump fast too. bcrypt's cost
# factor is tunable, so hashing stays expensive as hardware improves.
#
# 12 is roughly 250ms per hash on current hardware: unnoticeable at login,
# painful at scale for an attacker.
BCRYPT_ROUNDS = 12

# bcrypt silently truncates input beyond 72 bytes. Left unchecked, two long
# passwords sharing their first 72 bytes would be interchangeable at login.
# Rejecting is safer than silently ignoring the tail.
MAX_PASSWORD_BYTES = 72


#: **The one password rule** (11.4), for every form that sets one: setup,
#: invitations, changes, resets and temporary passwords. Length over
#: character-class rules — current guidance is to require length and screen
#: against common passwords, not to demand a symbol and a digit, which mostly
#: produces "Password1!". Mirrored in `web/src/passwordRule.ts`.
MIN_PASSWORD_LENGTH = 12


def _fits_bcrypt(password: str) -> str:
    # Bytes, not characters: 72 accented letters are more than 72 bytes, and
    # `hash_password` would refuse them with a 500 rather than a sentence.
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Passwords can be at most {MAX_PASSWORD_BYTES} characters.")
    return password


#: A password being set, as a request field.
NewPassword = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH), AfterValidator(_fits_bcrypt)]


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes.")
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time comparison, handled inside bcrypt.checkpw."""
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        # Malformed or empty hash — e.g. an SSO-only account with no password.
        return False
