"""Logos and backgrounds: images that are not photographs of people.

**A logo cannot go through the photo normaliser.** That one centre-crops to a
square and encodes JPEG, which turns a wordmark into its middle third and puts
a white rectangle behind a transparent mark. A background cannot either: a
television is 16:9 and cropping on upload decides the framing permanently and
invisibly.

So there are three normalisers, and these tests are mostly about the
differences between them.
"""

import io

import pytest
from PIL import Image

from app import images


def png(width: int, height: int, *, alpha: bool = False) -> bytes:
    mode = "RGBA" if alpha else "RGB"
    colour = (255, 0, 0, 0) if alpha else (255, 0, 0)
    buffer = io.BytesIO()
    Image.new(mode, (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def opened(raw: bytes) -> Image.Image:
    return Image.open(io.BytesIO(raw))


# -- Logos -------------------------------------------------------------------


def test_a_wordmark_keeps_its_shape():
    """600x80 is a normal logo. The photo normaliser would return its middle
    80 pixels as a square, which is a different image."""
    data, width, height, _ = images.normalise_logo(png(600, 80))

    assert (width, height) == (512, 68)
    assert opened(data).size == (512, 68)


def test_a_logo_keeps_its_transparency():
    """The reason it is PNG. A transparent mark flattened onto white is a white
    rectangle on every dark wall this product draws."""
    data, _, _, content_type = images.normalise_logo(png(300, 300, alpha=True))

    assert content_type == "image/png"
    assert opened(data).mode == "RGBA"


def test_a_small_logo_is_not_upscaled_past_its_box():
    """Fitted inside, not stretched to fill. A 120x40 logo is 120x40."""
    _, width, height, _ = images.normalise_logo(png(120, 40))

    assert (width, height) == (120, 40)


def test_a_logo_too_small_to_read_is_refused():
    with pytest.raises(images.ImageProblem) as problem:
        images.normalise_logo(png(20, 20))

    assert "at least" in str(problem.value)


def test_a_wide_short_logo_is_not_refused():
    """The photo rule would reject this — 80 is under `MIN_SIDE` — and 600x80
    is what most company logos actually are."""
    assert images.normalise_logo(png(600, 80))


# -- Backgrounds -------------------------------------------------------------


def test_a_background_is_fitted_not_cropped():
    """A television is 16:9 and the photograph somebody chose probably is not.
    Cropping here would decide the framing permanently; the screen covers with
    CSS instead, which is reversible and which the preview shows."""
    _, width, height, _ = images.normalise_background(png(4000, 4000))

    assert (width, height) == (1080, 1080)


def test_a_background_is_fitted_inside_a_wall():
    _, width, height, _ = images.normalise_background(png(3840, 2160))

    assert (width, height) == (1920, 1080)


def test_a_background_is_jpeg():
    """No transparency to preserve behind a leaderboard, and PNG would be
    several times the bytes for the same photograph."""
    _, _, _, content_type = images.normalise_background(png(1920, 1080))

    assert content_type == "image/jpeg"


def test_a_background_smaller_than_the_box_is_left_alone():
    _, width, height, _ = images.normalise_background(png(800, 600))

    assert (width, height) == (800, 600)


# -- The endpoint ------------------------------------------------------------


def test_an_admin_can_upload_a_logo(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))

    reply = client.post("/api/images/logo", content=png(600, 80))

    assert reply.status_code == 201, reply.json()
    assert len(reply.json()["digest"]) == 64
    assert reply.json()["width"] == 512


def test_the_same_file_twice_is_one_row(client, db, org, make_user, sign_in):
    """Content-addressed: re-uploading a file that is already here changes
    nothing rather than growing the table."""
    sign_in(make_user("admin"))
    raw = png(600, 80)

    first = client.post("/api/images/logo", content=raw).json()
    second = client.post("/api/images/logo", content=raw).json()

    assert first["digest"] == second["digest"]


def test_a_manager_cannot(client, db, org, make_user, sign_in, make_team):
    """A logo is what every wall in the building shows."""
    sign_in(make_user("manager", make_team("Enterprise")))

    assert client.post("/api/images/logo", content=png(600, 80)).status_code == 403


def test_an_unknown_kind_is_refused_by_name(client, db, org, make_user, sign_in):
    """Named kinds rather than processing options — the message says which
    exist, because the caller has just guessed one that does not."""
    sign_in(make_user("admin"))

    reply = client.post("/api/images/banner", content=png(600, 80))

    assert reply.status_code == 404
    assert "logo" in reply.json()["detail"]


def test_something_that_is_not_an_image_says_so(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))

    reply = client.post("/api/images/logo", content=b"not an image at all")

    assert reply.status_code == 400
    assert "image" in reply.json()["detail"].lower()


def test_an_uploaded_logo_is_readable_afterwards(
    client, db, org, make_user, sign_in
):
    sign_in(make_user("admin"))
    digest = client.post("/api/images/logo", content=png(600, 80)).json()["digest"]

    reply = client.get(f"/api/images/{digest}")

    assert reply.status_code == 200
    assert reply.headers["content-type"] == "image/png"


def test_a_wall_can_read_one_through_its_own_token(
    client, db, org, make_user, sign_in
):
    """A television has no session. Without this the logo is a broken image on
    every screen in the building."""
    sign_in(make_user("admin"))
    digest = client.post("/api/images/logo", content=png(600, 80)).json()["digest"]
    channel = client.post("/api/channels", json={"name": "Main"}).json()
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()

    assert client.get(f"/api/display/{token}/assets/{digest}").status_code == 200
