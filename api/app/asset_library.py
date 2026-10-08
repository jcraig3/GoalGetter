"""Organization → Assets (6.3): every file this organization holds, and
where each one is used.

The store under it (`app/assets.py`) has held logos, backgrounds and walk-up
clips for a while, each uploaded from the place it was for and visible only
there. This is the one place to see them all, add new ones, and remove the
ones nothing uses any more.

**Where a file is used is worked out, not recorded.** A reference is a hash
inside an appearance, a library background, a walk-up or a rule — wherever
the thing that uses it keeps its settings — so the answer is found by reading
those, and cannot drift from them the way a usage counter would.

**People's photographs are left out.** Four hundred headshots would bury
everything else, and a photo is managed on its person's page.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app import media as media_service
from app.models import (
    AchievementRule,
    Badge,
    Channel,
    ChannelScreen,
    Competition,
    Goal,
    Leaderboard,
    Notification,
    Organization,
    SavedBackground,
    StoredAsset,
    Team,
    TvAnnouncement,
    UserAccount,
    WalkupMedia,
)


@dataclass(frozen=True)
class Usage:
    label: str
    link: str


def kind_of(row: StoredAsset) -> str:
    """`image`, `video` or `audio`, from what the bytes were found to be."""
    family = row.content_type.split("/", 1)[0]
    return family if family in ("image", "video", "audio") else "image"


def _in_appearance(appearance: dict | None) -> list[tuple[str, str]]:
    """(digest, what it is) for each stored file an appearance names."""
    if not appearance:
        return []
    found = []
    value = appearance.get("logo")
    if isinstance(value, str) and value:
        found.append((value, "logo"))
    background = appearance.get("background")
    if isinstance(background, dict) and background.get("kind") in ("image", "video"):
        asset = background.get("asset")
        if isinstance(asset, str) and asset:
            found.append((asset, "background"))
    return found


def photo_ids(db: DbSession, org: Organization) -> set[int]:
    rows = db.execute(
        select(UserAccount.tenant_photo_image_id, UserAccount.custom_photo_image_id).where(
            UserAccount.organization_id == org.id,
            or_(
                UserAccount.tenant_photo_image_id.is_not(None),
                UserAccount.custom_photo_image_id.is_not(None),
            ),
        )
    ).all()
    return {i for pair in rows for i in pair if i is not None}


def photo_owners(db: DbSession, org: Organization) -> dict[int, tuple[str, str]]:
    """Each photograph's stored id → (whose, "uploaded" or "synced") — what
    the Profile pics shelf labels them with (Phase 27). The photo a person
    shows wins where they have both."""
    owners: dict[int, tuple[str, str]] = {}
    for person in db.scalars(
        select(UserAccount).where(
            UserAccount.organization_id == org.id,
            or_(
                UserAccount.tenant_photo_image_id.is_not(None),
                UserAccount.custom_photo_image_id.is_not(None),
            ),
        )
    ).all():
        if person.tenant_photo_image_id is not None:
            owners.setdefault(person.tenant_photo_image_id, (person.full_name, "synced"))
        if person.custom_photo_image_id is not None:
            owners[person.custom_photo_image_id] = (person.full_name, "uploaded")
    return owners


def usages(db: DbSession, org: Organization) -> dict[str, list[Usage]]:
    """Every place each stored file is used, by digest."""
    used: dict[str, list[Usage]] = defaultdict(list)

    for digest, what in _in_appearance(org.appearance):
        used[digest].append(Usage(f"The organization's {what}", "/appearance"))

    owners = (
        (Leaderboard, "board", lambda row: f"/leaderboards/{row.id}"),
        (Goal, "goal", lambda row: f"/goals/{row.id}"),
        (Competition, "competition", lambda row: f"/competitions/{row.id}"),
        (Channel, "channel", lambda row: f"/channels/{row.id}"),
    )
    for model, noun, link in owners:
        for row in db.scalars(select(model).where(model.organization_id == org.id)).all():
            name = getattr(row, "name", None)
            # A goal need not be named; "goal 192" would be an id, not a name.
            whose = f"{noun} “{name}”" if name else f"a {noun}"
            for digest, what in _in_appearance(row.appearance):
                used[digest].append(Usage(f"The {what} of {whose}", link(row)))

    screens = db.execute(
        select(ChannelScreen, Channel)
        .join(Channel, Channel.id == ChannelScreen.channel_id)
        .where(Channel.organization_id == org.id)
    ).all()
    for screen, channel in screens:
        for digest, what in _in_appearance(screen.appearance):
            used[digest].append(
                Usage(f"The {what} of a slide on “{channel.name}”", f"/channels/{channel.id}")
            )
        digest = media_service.asset_digest(screen.url) if screen.url else None
        if digest:
            used[digest].append(Usage(f"A slide on “{channel.name}”", f"/channels/{channel.id}"))

    for saved in db.scalars(
        select(SavedBackground).where(SavedBackground.organization_id == org.id)
    ).all():
        for digest, _ in _in_appearance({"background": saved.background}):
            used[digest].append(Usage(f"Background library: “{saved.name}”", "/appearance"))

    for walkup, person in db.execute(
        select(WalkupMedia, UserAccount)
        .join(UserAccount, UserAccount.id == WalkupMedia.user_id)
        .where(UserAccount.organization_id == org.id)
    ).all():
        digest = media_service.asset_digest(walkup.url) if walkup.url else None
        if digest:
            used[digest].append(Usage(f"Walk-up for {person.full_name}", f"/users/{person.id}"))

    for rule in db.scalars(
        select(AchievementRule).where(AchievementRule.organization_id == org.id)
    ).all():
        digest = media_service.asset_digest(rule.media_url) if rule.media_url else None
        if digest:
            used[digest].append(Usage(f"Celebration “{rule.name}”", "/celebrations"))

    from app import sounds as sound_service

    for kind, url in (org.celebration_sounds or {}).items():
        digest = media_service.asset_digest(url) if url else None
        if digest:
            label = sound_service.KIND_LABELS.get(kind, kind)
            used[digest].append(Usage(f"Default sound for {label.lower()}", "/celebrations"))

    for team in db.scalars(
        select(Team).where(Team.organization_id == org.id, Team.logo.is_not(None))
    ).all():
        used[team.logo].append(Usage(f"Logo of team “{team.name}”", "/teams"))

    for badge in db.scalars(select(Badge).where(Badge.organization_id == org.id)).all():
        if badge.icon.startswith("asset:"):
            used[badge.icon[len("asset:"):]].append(
                Usage(f"Badge “{badge.name}”", "/points/setup")
            )

    for announcement in db.scalars(
        select(TvAnnouncement).where(TvAnnouncement.organization_id == org.id)
    ).all():
        for url in (announcement.media_url, announcement.sound_url):
            digest = media_service.asset_digest(url) if url else None
            if digest:
                used[digest].append(
                    Usage(f"Announcement “{announcement.title}”", "/announcements?tab=announcements")
                )

    # Past wins: what played is what a replay plays again (Phase 27), so a
    # file a celebration used isn't offered for removal.
    from sqlalchemy import func

    for url, times in db.execute(
        select(Notification.media_url, func.count())
        .where(Notification.organization_id == org.id, Notification.media_url.is_not(None))
        .group_by(Notification.media_url)
    ).all():
        digest = media_service.asset_digest(url)
        if digest:
            what = "a past win" if times == 1 else f"{times} past wins"
            used[digest].append(Usage(f"Played for {what}", "/announcements"))

    return used
