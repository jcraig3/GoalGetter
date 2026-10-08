"""Uploaded video backgrounds: the ad-free loop.

**A video that uploads and then shows nothing is worse than a refusal**, which
is why video was held back in 4e-iii until something could check the file. So
most of these tests are about the refusals: each one is a file somebody would
otherwise upload successfully and then find a black screen on the wall.

The MP4s are built here box by box rather than committed as binaries. That
keeps them readable, and lets each test say exactly which property it is
about.
"""

import struct

import pytest

from app import appearance, video


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def mp4(
    *,
    codec: bytes = b"avc1",
    seconds: float = 10,
    width: int = 1920,
    height: int = 1080,
    brand: bytes = b"isom",
    handler: bytes = b"vide",
    moov_last: bool = False,
    wide_header: bool = False,
) -> bytes:
    """A minimal MP4: enough structure for every check `video.inspect` makes."""
    ftyp = box(b"ftyp", brand + b"\0\0\0\0" + b"isommp41")
    timescale = 1000
    mvhd = box(
        b"mvhd",
        b"\0\0\0\0"
        + struct.pack(">IIII", 0, 0, timescale, int(seconds * timescale))
        + b"\0" * 80,
    )
    tkhd = box(b"tkhd", b"\0" * 80 + struct.pack(">II", width << 16, height << 16))
    hdlr = box(b"hdlr", b"\0" * 8 + handler + b"\0" * 12)
    entry = struct.pack(">I4s", 16, codec) + b"\0" * 8
    stsd = box(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + entry)
    trak = box(
        b"trak",
        tkhd + box(b"mdia", hdlr + box(b"minf", box(b"stbl", stsd))),
    )
    moov = box(b"moov", mvhd + trak)
    body = b"\0" * 256
    if wide_header:
        # A 64-bit size: `size == 1`, with the real length in the next 8 bytes.
        mdat = struct.pack(">I4sQ", 1, b"mdat", 16 + len(body)) + body
    else:
        mdat = box(b"mdat", body)
    return ftyp + (mdat + moov if moov_last else moov + mdat)


# -- What passes -------------------------------------------------------------


def test_an_ordinary_h264_mp4_passes():
    found = video.inspect(mp4())

    assert (found.width, found.height, found.duration_ms, found.codec) == (
        1920, 1080, 10_000, "avc1",
    )


def test_a_file_with_its_index_at_the_end_still_passes():
    """Plenty of tools write the index after the footage. Range serving is what
    lets a browser fetch the end first, so nothing needs rewriting."""
    assert video.inspect(mp4(moov_last=True)).duration_ms == 10_000


def test_a_64_bit_box_length_is_read_properly():
    assert video.inspect(mp4(wide_header=True)).codec == "avc1"


def test_av1_passes():
    assert video.inspect(mp4(codec=b"av01")).codec == "av01"


# -- What is refused, and what it says ---------------------------------------


def test_hevc_is_refused_with_how_to_fix_it_on_an_iphone():
    """**The most common upload in the world** would otherwise save and then
    show a black screen: an iPhone records HEVC by default, and a Chrome-based
    television often cannot decode it."""
    with pytest.raises(video.VideoProblem) as refused:
        video.inspect(mp4(codec=b"hvc1"))

    assert "Most Compatible" in str(refused.value)


def test_a_quicktime_file_is_told_to_export_as_mp4():
    with pytest.raises(video.VideoProblem) as refused:
        video.inspect(mp4(brand=b"qt  "))

    assert "MP4" in str(refused.value)


def test_something_that_is_not_a_video_is_refused():
    with pytest.raises(video.VideoProblem):
        video.inspect(b"\x89PNG\r\n\x1a\n" + b"\0" * 100)


def test_sound_with_no_picture_is_refused():
    with pytest.raises(video.VideoProblem) as refused:
        video.inspect(mp4(handler=b"soun"))

    assert "no picture" in str(refused.value)


def test_a_film_is_not_a_loop():
    with pytest.raises(video.VideoProblem) as refused:
        video.inspect(mp4(seconds=video.MAX_SECONDS + 1))

    assert "seconds" in str(refused.value)


def test_a_file_cut_short_is_refused_rather_than_guessed_at():
    """A box claiming to run past the end is a truncated upload, and reading on
    would mean reading garbage as structure."""
    with pytest.raises(video.VideoProblem) as refused:
        video.inspect(mp4()[:-40])

    assert "cut short" in str(refused.value)


def test_too_big_is_refused_before_it_is_read(monkeypatch):
    monkeypatch.setattr(video, "MAX_UPLOAD_BYTES", 100)

    with pytest.raises(video.VideoProblem) as refused:
        video.inspect(mp4())

    assert "trim" in str(refused.value)


def test_an_empty_file_is_refused():
    with pytest.raises(video.VideoProblem):
        video.inspect(b"")


# -- It is a background kind now ---------------------------------------------


def test_video_is_a_background_kind():
    """Held back in 4e-iii, and allowed now that the file can be checked."""
    parsed = appearance.Background(kind="video", asset="a" * 64)

    assert parsed.kind == "video"


# -- Upload ------------------------------------------------------------------


@pytest.fixture
def admin(make_user):
    return make_user("admin", name="Admin")


def upload(client, data: bytes):
    return client.post(
        "/api/images/background-video",
        content=data,
        headers={"Content-Type": "video/mp4"},
    )


def test_an_admin_uploads_a_background_video(client, db, admin, sign_in):
    sign_in(admin)

    reply = upload(client, mp4(seconds=12.5))

    assert reply.status_code == 201, reply.json()
    assert reply.json()["duration_ms"] == 12_500


def test_the_refusal_reaches_the_person_uploading(client, db, admin, sign_in):
    sign_in(admin)

    reply = upload(client, mp4(codec=b"hvc1"))

    assert reply.status_code == 400
    assert "HEVC" in reply.json()["detail"]


def test_a_video_is_kept_exactly_as_uploaded(client, db, admin, sign_in):
    """Nothing is normalised without re-encoding, and re-encoding is ffmpeg —
    so the file that passes is the file that plays."""
    sign_in(admin)
    original = mp4()

    digest = upload(client, original).json()["digest"]
    served = client.get(f"/api/images/{digest}")

    assert served.content == original
    assert served.headers["content-type"] == "video/mp4"


def test_an_agent_cannot_upload_one(client, db, make_user, sign_in):
    sign_in(make_user("agent", name="Peter Parker"))

    assert upload(client, mp4()).status_code == 403


def test_a_declared_size_over_the_limit_is_refused_before_reading(
    client, db, admin, sign_in
):
    sign_in(admin)

    reply = client.post(
        "/api/images/background-video",
        content=b"x",
        headers={"Content-Length": str(video.MAX_UPLOAD_BYTES + 1)},
    )

    assert reply.status_code == 413


# -- Served in ranges --------------------------------------------------------


def stored(client, admin, sign_in) -> tuple[str, bytes]:
    sign_in(admin)
    data = mp4()
    return upload(client, data).json()["digest"], data


def test_a_range_is_answered_with_just_that_range(client, db, admin, sign_in):
    """**Safari will not play an MP4 from a server that ignores `Range`.**"""
    digest, data = stored(client, admin, sign_in)

    reply = client.get(f"/api/images/{digest}", headers={"Range": "bytes=0-99"})

    assert reply.status_code == 206
    assert reply.content == data[:100]
    assert reply.headers["content-range"] == f"bytes 0-99/{len(data)}"


def test_an_open_ended_range_runs_to_the_end(client, db, admin, sign_in):
    digest, data = stored(client, admin, sign_in)

    reply = client.get(f"/api/images/{digest}", headers={"Range": "bytes=100-"})

    assert reply.content == data[100:]


def test_a_suffix_range_is_the_last_bytes(client, db, admin, sign_in):
    """What a browser asks for when the index is at the end of the file."""
    digest, data = stored(client, admin, sign_in)

    reply = client.get(f"/api/images/{digest}", headers={"Range": "bytes=-50"})

    assert reply.content == data[-50:]


def test_a_range_past_the_end_is_refused_properly(client, db, admin, sign_in):
    digest, data = stored(client, admin, sign_in)

    reply = client.get(f"/api/images/{digest}", headers={"Range": f"bytes={len(data) + 10}-"})

    assert reply.status_code == 416
    assert reply.headers["content-range"] == f"bytes */{len(data)}"


def test_no_range_is_the_whole_file_and_says_ranges_are_welcome(
    client, db, admin, sign_in
):
    digest, data = stored(client, admin, sign_in)

    reply = client.get(f"/api/images/{digest}")

    assert reply.status_code == 200
    assert reply.content == data
    assert reply.headers["accept-ranges"] == "bytes"


def test_a_malformed_range_falls_back_to_the_whole_file(client, db, admin, sign_in):
    """Never a guess: an answer the browser did not ask for is worse than the
    ordinary one."""
    digest, data = stored(client, admin, sign_in)

    reply = client.get(f"/api/images/{digest}", headers={"Range": "bytes=abc-def"})

    assert reply.status_code == 200
    assert reply.content == data


def test_a_television_gets_ranges_through_its_own_token(
    client, db, admin, sign_in
):
    """The wall reads through its display token, not a session, and must get
    the same answer — it is the one actually playing the video."""
    digest, data = stored(client, admin, sign_in)
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    display = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = display["url"].rsplit("/", 1)[-1]
    client.cookies.clear()

    reply = client.get(
        f"/api/display/{token}/assets/{digest}", headers={"Range": "bytes=0-9"}
    )

    assert reply.status_code == 206
    assert reply.content == data[:10]
