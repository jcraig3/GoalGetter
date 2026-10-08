"""Checking an uploaded video before it goes behind a wall.

**This exists because a video that uploads and then shows nothing is worse
than a refusal.** 4e-iii held video back for exactly that reason: a background
kind that validates, saves and draws nothing was the failure that phase spent a
day undoing. So every property that decides whether a television can actually
play the file is checked here, at upload, where the person who can fix it is
looking at the screen.

**Why uploaded video at all, when YouTube is already a background kind:**
because it is the only honest way to a loop with no adverts. Whether an embedded
YouTube video shows ads is decided by the uploader's monetisation, not by the
site embedding it, and YouTube's developer policies forbid blocking or
interfering with them. A file served from this deployment has no ads, needs no
internet connection, and cannot be taken down from under a wall by somebody
else's channel.

**No ffmpeg, deliberately.** It is a large native dependency for one feature,
and nothing here needs to *change* the file — only to read enough of it to know
whether it will play. An MP4 is a tree of length-prefixed boxes, and walking
that tree is a few dozen lines.

What is checked, and why each one:

    container   MP4 only. It is what every phone and editor exports, and the
                one format every browser a television runs will play. A
                QuickTime .mov is the same structure but Chrome does not
                promise to play it, so it is refused with a sentence about
                exporting instead.
    codec       H.264 or AV1, and HEVC refused by name — iPhones record HEVC
                by default, and a Chrome-based television often cannot decode
                it. Without this check the most common upload in the world
                would save and then show a black screen.
    video track there has to be one. An MP4 can be audio only.
    duration    a minute at most. A background is a loop; anything longer is a
                film, and a 20 MB film is a small one.
    size        20 MB, under the 25 MB nginx will pass.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession

from app import assets
from app.models import StoredAsset

__all__ = [
    "MAX_SECONDS",
    "MAX_UPLOAD_BYTES",
    "Video",
    "VideoProblem",
    "inspect",
    "store_background",
]

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_SECONDS = 60

#: Sample-entry codes that every browser a television is likely to run will
#: decode. `avc1`/`avc3` are H.264; `av01` is AV1, which current Chrome plays.
PLAYABLE = {"avc1", "avc3", "av01"}

#: Refused by name, because the fix is specific and the person uploading is
#: almost certainly holding an iPhone.
HEVC = {"hvc1", "hev1"}

#: Boxes that contain other boxes, on the path to what we read.
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}


class VideoProblem(ValueError):
    """Why a file cannot be a background, in words somebody can act on."""


@dataclass
class Video:
    width: int
    height: int
    duration_ms: int
    codec: str


def _boxes(data: bytes, start: int = 0, end: int | None = None):
    """Yield (type, payload_start, payload_end) for each box in a range.

    Refuses rather than guesses on a malformed length: a box claiming to run
    past the end of the file is a truncated or hostile upload, and reading on
    would mean reading garbage as structure.
    """
    end = len(data) if end is None else end
    at = start
    while at + 8 <= end:
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        header = 8
        if size == 1:
            if at + 16 > end:
                raise VideoProblem("That file is cut short — it may not have finished uploading.")
            size = struct.unpack(">Q", data[at + 8 : at + 16])[0]
            header = 16
        elif size == 0:
            size = end - at
        if size < header or at + size > end:
            raise VideoProblem("That file is cut short — it may not have finished uploading.")
        yield kind, at + header, at + size
        at += size


def _find(data: bytes, start: int, end: int, kind: bytes):
    for found, payload_start, payload_end in _boxes(data, start, end):
        if found == kind:
            return payload_start, payload_end
    return None


def inspect(raw: bytes) -> Video:
    """Read enough of an MP4 to know whether a television will play it.

    Raises `VideoProblem` with the sentence to show when it will not.
    """
    if not raw:
        raise VideoProblem("That file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise VideoProblem(
            f"The largest video accepted is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB. "
            "A background loop is usually a few seconds long — trim it and try again."
        )

    if len(raw) < 12 or raw[4:8] != b"ftyp":
        raise VideoProblem("That is not an MP4 video. Export it as MP4 and try again.")
    brand = raw[8:12]
    if brand == b"qt  ":
        raise VideoProblem(
            "That is a QuickTime (.mov) file, which not every television can play. "
            "Export it as MP4 and try again."
        )

    # **Every top-level box, before looking inside any of them.** Searching for
    # the index alone stops as soon as it is found, so a file cut short in the
    # footage *after* the index would pass — and then play partway and stall
    # on the wall. Walking the whole top level checks every length against
    # the real end of the file; it reads headers only, so it costs nothing.
    top = {kind: (start, end) for kind, start, end in _boxes(raw)}
    moov = top.get(b"moov")
    if moov is None:
        raise VideoProblem("That MP4 has no playable content — it may be damaged.")

    duration_ms = _duration(raw, *moov)
    if duration_ms <= 0:
        raise VideoProblem("That video has no length — it may be damaged.")
    if duration_ms > MAX_SECONDS * 1000:
        raise VideoProblem(
            f"That video is {duration_ms // 1000} seconds long. A background loop "
            f"can be up to {MAX_SECONDS} seconds — a short clip loops better anyway."
        )

    track = _video_track(raw, *moov)
    if track is None:
        raise VideoProblem("That file has sound but no picture.")
    width, height, codec = track

    if codec in HEVC:
        raise VideoProblem(
            "That video is HEVC, which many televisions cannot play — it is what "
            "an iPhone records by default. Export it as H.264 (on an iPhone: "
            "Settings → Camera → Formats → Most Compatible) and try again."
        )
    if codec not in PLAYABLE:
        raise VideoProblem(
            f"That video uses a format ({codec.strip()}) televisions may not play. "
            "Export it as H.264 MP4 and try again."
        )

    return Video(width=width, height=height, duration_ms=duration_ms, codec=codec)


def _duration(data: bytes, start: int, end: int) -> int:
    """From `mvhd`: the whole movie's length, in milliseconds."""
    found = _find(data, start, end, b"mvhd")
    if found is None:
        return 0
    at, stop = found
    version = data[at]
    if version == 1:
        if at + 32 > stop:
            return 0
        timescale, duration = struct.unpack(">IQ", data[at + 20 : at + 32])
    else:
        if at + 20 > stop:
            return 0
        timescale, duration = struct.unpack(">II", data[at + 12 : at + 20])
    return int(duration * 1000 / timescale) if timescale else 0


def _video_track(data: bytes, start: int, end: int) -> tuple[int, int, str] | None:
    """The first track whose handler is `vide`: its size and codec."""
    for kind, t_start, t_end in _boxes(data, start, end):
        if kind != b"trak":
            continue
        mdia = _find(data, t_start, t_end, b"mdia")
        if mdia is None:
            continue
        hdlr = _find(data, *mdia, b"hdlr")
        # hdlr: version/flags (4), pre_defined (4), handler_type (4).
        if hdlr is None or data[hdlr[0] + 8 : hdlr[0] + 12] != b"vide":
            continue

        tkhd = _find(data, t_start, t_end, b"tkhd")
        width = height = 0
        if tkhd is not None and tkhd[1] - tkhd[0] >= 8:
            # The last eight bytes of tkhd are width and height, 16.16 fixed.
            w, h = struct.unpack(">II", data[tkhd[1] - 8 : tkhd[1]])
            width, height = w >> 16, h >> 16

        codec = "????"
        path = [b"minf", b"stbl", b"stsd"]
        at, stop = mdia
        for step in path:
            found = _find(data, at, stop, step)
            if found is None:
                break
            at, stop = found
        else:
            # stsd: version/flags (4), entry count (4), then the first sample
            # entry's size (4) and its four-character code.
            if stop - at >= 16:
                codec = data[at + 12 : at + 16].decode("latin-1")

        return width, height, codec
    return None


def store_background(db: DbSession, org_id: int, raw: bytes) -> StoredAsset:
    """Check a video and keep it, unchanged.

    **Unchanged** because there is nothing to normalise without re-encoding,
    and re-encoding is ffmpeg. The file that passes is the file that plays.
    """
    found = inspect(raw)
    return assets.keep(
        db,
        org_id,
        raw,
        content_type="video/mp4",
        width=found.width,
        height=found.height,
        duration_ms=found.duration_ms,
    )
