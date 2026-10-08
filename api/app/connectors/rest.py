"""One engine for every "call a URL and read JSON" integration.

**Twenty-five of the connectors on the roadmap are the same connector.** Freshdesk,
HubSpot, Zendesk, Pipedrive, Salesforce, Zoho, Gong, Outreach and the rest all do
the identical four things: authenticate, ask for a page of records changed since a
date, find the array inside the response, and ask for the next page. What differs is
a base URL, a header name, where the array lives and how paging is spelled.

So those are **data**, not code. A provider is a `RestSpec`; the engine reads it.
This is how Airbyte and Fivetran ship hundreds of sources without hundreds of
codebases, and it is the only shape in which that roadmap is finishable.

Two faces on the same engine:

* a **named connector** — `Freshdesk` — where the spec ships with the app and the
  admin is asked only what varies for them, usually a subdomain;
* the **generic API connector**, where the spec *is* the form, so a provider nobody
  has written a connector for yet is not a dead end.

**What this deliberately does not do** is transform anything. Rows come back as the
provider sent them and go straight into the same mapping, filtering and identity
resolution as every other source. A connector that reshaped its data would be a
second place where "which column is the person" gets decided.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.connectors import (
    ConnectionResult,
    LocalContext,
    SourceField,
    SourceRow,
    Truncated,
)

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0

#: The most pages one sync will ask for.
#:
#: A provider whose paging never says "that was the last one" — because a cursor
#: loops, or because `has_more` is missing and the row count happens to divide
#: exactly — would otherwise be asked forever. Reaching it raises `Truncated`, which
#: keeps the rows already read and stops the watermark advancing past the ones that
#: were not.
MAX_PAGES = 500

#: The most rows one sync will keep, matching the SQL connector.
MAX_ROWS = 100_000

#: How long to wait when a provider says "slow down".
#:
#: Honouring `Retry-After` is the difference between an integration a provider
#: tolerates and one they block. Capped because some send minutes and a sync that
#: sleeps for ten of them is a sync that has stopped.
MAX_RETRY_WAIT = 60.0
MAX_ATTEMPTS = 3


class RestProblem(Exception):
    """Something an admin can act on, phrased for them rather than for a log.

    Carries the HTTP status where there was one, because **401 and 403 are not the
    same problem and the advice for them is opposite.** A rejected credential does
    mean "check it and reconnect"; a 403 usually means the credential is perfectly
    good and has not been granted something — and telling somebody to reconnect
    sends them round a loop that cannot help. Callers that can tell the difference
    for their own provider read this and say so; the rest are unaffected.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


# ── How a provider authenticates ─────────────────────────────────────────────


@dataclass(frozen=True)
class AuthStyle:
    """How to prove who we are on each request.

    Four shapes cover essentially every business API. Named rather than expressed
    as a callback so a spec stays declarative — and so the generic connector can
    offer them as a dropdown.
    """

    #: `basic` — HTTP Basic. Freshdesk and several others put the API key in the
    #:   username and an ignored constant in the password.
    #: `bearer` — `Authorization: Bearer <token>`. Most modern APIs, and every
    #:   OAuth one.
    #: `header` — an arbitrary header, named by `header`. Zendesk-style tokens.
    #: `query` — a query parameter, named by `param`. Older APIs, and the reason
    #:   this engine never logs a full URL.
    kind: str = "bearer"
    header: str = "Authorization"
    param: str = "api_key"
    #: What goes in the password half of Basic auth when the key is the username.
    #: A constant, for the providers that ignore it — Freshdesk documents `X`.
    basic_password: str = "X"
    #: Which stored credential to use as the password half instead, when both
    #: halves are secrets rather than one being a placeholder.
    #:
    #: Three of the providers here work that way: Gong signs with an access key
    #: and a secret, Aircall with an id and a token, Zendesk with an email and an
    #: API token. Expressed as a *field name* rather than a value so the spec stays
    #: declarative and a secret never sits in a module-level constant.
    basic_password_field: str = ""


def _auth_headers(style: AuthStyle, token: str) -> dict[str, str]:
    if style.kind == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if style.kind == "header":
        return {style.header: token}
    return {}


def _auth_params(style: AuthStyle, token: str) -> dict[str, str]:
    return {style.param: token} if style.kind == "query" else {}


def _auth_basic(
    style: AuthStyle, token: str, password: str = ""
) -> tuple[str, str] | None:
    if style.kind != "basic":
        return None
    # The stored password wins over the constant, but only when there is one: a
    # provider that ignores the password half must still receive the placeholder
    # rather than an empty string, which some reject outright.
    return (token, password or style.basic_password)


# ── How a provider pages ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Paging:
    """How to ask for the next page, and how to know there is not one.

    **Knowing when to stop is the hard half.** A wrong "next page" rule either
    drops most of the data or asks forever, and both look like success from the
    outside — one returns a plausible number of rows, the other returns a timeout.
    """

    #: `page` — a page number, from `first_page`. Freshdesk, Zendesk.
    #: `cursor` — a token the response hands back, read from `cursor_at`.
    #:   HubSpot, Salesforce.
    #: `offset` — a row offset advanced by the page size.
    #: `none` — one response, everything in it.
    kind: str = "page"

    page_param: str = "page"
    size_param: str = "per_page"
    page_size: int = 100
    first_page: int = 1

    offset_param: str = "offset"

    #: Dotted path to the next cursor in the response body. Empty means the
    #: provider does not use one.
    cursor_at: str = ""
    cursor_param: str = "after"

    #: Dotted path to a boolean saying whether more remain. Checked *before*
    #: guessing from the row count, because a provider that tells us is more
    #: reliable than arithmetic.
    more_at: str = ""


# ── A provider, described ────────────────────────────────────────────────────


@dataclass(frozen=True)
class RestSpec:
    """Everything the engine needs to read one provider.

    Written once per provider and never at runtime. Placeholders in `base_url` are
    filled from the source's config — `{domain}` for a Freshdesk subdomain — which
    is what lets one spec serve every customer of that provider.
    """

    #: With `{placeholders}` filled from config.
    base_url: str
    #: Appended to the base. Kept separate so a spec can be reused for two
    #: endpoints later without repeating the host.
    path: str

    auth: AuthStyle = field(default_factory=AuthStyle)
    paging: Paging = field(default_factory=Paging)

    #: Dotted path to the array of records. Empty means the body *is* the array.
    rows_at: str = ""

    #: The query parameter that means "changed since", and how to format the value.
    #:
    #: **The single most important field in the spec**, and the one most often got
    #: wrong: it has to be the provider's *modified* filter, not its created or
    #: closed one. A record edited today but created last month has to come back,
    #: and a filter on the creation date never returns it. That mistake cost a day
    #: in 3a and is the reason the SQL connector refuses a query without `:since`.
    since_param: str = ""
    #: `iso` — `2026-08-21T12:00:00Z`. `date` — `2026-08-21`. `epoch` — seconds.
    since_format: str = "iso"

    #: How the window sits inside its parameter, when it is not the whole value.
    #:
    #: `"{since}"` — the default — means the parameter *is* the window, which is
    #: how most APIs take it. Salesforce takes a whole SOQL query in one parameter
    #: with the date buried in a `WHERE` clause, and it is not the only one: a
    #: template keeps that in the spec where every other provider quirk lives,
    #: rather than becoming a second connector.
    since_template: str = "{since}"

    #: Extra query parameters sent on every request — a sort order, an expansion.
    extra_params: tuple[tuple[str, str], ...] = ()

    #: What to call the provider in messages.
    provider_name: str = "the provider"

    #: A short, cheap request that proves the credentials work, if the provider has
    #: one. Falls back to asking for a single row of the real endpoint.
    probe_path: str = ""


def dig(body: Any, path: str) -> Any:
    """Follow a dotted path into a decoded JSON body.

    `""` returns the body itself, which is how "the response is the array" is
    spelled. A missing key returns None rather than raising: a provider omitting
    `paging.next` is how it says "no more pages", not a malformed response.
    """
    if not path:
        return body
    here = body
    for step in path.split("."):
        if not isinstance(here, dict):
            return None
        here = here.get(step)
    return here


#: How deep to look for the records when the settings did not find them.
#:
#: Two levels covers every shape anybody actually ships — `data`, `results.items`,
#: `_embedded.deals`. Deeper searching would start reporting paths that are more
#: confusing than helpful.
SEARCH_DEPTH = 2


def array_paths(body: Any, *, prefix: str = "", depth: int = SEARCH_DEPTH) -> list[str]:
    """Dotted paths to every list of records in a response.

    **What turns "connected, 0 records" from a dead end into an instruction.**
    Getting `rows_at` right is the fiddliest part of pointing this engine at a new
    provider, and the response itself knows the answer — so when the configured
    path finds nothing, the Test button reports where the lists actually are.

    Only lists whose first entry is an object: a list of ids or tag names is not
    where the records are, and offering it would send somebody down a path that
    produces a mapping error per row.
    """
    if depth < 0 or not isinstance(body, dict):
        return []

    found: list[str] = []
    for key, value in body.items():
        path = f"{prefix}{key}"
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                found.append(path)
        elif isinstance(value, dict):
            found.extend(array_paths(value, prefix=f"{path}.", depth=depth - 1))
    return found


def format_since(when: datetime | None, style: str) -> str | None:
    """The window, in whatever shape this provider reads.

    None when there is no window, so the caller omits the parameter entirely —
    sending an empty one is how you ask some APIs for nothing at all.
    """
    if when is None:
        return None
    when = when.astimezone(UTC)
    if style == "epoch":
        return str(int(when.timestamp()))
    if style == "date":
        return when.date().isoformat()
    if style != "iso":
        # **Not a fallback.** An unrecognised style used to return ISO, so a spec
        # that asked for `unix` instead of `epoch` sent a timestamp in the wrong
        # shape and the provider answered with either everything or nothing — no
        # error anywhere. A spec is code we write, so a typo in one is a bug to
        # raise on, not input to be lenient about.
        raise ValueError(
            f"Unknown since_format {style!r}. Known: 'iso', 'epoch', 'date'."
        )
    # `Z` rather than `+00:00`: both are valid ISO 8601 and a handful of APIs
    # reject the second.
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rows_in(body: Any, spec: RestSpec) -> list[dict]:
    """The records in one response.

    Non-dict entries are dropped rather than passed on. An API returning a list of
    ids where records were expected is a configuration mistake — `rows_at` pointing
    one level too deep — and letting those through produces a mapping error per row
    instead of one clear empty result.
    """
    found = dig(body, spec.rows_at)
    if isinstance(found, list):
        return [row for row in found if isinstance(row, dict)]
    return []


def next_page_params(
    body: Any, spec: RestSpec, *, page: int, seen: int, batch: int
) -> dict[str, Any] | None:
    """What to send to get the next page, or None when there is not one.

    Ordered by how much the provider told us, most explicit first: a cursor it
    handed back, then a flag it set, then arithmetic on the row count. Arithmetic
    is last because it is the only one that can be wrong — a final page that
    happens to be exactly full looks like a middle page, which costs one extra
    request that returns nothing and stops.
    """
    paging = spec.paging
    if paging.kind == "none":
        return None

    if paging.kind == "cursor":
        cursor = dig(body, paging.cursor_at)
        return {paging.cursor_param: cursor} if cursor else None

    # A provider that says whether more remain is believed, in both directions.
    if paging.more_at:
        more = dig(body, paging.more_at)
        if more is not None:
            if not more:
                return None
            return _advance(paging, page=page, seen=seen)

    # Nothing to go on but the size of what came back. A short page is the last.
    if batch < paging.page_size:
        return None
    return _advance(paging, page=page, seen=seen)


def _advance(paging: Paging, *, page: int, seen: int) -> dict[str, Any]:
    if paging.kind == "offset":
        return {paging.offset_param: seen}
    return {paging.page_param: page + 1}


# ── The engine ───────────────────────────────────────────────────────────────


class RestConnector:
    """A connector for one REST provider, driven entirely by its spec.

    Instantiated once per provider at import time. Holds no per-request state, so
    the same instance serves every source and every organization.
    """

    def __init__(
        self,
        key: str,
        display_name: str,
        spec: RestSpec,
        config_schema: type[BaseModel],
        credential_schema: type[BaseModel],
        *,
        token_field: str = "api_key",
        oauth: object | None = None,
    ):
        self.key = key
        self.display_name = display_name
        self.spec = spec
        self.config_schema = config_schema
        self.credential_schema = credential_schema
        #: Which credential field holds the token. `access_token` for OAuth
        #: providers, whatever the provider calls its key otherwise.
        self.token_field = token_field
        if oauth is not None:
            # Declared the same way any connector declares it, so `oauth_of` finds
            # it and the sync refreshes the token before every use.
            self.oauth = oauth

    # -- Reading -------------------------------------------------------------

    def _spec_for(self, config: BaseModel) -> RestSpec:
        """The spec with its placeholders filled from this source's settings.

        **An empty value is checked for separately from a missing key**, because
        formatting hides it: `{domain}` with `domain=""` produces
        `https://.freshdesk.com/api/v2`, which has no placeholder left in it and is
        structurally a perfectly good URL. Without this the source would be allowed
        to connect and fail at DNS resolution, and the message somebody got would be
        about a hostname rather than about the box they left blank.
        """
        import string

        values = config.model_dump()
        wanted = {
            name
            for _, name, _, _ in string.Formatter().parse(self.spec.base_url)
            if name
        }

        # Unknown keys before blank ones, and the order matters. A placeholder the
        # form does not offer at all is a spec that disagrees with its own config
        # model — a coding mistake — and reporting it as "not filled in" sends
        # somebody looking for a box that was never on the page.
        unknown = sorted(wanted - set(values))
        if unknown:
            raise RestProblem(
                f"This connector asks for a {unknown[0]!r} setting that its own "
                "form does not offer. That is a bug in the connector."
            )

        blank = sorted(n for n in wanted if not str(values.get(n) or "").strip())
        if blank:
            raise RestProblem(
                f"{_label(config, blank[0])} is not filled in yet, and "
                f"{self.spec.provider_name} needs it to know which account to read."
            )

        return dataclass_replace(self.spec, base_url=self.spec.base_url.format(**values))

    def _token(self, credentials: BaseModel) -> str:
        token = str(getattr(credentials, self.token_field, "") or "")
        if not token:
            raise RestProblem(
                f"No credential is stored for {self.spec.provider_name} yet."
            )
        return token

    def _password(self, credentials: BaseModel) -> str:
        """The password half of Basic auth, when the provider needs a real one.

        Empty for every other provider and every other auth style, which is what
        `_auth_basic` falls back on the constant for.
        """
        field = self.spec.auth.basic_password_field
        return str(getattr(credentials, field, "") or "") if field else ""

    def _pages(
        self,
        spec: RestSpec,
        token: str,
        since: datetime | None,
        password: str = "",
    ) -> Iterator[tuple[list[dict], Any]]:
        """Every page, one at a time, as (records, whole body).

        A generator so `fetch` streams: a provider with two hundred pages is read a
        hundred rows at a time rather than assembled in memory first.

        The raw body comes along because the Test button needs it. "Connected, 0
        records" is a true and useless answer when the real problem is that
        `rows_at` points at nothing — and the body is the only thing that can say
        where the records actually are. One request path rather than a second one
        just for testing, so what the button exercises is what a sync does.
        """
        params: dict[str, Any] = dict(spec.extra_params)
        if spec.paging.kind == "page":
            params[spec.paging.page_param] = spec.paging.first_page
        elif spec.paging.kind == "offset":
            params[spec.paging.offset_param] = 0

        # **The page size is asked for whatever the paging style**, and it used to
        # be sent only for page and offset paging. A cursor connector therefore got
        # the provider's default, which for HubSpot is *ten* — so reading a company
        # with twenty thousand deals took two thousand requests and stopped at the
        # five-hundred-page cap, silently, having read a quarter of them. Compounded
        # by HubSpot having no modified filter, so it re-reads everything every time.
        #
        # `params.update` on each page keeps it, so it is sent once and honoured
        # throughout. A cursor provider that rejects a size parameter sets
        # `size_param=""` and is left alone.
        if spec.paging.kind != "none" and spec.paging.size_param:
            params[spec.paging.size_param] = spec.paging.page_size

        window = format_since(since, spec.since_format)
        if spec.since_param and window:
            params[spec.since_param] = spec.since_template.format(since=window)
        elif spec.since_param and spec.since_template != "{since}":
            # A template with no window to put in it: send it with the clause
            # dropped, so a first sync asks for everything rather than for a query
            # containing the literal word `{since}`.
            params[spec.since_param] = spec.since_template.format(since="")

        page = spec.paging.first_page
        seen = 0

        with httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers=_auth_headers(spec.auth, token),
            auth=_auth_basic(spec.auth, token, password),
            follow_redirects=True,
        ) as client:
            for _ in range(MAX_PAGES):
                body = request_json(
                    client,
                    f"{spec.base_url.rstrip('/')}/{spec.path.lstrip('/')}",
                    {**params, **_auth_params(spec.auth, token)},
                    spec.provider_name,
                )
                batch = rows_in(body, spec)
                if batch:
                    yield batch, body
                elif page == spec.paging.first_page:
                    # An empty first page is still worth handing back: it carries
                    # the body the Test button explains itself with.
                    yield batch, body
                seen += len(batch)

                following = next_page_params(
                    body, spec, page=page, seen=seen, batch=len(batch)
                )
                if following is None:
                    return
                params.update(following)
                page += 1
            raise Truncated(
                f"Stopped after {MAX_PAGES} pages of {spec.provider_name}, so this "
                "run is incomplete. Narrow what the source imports, or shorten how "
                "much history it starts with."
            )

    def fetch(
        self,
        config: BaseModel,
        credentials: BaseModel,
        since: datetime | None = None,
        *,
        local: LocalContext | None = None,
    ) -> Iterator[SourceRow]:
        """Every record the provider has changed since the window opened.

        No `external_id`: which field identifies a record is the provider's
        business and the mapping's decision, not a guess made here. `sync` falls
        back to inserting when a mapping names none.
        """
        spec = self._spec_for(config)
        token = self._token(credentials)

        kept = 0
        for batch, _ in self._pages(spec, token, since, self._password(credentials)):
            for row in batch:
                if kept >= MAX_ROWS:
                    raise Truncated(
                        f"Stopped at {MAX_ROWS:,} rows from {spec.provider_name}, so "
                        "this run is incomplete. Narrow what the source imports, or "
                        "shorten how much history it starts with."
                    )
                kept += 1
                yield SourceRow(external_id=None, values=row)

    def discover(
        self,
        config: BaseModel,
        credentials: BaseModel,
        *,
        local: LocalContext | None = None,
    ) -> list[SourceField]:
        """The fields of the first page, so the mapper suggests from real records.

        One request, and the iterator is abandoned after it — the generator's
        `close` stops the loop rather than reading two hundred pages to describe
        six columns.
        """
        try:
            spec = self._spec_for(config)
            token = self._token(credentials)
        except RestProblem:
            return []

        pages = self._pages(spec, token, None, self._password(credentials))
        try:
            batch, _ = next(pages, ([], None))
        except Exception:  # noqa: BLE001 — an empty answer, like every discover
            return []
        finally:
            pages.close()

        return _fields_of(batch[:5])

    def test_connection(
        self, config: BaseModel, credentials: BaseModel
    ) -> ConnectionResult:
        """One real request, reported rather than raised.

        A failed test is a successful test — the client asked a question and got an
        answer — so this returns `ok: false` with the provider's own words rather
        than an exception.
        """
        try:
            spec = self._spec_for(config)
            token = self._token(credentials)
        except RestProblem as problem:
            return ConnectionResult(ok=False, detail=str(problem))

        try:
            pages = self._pages(spec, token, None, self._password(credentials))
            try:
                batch, body = next(pages, ([], None))
            finally:
                pages.close()
        except RestProblem as problem:
            return ConnectionResult(ok=False, detail=str(problem))
        except Exception as problem:  # noqa: BLE001 — reported, not raised
            return ConnectionResult(
                ok=False, detail=f"{type(problem).__name__}: {problem}"[:400]
            )

        if batch:
            return ConnectionResult(
                ok=True,
                detail=(
                    f"Connected to {spec.provider_name}. The first page returned "
                    f"{len(batch)} record{'' if len(batch) == 1 else 's'}."
                ),
                info={"columns": ", ".join(batch[0])},
            )

        # Reached the provider and found no records. Three reasons, and which one it
        # is matters enormously — an admin cannot tell them apart from outside, so
        # this says which.
        looked = "the response itself" if not spec.rows_at else repr(spec.rows_at)
        at = dig(body, spec.rows_at)

        if isinstance(at, list):
            # The shape is right and the list is empty. Nothing changed since the
            # window opened is the normal state of a healthy source, and calling
            # that a failure would train people to ignore the word.
            return ConnectionResult(
                ok=True,
                detail=(
                    f"Connected to {spec.provider_name}, and it returned no records. "
                    "That is a normal answer if nothing has changed — send it some "
                    "data and test again."
                ),
            )

        found = array_paths(body)
        if found:
            where = ", ".join(repr(path) for path in found)
            return ConnectionResult(
                ok=False,
                detail=(
                    f"Connected to {spec.provider_name}, but there are no records at "
                    f"{looked}. The lists in the response are at: {where}."
                ),
            )

        # No list anywhere. Almost always the wrong URL — a summary or a status
        # endpoint rather than the one that returns records.
        keys = ", ".join(sorted(body)[:8]) if isinstance(body, dict) else ""
        return ConnectionResult(
            ok=False,
            detail=(
                f"Connected to {spec.provider_name}, but the response holds no list "
                "of records at all. Check the URL is the endpoint that returns "
                "records rather than a summary."
                + (f" What came back has: {keys}." if keys else "")
            ),
        )


def _label(config: BaseModel, name: str) -> str:
    """What the form calls a field, so a message matches what is on screen.

    "Freshdesk domain is not filled in" rather than "'domain' is not filled in" —
    the second makes somebody hunt for a box whose label they never saw.
    """
    field = type(config).model_fields.get(name)
    return (field.title if field and field.title else name.replace("_", " ")).capitalize()


def dataclass_replace(spec: RestSpec, **changes) -> RestSpec:
    """`dataclasses.replace`, imported lazily to keep the module header short."""
    from dataclasses import replace

    return replace(spec, **changes)


def request_json(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
    provider_name: str,
    *,
    method: str = "GET",
    json: Any = None,
) -> Any:
    """One request, with the retries a shared API demands.

    `method` and `json` exist for one caller: Microsoft Graph's `$batch` endpoint,
    which is a POST and is how directory sync asks about twenty accounts in one
    round trip. Every connector uses the GET default. Adding the two arguments here
    was cheaper than a second copy of the retry, rate-limit and error handling,
    which is the part that is actually hard to get right.

    **Rate limits are honoured rather than fought.** A 429 with `Retry-After` is a
    provider asking politely; ignoring it is how an integration gets blocked for
    everyone on that account. A 5xx is retried too, because a transient gateway
    error should not fail a sync that would have worked a second later.

    Errors name the status and never the URL. A `query`-style credential lives in
    the query string, so a message quoting the full URL would put an API key into
    the run history where the whole point is that it is encrypted.
    """
    import time

    last = ""
    for attempt in range(MAX_ATTEMPTS):
        # `params or None`, not `params`. httpx *replaces* a URL's query string
        # with whatever it is given, so passing an empty dict strips one that is
        # already there — which silently broke Microsoft Graph's paging: its
        # `@odata.nextLink` is a complete URL carrying a `$skiptoken`, and losing
        # that means re-requesting page one until the page cap. Harmless for every
        # connector, since they always pass real parameters.
        response = client.request(method, url, params=params or None, json=json)

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                raise RestProblem(
                    f"{provider_name} replied with something that is not JSON."
                ) from None

        if response.status_code in (401, 403):
            # Never retried: a rejected credential is rejected, and hammering an
            # authentication endpoint is how an account gets locked.
            #
            # Worded apart, because the fix differs. A 401 is the credential; a 403
            # is the credential being fine and lacking permission, where "check it
            # and reconnect" is advice that cannot work.
            if response.status_code == 403:
                raise RestProblem(
                    f"{provider_name} accepted the credential and refused the "
                    "request (HTTP 403) — it is missing a permission rather than "
                    "being wrong.",
                    status=403,
                )
            raise RestProblem(
                f"{provider_name} refused the credential "
                f"(HTTP {response.status_code}). Check it and reconnect.",
                status=response.status_code,
            )

        if response.status_code == 404:
            raise RestProblem(
                f"{provider_name} has nothing at that path "
                "(HTTP 404). Check the source's settings.",
                status=404,
            )

        last = f"HTTP {response.status_code}"
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(_retry_after(response))
                continue

        raise RestProblem(f"{provider_name} returned {last}.")

    raise RestProblem(f"{provider_name} kept returning {last}.")


def _retry_after(response: httpx.Response) -> float:
    """How long the provider asked us to wait, within reason."""
    raw = response.headers.get("Retry-After", "")
    try:
        return min(float(raw), MAX_RETRY_WAIT)
    except ValueError:
        # No header, or a date rather than seconds. A second is enough for the
        # transient case and short enough not to look like a hang.
        return 1.0


def _fields_of(rows: list[dict]) -> list[SourceField]:
    """Each field's kind, guessed from the first record that has a value.

    Nested objects and arrays are reported as `string`, and deliberately not
    flattened: a mapping that pointed at `contact.owner.email` would be a second
    place where the shape of somebody's data is interpreted. If a provider buries
    the useful value, that belongs in its spec's `rows_at` or in a future mapping
    feature, not in a silent unwrap here.
    """
    fields: dict[str, SourceField] = {}
    for row in rows:
        for name, value in row.items():
            if not isinstance(name, str):
                continue
            existing = fields.get(name)
            if existing is not None and (existing.kind != "string" or value is None):
                continue
            fields[name] = SourceField(
                name=name,
                kind=_kind_of(value),
                samples=(str(value)[:60],) if value is not None else (),
            )
    return list(fields.values())


def _kind_of(value: object) -> str:
    """JSON has fewer types than a database, so this guesses more than SQL does.

    Nothing here mentions None, dicts or lists, and that is not an oversight: none
    of the checks below match them, so all three reach the final `"string"` on
    their own. An explicit line for them was here first and mutation testing showed
    it changing nothing. The *policy* — nested values are described rather than
    unwrapped — is real and lives on `_fields_of`, where it is enforced by there
    being no unwrapping code at all.
    """
    if isinstance(value, bool):
        # Before `int`, because `bool` is a subclass of it and a flag reported as a
        # number is a flag the mapper offers to sum.
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        if "@" in value:
            return "email"
        from app.mapping import _number, _parse_datetime

        if _parse_datetime(value) is not None:
            return "date"
        # `"1,250.00"` is a number somebody means as one — the same reasoning as
        # the webhook connector, and the same parser, so the wizard and the sync
        # agree about what is numeric.
        if _number(value) is not None:
            return "number"
    return "string"


class NoConfig(BaseModel):
    """For a provider that needs nothing beyond a credential."""


class ApiKey(BaseModel):
    """The commonest credential shape there is."""

    api_key: str = Field(default="", title="API key")
