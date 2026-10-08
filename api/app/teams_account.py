"""The Microsoft account announcements are posted to Teams channels as.

**Why an account at all.** Microsoft Graph lets an application post into a
channel only while importing old messages; everyday posting is always *as
somebody*. So choosing a channel from a list — rather than making a Workflows
link inside it — means one account signs in once, and every post comes from it.
An account made for the job ("GoalGetter") reads best in a channel and does not
leave when a person does.

**What it can reach is what it is in.** The picker lists the Teams this account
is a member of, and their channels it can see; a private channel appears only
if it is in that channel too. Posting anywhere else is refused by Microsoft,
which is the right boundary for an account nobody is watching.

One sign-in for the deployment, the same shape as `excel_account` — its own
refresh token, so signing the Excel account out does not stop announcements.
"""

from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy.orm import Session as DbSession

from app.crypto import decrypt, encrypt
from app.models import OauthClient
from app.oauth import secret_of
from app.tenant_account import HTTP_TIMEOUT, NotConnected, Refused, _describe, _tenant_of

logger = logging.getLogger(__name__)

__all__ = [
    "NotConnected",
    "Refused",
    "SCOPES",
    "access_token",
    "channels",
    "connected_as",
    "describe_channel",
    "forget",
    "is_connected",
    "joined_teams",
    "post_card",
    "store",
]

GRAPH = "https://graph.microsoft.com/v1.0"

#: The minimum: list its Teams, list their channels, post. Nothing reads a
#: message, and nothing here can.
SCOPES: list[str] = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "https://graph.microsoft.com/Team.ReadBasic.All",
    "https://graph.microsoft.com/Channel.ReadBasic.All",
    "https://graph.microsoft.com/ChannelMessage.Send",
]

WHERE = "Integrations → Microsoft Teams → Announcements"


def store(db: DbSession, connection: OauthClient, *, refresh_token: str, connected_as: str) -> None:
    connection.teams_post_refresh_token_encrypted = encrypt(refresh_token)
    connection.teams_post_connected_as = connected_as
    db.flush()


def forget(db: DbSession, connection: OauthClient) -> None:
    """Drop the account. Picked channels stay, and say they cannot post."""
    connection.teams_post_refresh_token_encrypted = None
    connection.teams_post_connected_as = ""
    db.flush()


def is_connected(connection: OauthClient | None) -> bool:
    return bool(connection and connection.teams_post_refresh_token_encrypted)


def connected_as(connection: OauthClient | None) -> str:
    return (connection.teams_post_connected_as or "") if connection else ""


def access_token(db: DbSession, connection: OauthClient) -> str:
    """A fresh access token, writing back a rotated refresh token — see
    `excel_account.access_token` for why that one line matters."""
    if not connection.teams_post_refresh_token_encrypted:
        raise NotConnected(f"No account is signed in to post to Teams. Sign one in under {WHERE}.")

    response = httpx.post(
        f"https://login.microsoftonline.com/{_tenant_of(connection)}/oauth2/v2.0/token",
        data={
            "grant_type": "refresh_token",
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            "refresh_token": decrypt(connection.teams_post_refresh_token_encrypted),
            "scope": " ".join(SCOPES),
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise Refused(
            "Microsoft would not renew access for "
            f"{connection.teams_post_connected_as or 'the posting account'}. "
            f"{_describe(response)} Sign it in again under {WHERE}."
        )
    body = response.json()
    token = str(body.get("access_token") or "")
    if not token:
        raise Refused("Microsoft returned no access token.")
    rotated = str(body.get("refresh_token") or "")
    if rotated:
        connection.teams_post_refresh_token_encrypted = encrypt(rotated)
        db.flush()
    return token


# ── Graph ────────────────────────────────────────────────────────────────────


class GraphProblem(Exception):
    """Something Microsoft refused, in words for the settings page."""


def _get(token: str, path: str, params: dict | None = None) -> dict:
    response = httpx.get(
        f"{GRAPH}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code == 403:
        raise GraphProblem(
            "Microsoft refused. The posting account needs Team.ReadBasic.All and "
            "Channel.ReadBasic.All — Re-run automatic setup on the Microsoft 365 "
            "connection, then sign the account in again."
        )
    if response.status_code == 404:
        raise GraphProblem("That Team or channel no longer exists, or this account is not in it.")
    if response.status_code >= 400:
        raise GraphProblem(f"Microsoft answered {response.status_code}.")
    return response.json()


def joined_teams(token: str) -> list[dict]:
    """The Teams this account is a member of, by name."""
    body = _get(token, "/me/joinedTeams", {"$select": "id,displayName"})
    found = [
        {"id": str(t["id"]), "name": str(t.get("displayName") or "").strip()}
        for t in body.get("value", [])
        if t.get("id")
    ]
    return sorted((t for t in found if t["name"]), key=lambda t: t["name"].lower())


def channels(token: str, team_id: str) -> list[dict]:
    """A Team's channels this account can see — private ones only if it is in them."""
    body = _get(token, f"/teams/{team_id}/channels", {"$select": "id,displayName,membershipType"})
    found = [
        {
            "id": str(c["id"]),
            "name": str(c.get("displayName") or "").strip(),
            "membership": str(c.get("membershipType") or "standard"),
        }
        for c in body.get("value", [])
        if c.get("id")
    ]
    # General first, the way Teams itself lists them.
    return sorted(
        (c for c in found if c["name"]),
        key=lambda c: (c["name"].lower() != "general", c["name"].lower()),
    )


def describe_channel(token: str, team_id: str, channel_id: str) -> str:
    """"Metropolis Sales Team › Closers" — checked with Microsoft, so a channel is
    saved only when this account can actually see it."""
    team = _get(token, f"/teams/{team_id}", {"$select": "displayName"})
    channel = _get(token, f"/teams/{team_id}/channels/{channel_id}", {"$select": "displayName"})
    return f"{team.get('displayName') or 'Team'} › {channel.get('displayName') or 'channel'}"[:300]


def message_of(card_payload: dict) -> dict:
    """A Workflows-shaped card payload, as a Graph channel message.

    Graph wants the card as a *string* in an attachment, referenced from the
    message body by id. The same card object is used either way, so a picked
    channel and a Workflows channel show the identical post.
    """
    attachments = card_payload.get("attachments") or []
    content = attachments[0].get("content") if attachments else {}
    return {
        "body": {"contentType": "html", "content": '<attachment id="goalgetter"></attachment>'},
        "attachments": [
            {
                "id": "goalgetter",
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": json.dumps(content),
            }
        ],
    }


def post_card(token: str, team_id: str, channel_id: str, card_payload: dict) -> httpx.Response:
    return httpx.post(
        f"{GRAPH}/teams/{team_id}/channels/{channel_id}/messages",
        json=message_of(card_payload),
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
        follow_redirects=False,
    )
