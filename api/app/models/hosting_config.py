from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class HostingConfig(Base, TimestampMixin):
    """How this deployment serves HTTPS, set in the app (Phase 20).

    One row: a deployment is one server. The API turns it into Caddy's
    configuration and pushes it live, and keeps the hosting lines of `.env`
    in step with it both ways — see `app/hosting_config.py`.
    """

    __tablename__ = "hosting_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: HTTPS on or off. Off keeps the name and certificate choice, so turning
    #: it back on is one switch.
    https_on: Mapped[bool] = mapped_column(Boolean, default=False)
    #: The name people type: goals.internal, goalgetter.company.com.
    https_host: Mapped[str] = mapped_column(String(253), default="")
    #: internal | letsencrypt | files
    certificate: Mapped[str] = mapped_column(String(16), default="internal")
    #: For `letsencrypt`: cloudflare | duckdns, its token (encrypted), and
    #: where Let's Encrypt sends expiry warnings.
    dns_provider: Mapped[str] = mapped_column(String(32), default="")
    dns_api_token_encrypted: Mapped[str | None] = mapped_column(Text)
    acme_email: Mapped[str] = mapped_column(String(320), default="")
    #: Who serves HTTPS instead of Caddy in Docker (Phase 21): "" (Caddy),
    #: `cloudflare` (a tunnel, run by the `tunnel` service with the token
    #: below) or `windows` (the Windows front door, set by its installer).
    front_door: Mapped[str] = mapped_column(String(16), default="")
    #: The Cloudflare tunnel's token, encrypted. A credential: never sent back.
    tunnel_token_encrypted: Mapped[str | None] = mapped_column(Text)
    #: The hosting lines of `.env` as they were last made to agree with the
    #: app. A line that differs from this now was edited in the file, and the
    #: file wins; a setting that differs was changed in the app, and it does.
    env_snapshot: Mapped[dict | None] = mapped_column(JSON)
    #: The settings before the last change, for Undo (Phase 22). Tokens stay
    #: encrypted in it, exactly as they were stored.
    previous: Mapped[dict | None] = mapped_column(JSON)
    #: While set, the last change is on trial: what worked before keeps
    #: working beside it, and it is undone by itself at this time unless kept.
    trial_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: When a trial nobody kept was undone by itself — for the Inbox (P7-5).
    #: Cleared by the next change.
    trial_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
