"""Walk-up media: what we will and will not put on a wall.

The allowlist here is a security boundary, not a convenience. A display is a
browser nobody is watching, pointed at whatever this module accepts.
"""

import pytest

from app import media
from app.media import MAX_CLIP_SECONDS, MediaError


# ── YouTube ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
    ],
)
def test_the_forms_people_actually_paste(url):
    assert media.youtube_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PLabc",
        "https://www.youtube.com/results?search_query=walk+up",
        "https://www.youtube.com/@somechannel",
        "https://www.youtube.com/watch?v=short",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        # The classic: a hostname that merely ends in the real one.
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
    ],
)
def test_anything_that_is_not_one_video_is_refused(url):
    """Refused rather than guessed at. A guess ends up on a wall."""
    assert media.youtube_id(url) is None


def test_a_video_id_is_checked_not_trusted(url="https://youtu.be/../../etc/passwd"):
    """The id is interpolated into an embed URL on the display page."""
    assert media.youtube_id(url) is None


# ── The allowlist ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix", [".gif", ".png", ".jpg", ".jpeg", ".webp", ".GIF"])
def test_images_are_allowed(suffix):
    clip = media.parse(f"https://cdn.example.com/party{suffix}")
    assert clip.kind == media.KIND_IMAGE


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/anything",
        "https://example.com/video.mp4",
        "https://example.com/script.js",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.com/thing.gif",
    ],
)
def test_everything_else_is_refused(url):
    """"Any http URL" would let an admin aim every screen in the building at
    anything at all."""
    with pytest.raises(MediaError):
        media.parse(url)


def test_an_empty_link_is_refused_with_a_usable_message():
    with pytest.raises(MediaError, match="leave it empty"):
        media.parse("   ")


def test_an_absurdly_long_link_is_refused():
    with pytest.raises(MediaError):
        media.parse("https://example.com/" + "a" * 600 + ".gif")


# ── Length ───────────────────────────────────────────────────────────────────


def test_a_clip_is_capped_not_rejected():
    """Somebody pasting a link to a four-minute song has not made a mistake,
    they have just not thought about the length. Trimming is a kinder answer
    than a validation error."""
    clip = media.parse(
        "https://youtu.be/dQw4w9WgXcQ", start_seconds=30, end_seconds=300
    )
    assert clip.duration == MAX_CLIP_SECONDS
    assert clip.start_seconds == 30


def test_a_short_clip_is_left_alone():
    clip = media.parse("https://youtu.be/dQw4w9WgXcQ", start_seconds=10, end_seconds=18)
    assert (clip.start_seconds, clip.end_seconds) == (10, 18)


def test_no_end_means_the_full_allowance():
    clip = media.parse("https://youtu.be/dQw4w9WgXcQ", start_seconds=45)
    assert clip.duration == MAX_CLIP_SECONDS


def test_an_end_before_the_start_is_refused():
    with pytest.raises(MediaError, match="after the start"):
        media.parse("https://youtu.be/dQw4w9WgXcQ", start_seconds=30, end_seconds=10)


def test_a_negative_start_is_clamped_to_zero():
    assert media.parse("https://youtu.be/dQw4w9WgXcQ", start_seconds=-5).start_seconds == 0


def test_an_image_has_no_timeline():
    """Offsets on a still are a number that means nothing and reads as though
    it does."""
    clip = media.parse("https://cdn.example.com/party.gif", start_seconds=99)
    assert clip.start_seconds == 0
    assert clip.end_seconds == MAX_CLIP_SECONDS


# ── Kind is derived, never stored ────────────────────────────────────────────


def test_kind_is_derived_from_the_url():
    """A `kind` column beside the URL is one more pair that can disagree — and
    this disagreement would only surface on a screen in front of an office."""
    assert media.kind_of("https://youtu.be/dQw4w9WgXcQ") == media.KIND_YOUTUBE
    assert media.kind_of("https://cdn.example.com/x.gif") == media.KIND_IMAGE
    assert media.kind_of("https://example.com/whatever") is None


def test_parse_and_kind_of_always_agree():
    """They are two paths to the same answer, so they must never diverge."""
    for url in (
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://cdn.example.com/party.gif",
        "https://cdn.example.com/party.PNG",
    ):
        assert media.parse(url).kind == media.kind_of(url)
