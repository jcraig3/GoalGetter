"""Keeping a file, once something else has decided it is safe to keep.

**The store, separated from the things that validate what goes in it.** A
photograph is checked by Pillow, a clip by `app/audio.py`, and both end up
here — so this holds the part that is the same for every kind: the hash, the
de-duplication, and the row.

Split out of `app/images.py` when audio arrived. Leaving `keep` there would
have meant the audio path importing the image module to store a sound.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import StoredAsset

__all__ = ["CACHE_CONTROL", "keep", "respond"]


def keep(
    db: DbSession,
    org_id: int,
    data: bytes,
    *,
    content_type: str,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = None,
) -> StoredAsset:
    """Store already-normalised bytes, or hand back the row that holds them.

    **The same file twice is one row.** The name is the hash of the stored
    bytes, so re-uploading something already here changes nothing — which also
    means a bulk upload run twice does not double the table.
    """
    digest = hashlib.sha256(data).hexdigest()

    existing = db.scalar(
        select(StoredAsset).where(
            StoredAsset.organization_id == org_id, StoredAsset.sha256 == digest
        )
    )
    if existing is not None:
        return existing

    row = StoredAsset(
        organization_id=org_id,
        sha256=digest,
        content_type=content_type,
        byte_size=len(data),
        width=width,
        height=height,
        duration_ms=duration_ms,
        data=data,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row


#: A year, and immutable. Safe because the URL is the hash of the content.
CACHE_CONTROL = "public, max-age=31536000, immutable"


def respond(row: StoredAsset, range_header: str | None):
    """Hand a stored file back, honouring a byte-range request.

    **Safari will not play an MP4 from a server that ignores `Range`**, and
    Chrome needs it to loop and seek without re-reading the whole file. Every
    other kind here is small enough to send whole, and a browser only asks for
    a range when it wants one — so the same path serves everything.

    One range only, which is all a video element ever asks for. A multi-range
    request, a malformed one, or one past the end falls back to the ordinary
    whole-file answer or a 416, never to a guess.

    Both asset routes use this, so a wall reading through its display token and
    an editor reading through a session get identical answers.
    """
    from fastapi import Response

    size = len(row.data)
    headers = {
        "Cache-Control": CACHE_CONTROL,
        "ETag": f'"{row.sha256}"',
        "Accept-Ranges": "bytes",
    }

    wanted = _range(range_header, size)
    if wanted is None:
        return Response(content=row.data, media_type=row.content_type, headers=headers)
    if wanted == "unsatisfiable":
        return Response(
            status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}
        )

    start, end = wanted
    return Response(
        content=row.data[start : end + 1],
        status_code=206,
        media_type=row.content_type,
        headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}"},
    )


def _range(header: str | None, size: int):
    """Parse `bytes=start-end`, `bytes=start-` or `bytes=-suffix`.

    None means "send the whole file" — no header, a unit other than bytes, or
    more than one range. "unsatisfiable" is a well-formed range that starts
    past the end.
    """
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    spec = header[len("bytes="):].strip()
    first, _, last = spec.partition("-")
    try:
        if first == "":
            # A suffix: the last N bytes.
            length = int(last)
            if length <= 0:
                return None
            return (max(size - length, 0), size - 1) if size else "unsatisfiable"
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or start < 0:
        return "unsatisfiable"
    if end < start:
        return None
    return start, min(end, size - 1)
