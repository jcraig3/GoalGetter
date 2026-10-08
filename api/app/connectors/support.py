"""Zendesk, on the REST engine.

Freshdesk's opposite number, and the second-most-asked-for helpdesk. It lives in
its own file rather than beside Freshdesk because the two share a category and
nothing else — different auth, different paging, and a different answer to the one
question that matters.

**Zendesk's incremental export is the right endpoint and the awkward one.**
`/api/v2/incremental/tickets.json` is built for exactly this job: give it a start
time and it returns everything changed since, in modification order. What it does
*not* do is page the way anything else does — it hands back a full `next_page` URL
rather than a token, which this engine cannot follow, and it caps a response at
1,000 tickets.

So one sync reads at most 1,000 changed tickets. That is a deliberate ceiling, not
an oversight: at any sane sync interval it is far more headroom than it sounds, the
window only advances on a clean run, and anything left behind is read on the next
one. Salesforce makes the identical trade for the identical reason.
"""

from __future__ import annotations

from dataclasses import replace

from pydantic import BaseModel, Field

from app.connectors import register
from app.connectors.rest import (
    AuthStyle,
    Paging,
    RestConnector,
    RestProblem,
    RestSpec,
)


class ZendeskConfig(BaseModel):
    subdomain: str = Field(
        default="",
        title="Subdomain",
        description="From your Zendesk address: for acme.zendesk.com, 'acme'.",
        examples=["acme"],
    )
    records: str = Field(
        default="tickets",
        title="What to import",
        # Only the two the incremental export offers. A list including endpoints
        # that 404 on this path would be a dropdown that lies.
        json_schema_extra={"enum": ["tickets", "users"]},
    )


class ZendeskSecrets(BaseModel):
    """Both halves are secrets, which is why the engine grew a second field.

    Zendesk signs API requests as Basic auth with `{email}/token` as the username
    and the API token as the password. The email is not really a secret, but it is
    half of a credential and splitting it across the config form and the secret
    form would put one half in plain text and one half encrypted, for no gain.
    """

    email: str = Field(
        default="",
        title="Agent email",
        description="The account the token belongs to. Sent as '<email>/token'.",
        examples=["reporting@acme.com"],
    )
    api_key: str = Field(
        default="",
        title="API token",
        description="Admin Center → Apps and integrations → Zendesk API → add a token.",
    )


ZENDESK = RestSpec(
    base_url="https://{subdomain}.zendesk.com",
    path="api/v2/incremental/{records}.json",
    provider_name="Zendesk",
    auth=AuthStyle(kind="basic", basic_password_field="api_key"),
    # See the module docstring: `next_page` is a full URL, which this engine does
    # not follow. One response per sync, up to a thousand records.
    paging=Paging(kind="none"),
    rows_at="{records}",
    since_param="start_time",
    since_format="epoch",
)


class ZendeskConnector(RestConnector):
    setup_steps = (
        "In Zendesk: Admin Center → Apps and integrations → Zendesk API.",
        "Turn on Token access, then Add API token, and copy it — it is "
        "shown once.",
        "Enter the email address of the agent account the token belongs to "
        "as well. Zendesk needs both halves.",
    )

    def __init__(self) -> None:
        super().__init__(
            key="zendesk",
            display_name="Zendesk",
            spec=ZENDESK,
            config_schema=ZendeskConfig,
            credential_schema=ZendeskSecrets,
        )

    def _token(self, credentials: BaseModel) -> str:
        """The username half: `<email>/token`, which is Zendesk's own spelling.

        Composed here rather than asked for, because "type your email followed by
        slash token" is a form field nobody fills in correctly the first time and
        the failure is an unexplained 401.
        """
        email = str(getattr(credentials, "email", "") or "").strip()
        token = super()._token(credentials)
        if not email:
            raise RestProblem(
                "Zendesk needs the email address the API token belongs to — it is "
                "sent as '<email>/token' and the token alone is not accepted."
            )
        return f"{email}/token"

    def _password(self, credentials: BaseModel) -> str:
        # The token itself is the password half. `_token` above spends the
        # username half on the email, so this cannot fall through to the default.
        return str(getattr(credentials, "api_key", "") or "")

    def _spec_for(self, config: BaseModel):  # type: ignore[override]
        """Fill the endpoint, and the array name that matches it.

        `rows_at` varies with the endpoint — `/incremental/tickets.json` returns
        `tickets`, `/incremental/users.json` returns `users` — so it is filled from
        the same value rather than hard-coded to one of them.
        """
        filled = super()._spec_for(config)
        values = config.model_dump()
        return replace(
            filled,
            path=filled.path.format(**values),
            rows_at=filled.rows_at.format(**values),
        )


register(ZendeskConnector())
