"""Google Sheets: a spreadsheet as a data source.

**The connector most people will actually reach for**, because a spreadsheet is
where numbers live in a company that has not built a pipeline. It is also the first
connector with two ways to prove who we are, and the choice matters more than it
looks:

**Sign in with Google** — the two-click experience. Right for a Google Workspace
company: the consent screen is *Internal*, so there is no verification review and no
seven-day token expiry. The connection belongs to whoever clicked, which is its one
weakness — when that person leaves and their account is suspended, the sync stops.

**A service account** — a robot Google account with its own address. You paste its
key once and then **share the spreadsheet with that address**, exactly as you would
with a colleague. No consent screen, no verification, and the access belongs to the
organisation rather than to a person. Better for a plain Gmail account, where the
OAuth route runs into Google's review process.

Neither is a mode anybody has to choose: whichever credential is present is the one
used. A stored key means service account, a stored token means OAuth. One less
question, and no way for the setting and the credential to disagree.

**A spreadsheet has no "changed since" filter**, so every sync reads the whole tab.
Sheets are small enough that this is cheap — but it means **the sheet needs a column
holding something unique per row**: an id, an invoice number, a reference. Without
one there is no way to tell a row being read again from a new row that looks the
same, and the mapping step says so plainly.

A row's *position* is not a substitute, which is why this connector does not offer it
as one: inserting a row shifts every row below, and each then claims its neighbour's
identity and overwrites that neighbour's figure. The numbers stay plausible, which is
the worst way for a number to be wrong.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectionResult,
    LocalContext,
    SourceField,
    SourceRow,
    register,
)
from app.connectors.grid import SCAN_ROWS, fields_of, rows_from
from app.connectors.rest import RestProblem, request_json
from app.oauth import OAuthSpec

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0

#: Where Google's token endpoint lives, for the service-account exchange.
TOKEN_URL = "https://oauth2.googleapis.com/token"

#: What a service-account assertion is allowed to ask for.
#:
#: Read-only, and only spreadsheets. A key with write access to a customer's Drive
#: would be a much bigger thing to be holding, and nothing here needs it.
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)

#: How long a minted service-account token claims to last.
#:
#: An hour is Google's maximum. Nothing caches it — see `_service_token`.
ASSERTION_LIFETIME = 3600

#: The most cells one read will ask for.
#:
#: A spreadsheet is not a warehouse: a hundred thousand rows in one is already a
#: sign somebody should be using a database. Bounded so a runaway sheet cannot
#: exhaust the API process.
MAX_ROWS = 50_000

GOOGLE = OAuthSpec(
    provider="google",
    provider_name="Google",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url=TOKEN_URL,
    scopes=SCOPES,
    # Both are required, and for different reasons. Without `access_type=offline`
    # Google issues no refresh token at all, so the source works for an hour.
    # Without `prompt=consent` it issues none on a *re-connect*, because the
    # account has already approved this app — which is the more confusing failure,
    # since the first connection worked.
    extra_authorize_params=(("access_type", "offline"), ("prompt", "consent")),
)


class SheetsConfig(BaseModel):
    """Which spreadsheet, which tab, and how to recognise a row."""

    spreadsheet_id: str = Field(
        default="",
        title="Spreadsheet",
        description=(
            "Set by the picker. Also accepts a pasted address — the long code "
            "between /d/ and /edit, or the whole URL."
        ),
        examples=["1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"],
        # Owned by the picker, which browses Drive and resolves a pasted link to
        # the same id. A box to paste a URL into was the only option before the
        # Drive scope existed; it is now the fallback inside the picker rather
        # than the main path.
        json_schema_extra={"hidden": True},
    )
    file_name: str = Field(
        default="",
        title="Spreadsheet name",
        description=(
            "Set by the picker. Kept because the id above is unreadable, and "
            "every screen that lists this source has to call it something."
        ),
        json_schema_extra={"hidden": True},
    )
    tab: str = Field(
        default="",
        title="Tab name",
        description="The tab at the bottom of the sheet. Empty means the first one.",
        examples=["Closed deals"],
        # Shown by the picker as a dropdown read from the spreadsheet itself,
        # which beats a text box somebody types a tab name into from memory — a
        # typo there used to produce "that tab is empty".
        json_schema_extra={"hidden": True},
    )
    header_row: int = Field(
        default=1,
        title="Which row holds the column names",
        description=(
            "Usually 1. Set it higher if the sheet has a title or a blank row "
            "above the table."
        ),
        # **Not advanced.** It is the one question a person genuinely answers
        # here, and getting it wrong names every column after somebody data —
        # which reads as "the connector is broken" rather than as a setting.
    )


class SheetsCredentials(BaseModel):
    """Either a signed-in account or a service account. Never both used at once."""

    #: Filled by the OAuth callback. Nobody types these.
    access_token: str = ""
    refresh_token: str = ""

    #: The whole JSON key file, pasted.
    #:
    #: Stored as text rather than parsed into fields because it is Google's
    #: document, not ours: they add keys to it, and a model listing the ones we
    #: know about today would silently drop tomorrow's.
    service_account_json: str = Field(
        default="",
        title="Service account key",
        description=(
            "The whole JSON file downloaded when the service account was created. "
            "After saving it, share the spreadsheet with the client_email inside it "
            "— the ordinary Share button, exactly as with a colleague."
        ),
        json_schema_extra={"multiline": True},
    )


def spreadsheet_id_of(pasted: str) -> str:
    """The id, whether somebody pasted the id or the whole address.

    Everybody pastes the address. Asking for "just the bit between /d/ and /edit"
    and then failing on the address is a form being pedantic about something it
    could work out.
    """
    text = pasted.strip()
    if "/d/" in text:
        text = text.split("/d/", 1)[1].split("/", 1)[0]
    return text.strip()


def _service_token(raw_key: str) -> str:
    """Trade a service-account key for an access token.

    A signed assertion rather than a password: the key never leaves this process,
    and what goes to Google is a short-lived claim it can verify with the public
    half.

    **Minted per use rather than cached.** A token lasts an hour and a sync runs at
    most every few minutes, so caching would save one request in twelve at the cost
    of somewhere to store it and a staleness bug to find later. If that ratio ever
    matters, `connector_credential.expires_at` already exists for it.
    """
    import jwt

    try:
        key = json.loads(raw_key)
    except ValueError:
        raise RestProblem(
            "That service account key is not valid JSON. Paste the whole file, "
            "including the outermost braces."
        ) from None

    for field in ("client_email", "private_key"):
        if not key.get(field):
            raise RestProblem(
                f"That key has no {field!r} in it. It should be the JSON file "
                "Google produced when the service account was created."
            )

    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": key["client_email"],
            "scope": " ".join(SCOPES),
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + ASSERTION_LIFETIME,
        },
        key["private_key"],
        algorithm="RS256",
    )

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        # Google's body here can echo the assertion, which is signed with the
        # private key. The status is enough.
        raise RestProblem(
            f"Google would not accept that service account key "
            f"(HTTP {response.status_code}). Check it is the current key and that "
            "the Sheets API is enabled for its project."
        )
    token = response.json().get("access_token")
    if not token:
        raise RestProblem("Google accepted the key but returned no access token.")
    return str(token)


class SheetsConnector:
    """Reads one tab of one spreadsheet."""

    #: A workbook has no notion of when a cell changed, so `fetch` ignores
    #: `since` and returns every row every time. That makes the sheet
    #: authoritative about absence: a row that is gone was deleted, and the
    #: fact it produced can be withdrawn. See `sync._withdraw_missing`.
    reads_everything = True

    key = "google_sheets"
    display_name = "Google Sheets"

    setup_steps = (
        "Open the spreadsheet in Google Sheets and copy its address.",
        "The long code between /d/ and /edit is the spreadsheet ID.",
        "Make sure the first row of the tab holds the column names.",
        "Then sign in with Google below. The account you use has to be able "
        "to open that spreadsheet.",
    )
    config_schema = SheetsConfig
    credential_schema = SheetsCredentials

    #: So the wizard offers a sign-in button and the sync refreshes the token.
    #: A service-account source simply never uses it.
    oauth = GOOGLE

    def _token(self, credentials: SheetsCredentials) -> str:
        """Whichever credential is present, turned into a bearer token.

        **Inferred rather than configured.** A stored key means service account, a
        stored token means a signed-in account. A separate "which mode" setting
        would be one more question and one more way for the answer and the
        credential to disagree.
        """
        if credentials.service_account_json.strip():
            return _service_token(credentials.service_account_json)
        if credentials.access_token:
            return credentials.access_token
        raise RestProblem(
            "This source is not connected yet. Either sign in with Google, or "
            "paste a service account key and share the spreadsheet with it."
        )

    def _values(self, config: SheetsConfig, token: str) -> list[list[Any]]:
        """The cells, as Google returns them."""
        sheet = spreadsheet_id_of(config.spreadsheet_id)
        if not sheet:
            raise RestProblem(
                "Spreadsheet is not filled in yet. Paste the sheet's web address."
            )

        # A whole-tab range. Naming no tab reads the first one, which is what a
        # sheet with a single tab wants and is the commonest case by far.
        from urllib.parse import quote

        where = quote(config.tab, safe="") if config.tab.strip() else "A:ZZ"
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{quote(sheet, safe='')}"
            f"/values/{where}"
        )

        with httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
        ) as client:
            body = request_json(
                client,
                url,
                # UNFORMATTED so a currency cell arrives as 1250.5 rather than
                # "$1,250.50" — the mapping can parse either, but the raw number
                # cannot be got wrong by a locale.
                {"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
                "Google Sheets",
            )
        found = body.get("values") if isinstance(body, dict) else None
        return found if isinstance(found, list) else []

    def test_connection(
        self, config: SheetsConfig, credentials: SheetsCredentials
    ) -> ConnectionResult:
        """Read the sheet and say what was found.

        Reports the column names, because "connected" does not tell an admin
        whether they reached the tab they meant — and picking the wrong tab is the
        easiest mistake here.
        """
        try:
            values = self._values(config, self._token(credentials))
        except RestProblem as problem:
            return ConnectionResult(ok=False, detail=str(problem))
        except Exception as problem:  # noqa: BLE001 — reported, not raised
            return ConnectionResult(
                ok=False, detail=f"{type(problem).__name__}: {problem}"[:400]
            )

        records = rows_from(values, header_row=config.header_row)
        if not values:
            return ConnectionResult(
                ok=False,
                detail=(
                    "Connected to Google, but that tab is empty. Check the tab name "
                    "— an empty one usually means a typo rather than an empty sheet."
                ),
            )
        if not records:
            return ConnectionResult(
                ok=False,
                detail=(
                    f"Found {len(values)} row(s) but no records under the header. "
                    f"Row {config.header_row} is being read as the column names — "
                    "is that the right row?"
                ),
            )
        return ConnectionResult(
            ok=True,
            detail=(
                f"Connected. Found {len(records)} row"
                f"{'' if len(records) == 1 else 's'} under the header."
            ),
            info={"columns": ", ".join(records[0])},
        )

    def discover(
        self,
        config: SheetsConfig,
        credentials: SheetsCredentials,
        *,
        local: LocalContext | None = None,
    ) -> list[SourceField]:
        """The header row, with each column's kind guessed from the cells below."""
        try:
            values = self._values(config, self._token(credentials))
        except Exception:  # noqa: BLE001 — an empty answer, like every discover
            return []
        # More rows than the five a sample needs: whether a column is a
        # choice or a name cannot be told from five, and the rows are
        # already in memory.
        return fields_of(rows_from(values, header_row=config.header_row)[:SCAN_ROWS])

    def fetch(
        self,
        config: SheetsConfig,
        credentials: SheetsCredentials,
        since: datetime | None = None,
        *,
        local: LocalContext | None = None,
    ) -> Iterator[SourceRow]:
        """Every row under the header.

        **`since` is ignored, and it has to be.** A spreadsheet has no notion of
        when a cell changed, so there is nothing to filter on — every sync reads
        the whole tab. Sheets are small enough that this is cheap; what it costs is
        correctness, which is why `row_identity` is a question the setup asks
        instead of a default it assumes.
        """
        records = rows_from(
            self._values(config, self._token(credentials)),
            header_row=config.header_row,
        )
        for record in records[:MAX_ROWS]:
            # No id offered, deliberately. A spreadsheet has nothing stable to
            # offer: a row's position looks like an id and is not one, because
            # inserting a row shifts every row below it and each then claims its
            # neighbour's identity. So the mapping names a column, and `sync`
            # refuses the row if it does not — which is a message somebody can act
            # on rather than a leaderboard that is quietly wrong.
            yield SourceRow(external_id=None, values=record)


register(SheetsConnector())
