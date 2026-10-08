from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration from environment variables.

    Validated once at startup. A missing value stops the container with a clear
    message, which is far better than starting and misbehaving later.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Public URL of the app. The OIDC redirect URI is built from this and must
    # match what is registered with the identity provider exactly — providers
    # reject a mismatch rather than guessing.
    app_url: str = "http://localhost:8080"

    # Python's root logger defaults to WARNING, which silently discards every
    # logger.info() in the codebase — including the security-relevant ones
    # (rejected sign-in flows, failed token exchanges). Set explicitly so the
    # logging we write actually reaches the log.
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Whose `X-Forwarded-For` we believe.
    #
    # An IP allowlist on a wall display is only as good as the address it
    # compares against, and behind nginx the socket peer is the *proxy* — so
    # the real client is only knowable from a header. A header a client can
    # set is a header a client can forge, which is why this is a list rather
    # than a boolean: the header is read only when the connection itself came
    # from one of these.
    #
    # Defaults to the private ranges, which is right for the shipped compose
    # file where nginx and the API share a Docker network. Narrow it if the API
    # is ever reachable from a private network you do not control — on that
    # network, anyone could otherwise claim any address.
    trusted_proxy_ips: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8"

    # How many proxies append to `X-Forwarded-For` before the API sees it.
    #
    # One for the shipped compose file: nginx, and nothing in front of it. Put
    # a load balancer or a CDN ahead of nginx and this becomes 2 — each of them
    # appends, and the client is that many places from the end.
    #
    # A count rather than an inspection because inspection does not work: on
    # Docker the real client arrives from a private address too, so "the first
    # hop that is not a known proxy" happily returns a forged one. See
    # `net.real_client_ip`.
    trusted_proxy_hops: int = 1

    # Addresses that are never a visitor, beside Docker's own gateway, which is
    # found by itself (`net.docker_gateways`). For a host that puts every
    # device behind one address of its own — a NAT or a VPN in front. Sign-in
    # limits treat them as unknown rather than as one visitor (P6-1).
    unknown_visitor_ips: str = ""

    # Which public client the automatic Entra setup signs in as.
    #
    # Empty means Microsoft's own command-line client, which exists in every
    # tenant and is why that setup needs nothing registered in advance — see
    # `providers.Bootstrap`. Set this to an application id of your own if your
    # tenant restricts Microsoft's tooling, which some do: the registration only
    # has to be a public client allowing the device code flow.
    entra_bootstrap_client_id: str = ""

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # Encrypts secrets the app must read back — the OIDC client secret today,
    # connector credentials later.
    #
    # Deliberately separate from anything session-related: rotating a session
    # key is routine and merely logs everyone out, while rotating this one
    # means re-encrypting every stored secret. Sharing one key would make the
    # routine operation dangerous.
    encryption_key: str = Field(min_length=32)

    # How long a session lasts without activity. Sliding: using the app extends
    # it, so an active user is not logged out mid-task.
    session_lifetime_days: int = 7

    # Send the session cookie over HTTPS only. Must be true in production —
    # over plain HTTP the cookie is readable by anything on the network.
    # False locally because development runs on http://localhost.
    secure_cookies: bool = False

    # ── HTTPS (Phase 13) ─────────────────────────────────────────────────────
    # Read from the same .env the `https` service uses, so the app knows what
    # Caddy is doing without asking it. See documentation/20-hosting.md.
    #
    # The name Caddy serves.
    https_host: str = ""
    # Compose's own setting, read so the app agrees with whether Caddy is
    # actually running: HTTPS is on only with `https` among these profiles.
    compose_profiles: str = ""
    https_port: int = 443
    # The plain-HTTP port Caddy answers on, for the root certificate download.
    http_port: int = 80
    # internal | letsencrypt | files
    https_certificate: str = "internal"
    # nginx's own published port: still plain HTTP, for TVs.
    app_port: int = 8080
    # Who handles HTTPS when it is not Caddy in Docker: `windows` (the front
    # door on the Windows host, Phase 17) or `cloudflare` (a Cloudflare
    # tunnel, Phase 18). HTTPS is then on without the `https` profile.
    https_front_door: str = ""

    @property
    def https_on(self) -> bool:
        """Caddy is running in front, answering at `https_host`."""
        profiles = {p.strip() for p in self.compose_profiles.split(",")}
        return bool(self.https_host) and ("https" in profiles or bool(self.https_front_door))

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once, not per request."""
    return Settings()  # pyright: ignore[reportCallIssue]
