"""Checking a sound before a wall plays it.

**Walk-up music was a link, and a link is not an answer for most people.** The
existing clip is a YouTube URL — which works, needs no storage, and requires
somebody to find their song on YouTube, copy the address and paste it. What
people actually have is a file. It is the most-loved feature in the product
this borrows from, and asking for a URL is most of the reason a floor ends up
with three songs between forty people.

**Metadata, not a decoder.** Re-encoding would mean ffmpeg: tens of megabytes
in the image and a subprocess per upload, to do a job that a cap on size and
length already does. What is genuinely needed is the length — so a fifteen
second clip can be enforced rather than hoped for — and the removal of tags,
which can carry a name, a comment and an embedded photograph into a file
somebody thinks is only a sound.
"""

from __future__ import annotations

import io

from mutagen import File as MutagenFile
from mutagen import MutagenError

__all__ = ["AudioProblem", "ACCEPTED", "MAX_UPLOAD_BYTES", "MAX_SECONDS", "normalise"]


class AudioProblem(ValueError):
    """Something an admin can act on, rather than a stack trace."""


#: What a browser is told it is getting, by what the file turned out to be.
#:
#: **Decided by decoding the header, never by the filename**, exactly as
#: images are. A `.mp3` that is really a zip is the interesting case, and it is
#: the one an extension check waves through.
ACCEPTED = {
    "MP3": "audio/mpeg",
    "MPEG": "audio/mpeg",
    "OggVorbis": "audio/ogg",
    "OggOpus": "audio/ogg",
    "MP4": "audio/mp4",
    "WAVE": "audio/wav",
    "FLAC": "audio/flac",
}

#: The largest upload accepted.
#:
#: A clip is capped at fifteen seconds of playback, and eight megabytes is a
#: generous ceiling for that even before trimming — while being small enough
#: that a mistaken album upload is refused rather than stored.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

#: The longest clip a wall will play.
#:
#: The same cap `media.MAX_CLIP_SECONDS` puts on a YouTube walk-up, for the same
#: reason: a celebration holds the rotation, and a whole song holds it for three
#: minutes. A longer file is not refused — it is played from its start and cut
#: here, which is what somebody uploading a full track expects.
MAX_SECONDS = 15


def normalise(raw: bytes) -> tuple[bytes, str, int]:
    """Validated, stripped of everything but sound.

    Returns the bytes, the content type, and the length in milliseconds.

    **The bytes come back changed but not re-encoded.** Removing tags rewrites
    the container around the same audio, which is what drops the artwork and
    the comments without needing a decoder.
    """
    if not raw:
        raise AudioProblem("That file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AudioProblem(
            f"That file is {len(raw) // (1024 * 1024)} MB. The largest accepted "
            f"is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    buffer = io.BytesIO(raw)
    try:
        parsed = MutagenFile(buffer)
    except MutagenError:
        parsed = None
    except Exception:  # noqa: BLE001 — anything it raises is a bad file
        parsed = None

    if parsed is None or parsed.info is None:
        raise AudioProblem(
            "That does not look like an audio file. MP3, M4A, WAV, OGG and "
            "FLAC are accepted."
        )

    kind = type(parsed.info).__name__.replace("Info", "") or ""
    content_type = _content_type(parsed, kind)
    if content_type is None:
        raise AudioProblem(
            "That audio format is not accepted. Use MP3, M4A, WAV, OGG or FLAC."
        )

    seconds = float(getattr(parsed.info, "length", 0) or 0)
    if seconds <= 0:
        raise AudioProblem("That file has no audio in it.")

    # **Tags go, and the file is rewritten without them.** An MP3 from a phone
    # can carry the owner's name, a comment and a full-size album cover, none
    # of which anybody thinks they are uploading with a sound.
    try:
        # `fileobj=`, not positional: mutagen reads a bare argument as
        # `filething` and refuses a buffer given that way.
        parsed.delete(fileobj=buffer)
        parsed.save(fileobj=buffer)
    except Exception:  # noqa: BLE001 — a file that parses but will not rewrite
        raise AudioProblem(
            "That audio file could not be read. It may be damaged."
        ) from None

    return buffer.getvalue(), content_type, int(seconds * 1000)


def _content_type(parsed: object, kind: str) -> str | None:
    """What to serve it as.

    Matched on the parser mutagen chose rather than on anything in the file,
    because the parser is the thing that actually read it.
    """
    for name, mime in ACCEPTED.items():
        if kind.startswith(name):
            return mime
    # `mutagen.File` returns a class named after the container for the ones
    # above and something else for anything exotic.
    class_name = type(parsed).__name__
    return ACCEPTED.get(class_name)


def clip_seconds(duration_ms: int | None) -> int:
    """How long a wall should hold the screen for this clip.

    Capped, so a full track uploaded by somebody who did not trim it plays its
    first fifteen seconds rather than stopping the rotation for a whole song.
    """
    if not duration_ms:
        return MAX_SECONDS
    return max(1, min(MAX_SECONDS, round(duration_ms / 1000)))
