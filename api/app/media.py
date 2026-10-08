"""Walk-up media: what plays when somebody is celebrated.

A batter has walk-up music. Somebody closing a deal gets fifteen seconds on the
wall, and that is the gamification rather than decoration around it.

**URLs, not uploads.** A YouTube link with a start and end offset covers walk-up
songs completely and a hosted GIF covers the rest, which is three columns rather
than file storage, upload limits, virus scanning, orphan cleanup and a
moderation queue — none of which this product has ever needed. Uploads can
follow if anybody actually wants local files.

**The allowlist is the security boundary.** A wall display is a browser nobody
is watching, pointed at whatever URL this module accepts, so "any http URL"
would let an admin aim every screen in the building at anything. Restricting to
YouTube and image extensions also gives the display page's content security
policy a finite set of hosts to admit deliberately rather than by accident.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

#: The longest a celebration may hold a screen.
#:
#: A wall screen owes the room its leaderboard back. Fifteen seconds is a
#: walk-up; three minutes is a hostage situation, and nobody who pastes a link
#: to a whole song is thinking about the twelve people trying to read a board
#: behind it.
MAX_CLIP_SECONDS = 15

YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
        "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
    }
)

IMAGE_SUFFIXES = (".gif", ".png", ".jpg", ".jpeg", ".webp", ".avif")

KIND_YOUTUBE = "youtube"
KIND_IMAGE = "image"
KIND_AUDIO = "audio"
KIND_VIDEO = "video"

#: How a stored file is named where a URL is expected.
#:
#: **A scheme rather than a second column.** Everything downstream of a clip —
#: the notification row, the celebration payload, the wall — carries one string
#: for "what to play". Adding a parallel `media_asset_id` beside it would mean
#: every one of those places learning which of the two to look at, and a pair
#: that can disagree about what a screen should be playing.
#:
#: `asset:<sha256>` is self-describing, which is what makes it safe to put in a
#: column that has always held a URL: nothing can mistake it for one.
ASSET_SCHEME = "asset:"

#: The same, for an uploaded **video** clip.
#:
#: A sibling scheme rather than a column, for the reason above — and so that
#: what a clip is can still be read off the one string that says what to play.
#: `asset:` predates it and keeps meaning audio, so nothing already stored
#: changes meaning.
#:
#: **Why uploaded video exists for walk-ups at all:** it is the only way to the
#: announcement people want — the music video filling the screen, the words
#: over it — with no adverts. A YouTube embed shows ads when its uploader says
#: so, nothing on this side may skip or hide them, and YouTube's embed rules
#: forbid laying anything over its player. A file served from this deployment
#: has none of those limits.
VIDEO_SCHEME = "video:"

#: The same, for a stored **picture** — an image from the asset library used
#: where a link to one would go (Phase 25): an announcement's picture, a
#: shout-out's, an image screen's.
IMAGE_SCHEME = "image:"

#: Every stored-file scheme, and what each one plays as.
STORED_SCHEMES = {ASSET_SCHEME: KIND_AUDIO, VIDEO_SCHEME: KIND_VIDEO, IMAGE_SCHEME: KIND_IMAGE}

#: A YouTube id is exactly this shape. Checked rather than trusted, because the
#: id is interpolated into an embed URL on the display page.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

#: A SHA-256, written out. See `asset_digest`.
_DIGEST = re.compile(r"[0-9a-f]{64}")


class MediaError(ValueError):
    """A URL we will not put on a wall. The message is shown to the person."""


@dataclass(frozen=True)
class Media:
    """A validated clip, ready to store."""

    url: str
    kind: str
    start_seconds: int
    end_seconds: int

    @property
    def duration(self) -> int:
        return self.end_seconds - self.start_seconds


def youtube_id(url: str) -> str | None:
    """The video id, or None if this is not a YouTube URL we understand.

    Handles the three forms people actually paste: `youtu.be/<id>`,
    `youtube.com/watch?v=<id>`, and `youtube.com/embed/<id>`. Anything else —
    a playlist, a channel, a search — is refused rather than guessed at, since
    a guess ends up on a wall.
    """
    parsed = urlparse(url)
    if parsed.hostname not in YOUTUBE_HOSTS:
        return None

    if parsed.hostname and parsed.hostname.endswith("youtu.be"):
        candidate = parsed.path.lstrip("/")
    elif parsed.path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    else:
        # /embed/<id>, and what people copy from a phone or a stream (Phase
        # 28): /shorts/<id>, /live/<id>, /v/<id>.
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
            candidate = parts[1]
        else:
            return None

    return candidate if _VIDEO_ID.match(candidate) else None


def parse(
    url: str, start_seconds: int | None = None, end_seconds: int | None = None
) -> Media:
    """Validate a URL and its offsets, or raise `MediaError`.

    The offsets are clamped rather than rejected when they run long: somebody
    pasting a link to a four-minute song has not made a mistake, they have
    simply not thought about the length, and trimming it is a kinder answer
    than a validation error.
    """
    url = url.strip()
    if not url:
        raise MediaError("Give a link, or leave it empty for no media.")
    if len(url) > 500:
        raise MediaError("That link is too long.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise MediaError("A link has to start with http:// or https://.")

    if youtube_id(url) is not None:
        kind = KIND_YOUTUBE
    elif parsed.path.lower().endswith(IMAGE_SUFFIXES):
        kind = KIND_IMAGE
    else:
        raise MediaError(
            "Use a YouTube link, or a direct link to a GIF or image "
            "(one ending in .gif, .png, .jpg or .webp)."
        )

    start = max(0, start_seconds or 0)
    # An image has no timeline. Storing offsets for one would be a number that
    # means nothing and reads as though it does.
    if kind == KIND_IMAGE:
        return Media(url=url, kind=kind, start_seconds=0, end_seconds=MAX_CLIP_SECONDS)

    end = end_seconds if end_seconds is not None else start + MAX_CLIP_SECONDS
    if end <= start:
        raise MediaError("The end has to come after the start.")

    return Media(
        url=url,
        kind=kind,
        start_seconds=start,
        # Clamped, not refused. See the docstring.
        end_seconds=min(end, start + MAX_CLIP_SECONDS),
    )


def asset_digest(url: str) -> str | None:
    """The stored file this names, or None if it names something on the web.

    Either scheme: the wall fetches an uploaded clip the same way whatever it
    is, and only `kind_of` needs to tell them apart.
    """
    for scheme in STORED_SCHEMES:
        if url.startswith(scheme):
            digest = url[len(scheme) :]
            break
    else:
        return None
    # Checked rather than trusted: this goes into a URL a television fetches,
    # and a hash is exactly sixty-four hex characters.
    return digest if _DIGEST.fullmatch(digest) else None


def kind_of(url: str) -> str | None:
    """What a stored URL is, derived rather than remembered.

    Deliberately not a column. A `kind` stored beside the URL is one more thing
    that can disagree with it — and unlike most such pairs, the disagreement
    would only show up on a wall screen in front of an office.
    """
    if asset_digest(url) is not None:
        return next(kind for scheme, kind in STORED_SCHEMES.items() if url.startswith(scheme))
    if youtube_id(url) is not None:
        return KIND_YOUTUBE
    if urlparse(url).path.lower().endswith(IMAGE_SUFFIXES):
        return KIND_IMAGE
    return None


def stored_ref(db, organization_id: int, ref: str, kinds: tuple[str, ...]) -> str:
    """A stored file named where a link would go — `video:<sha256>`,
    `image:…`, `asset:…` — checked to be this organization's, and of a kind
    allowed here. Returns the reference as it should be kept, or raises
    `MediaError` in words.

    The scheme says what it should be; the bytes say what it is, and they
    must agree, so a sound can't be put where a picture goes.
    """
    from sqlalchemy import select

    from app.asset_library import kind_of as stored_kind
    from app.models import StoredAsset

    digest = asset_digest(ref)
    if digest is None:
        raise MediaError("That isn't a file from the library.")
    wanted = kind_of(ref)
    if wanted not in kinds:
        raise MediaError(f"A {wanted} can't go here.")
    row = db.scalar(
        select(StoredAsset).where(StoredAsset.organization_id == organization_id, StoredAsset.sha256 == digest)
    )
    if row is None:
        raise MediaError("That file isn't in the library any more.")
    if stored_kind(row) != wanted:
        raise MediaError(f"That file is a {stored_kind(row)}, not a {wanted}.")
    return ref


def clip_of(db, organization_id: int, url: str, start_seconds: int | None = None) -> Media:
    """Anything a celebration can play, as a clip (Phase 27): a link, or a
    library file — a sound, a video or a picture — checked to be this
    organization's. Raises `MediaError` in words."""
    url = url.strip()
    if asset_digest(url) is None:
        return parse(url, start_seconds, None)
    kind = kind_of(url)
    stored_ref(db, organization_id, url, (KIND_AUDIO, KIND_VIDEO, KIND_IMAGE))
    if kind == KIND_AUDIO:
        from app import sounds

        return sounds.stored_clip(db, organization_id, url)
    if kind == KIND_IMAGE:
        return Media(url=url, kind=kind, start_seconds=0, end_seconds=MAX_CLIP_SECONDS)
    start = max(0, start_seconds or 0)
    return Media(url=url, kind=kind, start_seconds=start, end_seconds=start + MAX_CLIP_SECONDS)
