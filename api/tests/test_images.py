"""Taking bytes from outside and making them safe to keep.

The three things that have to happen, and the ways each is got wrong: proving it
is an image rather than trusting its name, making every one the same shape, and
dropping everything that is not pixels.
"""

import hashlib
import io

import pytest
from PIL import Image

from app import images
from app.models import StoredAsset


def made(width: int, height: int, fmt: str = "JPEG", colour=(120, 90, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format=fmt)
    return out.getvalue()


# ── Proving it is an image ───────────────────────────────────────────────────


def test_a_file_that_is_not_an_image_is_refused():
    """**The oldest upload hole there is.** Nothing here looks at the filename."""
    with pytest.raises(images.ImageProblem) as caught:
        images.normalise(b"MZ\x90\x00this is an executable")

    assert "does not look like an image" in str(caught.value)


def test_a_jpeg_header_with_nothing_behind_it_is_refused():
    """`verify` checks structure rather than content, which is why the module
    opens the file twice."""
    with pytest.raises(images.ImageProblem):
        images.normalise(b"\xff\xd8\xff\xe0" + b"\x00" * 200)


def test_an_empty_file_says_so(): 
    with pytest.raises(images.ImageProblem) as caught:
        images.normalise(b"")

    assert "empty" in str(caught.value)


def test_something_larger_than_the_cap_is_refused_before_decoding():
    """The size check comes first: a decompression bomb is a small file that
    becomes an enormous bitmap, so the encoded cap alone is not the guard."""
    with pytest.raises(images.ImageProblem) as caught:
        images.normalise(b"\x00" * (images.MAX_UPLOAD_BYTES + 1))

    assert "MB" in str(caught.value)


def test_an_image_too_small_to_improve_on_initials_is_refused():
    with pytest.raises(images.ImageProblem) as caught:
        images.normalise(made(80, 80))

    assert "at least" in str(caught.value)


# ── One shape ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "size", [(400, 400), (1200, 800), (800, 1200), (2000, 2000), (401, 399)]
)
def test_everything_comes_out_the_same_square(size):
    """Every avatar renders in the same circle, so every photo is one square."""
    data, width, height = images.normalise(made(*size))

    assert (width, height) == (images.SIDE, images.SIDE)
    assert Image.open(io.BytesIO(data)).size == (images.SIDE, images.SIDE)


def test_a_portrait_is_cropped_rather_than_squashed():
    """Resizing first would squash a face; cropping keeps the middle of the
    frame, which for a photograph of a person is the person."""
    tall = Image.new("RGB", (400, 1200), (255, 0, 0))
    # A green band across the centre — what a centre crop must keep.
    for y in range(560, 640):
        for x in range(400):
            tall.putpixel((x, y), (0, 255, 0))
    out = io.BytesIO()
    tall.save(out, format="PNG")

    data, _, _ = images.normalise(out.getvalue())
    middle = Image.open(io.BytesIO(data)).getpixel((images.SIDE // 2, images.SIDE // 2))

    assert middle[1] > middle[0], "the centre band should survive the crop"


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_the_formats_people_actually_have_are_accepted(fmt):
    data, _, _ = images.normalise(made(500, 500, fmt))

    assert Image.open(io.BytesIO(data)).format == "JPEG"


# ── Nothing but pixels ───────────────────────────────────────────────────────


def test_location_data_does_not_survive():
    """**A photo taken on a phone carries where it was taken.** Re-encoding from
    pixel data is what removes it; stripping named tags would leave whatever the
    next format adds."""
    source = Image.new("RGB", (600, 600), (10, 20, 30))
    exif = source.getexif()
    exif[0x010F] = "SecretCameraCo"  # Make
    exif[0x0110] = "Pixel 9 Pro"  # Model
    exif[0x013B] = "Peter Parker"  # Artist — the owner's name, on every shot
    out = io.BytesIO()
    source.save(out, format="JPEG", exif=exif)
    assert b"SecretCameraCo" in out.getvalue(), "the fixture must carry it in"

    data, _, _ = images.normalise(out.getvalue())

    assert b"SecretCameraCo" not in data
    assert b"Peter Parker" not in data
    # dict() rather than truthiness: an empty Exif object is not falsey.
    assert dict(Image.open(io.BytesIO(data)).getexif()) == {}


# ── Keeping it ───────────────────────────────────────────────────────────────


def test_storing_returns_a_row_named_by_its_content(db, org):
    row = images.store(db, org.id, made(600, 600))

    assert row.sha256 == hashlib.sha256(row.data).hexdigest()
    assert row.content_type == "image/jpeg"
    assert (row.width, row.height) == (images.SIDE, images.SIDE)
    assert row.byte_size == len(row.data)


def test_the_same_photo_twice_is_one_row(db, org):
    """So a bulk upload run twice does not double the table."""
    from sqlalchemy import func, select

    first = images.store(db, org.id, made(600, 600))
    second = images.store(db, org.id, made(600, 600))

    assert first.id == second.id
    assert db.scalar(select(func.count()).select_from(StoredAsset)) == 1


def test_two_organizations_do_not_share_a_row(db, org):
    """A coincidence of content is not a reason to cross a boundary the rest of
    this schema respects."""
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()

    mine = images.store(db, org.id, made(600, 600))
    theirs = images.store(db, other.id, made(600, 600))

    assert mine.id != theirs.id
    assert mine.sha256 == theirs.sha256


# ── Serving it ───────────────────────────────────────────────────────────────


def test_the_bytes_come_back_under_their_hash(client, db, org, make_user, sign_in):
    sign_in(make_user("agent"))
    row = images.store(db, org.id, made(600, 600))
    db.commit()

    reply = client.get(f"/api/images/{row.sha256}")

    assert reply.status_code == 200
    assert reply.headers["content-type"] == "image/jpeg"
    assert reply.content == row.data


def test_it_is_cacheable_forever_because_the_url_is_the_content(
    client, db, org, make_user, sign_in
):
    """A new photo is a new hash and a new URL, so the answer for a given URL can
    never change."""
    sign_in(make_user("agent"))
    row = images.store(db, org.id, made(600, 600))
    db.commit()

    reply = client.get(f"/api/images/{row.sha256}")

    assert "immutable" in reply.headers["cache-control"]
    assert reply.headers["etag"] == f'"{row.sha256}"'


def test_a_stranger_gets_nothing(client, db, org):
    """These are photographs of staff."""
    row = images.store(db, org.id, made(600, 600))
    db.commit()

    assert client.get(f"/api/images/{row.sha256}").status_code == 401


def test_another_organization_cannot_confirm_it_holds_the_same_image(
    client, db, org, make_user, sign_in
):
    """**The hash is not a secret.** Two tenants holding the same stock photo
    must not become a way for one to learn that about the other."""
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = images.store(db, other.id, made(600, 600, colour=(1, 2, 3)))
    sign_in(make_user("admin"))
    db.commit()

    assert client.get(f"/api/images/{theirs.sha256}").status_code == 404


def test_an_unknown_hash_is_a_404(client, db, org, make_user, sign_in):
    sign_in(make_user("agent"))
    db.commit()

    assert client.get(f"/api/images/{'0' * 64}").status_code == 404
