"""The generic API connector: the REST engine with its spec on the form.

**So "we don't support that yet" is never a dead end.** Every named connector is a
`RestSpec` written by us; this one lets an admin write it themselves. Anything with a
JSON endpoint and a key — a niche CRM, an internal service, a reporting API nobody
else has asked for — can feed GoalGetter today rather than after we ship a connector
for it.

It is also how a named connector gets prototyped. Point this at a provider, get the
paging and the date filter right against their real API, and the working settings
*are* the spec for a proper connector later.

**More fields than anything else in the product, deliberately.** Pointing at an
arbitrary API genuinely needs these answers and there is no honest way to guess
them — so they are asked plainly, each with a sentence saying what it is for, rather
than hidden behind a wizard that guesses wrong. Everything except the URL has a
default that suits the commonest API, so the usual case is: paste a URL, choose how
it authenticates, and press Test.
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


class ApiConfig(BaseModel):
    """Everything the engine needs, asked of the admin instead of shipped.

    Ordered as somebody works it out: where, then how to get in, then how to read
    the answer, then how to ask for the next page.
    """

    url: str = Field(
        default="",
        title="URL",
        description=(
            "The full address of the endpoint that returns the records, including "
            "any path. Query parameters are added below."
        ),
        examples=["https://api.example.com/v2/deals"],
    )

    auth_kind: str = Field(
        default="bearer",
        title="How it authenticates",
        description=(
            "Bearer is the commonest. Basic puts the key in the username. Header "
            "and query are for APIs that want it somewhere specific."
        ),
        json_schema_extra={"enum": ["bearer", "basic", "header", "query", "none"]},
    )
    auth_header: str = Field(
        default="Authorization",
        title="Header name",
        description="Only used when authentication is set to Header.",        json_schema_extra={"advanced": True},
    )
    auth_param: str = Field(
        default="api_key",
        title="Query parameter name",
        description=(
            "Only used when authentication is set to Query. Bear in mind a key in a "
            "URL is a key in every log between here and there."
        ),        json_schema_extra={"advanced": True},
    )

    rows_at: str = Field(
        default="",
        title="Where the records are",
        description=(
            "A dotted path to the list inside the response — 'data', or "
            "'results.items'. Leave empty if the response is the list itself."
        ),
        examples=["data"],
    )

    since_param: str = Field(
        default="",
        title="Changed-since parameter",
        description=(
            "The parameter that asks for records modified since a date. Use the "
            "one for when a record was last *changed*, not when it was created — a "
            "record edited today but created last month has to come back, and a "
            "created-since filter never returns it. Leave empty only if the API "
            "has no such filter: every sync will then read everything."
        ),
        examples=["updated_since"],
    )
    since_format: str = Field(
        default="iso",
        title="Date format it expects",
        description="ISO is 2026-08-21T12:00:00Z. Date is 2026-08-21. Epoch is seconds.",
        json_schema_extra={"enum": ["iso", "date", "epoch"], "advanced": True},
    )

    paging_kind: str = Field(
        default="none",
        title="How it pages",
        description=(
            "Start with None and press Test: if the record count looks suspiciously "
            "round, it pages. Page is a number, Cursor is a token the response "
            "hands back, Offset is a row count."
        ),
        json_schema_extra={"enum": ["none", "page", "cursor", "offset"]},
    )
    page_param: str = Field(
        default="page",
        title="Page parameter",
        json_schema_extra={"advanced": True},
    )
    size_param: str = Field(
        default="per_page",
        title="Page size parameter",
        json_schema_extra={"advanced": True},
    )
    page_size: int = Field(
        default=100,
        title="Records per page",
        description="Ask for the largest the API allows; fewer requests, same data.",        json_schema_extra={"advanced": True},
    )
    cursor_at: str = Field(
        default="",
        title="Where the next cursor is",
        description=(
            "A dotted path to the token for the following page — 'paging.next'. "
            "Only used when paging is set to Cursor."
        ),        json_schema_extra={"advanced": True},
    )
    cursor_param: str = Field(
        default="after",
        title="Cursor parameter",
        json_schema_extra={"advanced": True},
    )
    more_at: str = Field(
        default="",
        title="Where the more-records flag is",
        description=(
            "A dotted path to a true/false saying whether records remain — "
            "'has_more'. Optional, and worth filling in: it is more reliable than "
            "guessing from how full the last page was."
        ),        json_schema_extra={"advanced": True},
    )

    extra_params: dict[str, str] = Field(
        default_factory=dict,
        title="Extra parameters",
        description=(
            "One per line, as name=value. For a sort order, a status filter, an "
            "expansion — anything the API needs on every request."
        ),        json_schema_extra={"advanced": True},
    )

    provider_name: str = Field(
        default="",
        title="What to call it",
        description="Used in messages, so a failure names the thing that failed.",
        examples=["Example CRM"],        json_schema_extra={"advanced": True},
    )


class ApiSecrets(BaseModel):
    """The one credential, whatever the API calls it."""

    api_key: str = Field(
        default="",
        title="Key or token",
        description="Left empty if the endpoint needs no authentication.",
    )


class GenericApiConnector(RestConnector):
    """The engine, configured at runtime instead of at import.

    Every named REST connector holds a spec written once and reads only what
    varies per customer from its config. This one inverts that: the config *is*
    the spec, assembled per request.
    """

    setup_steps = (
        "Find the endpoint in your system's API documentation that lists "
        "the records you want to count.",
        "Call it once yourself — in a browser, or with curl — and keep the "
        "response. Everything below is read off it.",
        "Fill in the address, how it authenticates, and where the records "
        "sit in the response.",
        "Press Save and test. It reports what it found, so a wrong answer "
        "shows up now rather than as an empty leaderboard later.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="api",
            display_name="Any JSON API",
            # A placeholder spec. `_spec_for` replaces it wholesale, but the base
            # class wants one and a half-built spec here would be a trap for
            # anybody reading this expecting it to be used.
            spec=RestSpec(base_url="", path="", provider_name="the API"),
            config_schema=ApiConfig,
            credential_schema=ApiSecrets,
            token_field="api_key",
        )

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        """Build the spec out of the form.

        Deliberately not calling `super()`: the base class's job is filling
        placeholders in a spec that already exists, and there is nothing here to
        fill — the whole spec arrives from the config. The one thing kept is the
        blank-value check, because "URL is not filled in yet" is the most likely
        thing to be wrong and it deserves the same message as everywhere else.
        """
        from app.connectors.rest import RestProblem

        assert isinstance(config, ApiConfig)
        url = config.url.strip()
        if not url:
            raise RestProblem(
                "URL is not filled in yet, so there is nothing to read from."
            )
        if not url.startswith(("http://", "https://")):
            raise RestProblem(
                "The URL has to start with http:// or https://. Paste the whole "
                "address, as it appears in the API's documentation."
            )

        # Split so the engine's own `base_url` / `path` join produces exactly what
        # was pasted, rather than a doubled or missing slash.
        base, _, path = url.partition("://")
        host, _, rest_of_path = path.partition("/")

        return RestSpec(
            base_url=f"{base}://{host}",
            path=rest_of_path,
            provider_name=config.provider_name.strip() or "the API",
            auth=AuthStyle(
                kind=config.auth_kind,
                header=config.auth_header or "Authorization",
                param=config.auth_param or "api_key",
            ),
            paging=Paging(
                kind=config.paging_kind,
                page_param=config.page_param or "page",
                size_param=config.size_param or "per_page",
                page_size=config.page_size or 100,
                cursor_at=config.cursor_at,
                cursor_param=config.cursor_param or "after",
                more_at=config.more_at,
            ),
            rows_at=config.rows_at,
            since_param=config.since_param,
            since_format=config.since_format,
            extra_params=tuple((config.extra_params or {}).items()),
        )

    def _token(self, credentials: BaseModel) -> str:
        """An empty key is allowed here, unlike every named connector.

        A public endpoint, or one behind a network the deployment is already
        inside, needs no credential — and refusing that would make the connector
        useless for the internal-service case it is most obviously good for.
        """
        return str(getattr(credentials, "api_key", "") or "")


register(GenericApiConnector())
