"""The Microsoft Teams structure: Teams, their channels, and who is in them.

Kept by Microsoft's own ids, so a Team renamed in Microsoft is renamed here
rather than breaking whatever it was linked to.

**Read as little as the job needs.** A scheduled sync reads the list of Teams
(one request, usually), the members of whatever is *linked*, and the channels of
Teams that have a linked channel. Everything else — every channel of every Team,
so an admin can pick one — is read only when an admin presses "Read from
Microsoft Teams". A tenant with two hundred Teams would otherwise spend four
hundred requests a day telling us about Teams nobody here uses.

A standard channel's members are exactly its Team's, so they are never read:
only private and shared channels have people of their own.

**Channels are optional.** They need `Channel.ReadBasic.All` and
`ChannelMember.Read.All`, which a registration made before this existed does not
have. Without them the Teams are still read and the panel says what to grant; a
refusal never costs the sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app import tenant_account
from app.connectors.rest import HTTP_TIMEOUT, RestProblem
from app.models import M365Link, M365Member, M365Source, OauthClient

logger = logging.getLogger(__name__)

__all__ = ["Channel", "Structure", "TeamInfo", "read", "store", "wanted"]

#: The delegated scopes channels need, asked for separately so that a
#: registration without them still reads its Teams.
CHANNEL_SCOPES = [
    "https://graph.microsoft.com/Channel.ReadBasic.All",
    "https://graph.microsoft.com/ChannelMember.Read.All",
]

TEAMS_REFUSED = (
    "Microsoft Teams could not be read. Grant GroupMember.Read.All to this app "
    "registration."
)

def channels_refused(mode: str | None) -> str:
    """What to do about channels being refused, for this connection's mode.

    **The kind of permission is the whole of the advice**, the same trap the
    directory's own message warns about: a delegated grant of the same name
    consents cleanly, shows green in Entra, and is invisible to an app-only
    token.
    """
    kind = "DELEGATED" if mode == "delegated" else "APPLICATION"
    who = (
        "A Cloud Application Administrator can grant these."
        if mode == "delegated"
        else "Granting application permissions needs a Privileged Role "
        "Administrator or Global Administrator."
    )
    return (
        "Microsoft refused to list channels, so only Teams are shown. Add "
        f"Channel.ReadBasic.All and ChannelMember.Read.All as {kind} permissions "
        "— Microsoft 365 connection → Re-run automatic setup does it — and grant "
        f"admin consent. {who}"
    )


@dataclass
class TeamInfo:
    external_id: str
    name: str
    #: None when not read this time — which is not the same as "nobody".
    members: list[str] | None = None


@dataclass
class Channel:
    external_id: str
    team_external_id: str
    name: str
    membership: str
    #: Private and shared channels only, and None when not read this time.
    members: list[str] | None = None


@dataclass
class Structure:
    teams: list[TeamInfo] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    #: What could not be read, in words for the settings page.
    problems: list[str] = field(default_factory=list)
    #: Whether the list of Teams itself was read. False means nothing is known.
    teams_read: bool = True
    #: The Teams whose channels were read in full. Only their missing channels
    #: may be marked gone: a Team whose channels were not asked about has not
    #: lost any.
    channels_read_for: set[str] = field(default_factory=set)


@dataclass
class Wanted:
    """What one read should ask about. `None` means everything."""

    members_for: set[str] | None = None
    channels_for: set[str] | None = None


def wanted(db: DbSession, org_id: int) -> Wanted:
    """What a scheduled sync needs: the linked sources and their Teams."""
    rows = db.execute(
        select(M365Source)
        .join(M365Link, M365Link.source_id == M365Source.id)
        .where(M365Source.organization_id == org_id)
    ).scalars().all()
    members = {row.external_id for row in rows}
    channels: set[str] = set()
    for row in rows:
        if row.kind == "channel" and row.parent_id is not None:
            parent = db.get(M365Source, row.parent_id)
            if parent is not None:
                channels.add(parent.external_id)
    return Wanted(members_for=members, channels_for=channels)


def _asked(which: set[str] | None, external_id: str) -> bool:
    return which is None or external_id in which


def read(db: DbSession, connection: OauthClient, want: Wanted | None = None) -> Structure:
    """Read the Teams and, as far as `want` asks and the permissions allow,
    their channels and members."""
    from app.directory import microsoft

    want = want or Wanted()
    out = Structure()
    token = microsoft.token_for(db, connection)
    channel_token: str | None = token
    if connection.directory_auth_mode == "delegated":
        # A separate token for channels: asking for scopes a delegated
        # registration was never granted fails the whole token request, and
        # that must cost the channels, not the Teams.
        try:
            channel_token = tenant_account.access_token(
                db, connection, scopes=microsoft.DELEGATED_SCOPES + CHANNEL_SCOPES
            )
        except Exception:  # noqa: BLE001
            channel_token = None

    with httpx.Client(timeout=HTTP_TIMEOUT, headers={"Authorization": f"Bearer {token}"}) as client:
        try:
            teams = microsoft._collect(
                client,
                f"{microsoft.GRAPH}/groups",
                {
                    "$filter": "resourceProvisioningOptions/Any(x:x eq 'Team')",
                    "$select": "id,displayName",
                    "$top": microsoft.PAGE_SIZE,
                },
            )
        except RestProblem as problem:
            logger.info("Could not read Teams: %s", problem)
            out.problems.append(TEAMS_REFUSED)
            out.teams_read = False
            return out

        for team in teams:
            team_id = str(team.get("id") or "")
            name = str(team.get("displayName") or "").strip()
            if not team_id or not name:
                continue
            info = TeamInfo(external_id=team_id, name=name)
            if _asked(want.members_for, team_id):
                try:
                    info.members = [
                        str(m["id"])
                        for m in microsoft._collect(
                            client,
                            f"{microsoft.GRAPH}/groups/{team_id}/members",
                            {"$select": "id", "$top": microsoft.PAGE_SIZE},
                        )
                        if m.get("id")
                    ]
                except RestProblem as problem:
                    logger.info("Could not read members of %s: %s", name, problem)
            out.teams.append(info)

    asking = [t for t in out.teams if _asked(want.channels_for, t.external_id)]
    if not asking:
        return out
    refused = channels_refused(connection.directory_auth_mode)
    if channel_token is None:
        out.problems.append(refused)
        return out

    with httpx.Client(
        timeout=HTTP_TIMEOUT, headers={"Authorization": f"Bearer {channel_token}"}
    ) as client:
        for team in asking:
            try:
                channels = microsoft._collect(
                    client,
                    f"{microsoft.GRAPH}/teams/{team.external_id}/channels",
                    {"$select": "id,displayName,membershipType"},
                )
            except RestProblem as problem:
                logger.info("Could not read channels of %s: %s", team.name, problem)
                if problem.status in (401, 403):
                    # A permission, not this Team: every other Team would be
                    # refused the same way, so asking fifty times is fifty
                    # requests to learn one thing.
                    out.problems.append(refused)
                    break
                continue
            out.channels_read_for.add(team.external_id)

            for channel in channels:
                channel_id = str(channel.get("id") or "")
                name = str(channel.get("displayName") or "").strip()
                membership = str(channel.get("membershipType") or "standard")
                if membership not in ("standard", "private", "shared"):
                    membership = "standard"
                if not channel_id or not name:
                    continue
                found = Channel(
                    external_id=channel_id, team_external_id=team.external_id,
                    name=name, membership=membership,
                )
                if membership != "standard" and _asked(want.members_for, channel_id):
                    try:
                        found.members = [
                            str(m["userId"])
                            for m in microsoft._collect(
                                client,
                                f"{microsoft.GRAPH}/teams/{team.external_id}"
                                f"/channels/{channel_id}/members",
                            )
                            if m.get("userId")
                        ]
                    except RestProblem as problem:
                        logger.info("Could not read members of %s: %s", name, problem)
                out.channels.append(found)
    return out


def store(db: DbSession, org_id: int, structure: Structure, *, now: datetime) -> None:
    """Write what was read: update what is known, add what is new, and mark as
    gone what was looked for and not found.

    **Only what was actually asked about changes.** Members not read this time
    keep the ones stored; channels of a Team that was not asked about are not
    gone, just not looked at.
    """
    if not structure.teams_read:
        return
    existing = {
        (row.kind, row.external_id): row
        for row in db.scalars(select(M365Source).where(M365Source.organization_id == org_id)).all()
    }
    seen: set[int] = set()

    def upsert(kind, external_id, name, parent_id=None, membership=None) -> M365Source:
        row = existing.get((kind, external_id))
        if row is None:
            row = M365Source(
                organization_id=org_id, kind=kind, external_id=external_id,
                name=name[:300], parent_id=parent_id, membership=membership,
                last_seen_at=now,
            )
            db.add(row)
            db.flush()
            existing[(kind, external_id)] = row
        else:
            row.name = name[:300]
            row.parent_id = parent_id
            row.membership = membership
            row.last_seen_at = now
            row.gone_at = None
        seen.add(row.id)
        return row

    def members(source: M365Source, people: list[str] | None) -> None:
        if people is None:
            return
        db.execute(delete(M365Member).where(M365Member.source_id == source.id))
        for person in dict.fromkeys(people):
            db.add(M365Member(source_id=source.id, person_external_id=person))

    teams: dict[str, M365Source] = {}
    for team in structure.teams:
        row = upsert("team", team.external_id, team.name)
        members(row, team.members)
        teams[team.external_id] = row

    for channel in structure.channels:
        parent = teams.get(channel.team_external_id)
        if parent is None:
            continue
        row = upsert("channel", channel.external_id, channel.name, parent.id, channel.membership)
        members(row, channel.members if channel.membership != "standard" else [])

    by_id = {row.id: row for row in existing.values()}
    for (kind, _), row in existing.items():
        if row.id in seen or row.gone_at is not None:
            continue
        if kind == "channel":
            parent = by_id.get(row.parent_id) if row.parent_id else None
            # A channel is gone when its Team is, or when its Team's channels
            # were read and it was not among them.
            if parent is not None and parent.id in seen and (
                parent.external_id not in structure.channels_read_for
            ):
                continue
        row.gone_at = now
    db.flush()
