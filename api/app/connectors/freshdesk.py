"""Freshdesk: tickets, as the first provider on the REST engine.

**Chosen first among the REST providers because it has no OAuth.** Its credential
is a plain API key, so the engine gets proven against a real provider's paging and
filtering without a consent flow in the way — the same reason webhook came before
SQL, and SQL before OAuth.

The whole connector is a spec and two small models. That is the point: if adding
Freshdesk had needed a request loop, a paging rule and a retry policy of its own,
the twenty-odd providers after it would each need theirs too.

**Verify the specifics against Freshdesk's current documentation before trusting
this against a live account.** The shape below reflects how their v2 API works —
Basic auth with the key as the username, `updated_since` for the window, numbered
pages — but a provider's endpoint names and defaults are exactly the sort of thing
that changes without anybody telling us, and no unit test can notice. The Test
button reports their own words, which is where a mismatch will show up.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.connectors import register
from app.connectors.rest import (
    ApiKey,
    AuthStyle,
    Paging,
    RestConnector,
    RestSpec,
)


class FreshdeskConfig(BaseModel):
    """Which Freshdesk account, and which records.

    Only the subdomain is genuinely per-customer; everything else about the
    provider lives in the spec below and nobody should have to know it.
    """

    domain: str = Field(
        default="",
        title="Freshdesk domain",
        description=(
            "Just the first part of your Freshdesk address. For "
            "acme.freshdesk.com, that is 'acme'."
        ),
        examples=["acme"],
    )

    #: Which endpoint to read.
    #:
    #: A choice rather than a fixed value because the two answer different
    #: questions — tickets measure work handled, contacts measure accounts touched
    #: — and both are things a sales or support leaderboard is built on.
    records: str = Field(
        default="tickets",
        title="What to import",
        json_schema_extra={"enum": ["tickets", "contacts", "companies"]},
    )


class FreshdeskKey(ApiKey):
    """The API key from an agent's profile settings.

    Inherits the field so every REST provider spells its credential the same way,
    which is what lets the engine read it without knowing whose it is.
    """

    api_key: str = Field(
        default="",
        title="API key",
        description=(
            "Found under your Freshdesk profile settings. It has the permissions "
            "of the agent it belongs to, so a key from an account that can see "
            "every ticket is the one to use."
        ),
    )


#: How to read Freshdesk.
#:
#: `updated_since` rather than `created_since`, and that is the field worth
#: checking twice: a ticket opened last month and resolved today has to come back,
#: and a filter on the creation date never returns it. The same trap the SQL
#: connector refuses a query for.
FRESHDESK = RestSpec(
    base_url="https://{domain}.freshdesk.com/api/v2",
    path="{records}",
    provider_name="Freshdesk",
    auth=AuthStyle(kind="basic", basic_password="X"),
    paging=Paging(kind="page", page_param="page", size_param="per_page", page_size=100),
    # The response is the array itself for these endpoints, so no path to dig.
    rows_at="",
    since_param="updated_since",
    since_format="iso",
    # Oldest first, so a run interrupted halfway leaves the window in a sensible
    # place rather than having read the newest and none of the middle.
    extra_params=(("order_type", "asc"),),
)


class FreshdeskConnector(RestConnector):
    """The engine, told about Freshdesk.

    A subclass only so the endpoint can vary with `records` — everything else is
    the spec. `path` carries a placeholder and the base class fills both from the
    same config dump, so nothing here has to know how that works.
    """

    setup_steps = (
        "In Freshdesk: click your avatar (top right) → Profile settings.",
        "Your API key is on the right of that page. Copy it.",
        "The key carries that agent's permissions, so use an account that "
        "can see every ticket you want counted.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="freshdesk",
            display_name="Freshdesk",
            spec=FRESHDESK,
            config_schema=FreshdeskConfig,
            credential_schema=FreshdeskKey,
            token_field="api_key",
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        """Fill the endpoint as well as the host.

        `path` is the one part of a spec that a provider might reasonably want to
        vary per source, and Freshdesk is the first case: tickets and contacts are
        the same API with a different noun.
        """
        filled = super()._spec_for(config)
        values = config.model_dump()
        return type(filled)(
            **{
                **{f: getattr(filled, f) for f in filled.__dataclass_fields__},
                "path": filled.path.format(**values),
            }
        )


register(FreshdeskConnector())
