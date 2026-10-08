"""Reading people out of a Microsoft 365 tenant.

**No account signs in for this.** The permissions are *application* ones —
`User.Read.All`, `GroupMember.Read.All`, `MailboxSettings.Read` — so the token
comes from the client credentials grant using the connection's own id and secret.
A sync runs at three in the morning with nobody at a keyboard: there is no popup,
no refresh token, and a fresh token is minted per run and thrown away.

**This went delegated for a while and came back, and the round trip is worth
recording.** The argument for delegated was consent: a Cloud Application
Administrator cannot grant consent for Microsoft Graph app roles, so on paper the
admin who sets an integration up can build this and never switch it on. In the
tenants this actually ships into, that consent is available — and the delegated
version cost something the application one does not: it acted as one person, so
the sync stopped when they left, months later, looking like an unrelated fault.

An application has no account to offboard and no token to expire. What it needs
instead is one press of *Grant admin consent*, which the setup attempts on the
admin's behalf and the panel links to when it could not.

**The whole membership, every time.** Graph offers a delta query and this does not
use one, deliberately: a delta tells you what changed, and reconcile needs to know
what is *absent* — see `app/directory/reconcile.py`. A tenant of two thousand people
is three requests at the page size below.

**Not every account is a person, and this is where that gets decided.** A tenant is
full of things that would otherwise become leaderboard entries called "Conference
Room B":

* **shared mailboxes, rooms and equipment** — found by asking each account what its
  mailbox is *for*, which is the only reliable signal Graph offers;
* **guests** — external collaborators, who are in the directory and are not staff;
* **accounts with no email** — service accounts, mostly, and somebody with no
  address could not sign in here anyway.

Everything else is a person, including disabled ones: those come back marked
`enabled=False` so reconcile archives them rather than silently dropping them, which
is how a leaver is noticed at all.
"""

from __future__ import annotations

import logging

import httpx

from sqlalchemy.orm import Session as DbSession

from app import tenant_account
from app.connectors.rest import HTTP_TIMEOUT, RestProblem, request_json
from app.directory.rules import Person
from app.models import OauthClient
from app.oauth import secret_of

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"

#: Graph's maximum, and worth asking for: the default is far smaller and a tenant
#: of two thousand people would otherwise be twenty round trips instead of three.
PAGE_SIZE = 999

#: How many sub-requests one `$batch` may carry. Graph's own limit.
BATCH = 20

#: The most pages to follow before giving up, per collection.
#:
#: Graph pages honestly, so this is a backstop against a loop rather than an
#: expected limit — at 999 a page it allows a tenant of a hundred thousand people.
MAX_PAGES = 100

#: Fields worth asking for. Anything not listed here is not returned at all, so
#: this list *is* what a rule can match on.
USER_FIELDS = (
    "id,displayName,mail,userPrincipalName,jobTitle,department,"
    # `assignedLicenses` costs nothing extra — it comes back from the same call
    # under the same permission — and is the only signal here for "somebody
    # actually works here" rather than "an object exists in the directory".
    "officeLocation,accountEnabled,userType,assignedLicenses"
)

#: Mailboxes that belong to a room, a projector or a team rather than a person.
NOT_A_PERSON = {"shared", "room", "equipment", "linked"}

#: The application permissions this needs, named the way Entra names them.
#:
#: Here so that a 403 can say which ones rather than leaving somebody to work it
#: out — see `_needs_consent`. These are *app roles*, which is the detail that
#: makes the failure confusing: a Cloud Application Administrator can create the
#: registration and grant every delegated permission on it, and cannot grant
#: these. Only a Privileged Role Administrator can.
#: What reading a directory *needs*, whichever mode. The optional ones are in
#: `providers.py`, and their absence costs group rules and room filtering rather
#: than the sync.
REQUIRED = ("User.Read.All",)


class DirectoryProblem(Exception):
    """Something an admin can act on, phrased for them rather than for a log."""


#: The delegated scopes, when this connection acts as an account.
DELEGATED_SCOPES = [
    "https://graph.microsoft.com/User.Read.All",
    "https://graph.microsoft.com/GroupMember.Read.All",
]


def token_for(db: DbSession, connection: OauthClient) -> str:
    """A fresh token for reading this directory, however it signs in.

    **Two modes, and the branch is the whole of the difference** — see
    `oauth_client.directory_auth_mode`. Acting as the application needs no account
    and one consent press by a Privileged Role Administrator; acting as an account
    needs a sign-in a Cloud Application Administrator can do alone. A deployment
    picks at setup, because the two permission sets cannot share a registration.
    """
    tenant = (connection.tenant_id or "").strip()
    if not tenant:
        raise DirectoryProblem(
            "This Microsoft connection has no directory (tenant) ID, and reading "
            "your people needs one. Add it on the Integrations page."
        )

    if connection.directory_auth_mode == "delegated":
        try:
            return tenant_account.access_token(db, connection, scopes=DELEGATED_SCOPES)
        except (tenant_account.NotConnected, tenant_account.Refused) as problem:
            raise DirectoryProblem(str(problem)) from None

    response = httpx.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            # `.default` means "every application permission already granted",
            # which is what admin consent decided. Naming scopes individually is
            # not how this grant works.
            "scope": "https://graph.microsoft.com/.default",
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        # Microsoft's own words: "AADSTS7000215: Invalid client secret" is worth
        # passing straight through.
        raise DirectoryProblem(
            f"Microsoft refused the connection ({response.status_code}). "
            f"{_refused(response)}"
        )
    token = response.json().get("access_token")
    if not token:
        raise DirectoryProblem("Microsoft returned no access token.")
    return str(token)


def _refused(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error_description") or body.get("error") or ""
    return str(error)[:400] if error else ""


def _needs_consent(connection: OauthClient) -> DirectoryProblem:
    """A 403 from Graph, rephrased as the thing to go and do.

    **The advice differs by mode, and getting it wrong wasted an afternoon.** In
    application mode the permission needed is an app role, which a Cloud
    Application Administrator cannot consent to — and worse, the delegated version
    of the same name consents cleanly, shows green in Entra, and is invisible to
    an app-only token. So the message names the *type*, not just the name.
    """
    tenant = (connection.tenant_id or "").strip()
    where = (
        f"https://login.microsoftonline.com/{tenant}/adminconsent"
        f"?client_id={connection.client_id}"
    )

    if connection.directory_auth_mode == "delegated":
        return DirectoryProblem(
            "Microsoft accepted the sign-in and refused to read your directory. "
            f"The application is missing admin consent for {REQUIRED[0]} as a "
            "DELEGATED permission. A Cloud Application Administrator can grant "
            f"this. Grant it at: {where}"
        )

    return DirectoryProblem(
        "Microsoft accepted the credential and refused to read your directory. "
        f"This needs {REQUIRED[0]} as an APPLICATION permission. Check Entra "
        "→ App registrations → API permissions: if it lists it as "
        "Delegated, that is the problem — a delegated permission acts as a "
        "signed-in person and nobody signs in for this mode, so the token carries "
        "none of it however green the consent column looks. Re-run the automatic "
        f"setup to add the application version, then grant consent at: {where} "
        "Consenting before re-running grants the delegated one again and changes "
        "nothing. Granting an application permission needs a Privileged Role "
        "Administrator — or switch this connection to the service-account "
        "mode, which a Cloud Application Administrator can finish alone."
    )


def _collect(client: httpx.Client, url: str, params: dict | None = None) -> list[dict]:
    """Every item of a Graph collection, following `@odata.nextLink`.

    The next link is a **complete URL** with its own query string, so it is
    requested as-is rather than having parameters merged into it — merging would
    duplicate `$select` and produce a request Graph rejects.
    """
    found: list[dict] = []
    next_url: str | None = url
    send_params = params

    for _ in range(MAX_PAGES):
        if next_url is None:
            return found
        body = request_json(client, next_url, send_params or {}, "Microsoft 365")
        found.extend(item for item in body.get("value", []) if isinstance(item, dict))
        next_url = body.get("@odata.nextLink")
        # Already baked into the next link, and sending them again is an error.
        send_params = None

    logger.warning("Stopped reading %s after %s pages", url, MAX_PAGES)
    return found


def _mailbox_purposes(client: httpx.Client, ids: list[str]) -> dict[str, str]:
    """What each account's mailbox is *for*, in batches of twenty.

    The one reliable way to tell a person from a meeting room. Costs one request
    per twenty accounts rather than one per account, which is the difference
    between a sync and a rate-limit ban.

    **A failure here is not fatal.** An account whose purpose cannot be read is
    treated as a person: including a meeting room by mistake is a visible, fixable
    annoyance, and excluding a real employee because one sub-request failed is a
    person silently missing from the leaderboard.
    """
    purposes: dict[str, str] = {}
    for start in range(0, len(ids), BATCH):
        chunk = ids[start : start + BATCH]
        requests = [
            {
                "id": str(index),
                "method": "GET",
                "url": f"/users/{user_id}/mailboxSettings?$select=userPurpose",
            }
            for index, user_id in enumerate(chunk)
        ]
        try:
            body = request_json(
                client,
                f"{GRAPH}/$batch",
                {},
                "Microsoft 365",
                method="POST",
                json={"requests": requests},
            )
        except Exception as problem:  # noqa: BLE001 — see the docstring
            logger.info("Could not read mailbox purposes: %s", problem)
            continue
        for answer in body.get("responses", []):
            if answer.get("status") != 200:
                continue
            index = int(answer.get("id", -1))
            if 0 <= index < len(chunk):
                purpose = (answer.get("body") or {}).get("userPurpose")
                if purpose:
                    purposes[chunk[index]] = str(purpose).lower()
    return purposes


def photo_tags(client: httpx.Client, ids: list[str]) -> dict[str, str]:
    """Graph's tag for each person's photograph, in batches of twenty.

    **Metadata first, bytes second.** A photograph is binary, so it cannot ride
    in a `$batch` and each one is a request of its own. Asking what the photo
    *is* first costs one request per twenty people and means the expensive call
    happens only for the faces that changed — four hundred and fifty downloads
    the first night and none the next.

    Missing is normal, not an error: most directories have photographs for some
    people and not others. An account with none is simply absent from the result.
    """
    tags: dict[str, str] = {}
    for start in range(0, len(ids), BATCH):
        chunk = ids[start : start + BATCH]
        requests = [
            {"id": str(index), "method": "GET", "url": f"/users/{user_id}/photo"}
            for index, user_id in enumerate(chunk)
        ]
        try:
            response = client.post(f"{GRAPH}/$batch", json={"requests": requests})
            response.raise_for_status()
            replies = response.json().get("responses", [])
        except Exception:  # noqa: BLE001 — a face is not worth failing a sync for
            logger.warning("directory: could not read photo tags for a batch")
            continue

        for reply in replies:
            if reply.get("status") != 200:
                continue
            body = reply.get("body") or {}
            tag = body.get("@odata.mediaEtag") or body.get("id")
            if not tag:
                continue
            index = int(reply.get("id", -1))
            if 0 <= index < len(chunk):
                tags[chunk[index]] = str(tag)[:120]
    return tags


def photo_bytes(client: httpx.Client, user_id: str) -> bytes | None:
    """One person's photograph, or `None` if there is not one.

    A 404 is the ordinary answer for somebody who never uploaded one, so it is
    not logged. Anything else is worth a line but not an exception: the sync's
    job is people, and a face it could not fetch tonight it can fetch tomorrow.
    """
    try:
        response = client.get(f"{GRAPH}/users/{user_id}/photo/$value")
    except Exception:  # noqa: BLE001
        logger.warning("directory: photo request failed for %s", user_id)
        return None

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        logger.warning(
            "directory: photo for %s came back %s", user_id, response.status_code
        )
        return None
    return response.content


def _groups(client: httpx.Client) -> dict[str, list[str]]:
    """Which groups each person belongs to, by user id.

    Microsoft Teams *are* Microsoft 365 groups, which is why this needs no separate
    integration: the same token reads both. Group membership is the strongest of
    the four things a rule can match on — a department is a string somebody typed
    into Entra once, while membership of *Phoenix Sales* is a fact somebody
    actively maintains.
    """
    membership: dict[str, list[str]] = {}
    try:
        groups = _collect(
            client,
        f"{GRAPH}/groups",
        {
            "$select": "id,displayName",
            "$filter": "groupTypes/any(c:c eq 'Unified')",
                "$top": PAGE_SIZE,
            },
        )
    except RestProblem as problem:
        # **Optional, so a refusal costs group rules and nothing else.**
        # `GroupMember.Read.All` is not in every registration — the product this
        # was modelled on runs without it — and letting a 403 here kill the sync
        # would trade every person in the tenant for one of the four things a rule
        # can match on.
        logger.info("Could not read groups (%s). Group rules will match nobody.", problem)
        return {}

    for group in groups:
        name = str(group.get("displayName") or "").strip()
        group_id = str(group.get("id") or "")
        if not name or not group_id:
            continue
        try:
            members = _collect(
                client,
                f"{GRAPH}/groups/{group_id}/members",
                {"$select": "id", "$top": PAGE_SIZE},
            )
        except Exception as problem:  # noqa: BLE001
            # One unreadable group must not cost the whole sync. Its rules simply
            # match nobody this time round.
            logger.info("Could not read members of %s: %s", name, problem)
            continue
        for member in members:
            member_id = str(member.get("id") or "")
            if member_id:
                membership.setdefault(member_id, []).append(name)
    return membership


def people(
    db: DbSession, connection: OauthClient, *, with_groups: bool = True
) -> list[Person]:
    """Everybody in the tenant who is a person, with their group membership.

    Raises rather than returning a short list on failure. **Reconcile archives
    anybody absent**, so half a directory is far more dangerous than none at all —
    it would look like half the company left.
    """
    token = token_for(db, connection)

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    ) as client:
        try:
            accounts = _collect(
                client, f"{GRAPH}/users", {"$select": USER_FIELDS, "$top": PAGE_SIZE}
            )
        except RestProblem as problem:
            # Translated here rather than in the engine, because this is the only
            # layer that knows *which* permissions were needed.
            if problem.status == 403:
                raise _needs_consent(connection) from None
            raise
        candidates = [
            a
            for a in accounts
            if _is_person(a)
            and not (connection.directory_ignore_unlicensed and _unlicensed(a))
        ]
        purposes = _mailbox_purposes(client, [str(a["id"]) for a in candidates])
        membership = _groups(client) if with_groups else {}

    found = []
    for account in candidates:
        user_id = str(account["id"])
        if purposes.get(user_id) in NOT_A_PERSON:
            continue
        found.append(
            Person(
                external_id=user_id,
                # `mail` is the real mailbox; `userPrincipalName` is the sign-in
                # name and is often the same. Falling back matters for tenants that
                # never set `mail`, where every person would otherwise be skipped.
                email=str(account.get("mail") or account.get("userPrincipalName") or ""),
                display_name=str(account.get("displayName") or ""),
                job_title=str(account.get("jobTitle") or ""),
                department=str(account.get("department") or ""),
                office_location=str(account.get("officeLocation") or ""),
                groups=tuple(membership.get(user_id, ())),
                enabled=bool(account.get("accountEnabled", True)),
            )
        )
    return found


def _unlicensed(account: dict) -> bool:
    """Whether this account holds no licence at all.

    **Deliberately the simple test.** A richer version would resolve each
    `skuId` against the tenant's subscribed SKUs and discount the free ones —
    Fabric Free and Power BI Standard make an account look licensed while nobody
    works there. That needs `Organization.Read.All` and a second Graph call, and
    it refines a filter rather than making one possible, so it is not here yet.

    An account with an empty list is unambiguous, and that is the overwhelming
    majority of what this exists to remove.
    """
    return not (account.get("assignedLicenses") or [])


def _is_person(account: dict) -> bool:
    """Whether an account is worth asking any further questions about.

    The cheap checks, done before spending a batch request on the mailbox.
    """
    if not account.get("id"):
        return False
    # Guests are in the directory and are not staff. Including them would put a
    # customer's own employees on the client's leaderboard.
    if str(account.get("userType") or "").lower() == "guest":
        return False
    # Somebody with no address could not sign in here, and there would be nothing
    # to match their metric rows against either.
    return bool(account.get("mail") or account.get("userPrincipalName"))
