"""OpenID Connect Authorization Code flow with PKCE.

The shape of the flow, and what each piece defends against:

    /sso/start
      generate state, nonce, code_verifier
      stash them in a short-lived encrypted cookie
      redirect the browser to the provider

    provider authenticates the user, redirects back with ?code&state

    /sso/callback
      state must match the cookie          -> blocks CSRF / injected logins
      exchange code + code_verifier        -> blocks a stolen code being reused
      verify id_token signature via JWKS   -> blocks a forged token
      nonce must match                     -> blocks replay of an old token
      then, and only then, trust the claims
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from app.crypto import decrypt, encrypt

DISCOVERY_PATH = "/.well-known/openid-configuration"
HTTP_TIMEOUT = 10.0

# How long the user has to complete sign-in at the provider before the stashed
# state expires. Long enough for a password plus MFA prompt, short enough that
# a leaked cookie is not useful later.
FLOW_TTL_SECONDS = 600

# Discovery documents change very rarely, and refetching one on every sign-in
# adds a round trip to the provider before the user sees anything.
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_DISCOVERY_TTL = 3600.0

# PyJWKClient keeps its own cache of the provider's signing keys, so one client
# per JWKS URL avoids refetching them on every login.
_jwk_clients: dict[str, PyJWKClient] = {}


@dataclass
class FlowState:
    """The three values that must survive the round trip to the provider."""

    state: str
    nonce: str
    code_verifier: str


def discover(issuer: str) -> dict[str, Any]:
    """Fetch (and cache) the provider's OIDC metadata."""
    cached = _discovery_cache.get(issuer)
    if cached and time.monotonic() - cached[0] < _DISCOVERY_TTL:
        return cached[1]

    response = httpx.get(
        f"{issuer.rstrip('/')}{DISCOVERY_PATH}",
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    document = response.json()
    _discovery_cache[issuer] = (time.monotonic(), document)
    return document


def _jwk_client(jwks_uri: str) -> PyJWKClient:
    if jwks_uri not in _jwk_clients:
        _jwk_clients[jwks_uri] = PyJWKClient(jwks_uri, cache_keys=True)
    return _jwk_clients[jwks_uri]


def new_flow_state() -> FlowState:
    return FlowState(
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64),
    )


def _code_challenge(verifier: str) -> str:
    """S256 challenge: the SHA-256 of the verifier, base64url without padding.

    PKCE exists because an authorization code can be intercepted. The provider
    only ever sees this hash; redeeming the code requires the original
    verifier, which never left our server. A stolen code is therefore useless.
    """
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def authorization_url(
    document: dict[str, Any],
    client_id: str,
    redirect_uri: str,
    scopes: str,
    flow: FlowState,
) -> str:
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": flow.state,
        "nonce": flow.nonce,
        "code_challenge": _code_challenge(flow.code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{document['authorization_endpoint']}?{urlencode(params)}"


def seal_flow(flow: FlowState, next_path: str) -> str:
    """Encrypt the flow state for the browser to hold between the two requests.

    Encrypted rather than plain: the cookie holds the code_verifier, and anyone
    who can read it plus intercept the code could complete the exchange. Fernet
    is authenticated, so a tampered cookie fails to decrypt rather than
    silently changing the state we compare against.
    """
    return encrypt(
        json.dumps(
            {
                "state": flow.state,
                "nonce": flow.nonce,
                "verifier": flow.code_verifier,
                "next": next_path,
                "exp": time.time() + FLOW_TTL_SECONDS,
            }
        )
    )


def open_flow(sealed: str) -> tuple[FlowState, str]:
    """Reverse of seal_flow. Raises ValueError if tampered or expired."""
    data = json.loads(decrypt(sealed))
    if data.get("exp", 0) < time.time():
        raise ValueError("Sign-in took too long. Please try again.")
    return (
        FlowState(
            state=data["state"], nonce=data["nonce"], code_verifier=data["verifier"]
        ),
        data.get("next") or "/",
    )


def exchange_code(
    document: dict[str, Any],
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    client_secret: str,
    code_verifier: str,
) -> dict[str, Any]:
    response = httpx.post(
        document["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        # The provider's error body can contain the client secret we just sent
        # back to us in some implementations, so only the code is surfaced.
        raise ValueError(f"Token exchange failed (HTTP {response.status_code}).")
    return response.json()


def verify_id_token(
    document: dict[str, Any],
    id_token: str,
    *,
    client_id: str,
    issuer: str,
    nonce: str,
) -> dict[str, Any]:
    """Validate the ID token and return its claims.

    Every check here matters:

      signature — proves the provider issued it, not the browser
      audience  — proves it was issued for THIS app, not another one that
                  happens to use the same provider
      issuer    — proves it came from the tenant we configured
      expiry    — handled by PyJWT
      nonce     — proves it belongs to the sign-in we just started, so an old
                  captured token cannot be replayed

    Decoding without verification is the single most common OIDC mistake: the
    claims are attacker-controlled until the signature is checked.
    """
    signing_key = _jwk_client(document["jwks_uri"]).get_signing_key_from_jwt(id_token)

    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=document.get("id_token_signing_alg_values_supported", ["RS256"]),
        audience=client_id,
        issuer=issuer,
        options={"require": ["exp", "iat", "aud", "iss", "sub"]},
    )

    if claims.get("nonce") != nonce:
        raise ValueError("Token nonce did not match this sign-in attempt.")

    return claims
