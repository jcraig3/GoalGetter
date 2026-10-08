"""Creating the Entra application for an admin, instead of describing it to them.

**The manual path is five minutes of console work and four ways to get it wrong**:
a redirect URI that must match exactly, permissions that exist twice under the same
name on different tabs, a *Grant admin consent* button nobody presses unless told,
and a secret that is shown once. `ProviderSetup` exists largely to narrate all four.
This does them instead.

**Nothing is registered in advance, by anybody.** That is the part worth
understanding, because it is what makes this possible in software somebody pulls
onto their own server: the sign-in runs as Microsoft's *own* command-line client,
which is a public client already present in every tenant — see
`providers.GRAPH_CLI_CLIENT_ID`. There is no application belonging to this project
anywhere in the flow, no secret shipped in the repository, and nothing a
deployment has to be given. The admin consents on screen to three delegated
permissions, we spend the resulting token creating *their* registration, and the
bootstrap token is discarded at the end of the request.

**Device code rather than a redirect**, and the reason is not that a browser is
missing — the admin is looking at one. It is that every deployment lives at a
different URL, Entra matches redirect URIs exactly and has no wildcards, so no
redirect-based flow can be pre-registered for software that has not been installed
yet. The device code flow is the only one that needs no callback at all, which also
means this works from a laptop, from behind a firewall, and from a server Microsoft
cannot reach.

**Three ways a tenant can refuse, all of them fine.** Conditional Access may block
device sign-in; the tenant may require assignment for Microsoft's command-line
client; the admin may not hold a senior enough role. All three surface as a
readable message and the manual form is directly underneath it on the same panel,
so a refusal costs a click rather than a support conversation.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings
from app.providers import Bootstrap, Permission

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"

#: Microsoft Graph's own application id. The same value in every tenant — it is
#: Microsoft's, not a customer's — but the *service principal* it resolves to is
#: per-tenant, which is why it is looked up rather than hardcoded further.
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"

HTTP_TIMEOUT = 30.0

#: How long the created secret lasts. Microsoft's own maximum for a new one.
#:
#: Worth stating rather than taking the default: a connection that stops working in
#: two years with an authorization error is the single least debuggable failure this
#: module can produce, and the expiry is at least visible in their console.
SECRET_DAYS = 365 * 2


class SetupProblem(Exception):
    """Something an admin can act on, phrased for them rather than for a log."""


@dataclass(frozen=True)
class DeviceCode:
    """What to put on screen while the admin goes and signs in."""

    user_code: str
    #: Where Microsoft says to enter it. Displayed as given rather than hardcoded:
    #: the value is Microsoft's to change, and it varies by cloud — a tenant in the
    #: government or China clouds is sent somewhere else entirely.
    verification_uri: str
    #: Held by the caller between the two requests, never shown. Anyone holding it
    #: can collect the token the admin is in the middle of approving.
    device_code: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class Approval:
    """The admin, having signed in and consented."""

    access_token: str
    tenant_id: str


@dataclass(frozen=True)
class Registration:
    """The application that now exists in their directory."""

    client_id: str
    client_secret: str
    tenant_id: str
    #: Permission names that are granted and working.
    granted: tuple[str, ...]
    #: Permission names the application asks for that this admin could not consent
    #: to. **Not a failure** — the registration is real and the rest of it works.
    #: Microsoft reserves consent for its own application permissions to
    #: Privileged Role Administrator, so a Cloud Application Administrator can
    #: create all of this and still not finish the last step.
    pending: tuple[str, ...]


def client_id_for(bootstrap: Bootstrap) -> str:
    """Which public client to sign in as.

    The deployment's own choice wins, for the tenant that restricts Microsoft's
    command-line client — a real configuration, and one that otherwise leaves an
    admin with an error they cannot act on.
    """
    override = (get_settings().entra_bootstrap_client_id or "").strip()
    return override or bootstrap.client_id


def start(bootstrap: Bootstrap) -> DeviceCode:
    """Ask Microsoft for a code, which the admin then goes and enters.

    Only called when somebody has pressed the button: the code lives fifteen
    minutes from this moment, so requesting one early spends most of that window
    on somebody reading the page.
    """
    response = httpx.post(
        bootstrap.devicecode_url,
        data={
            "client_id": client_id_for(bootstrap),
            "scope": " ".join(bootstrap.scopes),
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise SetupProblem(
            "Microsoft would not start the sign-in. " + _refusal(response)
        )

    body = _decoded(response)
    code = str(body.get("user_code") or "")
    uri = str(body.get("verification_uri") or "")
    device = str(body.get("device_code") or "")
    if not (code and uri and device):
        raise SetupProblem("Microsoft did not return a sign-in code.")

    return DeviceCode(
        user_code=code,
        verification_uri=uri,
        device_code=device,
        # Microsoft's own pacing, honoured rather than guessed: polling faster than
        # it asks earns `slow_down` and then nothing at all.
        interval=_positive(body.get("interval"), 5),
        expires_in=_positive(body.get("expires_in"), 900),
    )


def poll(bootstrap: Bootstrap, device_code: str) -> Approval | None:
    """The admin's token once they have finished, or None while they have not.

    None is the *expected* answer for most of this flow's life, and is why it is a
    return value rather than an exception: somebody reading a consent screen is not
    an error condition.
    """
    response = httpx.post(
        bootstrap.token_url,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": client_id_for(bootstrap),
            "device_code": device_code,
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    body = _decoded(response)

    if response.status_code == 200:
        token = str(body.get("access_token") or "")
        if not token:
            raise SetupProblem("Microsoft returned no access token.")
        return Approval(
            access_token=token,
            tenant_id=_tenant_of(str(body.get("id_token") or "")),
        )

    error = str(body.get("error") or "")
    if error in ("authorization_pending", "slow_down"):
        return None
    if error == "authorization_declined":
        raise SetupProblem(
            "That sign-in was declined, so nothing was created. Start again, or "
            "register the application by hand using the steps below."
        )
    if error in ("expired_token", "bad_verification_code"):
        raise SetupProblem(
            "That code has expired. Start again — a code lasts about fifteen "
            "minutes from when it appears."
        )
    raise SetupProblem("Microsoft refused the sign-in. " + _refusal(response))


# ── Creating the application ─────────────────────────────────────────────────


@dataclass(frozen=True)
class _Wanted:
    """One permission, resolved to the id Microsoft's API works in."""

    name: str
    #: `application` for an app role, anything else for a delegated scope.
    kind: str
    id: str

    @property
    def is_role(self) -> bool:
        return self.kind == "application"


def provision(
    approval: Approval,
    *,
    app_name: str,
    redirect_uris: list[str],
    permissions: list[Permission],
) -> Registration:
    """Create — or bring up to date — the application, and consent to it.

    **Re-running this is safe and is the intended way to rotate the secret.** An
    application of this name in the tenant is updated rather than duplicated, which
    matters because the alternative is a directory slowly filling with identical
    registrations nobody can tell apart.

    Consent is attempted per permission and reported rather than insisted on: see
    `Registration.pending`. Refusing to create anything because the last of six
    steps needs a more senior admin would throw away the five that worked.
    """
    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={
            "Authorization": f"Bearer {approval.access_token}",
            "Content-Type": "application/json",
        },
        follow_redirects=True,
    ) as client:
        graph = _graph_principal(client)
        wanted, unknown = _resolve(permissions, graph)

        application = _application(client, app_name)
        _configure(client, application, redirect_uris, wanted)
        principal = _principal_for(client, str(application["appId"]), app_name)
        secret = _secret(client, str(application["id"]), app_name)
        granted, refused = _consent(client, principal, graph, wanted)

    return Registration(
        client_id=str(application["appId"]),
        client_secret=secret,
        tenant_id=approval.tenant_id,
        granted=tuple(granted),
        pending=tuple(refused + unknown),
    )


def _graph_principal(client: httpx.Client) -> dict:
    """Microsoft Graph as it exists in *this* tenant, with its permission ids.

    **The reason there is not a table of GUIDs in this file.** Every permission
    Entra works in is an id, and the names an admin reads — `Files.Read.All` — are
    only labels on them. Looking them up here means the created application asks
    for exactly what `providers.py` says and what the panel displays, from one
    list, rather than from a second copy that can drift out of step with it.
    """
    found = _call(
        client,
        "GET",
        f"{GRAPH}/servicePrincipals",
        params={
            "$filter": f"appId eq '{GRAPH_APP_ID}'",
            "$select": "id,appRoles,oauth2PermissionScopes",
        },
    )
    principals = found.get("value") or []
    if not principals:
        raise SetupProblem(
            "Microsoft Graph does not appear in this directory, so permissions "
            "cannot be looked up. Register the application by hand instead."
        )
    return principals[0]


def _resolve(
    permissions: list[Permission], graph: dict
) -> tuple[list[_Wanted], list[str]]:
    """Each permission as an id, and the names that could not be found.

    An unrecognised name is reported rather than raised. It means this build asks
    for something Microsoft has renamed or withdrawn — a real possibility over the
    life of a self-hosted install — and the right answer is a working registration
    missing one permission, with that permission named, rather than no registration
    at all.
    """
    roles = {
        str(role.get("value")): str(role.get("id"))
        for role in graph.get("appRoles") or []
        if role.get("value") and role.get("id")
    }
    scopes = {
        str(scope.get("value")): str(scope.get("id"))
        for scope in graph.get("oauth2PermissionScopes") or []
        if scope.get("value") and scope.get("id")
    }

    wanted: list[_Wanted] = []
    unknown: list[str] = []
    for permission in permissions:
        source = roles if permission.kind == "application" else scopes
        found = source.get(permission.name)
        if found is None:
            logger.warning("Microsoft Graph has no %s permission", permission.name)
            unknown.append(permission.name)
            continue
        wanted.append(_Wanted(name=permission.name, kind=permission.kind, id=found))
    return wanted, unknown


def _application(client: httpx.Client, app_name: str) -> dict:
    """The registration to use, created if this is the first time.

    Matched by display name, which is the only handle available: the tenant is
    somebody else's and holds no record of ours. Two deployments pointing at one
    tenant would share a registration, which is the right answer — that is one
    application serving both, exactly as an admin doing this by hand would.
    """
    # Doubled quotes are OData's escape. `app_name` comes from the catalogue rather
    # than from input, so this guards against a future entry rather than a caller.
    quoted = app_name.replace("'", "''")
    found = _call(
        client,
        "GET",
        f"{GRAPH}/applications",
        params={"$filter": f"displayName eq '{quoted}'", "$select": "id,appId"},
    )
    existing = found.get("value") or []
    if existing:
        return existing[0]

    return _call(
        client,
        "POST",
        f"{GRAPH}/applications",
        json={
            "displayName": app_name,
            # Single tenant. A multi-tenant registration would let accounts from
            # any directory reach this deployment's sign-in, which is emphatically
            # not what somebody connecting their own company's Microsoft expects.
            "signInAudience": "AzureADMyOrg",
        },
        expect=(201,),
    )


def _configure(
    client: httpx.Client,
    application: dict,
    redirect_uris: list[str],
    wanted: list[_Wanted],
) -> None:
    """Set the callbacks and the permissions the application asks for.

    The redirect URIs come from the same function that renders them for copying on
    the manual path, so the automatic and the manual registration cannot disagree
    about what to register — which is the failure the panel spends a whole hint
    warning about.

    A `web` platform, not `spa` or `publicClient`: these callbacks are received by
    the API, which then exchanges the code using the secret created below.
    """
    _call(
        client,
        "PATCH",
        f"{GRAPH}/applications/{application['id']}",
        json={
            "web": {"redirectUris": redirect_uris},
            "requiredResourceAccess": [
                {
                    "resourceAppId": GRAPH_APP_ID,
                    "resourceAccess": [
                        {"id": item.id, "type": "Role" if item.is_role else "Scope"}
                        for item in wanted
                    ],
                }
            ],
        },
        expect=(204, 200),
    )


def _principal_for(client: httpx.Client, app_id: str, app_name: str) -> dict:
    """The application's service principal, which is what permissions attach to.

    An application and its service principal are two objects, and the distinction
    is invisible in the console — creating an app registration there quietly makes
    both. Nothing can be consented to without one, so a missing service principal
    would produce a registration that looks complete and grants nothing.
    """
    found = _call(
        client,
        "GET",
        f"{GRAPH}/servicePrincipals",
        params={"$filter": f"appId eq '{app_id}'", "$select": "id"},
    )
    existing = found.get("value") or []
    if existing:
        return existing[0]
    return _call(
        client,
        "POST",
        f"{GRAPH}/servicePrincipals",
        json={"appId": app_id, "displayName": app_name},
        expect=(201,),
    )


def _secret(client: httpx.Client, object_id: str, app_name: str) -> str:
    """A fresh client secret, which Microsoft returns exactly once.

    Appended rather than replacing: an existing secret keeps working until it
    expires, so re-running this to rotate does not break a deployment that is still
    using the old one. The old one is left to lapse rather than being deleted,
    because deleting a credential belonging to something else in the tenant is not
    a decision to make on somebody's behalf.
    """
    ends = datetime.now(UTC) + timedelta(days=SECRET_DAYS)
    body = _call(
        client,
        "POST",
        f"{GRAPH}/applications/{object_id}/addPassword",
        json={
            "passwordCredential": {
                "displayName": f"{app_name} ({ends.date().isoformat()})",
                "endDateTime": ends.isoformat().replace("+00:00", "Z"),
            }
        },
        expect=(200, 201),
    )
    secret = str(body.get("secretText") or "")
    if not secret:
        raise SetupProblem(
            "Microsoft created the application but returned no client secret. "
            "Add one by hand in Certificates & secrets."
        )
    return secret


def _consent(
    client: httpx.Client,
    principal: dict,
    graph: dict,
    wanted: list[_Wanted],
) -> tuple[list[str], list[str]]:
    """Press *Grant admin consent*, as far as this admin is allowed to.

    **Two mechanisms, because Entra has two.** Delegated permissions are one grant
    holding a space-separated list; application permissions are one assignment
    each. They are also governed differently, and that is the whole reason this
    reports rather than raises: Cloud Application Administrator can consent to
    every delegated permission here, and to none of Microsoft Graph's application
    ones. Whoever finishes those has to hold Privileged Role Administrator.
    """
    granted: list[str] = []
    refused: list[str] = []

    delegated = [item for item in wanted if not item.is_role]
    if delegated:
        names = [item.name for item in delegated]
        try:
            _grant_delegated(client, str(principal["id"]), str(graph["id"]), names)
            granted.extend(names)
        except SetupProblem as problem:
            logger.info("Could not consent to delegated permissions: %s", problem)
            refused.extend(names)

    for item in wanted:
        if not item.is_role:
            continue
        try:
            _grant_role(client, str(principal["id"]), str(graph["id"]), item.id)
            granted.append(item.name)
        except SetupProblem as problem:
            logger.info("Could not consent to %s: %s", item.name, problem)
            refused.append(item.name)

    return granted, refused


def _grant_delegated(
    client: httpx.Client, principal_id: str, graph_id: str, names: list[str]
) -> None:
    """One grant for every delegated permission, on behalf of everybody.

    `AllPrincipals` is what tenant-wide consent means — the alternative consents
    for one user, which would leave every other person in the company facing a
    consent prompt they are probably not allowed to answer.

    Updated in place when one already exists. Posting a second grant for the same
    pair is how a tenant ends up with two, and which of them Entra honours is not
    something to leave to chance.
    """
    found = _call(
        client,
        "GET",
        f"{GRAPH}/oauth2PermissionGrants",
        params={
            "$filter": (
                f"clientId eq '{principal_id}' and consentType eq 'AllPrincipals' "
                f"and resourceId eq '{graph_id}'"
            )
        },
    )
    existing = found.get("value") or []
    scope = " ".join(names)

    if existing:
        _call(
            client,
            "PATCH",
            f"{GRAPH}/oauth2PermissionGrants/{existing[0]['id']}",
            json={"scope": scope},
            expect=(204, 200),
        )
        return

    _call(
        client,
        "POST",
        f"{GRAPH}/oauth2PermissionGrants",
        json={
            "clientId": principal_id,
            "consentType": "AllPrincipals",
            "resourceId": graph_id,
            "scope": scope,
        },
        expect=(201, 200),
    )


def _grant_role(
    client: httpx.Client, principal_id: str, graph_id: str, role_id: str
) -> None:
    """Assign one application permission.

    A 409 means it is already assigned, which is success on a re-run and not
    something to report to somebody as a failure.
    """
    _call(
        client,
        "POST",
        f"{GRAPH}/servicePrincipals/{graph_id}/appRoleAssignedTo",
        json={
            "principalId": principal_id,
            "resourceId": graph_id,
            "appRoleId": role_id,
        },
        expect=(201, 200, 409),
    )


# ── Talking to Graph ─────────────────────────────────────────────────────────


def _call(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    expect: tuple[int, ...] = (200,),
) -> dict:
    """One Graph request, with Microsoft's own words on failure.

    Deliberately no retry. Every call here writes, or decides what to write next,
    and repeating a create after an ambiguous failure is how a tenant acquires two
    of something. The whole flow is a few seconds long in front of somebody who
    can press the button again.
    """
    response = client.request(method, url, params=params, json=json)
    if response.status_code in expect:
        return _decoded(response)
    raise SetupProblem(_refusal(response))


def _decoded(response: httpx.Response) -> dict:
    """The body as a dict, or an empty one.

    A 204 has no body at all, and several of the calls above accept one.
    """
    if not response.content:
        return {}
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _refusal(response: httpx.Response) -> str:
    """What Microsoft said, phrased for the person who has to act on it.

    **Passed through rather than summarised**, because Microsoft's messages here
    are unusually good and unusually specific: "the tenant admin has configured the
    application to block users unless they are assigned" tells somebody exactly
    what to do, and no wording of ours would.
    """
    body = _decoded(response)
    error = body.get("error")
    detail = ""
    if isinstance(error, dict):
        detail = str(error.get("message") or "")
    elif error:
        detail = str(body.get("error_description") or error)
    detail = detail or response.text[:200]
    return f"Microsoft said (HTTP {response.status_code}): {detail[:400]}"


def _tenant_of(id_token: str) -> str:
    """Which directory the admin signed in to, from the token issued to us.

    **Reading a token is usually the wrong thing to do**, and this is the exception
    Microsoft documents: an id token is issued *to* this client, for this client,
    and `tid` is the value it is for. The alternative is asking for
    `Organization.Read.All` on the consent screen purely to look up something we
    have already been told, which is a worse trade than parsing three fields.

    Not verified, and it does not need to be: it arrived over TLS from the token
    endpoint in a direct response to our own request, and a wrong tenant here
    produces a connection that immediately fails to sign anybody in.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise SetupProblem(
            "Microsoft did not say which directory that was. Register the "
            "application by hand instead."
        )
    try:
        # Base64url without padding, which is how JWT segments are encoded.
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(raw)
    except (binascii.Error, ValueError) as problem:
        raise SetupProblem(
            "Microsoft's sign-in response could not be read. Please try again."
        ) from problem

    tenant = str(claims.get("tid") or "") if isinstance(claims, dict) else ""
    if not tenant:
        raise SetupProblem(
            "That account has no directory, so there is nothing to register an "
            "application in. Sign in with a work or school account."
        )
    return tenant


def _positive(value: Any, fallback: int) -> int:
    """A count from Microsoft, or ours when it sent something unusable.

    Zero is as dangerous as missing: an interval of nothing is a client polling a
    token endpoint as fast as it can, which earns a rate limit and then a block.
    """
    try:
        found = int(value)
    except (TypeError, ValueError):
        return fallback
    return found if found > 0 else fallback
