"""Sounds for celebrations: the starter pack, the organization's own, and
which plays for which kind of win (6.17).

Three places a celebration's sound can come from, in order:

  1. **The person's own walk-up**, frozen on the notification when it was
     made — what they chose for themselves always wins.
  2. **The rule's sound**, for a celebration rule (set on the rule).
  3. **The organization's default for that kind of win** — goal hit, contest
     won, shout-out, birthday — chosen on the Celebrations page and applied
     by the wall when nothing above it set one. See
     `channels._as_celebration`.

All three name a sound the same way: `asset:<sha256>` in the organization's
own store, so a television fetches it through its own token like any other.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import media as media_service
from app.media import Media
from app.models import StoredAsset

#: The kinds of win an organization can set a default sound for, and how the
#: Celebrations page names them. A rule has its own sound on the rule.
KIND_LABELS = {
    "goal": "Goals hit",
    "competition": "Competitions won",
    "recognition": "Recognition",
    "occasion": "Birthdays and anniversaries",
}


def kind_of_event(event_key: str) -> str | None:
    """Which default applies to a notification, if any."""
    if event_key == "goal.achieved" or event_key.startswith("goal.stretch."):
        return "goal"
    if event_key == "competition.won":
        return "competition"
    if event_key == "recognition":
        return "recognition"
    if event_key in ("person.birthday", "person.work_anniversary"):
        return "occasion"
    return None


def default_for(sounds: dict | None, event_key: str) -> str | None:
    kind = kind_of_event(event_key)
    return (sounds or {}).get(kind) if kind else None


def audio_row(db: DbSession, organization_id: int, url: str) -> StoredAsset:
    """The organization's stored sound this names, or a refusal."""
    digest = media_service.asset_digest(url) if url.startswith(media_service.ASSET_SCHEME) else None
    row = (
        db.scalar(
            select(StoredAsset).where(
                StoredAsset.organization_id == organization_id, StoredAsset.sha256 == digest
            )
        )
        if digest
        else None
    )
    if row is None or not row.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That sound is not in this organization's Assets.",
        )
    return row


def stored_clip(db: DbSession, organization_id: int, url: str) -> Media:
    """A stored sound as a clip: from its start, for as long as it is (to the
    wall's limit)."""
    row = audio_row(db, organization_id, url)
    length = (row.duration_ms or 0) // 1000 or media_service.MAX_CLIP_SECONDS
    return Media(
        url=url,
        kind=media_service.KIND_AUDIO,
        start_seconds=0,
        end_seconds=min(max(1, length), media_service.MAX_CLIP_SECONDS),
    )
