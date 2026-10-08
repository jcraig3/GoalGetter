"""Taking an image from somebody and making it safe to keep.

**Three things have to happen before bytes from outside are stored, and the
order matters.**

*Prove it is an image.* Not by its name — a file called `photo.jpg` that is not
one is the oldest upload hole there is — but by decoding it. `Image.verify`
parses the container, and a second open actually reads the pixels, because
`verify` is documented as checking structure rather than content and a truncated
file passes it.

*Make it one shape.* Every avatar renders in the same circle, so every stored
photo is the same square. Cropping here rather than in CSS means one decode
instead of one per page view, and it means the bytes on the wire are the bytes
being shown.

*Drop everything that is not pixels.* A photo taken on a phone carries the GPS
coordinates of wherever it was taken, the device, and often the owner's name.
Re-encoding from the pixel data is what removes them; stripping named EXIF tags
would leave whatever the next format adds.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session as DbSession

from app import assets
from app.models import StoredAsset

__all__ = ["ImageProblem", "MAX_UPLOAD_BYTES", "SIDE", "store"]


class ImageProblem(Exception):
    """An upload that cannot be stored, phrased for whoever chose the file."""


#: The largest file accepted, before anything is decoded.
#:
#: **Checked first, on the raw bytes.** A decompression bomb is a small file that
#: becomes an enormous bitmap, so the size limit that matters is this one plus
#: the pixel cap below — a cap on the encoded bytes alone would let a 2 MB PNG
#: allocate gigabytes.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

#: The most pixels a source image may have, decoded.
#:
#: Forty megapixels is far beyond any phone or camera somebody photographs a
#: colleague with, and far below what it takes to exhaust memory. Pillow has its
#: own bomb guard; this makes the refusal ours, and legible.
MAX_PIXELS = 40_000_000

#: What every stored image is resized to.
#:
#: Four hundred square: sharp on a retina avatar, large enough for a profile
#: page, and about forty kilobytes as JPEG.
SIDE = 400

#: The smallest image worth keeping.
#:
#: Below this, upscaling to `SIDE` produces something visibly worse than the
#: initials it would replace — and the point of a photo is that it is better.
MIN_SIDE = 200

#: What a browser is told it is getting.
OUTPUT_TYPE = "image/jpeg"

#: Formats accepted in. Decided by what Pillow reports after decoding, never by
#: the filename or the browser's claimed content type.
ACCEPTED = {"JPEG", "PNG", "WEBP"}


def normalise(raw: bytes) -> tuple[bytes, int, int]:
    """Validated, square, stripped of everything but pixels.

    Raises `ImageProblem` with a sentence somebody can act on, rather than
    letting a Pillow exception reach an API response.
    """
    if not raw:
        raise ImageProblem("That file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageProblem(
            f"That file is {len(raw) // (1024 * 1024)} MB. The largest accepted "
            f"is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    try:
        # **Two opens, deliberately.** `verify` parses the container and then
        # leaves the file unusable, and it is documented as checking structure
        # rather than content — a truncated JPEG passes it and fails on decode.
        Image.open(io.BytesIO(raw)).verify()
        image = Image.open(io.BytesIO(raw))
    except UnidentifiedImageError:
        raise ImageProblem(
            "That does not look like an image. JPEG, PNG and WebP are accepted."
        ) from None
    except Exception:  # noqa: BLE001 — anything Pillow raises is a bad file
        raise ImageProblem("That image could not be read. It may be damaged.") from None

    if image.format not in ACCEPTED:
        raise ImageProblem(
            f"{image.format or 'That format'} is not accepted. "
            "Use a JPEG, PNG or WebP."
        )

    width, height = image.size
    if width * height > MAX_PIXELS:
        raise ImageProblem("That image is too large to process. Scale it down first.")
    if min(width, height) < MIN_SIDE:
        raise ImageProblem(
            f"That image is {width}×{height}. It needs to be at least "
            f"{MIN_SIDE} pixels on its shortest side."
        )

    try:
        square = _square(image)
    except Exception:  # noqa: BLE001 — a file that decodes but will not render
        raise ImageProblem("That image could not be read. It may be damaged.") from None

    out = io.BytesIO()
    # No `exif=` argument and no ICC profile carried over: re-encoding from pixel
    # data is what drops the location, the device and the owner's name.
    square.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), SIDE, SIDE


def _square(image: Image.Image) -> Image.Image:
    """Centre-cropped to a square, then resized, in that order.

    Resizing first would squash a portrait into a circle; cropping first keeps
    the middle of the frame, which for a photograph of a person is the person.
    """
    # Honour the orientation tag before discarding it, or a phone photo taken
    # sideways is stored sideways.
    from PIL import ImageOps

    image = ImageOps.exif_transpose(image) or image
    image = image.convert("RGB")

    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    image = image.crop((left, top, left + side, top + side))
    return image.resize((SIDE, SIDE), Image.Resampling.LANCZOS)


#: The longest side a logo is kept at.
#:
#: A wall header draws it a couple of hundred pixels tall at most, and a retina
#: television doubles that. Beyond this is bytes nobody sees.
LOGO_SIDE = 512

#: The box a background is fitted inside.
#:
#: A wall is designed at 1920x1080, so anything larger is detail the screen
#: cannot show. Kept as JPEG: a photograph behind a leaderboard has no
#: transparency to preserve and PNG would be five times the bytes.
BACKGROUND_WIDTH = 1920
BACKGROUND_HEIGHT = 1080

#: The smallest logo worth keeping. Lower than `MIN_SIDE` because a wordmark is
#: legitimately wide and short — 600x80 is a normal logo and would fail a
#: square-shaped rule.
MIN_LOGO_SIDE = 40

PNG_TYPE = "image/png"


def _decode(raw: bytes) -> Image.Image:
    """Everything `normalise` checks before it starts cropping.

    Split out because a logo and a background need the same refusals — empty,
    oversized, not an image, a format we do not accept — and differ only in
    what they do afterwards.
    """
    if not raw:
        raise ImageProblem("That file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageProblem(
            f"That file is {len(raw) // (1024 * 1024)} MB. The largest accepted "
            f"is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    try:
        Image.open(io.BytesIO(raw)).verify()
        image = Image.open(io.BytesIO(raw))
    except UnidentifiedImageError:
        raise ImageProblem(
            "That does not look like an image. JPEG, PNG and WebP are accepted."
        ) from None
    except Exception:  # noqa: BLE001 — anything Pillow raises is a bad file
        raise ImageProblem("That image could not be read. It may be damaged.") from None

    if image.format not in ACCEPTED:
        raise ImageProblem(
            f"{image.format or 'That format'} is not accepted. "
            "Use a JPEG, PNG or WebP."
        )
    if image.size[0] * image.size[1] > MAX_PIXELS:
        raise ImageProblem("That image is too large to process. Scale it down first.")
    return image


def normalise_logo(raw: bytes) -> tuple[bytes, int, int, str]:
    """A logo, fitted inside a box, with its transparency intact.

    **Not `normalise`.** That one centre-crops to a square and encodes JPEG,
    which turns a wordmark into its middle third and puts a white rectangle
    behind a transparent mark. A logo has to keep its shape and its alpha, so
    it keeps its own function rather than a flag on that one.
    """
    from PIL import ImageOps

    image = _decode(raw)
    if min(image.size) < MIN_LOGO_SIDE:
        raise ImageProblem(
            f"That image is {image.size[0]}×{image.size[1]}. A logo needs to be "
            f"at least {MIN_LOGO_SIDE} pixels on its shortest side."
        )

    image = ImageOps.exif_transpose(image) or image
    # RGBA even for an opaque source, so one output format covers both and
    # nothing has to branch on whether the original had transparency.
    image = image.convert("RGBA")
    image.thumbnail((LOGO_SIDE, LOGO_SIDE), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    # Re-encoded from pixel data with no `exif=`: the same reason as a
    # photograph, which is that metadata travels further than people expect.
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.size[0], image.size[1], PNG_TYPE


def normalise_background(raw: bytes) -> tuple[bytes, int, int, str]:
    """A wall background, fitted inside 1920x1080.

    **Fitted, not cropped.** A television is 16:9 and the photograph somebody
    chose probably is not; cropping here would decide for them, permanently and
    invisibly. The screen covers with CSS instead, which is reversible and
    which the preview shows.
    """
    from PIL import ImageOps

    image = _decode(raw)
    if min(image.size) < MIN_SIDE:
        raise ImageProblem(
            f"That image is {image.size[0]}×{image.size[1]}. A background needs "
            f"to be at least {MIN_SIDE} pixels on its shortest side."
        )

    image = ImageOps.exif_transpose(image) or image
    image = image.convert("RGB")
    image.thumbnail((BACKGROUND_WIDTH, BACKGROUND_HEIGHT), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82, optimize=True)
    return out.getvalue(), image.size[0], image.size[1], OUTPUT_TYPE


#: The box a library picture with transparency is fitted inside: art, a badge,
#: a sticker. Large enough for a wall, small enough to stay a PNG.
ART_SIDE = 1024


def normalise_library_image(raw: bytes) -> tuple[bytes, int, int, str]:
    """A picture for Organization → Assets (6.3), whatever it is for.

    **Two shapes, decided by the picture.** One with transparency is art — a
    badge, a mark, a cut-out — and keeps its alpha as a PNG inside
    `ART_SIDE`. One without is a photograph or a backdrop, fitted inside a
    television as a JPEG, exactly as a background is. Either keeps its own
    shape: nothing here crops.
    """
    from PIL import ImageOps

    image = _decode(raw)
    image = ImageOps.exif_transpose(image) or image
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha and image.convert("RGBA").getextrema()[3][0] < 255:
        image = image.convert("RGBA")
        image.thumbnail((ART_SIDE, ART_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        return out.getvalue(), image.size[0], image.size[1], PNG_TYPE
    return normalise_background(raw)


def store_library_image(db: DbSession, org_id: int, raw: bytes) -> StoredAsset:
    data, width, height, content_type = normalise_library_image(raw)
    return assets.keep(
        db, org_id, data, content_type=content_type, width=width, height=height
    )


def store_logo(db: DbSession, org_id: int, raw: bytes) -> StoredAsset:
    data, width, height, content_type = normalise_logo(raw)
    return assets.keep(
        db, org_id, data, content_type=content_type, width=width, height=height
    )


def store_background(db: DbSession, org_id: int, raw: bytes) -> StoredAsset:
    data, width, height, content_type = normalise_background(raw)
    return assets.keep(
        db, org_id, data, content_type=content_type, width=width, height=height
    )


def store(db: DbSession, org_id: int, raw: bytes) -> StoredAsset:
    """Normalise and keep it, or hand back the row that already holds it.

    **The same photo twice is one row.** The name is the hash of the stored
    bytes, so re-uploading a file that is already here changes nothing — which
    also means a bulk upload run twice does not double the table.
    """
    data, width, height = normalise(raw)
    return assets.keep(
        db, org_id, data, content_type=OUTPUT_TYPE, width=width, height=height
    )


