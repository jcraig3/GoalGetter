"""Gong and Aircall — the conversation platforms.

Both are "how much did this person actually talk to customers", which is a
leaderboard metric a lot of sales teams care about more than deal counts, because
it is the leading indicator rather than the trailing one.

Together in one file because they are the same shape twice: Basic auth where both
halves are secrets, a `since` on a modified-or-started timestamp, and rows under a
named key. Between them they were the reason `basic_password_field` exists.

**Neither has been run against a live account.** Same caveat as every REST
connector here: the shapes below are read from each provider's documentation, and
only the Test button against a real key proves the endpoint is the one they still
use.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.connectors import register
from app.connectors.rest import (
    AuthStyle,
    Paging,
    RestConnector,
    RestSpec,
)

# ── Gong ─────────────────────────────────────────────────────────────────────


class GongConfig(BaseModel):
    """Nothing varies per customer. Gong is one host for everybody.

    An empty config is worth keeping rather than collapsing away: the wizard's
    settings step renders from this schema, and a connector with no schema at all
    is a special case in the form code for the sake of one screen.
    """

    records: str = Field(
        default="calls",
        title="What to import",
        json_schema_extra={"enum": ["calls", "users"]},
    )


class GongSecrets(BaseModel):
    api_key: str = Field(
        default="",
        title="Access key",
        description="Company Settings → Ecosystem → API. Generated as a pair.",
    )
    api_secret: str = Field(
        default="",
        title="Access key secret",
        description="Shown once when the key is created.",
    )


GONG = RestSpec(
    base_url="https://api.gong.io",
    path="v2/{records}",
    provider_name="Gong",
    auth=AuthStyle(kind="basic", basic_password_field="api_secret"),
    # `size_param=""` on purpose: Gong pages by cursor and documents no
    # page-size parameter, so the engine must not invent one. Left at the default
    # this would have started sending `per_page`, which Gong never asked for —
    # caught by a test written while fixing the opposite bug on HubSpot.
    paging=Paging(
        kind="cursor",
        cursor_at="records.cursor",
        cursor_param="cursor",
        size_param="",
    ),
    rows_at="{records}",
    since_param="fromDateTime",
)


class GongConnector(RestConnector):
    setup_steps = (
        "In Gong: Company Settings → Ecosystem → API.",
        "Create an API key. Gong shows an access key and a secret — copy "
        "both now, as the secret is shown once.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="gong",
            display_name="Gong",
            spec=GONG,
            config_schema=GongConfig,
            credential_schema=GongSecrets,
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        from dataclasses import replace

        filled = super()._spec_for(config)
        values = config.model_dump()
        return replace(
            filled,
            path=filled.path.format(**values),
            rows_at=filled.rows_at.format(**values),
        )


# ── Aircall ──────────────────────────────────────────────────────────────────


class AircallConfig(BaseModel):
    records: str = Field(
        default="calls",
        title="What to import",
        json_schema_extra={"enum": ["calls", "users"]},
    )


class AircallSecrets(BaseModel):
    api_key: str = Field(
        default="",
        title="API ID",
        description="Dashboard → Integrations → API Keys. The first half of the pair.",
    )
    api_token: str = Field(
        default="",
        title="API token",
        description="The second half, shown when the key is created.",
    )


AIRCALL = RestSpec(
    base_url="https://api.aircall.io",
    path="v1/{records}",
    provider_name="Aircall",
    auth=AuthStyle(kind="basic", basic_password_field="api_token"),
    # Plain page numbers. Aircall also returns `meta.next_page_link`, which is a
    # full URL this engine will not follow — the row-count arithmetic in
    # `next_page_params` stops on a short page, which is the same answer.
    paging=Paging(kind="page", page_param="page", size_param="per_page", page_size=50),
    rows_at="{records}",
    # A Unix timestamp, and on `calls` it filters on when the call *started*.
    # Aircall has no modified-since, so an edit to an old call — a tag added, a
    # note written — does not come back. Worth knowing rather than hiding: the
    # numbers a leaderboard reads from a call are set when it happens.
    since_param="from",
    since_format="epoch",
)


class AircallConnector(RestConnector):
    setup_steps = (
        "In Aircall: Dashboard → Integrations & API → API Keys.",
        "Create an API key. Aircall shows an API ID and an API token — "
        "copy both.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="aircall",
            display_name="Aircall",
            spec=AIRCALL,
            config_schema=AircallConfig,
            credential_schema=AircallSecrets,
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        from dataclasses import replace

        filled = super()._spec_for(config)
        values = config.model_dump()
        return replace(
            filled,
            path=filled.path.format(**values),
            rows_at=filled.rows_at.format(**values),
        )


register(GongConnector())
register(AircallConnector())
