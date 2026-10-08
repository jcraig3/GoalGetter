"""Excel on Microsoft 365: a workbook as a data source.

**The same connector as Google Sheets wearing a different badge.** Both read a
rectangle of cells whose first useful row names the columns, so the transform lives
in `grid.py` and is shared. What differs is two things and only two: which
identity provider signs you in, and which URL returns the cells.

That is the point of having built the pieces first. This file is a spec, two models
and one request.

**Two things about Microsoft's OAuth are different from Google's** and both bite if
you assume otherwise:

`offline_access` has to be *in the scopes* to get a refresh token — Microsoft has no
equivalent of Google's `access_type=offline` parameter. Leave it out and the source
works for an hour.

The endpoints take a **tenant** segment. `common` is used here so one registration
serves whatever directory the account belongs to, which is what a single-tenant app
registration wants anyway; Microsoft resolves the real tenant during sign-in.
"""

from __future__ import annotations

import base64
import logging
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
GRAPH = "https://graph.microsoft.com/v1.0"

#: The most rows one read will keep, matching the Sheets connector.
MAX_ROWS = 50_000

MICROSOFT = OAuthSpec(
    provider="microsoft",
    provider_name="Microsoft",
    # `{tenant}` is filled from the connection by `oauth.endpoints_for`, falling
    # back to `common`. Hard-coding `common` here was wrong for a single-tenant app
    # registration, which is the kind the setup steps produce and the kind most
    # companies make — it fails at the authorize step with an error naming neither
    # the tenant nor the fix.
    authorize_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
    token_url="https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    # `Files.Read.All` rather than `Files.Read`: a team's workbook usually lives in
    # somebody else's OneDrive or a SharePoint site, and the narrower scope only
    # reaches files the signed-in account owns.
    #
    # `offline_access` is what makes a refresh token appear at all. Microsoft has no
    # `access_type` parameter, so leaving this out produces a source that works for
    # an hour and then stops — the same failure Google's parameter guards against,
    # spelled completely differently.
    scopes=("Files.Read.All", "offline_access"),
)


class ExcelConfig(BaseModel):
    """Which workbook, which worksheet.

    **Two ways to name a file, and the picker sets the good one.** `drive_id` and
    `item_id` are what Graph actually addresses a file by; `file_url` is a sharing
    link that has to be resolved into exactly those two before anything can be
    read. The picker fills the ids in directly, which is one fewer request, one
    fewer way to fail, and immune to a link being re-generated or a file being
    moved.

    `file_url` stays because sources connected before the picker existed hold one,
    and because a deployment can always fall back to pasting if browsing is
    unavailable — it is still resolved exactly as it was.
    """

    drive_id: str = Field(
        default="",
        title="Drive",
        description="Set by the workbook picker. Not typed by hand.",
        json_schema_extra={"hidden": True},
    )
    item_id: str = Field(
        default="",
        title="File",
        description="Set by the workbook picker. Not typed by hand.",
        json_schema_extra={"hidden": True},
    )
    file_name: str = Field(
        default="",
        title="Workbook name",
        description=(
            "Set by the picker. Kept because the ids above are unreadable, and "
            "every screen that lists this source has to call it something."
        ),
        json_schema_extra={"hidden": True},
    )
    file_url: str = Field(
        default="",
        title="Workbook link",
        description=(
            "Only needed if you are not using the picker: the sharing link to the "
            ".xlsx file — Share → Copy link in Excel or OneDrive."
        ),
        examples=["https://contoso-my.sharepoint.com/:x:/g/personal/…"],
        # **Moved out of Advanced and into the picker.** Pasting a link was the
        # only way to reach a file on a SharePoint site, which `/me/drive/recent`
        # does not cover — so for anybody whose team keeps its spreadsheets in a
        # site, the fallback *was* the main path, and it sat two clicks down under
        # a heading telling them not to look.
        json_schema_extra={"hidden": True},
    )
    worksheet: str = Field(
        default="",
        title="Worksheet name",
        description="The tab at the bottom of the workbook. Empty means the first one.",
        examples=["Closed deals"],
        # Shown by the picker as a dropdown read from the workbook itself, which
        # is strictly better than a text box somebody types a tab name into from
        # memory — a typo there used to produce "that worksheet is empty".
        json_schema_extra={"hidden": True},
    )
    header_row: int = Field(
        default=1,
        title="Which row holds the column names",
        description=(
            "Usually 1. Set it higher if the sheet has a title or a blank row "
            "above the table."
        ),
        # **Not advanced.** It was the only thing left in that disclosure once the
        # ids and the link moved into the picker, so "Advanced settings (1)" was a
        # closed door in front of a single ordinary question. And it is not a
        # preference: get it wrong and every column is named after somebody's
        # data, which fails in a way that reads as "the connector is broken".
        # Anything a person must answer to connect a sheet belongs in the form.
    )


class ExcelCredentials(BaseModel):
    """Filled by the OAuth callback. Nobody types these."""

    access_token: str = ""
    refresh_token: str = ""


def share_token(url: str) -> str:
    """A sharing link, in the form Graph accepts as an id.

    Microsoft's documented encoding: base64url of the URL, padding stripped, with a
    `u!` prefix. Worth having as its own function because it is the sort of thing
    that looks like it works when it does not — a wrong encoding produces a 400
    about a malformed id, which says nothing about the link somebody pasted.
    """
    encoded = base64.urlsafe_b64encode(url.strip().encode()).decode().rstrip("=")
    return f"u!{encoded}"


class ExcelConnector:
    """Reads one worksheet of one workbook through Microsoft Graph."""

    #: A workbook has no notion of when a cell changed, so `fetch` ignores
    #: `since` and returns every row every time. That makes the sheet
    #: authoritative about absence: a row that is gone was deleted, and the
    #: fact it produced can be withdrawn. See `sync._withdraw_missing`.
    reads_everything = True

    key = "microsoft_excel"
    display_name = "Excel"

    setup_steps = (
        "Sign in once under Integrations → Microsoft 365 → Excel spreadsheets, "
        "if nobody has yet. Every workbook is read as that account.",
        "Choose the workbook from the list, then the worksheet from the dropdown.",
        "Make sure the first row of the sheet holds the column names.",
    )
    config_schema = ExcelConfig
    credential_schema = ExcelCredentials

    oauth = MICROSOFT

    def _token(self, credentials: ExcelCredentials) -> str:
        """The access token to read with.

        **Usually the deployment's, not this source's.** `oauth.ensure_fresh`
        substitutes the org-wide Excel account's token when one is signed in, so
        what arrives here is normally that. The message assumes as much, because
        the fix is one sign-in on the Integrations page rather than something to
        do per workbook.
        """
        if not credentials.access_token:
            raise RestProblem(
                "No Microsoft account is signed in for spreadsheets. Sign one in "
                "under Integrations → Microsoft 365 → Excel spreadsheets; every "
                "workbook reads as that account."
            )
        return credentials.access_token

    def _values(self, config: ExcelConfig, token: str) -> list[list[Any]]:
        """The used range of the worksheet, as rows of cells.

        Two requests, not one. Graph identifies a file by an internal id, and what
        an admin has is a sharing link — so the link is resolved to an id first.
        Asking them to find the id instead would be asking them to use Graph
        Explorer, which is not a thing anybody should have to do to import a
        spreadsheet.
        """
        if not (config.drive_id.strip() and config.item_id.strip()) and not config.file_url.strip():
            raise RestProblem(
                "No workbook has been chosen yet. Pick one from the list, or "
                "paste a sharing link."
            )

        with httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
        ) as client:
            if config.drive_id.strip() and config.item_id.strip():
                # Chosen from the picker, so there is nothing to resolve — these
                # are already the two values the sharing link would have been
                # turned into.
                drive = config.drive_id.strip()
                item_id: str | None = config.item_id.strip()
            else:
                item = request_json(
                    client,
                    f"{GRAPH}/shares/{share_token(config.file_url)}/driveItem",
                    {"$select": "id,name,parentReference"},
                    "Microsoft",
                )
                item_id = item.get("id") if isinstance(item, dict) else None
                drive = (
                    (item.get("parentReference") or {}).get("driveId")
                    if isinstance(item, dict)
                    else None
                )
                if not item_id:
                    raise RestProblem(
                        "Microsoft found nothing at that link. Check it is a "
                        "sharing link to the workbook itself rather than to a "
                        "folder."
                    )

            # Addressed through the drive the file actually lives in. `/me/drive`
            # would only find it when the signed-in account is its owner, which is
            # exactly not the case for a shared team workbook.
            base = f"{GRAPH}/drives/{drive}/items/{item_id}" if drive else f"{GRAPH}/shares/{share_token(config.file_url)}/driveItem"
            where = (
                f"/workbook/worksheets/{config.worksheet.strip()}"
                if config.worksheet.strip()
                else "/workbook/worksheets"
            )

            if not config.worksheet.strip():
                # No worksheet named: use the first one the workbook reports, which
                # is what a single-sheet workbook wants and most of them are.
                listed = request_json(client, f"{base}{where}", {}, "Microsoft")
                sheets = listed.get("value") if isinstance(listed, dict) else None
                if not sheets:
                    raise RestProblem("That workbook has no worksheets in it.")
                where = f"/workbook/worksheets/{sheets[0].get('id')}"

            body = request_json(
                client,
                f"{base}{where}/usedRange(valuesOnly=true)",
                {"$select": "values"},
                "Microsoft",
            )

        found = body.get("values") if isinstance(body, dict) else None
        return found if isinstance(found, list) else []

    def test_connection(
        self, config: ExcelConfig, credentials: ExcelCredentials
    ) -> ConnectionResult:
        """Read the sheet and report the columns, so a wrong worksheet is visible."""
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
                    "Connected to Microsoft, but that worksheet is empty. An empty "
                    "one usually means a typo in the name rather than an empty file."
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
        config: ExcelConfig,
        credentials: ExcelCredentials,
        *,
        local: LocalContext | None = None,
    ) -> list[SourceField]:
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
        config: ExcelConfig,
        credentials: ExcelCredentials,
        since: datetime | None = None,
        *,
        local: LocalContext | None = None,
    ) -> Iterator[SourceRow]:
        """Every row under the header.

        `since` is ignored, for the same reason as Google Sheets: a workbook has no
        notion of when a cell changed, so there is nothing to filter on. And no id
        is offered, for the same reason too — a row's position looks like an
        identity and is not one, so the mapping names a column and `sync` refuses
        the row if it does not.
        """
        records = rows_from(
            self._values(config, self._token(credentials)),
            header_row=config.header_row,
        )
        for record in records[:MAX_ROWS]:
            yield SourceRow(external_id=None, values=record)


register(ExcelConnector())
