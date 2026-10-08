"""Posting wins into chat channels.

A destination is a channel with a webhook link, a list of which kinds of win
it wants, and whose. A job pass finds wins it has not seen, turns each into a
card, and posts it — once, however many times the pass runs.

**Why Workflows webhooks and not Microsoft Graph.** Graph can post into a
Teams channel only as a signed-in person: `ChannelMessage.Send` is delegated
only, and application-only posting is reserved for migrations. That would make
every announcement depend on one real account, and stop the day it is disabled.
Microsoft retired the old channel webhooks on 22 May 2026; the replacement is a
Workflows link made inside the channel, which accepts an Adaptive Card and needs
no app registration and no permission at all.

**Only Microsoft's own webhook hosts are accepted.** The server posts to
whatever link is stored, so an unchecked one would let anybody who can edit a
destination make the server call an arbitrary address inside the network it
runs on. Refused at save, and checked again before every post.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session as DbSession, object_session

from app import crypto, events, public_url
from app.models import AnnouncementDelivery, AnnouncementDestination, Notification, Organization

logger = logging.getLogger(__name__)

__all__ = [
    "CHOICES",
    "DEFAULT_CHOICES",
    "LinkProblem",
    "Report",
    "card",
    "check_link",
    "deliver",
    "hint_of",
    "newest_notification_id",
    "send_test",
]

#: Which kinds of win a destination can ask for, and what each is called on
#: the settings page. Only events that are already public — a chat channel is
#: read by a whole team, and the rule that keeps "behind on your goal" off the
#: wall keeps it out of the channel for the same reason.
CHOICES: dict[str, str] = {
    events.GOAL_ACHIEVED.key: "Goals hit",
    "goal.stretch": "Stretch targets hit",
    events.RECOGNITION.key: "Recognition",
    events.COMPETITION_WON.key: "Competition wins",
    "achievement": "Achievements",
    events.WHEEL_WON.key: "Prize wheel wins",
    events.BIRTHDAY.key: "Birthdays",
    events.WORK_ANNIVERSARY.key: "Work anniversaries",
}

#: What a new destination starts with: the wins people worked for.
DEFAULT_CHOICES = [
    events.GOAL_ACHIEVED.key,
    "goal.stretch",
    events.RECOGNITION.key,
    events.COMPETITION_WON.key,
    "achievement",
]

#: The hosts a Teams Workflows link lives on. Checked as suffixes of the real
#: host, so a look-alike such as `logic.azure.com.example.net` does not pass.
TEAMS_HOSTS = (
    ".logic.azure.com",
    ".api.powerplatform.com",
    ".environment.api.powerplatform.com",
)

#: How many to post to one channel in one pass. A burst — a backfill, a busy
#: afternoon — is spread over several passes rather than hitting the Workflows
#: throttle all at once.
PER_PASS = 20

#: When to try again, by attempt. After the last, it is given up on and the
#: destination says why.
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1))

HTTP_TIMEOUT = 10.0


class LinkProblem(ValueError):
    """Why a webhook link cannot be used, in words somebody can act on."""


def check_link(kind: str, url: str) -> str:
    """The link, tidied, or `LinkProblem`."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise LinkProblem("A webhook link starts with https://.")
    host = (parsed.hostname or "").lower()
    if kind == "teams" and not any(host.endswith(suffix) for suffix in TEAMS_HOSTS):
        raise LinkProblem(
            "That is not a Teams Workflows link. In the channel, choose ⋯ → "
            "Workflows → “Post to a channel when a webhook request is received”, "
            "and copy the link it gives you."
        )
    if kind == "slack" and (host != "hooks.slack.com" or not parsed.path.startswith("/services/")):
        # Exact host, not a suffix: Slack's webhooks live on one name, and a
        # look-alike subdomain has no business receiving a post.
        raise LinkProblem(
            "That is not a Slack incoming webhook link. In Slack, add the "
            "Incoming Webhooks app to the channel and copy the link it gives "
            "you — it starts https://hooks.slack.com/services/."
        )
    return url


def hint_of(encrypted: str | None) -> str:
    """Enough of a stored link to recognise, and not enough to use.

    The link carries its own signature, so whoever holds it can post into the
    channel. The settings page is shown the host and the last few characters.
    """
    if not encrypted:
        return ""
    try:
        url = crypto.decrypt(encrypted)
    except ValueError:
        return "(unreadable — save it again)"
    parsed = urlparse(url)
    return f"{parsed.hostname}/…{url[-6:]}"


def newest_notification_id(db: DbSession, org_id: int) -> int:
    """Where a new destination starts reading from: now."""
    return db.scalar(
        select(func.coalesce(func.max(Notification.id), 0)).where(
            Notification.organization_id == org_id
        )
    ) or 0


def _wanted(destination: AnnouncementDestination, row: Notification) -> bool:
    chosen = set(destination.events or [])
    if row.event_key.startswith("achievement:"):
        return "achievement" in chosen
    if row.event_key.startswith(events.STRETCH_PREFIX):
        # One choice for all three levels: "tell us about stretch targets".
        return "goal.stretch" in chosen
    return row.event_key in chosen and events.is_public(row.event_key)


def _in_scope(destination: AnnouncementDestination, row: Notification) -> bool:
    if destination.office_id is not None:
        return row.about_office_id == destination.office_id
    if destination.team_id is not None:
        return row.about_team_id == destination.team_id
    return True


def _win_key(row: Notification) -> str:
    """One per win, not one per recipient — the key the wall uses."""
    return f"{row.event_key}|{row.subject_type}|{row.subject_id}|{row.period_anchor or ''}"


def _plain(text: str | None) -> str:
    """Text safe for an Adaptive Card, which reads a little Markdown.

    A recognition somebody typed is shown as they typed it, not as formatting:
    an asterisk in "5* service" should not turn the rest of the line bold.
    """
    return re.sub(r"([\\*_\[\]()#>`~])", r"\\\1", text or "")


def card(row: Notification) -> dict:
    """A win as a Teams Adaptive Card, in the order a person reads it: what it
    is for, whose it is, then the detail — the same order the wall uses."""
    from app import channels

    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": _plain(channels.occasion_of(row).upper()),
            "weight": "Bolder",
            "size": "Small",
            "color": "Accent",
            "spacing": "None",
        },
    ]
    if row.about_name:
        body.append(
            {"type": "TextBlock", "text": _plain(row.about_name), "weight": "Bolder",
             "size": "ExtraLarge", "wrap": True, "spacing": "Small"}
        )
    if row.title and row.title not in (row.about_name, channels.occasion_of(row)):
        body.append({"type": "TextBlock", "text": _plain(row.title), "size": "Medium", "wrap": True})
    if row.body:
        body.append({"type": "TextBlock", "text": _plain(row.body), "isSubtle": True, "wrap": True})

    content: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
    }
    if row.link_url:
        content["actions"] = [
            {
                "type": "Action.OpenUrl",
                "title": "Open in GoalGetter",
                "url": _open_url(row),
            }
        ]
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": content,
            }
        ],
    }


def _open_url(row: Notification) -> str:
    """Where "Open in GoalGetter" goes: the address set in Settings (11.7).
    Read through the row's own session — these are built deep inside a job."""
    db = object_session(row)
    return (public_url.get(db) if db is not None else public_url.default()) + (row.link_url or "")


def _mrkdwn(text: str | None) -> str:
    """Text safe for Slack's own markup: `&`, `<` and `>` are the three it
    reads, so "<@here>" typed into a recognition cannot ping a channel."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_message(row: Notification) -> dict:
    """A win as a Slack message, in the same order the Teams card uses."""
    from app import channels

    occasion = channels.occasion_of(row)
    lines = [f"*{_mrkdwn(occasion.upper())}*"]
    if row.about_name:
        lines.append(f"*{_mrkdwn(row.about_name)}*")
    if row.title and row.title not in (row.about_name, occasion):
        lines.append(_mrkdwn(row.title))
    if row.body:
        lines.append(f"_{_mrkdwn(row.body)}_")
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]
    if row.link_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Open in GoalGetter"},
                "url": _open_url(row),
            }],
        })
    # `text` is what a notification and a screen reader show.
    fallback = " — ".join(part for part in (occasion, row.about_name, row.title) if part)
    return {"text": fallback, "blocks": blocks}


def message_for(destination: AnnouncementDestination, row: Notification) -> dict:
    """The post for this destination's kind of chat."""
    return slack_message(row) if destination.kind == "slack" else card(row)


@dataclass
class Report:
    destinations: int = 0
    queued: int = 0
    sent: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return (
            f"announcements {self.destinations} destinations, {self.queued} queued, "
            f"{self.sent} sent, {self.failed} failed"
        )


Poster = Callable[[str, dict], httpx.Response]
#: (token, team id, channel id, card payload) — a picked channel, through Graph.
GraphPoster = Callable[[str, str, str, dict], httpx.Response]


def _post(url: str, payload: dict) -> httpx.Response:
    # No redirects: a webhook that answers with a redirect is not one to follow
    # to wherever it points.
    return httpx.post(url, json=payload, timeout=HTTP_TIMEOUT, follow_redirects=False)


def _post_graph(token: str, team_id: str, channel_id: str, payload: dict) -> httpx.Response:
    from app import teams_account

    return teams_account.post_card(token, team_id, channel_id, payload)


def deliver(
    db: DbSession,
    *,
    now: datetime | None = None,
    post: Poster | None = None,
    post_graph: GraphPoster | None = None,
) -> Report:
    """One pass: queue new wins for every destination, then post what is due.

    **Queued first, posted second, in separate steps.** A win is written down as
    owed to a channel before any network call is made, so a pass that dies
    half-way through posting loses nothing — the next pass finds the rows still
    pending. And the unique index on (destination, win) is what makes queuing
    twice impossible rather than merely unlikely.

    `post` is injectable so a test never touches the network.
    """
    now = now or datetime.now(UTC)
    # Looked up when called, not bound as a default when this was defined —
    # so a test replacing `_post` really does keep the pass off the network.
    post = post or _post
    post_graph = post_graph or _post_graph
    report = Report()

    paused = {
        org_id
        for (org_id,) in db.execute(
            select(Organization.id).where(Organization.teams_enabled.is_(False))
        ).all()
    }

    for destination in db.scalars(
        select(AnnouncementDestination).where(AnnouncementDestination.enabled.is_(True))
    ).all():
        if destination.kind == "teams" and destination.organization_id in paused:
            # Nothing queued and nothing sent while Microsoft Teams is off.
            # Switching it back on starts from then — see `resume`. Slack has
            # no such switch: each Slack channel is switched on its own.
            continue
        report.destinations += 1
        report.queued += _queue(db, destination)
        sent, failed = _send_due(db, destination, now=now, post=post, post_graph=post_graph)
        report.sent += sent
        report.failed += failed

    return report


def _queue(db: DbSession, destination: AnnouncementDestination) -> int:
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.organization_id == destination.organization_id,
            Notification.id > destination.last_notification_id,
        )
        .order_by(Notification.id)
    ).all()

    queued = 0
    highest = destination.last_notification_id
    for row in rows:
        highest = max(highest, row.id)
        if not (_wanted(destination, row) and _in_scope(destination, row)):
            continue
        inserted = db.scalar(
            insert(AnnouncementDelivery)
            .values(
                destination_id=destination.id,
                notification_id=row.id,
                win_key=_win_key(row),
                payload=message_for(destination, row),
                status="pending",
            )
            .on_conflict_do_nothing()
            .returning(AnnouncementDelivery.id)
        )
        if inserted is not None:
            queued += 1

    # Past everything examined, not only what matched — the same reason the
    # achievement rules' watermark works that way.
    destination.last_notification_id = highest
    return queued


def _send_due(
    db: DbSession,
    destination: AnnouncementDestination,
    *,
    now: datetime,
    post: Poster,
    post_graph: GraphPoster,
) -> tuple[int, int]:
    due = db.scalars(
        select(AnnouncementDelivery)
        .where(
            AnnouncementDelivery.destination_id == destination.id,
            AnnouncementDelivery.status.in_(("pending", "retrying")),
            AnnouncementDelivery.next_attempt_at <= now,
        )
        .order_by(AnnouncementDelivery.id)
        .limit(PER_PASS)
    ).all()
    if not due:
        return 0, 0

    try:
        send = _sender(db, destination, post=post, post_graph=post_graph)
    except _CannotSend as problem:
        # Nothing is tried: a link that no longer passes, or an account that
        # cannot sign in, would fail every delivery the same way.
        destination.last_error = str(problem)[:500]
        destination.last_error_at = now
        return 0, 0

    sent = failed = 0
    for delivery in due:
        error = send(delivery.payload)
        delivery.attempts += 1
        if error is None:
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.last_error = None
            destination.last_sent_at = now
            sent += 1
            continue

        failed += 1
        delivery.last_error = error[:500]
        destination.last_error = error[:500]
        destination.last_error_at = now
        if delivery.attempts > len(BACKOFF):
            delivery.status = "gave_up"
        else:
            delivery.status = "retrying"
            delivery.next_attempt_at = now + BACKOFF[delivery.attempts - 1]
    return sent, failed


class _CannotSend(Exception):
    """Why a destination cannot be posted to at all right now."""


def _sender(
    db: DbSession | None,
    destination: AnnouncementDestination,
    *,
    post: Poster,
    post_graph: GraphPoster,
) -> Callable[[dict], str | None]:
    """How to post to this destination: its Workflows link, or Graph as the
    signed-in account. Worked out once per pass — one token, one link check."""
    if destination.via == "graph":
        from app import teams_account
        from app.models import OauthClient

        connection = (
            db.scalar(
                select(OauthClient).where(
                    OauthClient.organization_id == destination.organization_id,
                    OauthClient.provider == "microsoft",
                )
            )
            if db is not None
            else None
        )
        if connection is None:
            raise _CannotSend("Microsoft 365 is not connected, so a picked channel cannot be posted to.")
        try:
            token = teams_account.access_token(db, connection)
        except (teams_account.NotConnected, teams_account.Refused) as problem:
            raise _CannotSend(str(problem)) from None
        who = teams_account.connected_as(connection) or "The posting account"
        where = destination.channel_label or "that channel"
        team_id = destination.team_external_id or ""
        channel_id = destination.channel_external_id or ""
        return lambda payload: _attempt_graph(
            lambda: post_graph(token, team_id, channel_id, payload), who=who, where=where
        )

    try:
        url = check_link(destination.kind, crypto.decrypt(destination.webhook_url or ""))
    except (ValueError, LinkProblem) as problem:
        raise _CannotSend(str(problem)) from None
    return lambda payload: _attempt(url, payload, post, kind=destination.kind)


def _attempt_graph(call: Callable[[], httpx.Response], *, who: str, where: str) -> str | None:
    """Post once through Graph. None on success, otherwise why not, in words."""
    try:
        response = call()
    except httpx.HTTPError as problem:
        return f"Could not reach Microsoft Teams: {problem.__class__.__name__}."
    if 200 <= response.status_code < 300:
        return None
    if response.status_code == 401:
        return "Microsoft refused the posting account's sign-in. Sign it in again."
    if response.status_code == 403:
        return (
            f"{who} cannot post in {where}. Add it to that Team — and to the "
            "channel, if the channel is private."
        )
    if response.status_code == 404:
        return f"{where} no longer exists in Microsoft Teams. Pick another channel."
    return f"Microsoft Teams answered {response.status_code}."


def _attempt(url: str, payload: dict, post: Poster, *, kind: str = "teams") -> str | None:
    """Post once. None on success, otherwise what went wrong, in words."""
    try:
        response = post(url, payload)
    except httpx.HTTPError as problem:
        return f"Could not reach the channel: {problem.__class__.__name__}."
    if 200 <= response.status_code < 300:
        return None
    if kind == "slack" and response.status_code in (403, 404, 410):
        # Slack's own words: invalid_token, no_service, channel_is_archived.
        return (
            f"Slack refused the post ({response.status_code}). The webhook may "
            "have been removed or the channel archived — make a new webhook link."
        )
    if response.status_code in (401, 403, 404):
        return (
            f"The channel refused the post ({response.status_code}). The Workflow "
            "may have been deleted or switched off — make a new link in the channel."
        )
    return f"The channel answered {response.status_code}."


def send_test(
    destination: AnnouncementDestination,
    *,
    db: DbSession | None = None,
    post: Poster | None = None,
    post_graph: GraphPoster | None = None,
) -> str | None:
    """Post a hello card now. None on success, otherwise why not.

    **A chat channel, not a wall** — so a test is reasonable here in a way the
    wall's removed test button was not: it is one message, in one channel, sent
    by the person who is setting it up and watching it arrive.
    """
    post = post or _post
    post_graph = post_graph or _post_graph
    try:
        send = _sender(db, destination, post=post, post_graph=post_graph)
    except _CannotSend as problem:
        return str(problem)
    if destination.kind == "slack":
        hello = _mrkdwn(f"Wins will be posted here as “{destination.name}”.")
        return send({
            "text": "GoalGetter is connected",
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*GOALGETTER*\n*Connected*\n{hello}"}}],
        })
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": "GOALGETTER", "weight": "Bolder",
                         "size": "Small", "color": "Accent"},
                        {"type": "TextBlock", "text": "Connected", "weight": "Bolder",
                         "size": "ExtraLarge"},
                        {"type": "TextBlock", "wrap": True,
                         "text": _plain(f"Wins will be posted here as “{destination.name}”.")},
                    ],
                },
            }
        ],
    }
    return send(payload)


def resume(db: DbSession, org_id: int) -> None:
    """Carry every channel on from now, after a pause.

    **A pause does not save wins up.** A week of wins arriving in one burst the
    moment somebody switches posting back on would be worse than missing them —
    the same reason a channel switched back on starts from now.
    """
    newest = newest_notification_id(db, org_id)
    for destination in db.scalars(
        select(AnnouncementDestination).where(
            AnnouncementDestination.organization_id == org_id,
            # The Teams switch pauses Teams channels only.
            AnnouncementDestination.kind == "teams",
        )
    ).all():
        destination.last_notification_id = max(destination.last_notification_id, newest)
    # Anything already queued before the pause is dropped too, for the same
    # reason: it is news from before the quiet.
    db.execute(
        AnnouncementDelivery.__table__.update()
        .where(
            AnnouncementDelivery.destination_id.in_(
                select(AnnouncementDestination.id).where(
                    AnnouncementDestination.organization_id == org_id,
                    AnnouncementDestination.kind == "teams",
                )
            ),
            AnnouncementDelivery.status.in_(("pending", "retrying")),
        )
        .values(status="gave_up", last_error="Dropped when posting was paused.")
    )

