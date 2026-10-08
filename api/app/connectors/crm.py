"""Four CRMs: HubSpot, Salesforce, Pipedrive and Close.

One file rather than three, because there is almost nothing in each. That is the
whole point of the REST engine: a provider is a `RestSpec` and two small models, so
the third CRM costs an afternoon of reading documentation rather than a week of
writing a client.

**Read this before trusting any of them against a live account.** The shapes below
reflect each provider's documented API, but endpoint names, default page sizes and
filter parameters are exactly the sort of thing that changes without anybody telling
us, and no unit test can notice. Each connector's Test button reports the provider's
own words, which is where a mismatch will show up. A trial account is worth more than
another day of test-writing here.

**Their incremental stories differ, and one of them cannot do it at all.** Worth
stating plainly because it is the single most consequential difference between them:

* **Pipedrive** has `updated_since` on its v2 endpoints. Clean.
* **Close** has `date_updated__gt`, and offset paging that tells us when to stop
  with `has_more` rather than leaving it to arithmetic.
* **Salesforce** takes a whole SOQL query in one parameter, with the window in a
  `WHERE` clause — which is what `since_template` on the spec exists for.

  **It signs in**, like Sheets and Excel, and for a reason particular to it: a
  Salesforce access token expires within hours, so the pasted-token version this
  had first stopped working on its own with nothing to explain why. `refresh_token`
  in its scope list is what lets the sync renew one before every use.
* **HubSpot's** list endpoints have no modified filter; filtering needs a POST to a
  search endpoint, which this engine does not do. So HubSpot **reads everything
  every sync**. That is correct but costly, and the trade is deliberate: a full read
  is expensive, while a wrong filter silently misses edited records. Expensive and
  right beats cheap and wrong, and `external_id` makes the re-reading harmless.

**Which is also the reassuring shape of getting a `since_param` wrong.** Almost
every API ignores a query parameter it does not recognise, so a misspelled filter
degrades into HubSpot's situation — a full read every sync — rather than into
silently missing rows. `external_id` then makes the extra rows harmless. The two
mistakes that are *not* survivable are a wrong `rows_at`, which reads nothing, and
a wrong external id, which duplicates everything.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.connectors import register
from app.oauth import OAuthSpec
from app.connectors.rest import (
    ApiKey,
    AuthStyle,
    NoConfig,
    Paging,
    RestConnector,
    RestSpec,
)

# ── HubSpot ──────────────────────────────────────────────────────────────────


class HubspotConfig(BaseModel):
    """Which records. Nothing else varies per customer — the host is fixed."""

    records: str = Field(
        default="deals",
        title="What to import",
        json_schema_extra={"enum": ["deals", "contacts", "companies", "tickets"]},
    )
    properties: str = Field(
        default="",
        title="Extra properties to fetch",
        description=(
            "Comma-separated. HubSpot returns only a handful of properties unless "
            "asked — so a custom field will be missing from the mapping step until "
            "it is named here."
        ),
        examples=["amount,closedate,hubspot_owner_id,dealstage"],
        json_schema_extra={"advanced": True},
    )


class HubspotToken(ApiKey):
    api_key: str = Field(
        default="",
        title="Private app token",
        description=(
            "Settings → Integrations → Private apps → create one with read access "
            "to the objects you want. Starts with 'pat-'."
        ),
    )


HUBSPOT = RestSpec(
    base_url="https://api.hubapi.com",
    path="crm/v3/objects/{records}",
    provider_name="HubSpot",
    auth=AuthStyle(kind="bearer"),
    # A cursor, and HubSpot is explicit about when there is no next page — which is
    # more reliable than guessing from how full the last one was.
    paging=Paging(
        kind="cursor",
        cursor_at="paging.next.after",
        cursor_param="after",
        size_param="limit",
        page_size=100,
    ),
    rows_at="results",
    # Deliberately empty. See the module docstring: HubSpot cannot filter on a GET,
    # and reading everything is the honest cost of not guessing.
    since_param="",
)


class HubspotConnector(RestConnector):
    setup_steps = (
        "In HubSpot: Settings (the cog, top right) → Integrations → Private apps.",
        "Create a private app, or open an existing one.",
        "On the Scopes tab, tick the read scope for what you are importing — "
        "crm.objects.deals.read for deals.",
        "Create the app and copy its access token. It starts with 'pat-'.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="hubspot",
            display_name="HubSpot",
            spec=HUBSPOT,
            config_schema=HubspotConfig,
            credential_schema=HubspotToken,
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        """Fill the endpoint, and ask for the properties somebody named.

        **HubSpot returns almost nothing by default.** A deal comes back with an id
        and a couple of system fields unless the request lists what it wants, so a
        source configured without `properties` discovers three columns and none of
        them are the amount. That is a confusing enough failure to be worth handling
        here rather than in a hint.
        """
        from dataclasses import replace

        filled = super()._spec_for(config)
        values = config.model_dump()
        extra = str(values.get("properties") or "").strip()
        return replace(
            filled,
            path=filled.path.format(**values),
            extra_params=(
                (*filled.extra_params, ("properties", extra)) if extra else filled.extra_params
            ),
        )


# ── Salesforce ───────────────────────────────────────────────────────────────


class SalesforceConfig(BaseModel):
    """Where the org lives, and what to ask it for.

    A SOQL query rather than an object picker, for the same reason the SQL
    connector takes a query: anybody who can answer "which fields" already knows
    SOQL, and an abstraction over it is a worse SOQL that still has to be learned.
    """

    instance: str = Field(
        default="",
        title="Instance",
        description=(
            "The host from your Salesforce address, without https:// — "
            "acme.my.salesforce.com."
        ),
        examples=["acme.my.salesforce.com"],
    )
    soql: str = Field(
        default=(
            "SELECT Id, Amount, CloseDate, Owner.Email FROM Opportunity "
            "WHERE IsWon = true"
        ),
        title="Query",
        description=(
            "The window is added automatically as an AND on LastModifiedDate, so "
            "there is no need to write one — and writing one on CloseDate instead "
            "is the mistake that makes edited records never come back."
        ),
        json_schema_extra={"multiline": True},
    )
    version: str = Field(
        default="v60.0",
        title="API version",
        json_schema_extra={"advanced": True},
    )


class SalesforceCredentials(BaseModel):
    """Filled by the OAuth callback. Nobody types these.

    **This used to be a pasted access token**, and Salesforce access tokens expire
    within hours — so unlike every other connector here, that one stopped working on
    its own with nothing to explain why. Signing in properly is what `refresh_token`
    in the scope list buys: the sync renews the token before every use.
    """

    access_token: str = ""
    refresh_token: str = ""


#: How this deployment signs in to Salesforce.
#:
#: `{tenant}` is the login host, filled from the connection — production, a sandbox,
#: or a company's own My Domain — falling back to `login.salesforce.com`. Salesforce
#: rejects an authorization request sent to the wrong one of those, and the error
#: says nothing about which.
SALESFORCE_OAUTH = OAuthSpec(
    provider="salesforce",
    provider_name="Salesforce",
    authorize_url="https://{tenant}/services/oauth2/authorize",
    token_url="https://{tenant}/services/oauth2/token",
    default_tenant="login.salesforce.com",
    # `refresh_token` is Salesforce's spelling of offline access, and leaving it out
    # produces a source that works for two hours. `api` is what permits the query
    # endpoint at all.
    scopes=("api", "refresh_token"),
)


SALESFORCE = RestSpec(
    base_url="https://{instance}",
    path="services/data/{version}/query",
    provider_name="Salesforce",
    auth=AuthStyle(kind="bearer"),
    # Salesforce hands back a full path to the next batch rather than a token, so
    # the cursor is that path. `next_page_params` sends it as a parameter, which is
    # wrong for Salesforce — so paging is left off and the first batch is what a
    # sync reads. Two thousand records a sync, which for an hourly incremental read
    # is far more headroom than it sounds.
    paging=Paging(kind="none"),
    rows_at="records",
    since_param="q",
    since_template="{since}",
)


class SalesforceConnector(RestConnector):
    setup_steps = (
        "Copy the host from your Salesforce address — acme.my.salesforce.com — "
        "into Instance below.",
        "Write a SOQL query returning one row per thing you want counted. The "
        "changed-since filter is added for you.",
        "Then sign in with Salesforce. The account you use needs to see every "
        "record you want on the leaderboard.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="salesforce",
            display_name="Salesforce",
            spec=SALESFORCE,
            config_schema=SalesforceConfig,
            credential_schema=SalesforceCredentials,
            token_field="access_token",
            oauth=SALESFORCE_OAUTH,
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        """Build the SOQL, with the window appended rather than written by hand.

        **The one thing this connector will not let somebody get wrong.** A query
        filtered on `CloseDate` looks right and silently never returns an
        opportunity edited after it closed — the same trap the SQL connector refuses
        a query for. So the window is added here, on `LastModifiedDate`, and the
        admin's query says only which records they want.
        """
        from dataclasses import replace

        assert isinstance(config, SalesforceConfig)
        filled = super()._spec_for(config)
        query = config.soql.strip().rstrip(";")
        joiner = "AND" if " where " in f" {query.lower()} " else "WHERE"
        return replace(
            filled,
            path=filled.path.format(**config.model_dump()),
            # `{since}` is filled by the engine, which also drops the clause
            # entirely on a first sync when there is no window yet.
            since_template=f"{query} {joiner} LastModifiedDate > {{since}}",
        )


# ── Pipedrive ────────────────────────────────────────────────────────────────


class PipedriveConfig(BaseModel):
    company: str = Field(
        default="",
        title="Company domain",
        description="From your Pipedrive address: for acme.pipedrive.com, 'acme'.",
        examples=["acme"],
    )
    records: str = Field(
        default="deals",
        title="What to import",
        json_schema_extra={"enum": ["deals", "activities", "persons", "organizations"]},
    )


class PipedriveToken(ApiKey):
    api_key: str = Field(
        default="",
        title="API token",
        description="Personal preferences → API in Pipedrive.",
    )


PIPEDRIVE = RestSpec(
    base_url="https://{company}.pipedrive.com",
    path="api/v2/{records}",
    provider_name="Pipedrive",
    # A query parameter, which Pipedrive requires. It is the reason this engine
    # never puts a URL in an error message.
    auth=AuthStyle(kind="query", param="api_token"),
    paging=Paging(
        kind="cursor",
        cursor_at="additional_data.next_cursor",
        cursor_param="cursor",
        size_param="limit",
        page_size=100,
    ),
    rows_at="data",
    # v2 rather than v1 precisely for this: v1 has no modified filter on its list
    # endpoints, and its `/recents` alternative returns a mixture of record types
    # that no single mapping can describe.
    since_param="updated_since",
)


class PipedriveConnector(RestConnector):
    setup_steps = (
        "In Pipedrive: click your avatar (top right) → Personal preferences.",
        "Open the API tab and copy the personal API token shown there.",
        "The token has that user's permissions, so use an account that can "
        "see every deal you want on the leaderboard.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="pipedrive",
            display_name="Pipedrive",
            spec=PIPEDRIVE,
            config_schema=PipedriveConfig,
            credential_schema=PipedriveToken,
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        from dataclasses import replace

        filled = super()._spec_for(config)
        return replace(filled, path=filled.path.format(**config.model_dump()))


# ── Close ────────────────────────────────────────────────────────────────────


class CloseConfig(BaseModel):
    records: str = Field(
        default="opportunity",
        title="What to import",
        json_schema_extra={"enum": ["opportunity", "lead", "activity/call"]},
    )


class CloseToken(ApiKey):
    api_key: str = Field(
        default="",
        title="API key",
        description="Settings → API Keys in Close. Starts with 'api_'.",
    )


CLOSE = RestSpec(
    base_url="https://api.close.com",
    path="api/v1/{records}/",
    provider_name="Close",
    # The key is the username and the password half is genuinely blank, which is
    # why `basic_password` is overridden rather than left at its placeholder.
    auth=AuthStyle(kind="basic", basic_password=""),
    paging=Paging(
        kind="offset",
        offset_param="_skip",
        size_param="_limit",
        page_size=100,
        more_at="has_more",
    ),
    rows_at="data",
    since_param="date_updated__gt",
)


class CloseConnector(RestConnector):
    setup_steps = (
        "In Close: Settings → Developer → API Keys.",
        "Create a new API key and copy it. It starts with 'api_'.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="close",
            display_name="Close",
            spec=CLOSE,
            config_schema=CloseConfig,
            credential_schema=CloseToken,
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        from dataclasses import replace

        filled = super()._spec_for(config)
        return replace(filled, path=filled.path.format(**config.model_dump()))


register(HubspotConnector())
register(SalesforceConnector())
register(PipedriveConnector())
register(CloseConnector())
