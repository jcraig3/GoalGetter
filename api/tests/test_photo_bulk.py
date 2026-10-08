"""Four hundred headshots in one go.

**Matched by filename through the same ladder that matches a CRM row.**
`pparker.jpg` finds Peter Parker the way `pparker@` in a warehouse view does — and
refuses, the same way, where two people fit.
"""

import io
import zipfile

import pytest
from PIL import Image

from app import photo_bulk


def image(colour=(90, 140, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (500, 500), colour).save(out, format="JPEG")
    return out.getvalue()


def archive(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return out.getvalue()


def named(make_user, db, full_name: str, email: str):
    user = make_user("agent")
    user.full_name = full_name
    user.email = email
    db.flush()
    return user


@pytest.fixture
def peter(db, make_user):
    return named(make_user, db, "Peter Parker", "peterp@acme.test")


# ── Matching ─────────────────────────────────────────────────────────────────


def test_a_file_named_for_a_login_finds_the_person(db, org, peter):
    """The convention a CRM export uses, which is not the directory's."""
    report = photo_bulk.apply_archive(db, org.id, archive({"pparker.jpg": image()}))

    assert report.matched == 1
    assert report.outcomes[0].user_name == "Peter Parker"
    assert peter.custom_photo_image_id is not None


def test_a_file_named_for_an_email_finds_the_person(db, org, peter):
    report = photo_bulk.apply_archive(
        db, org.id, archive({"peterp@acme.test.png": image()})
    )

    assert report.matched == 1


def test_subfolders_are_ignored_rather_than_refused(db, org, peter):
    """A folder exported from a shared drive arrives with them, and the name at
    the end is the part that matters."""
    report = photo_bulk.apply_archive(
        db, org.id, archive({"headshots/2026/pparker.jpg": image()})
    )

    assert report.matched == 1


def test_what_a_mac_puts_in_every_archive_is_skipped_silently(db, org, peter):
    """Reporting `__MACOSX/._pparker.jpg` as an unmatched person is noise in the
    one place somebody is scanning for real problems."""
    report = photo_bulk.apply_archive(
        db,
        org.id,
        archive({"pparker.jpg": image(), "__MACOSX/._pparker.jpg": b"junk"}),
    )

    assert len(report.outcomes) == 1
    assert report.matched == 1


# ── Refusing ─────────────────────────────────────────────────────────────────


def test_two_people_who_fit_are_a_question_not_a_guess(db, org, make_user):
    """The same refusal the CRM matcher makes, and the message says the fix."""
    named(make_user, db, "Bruce Banner", "bruceb@acme.test")
    named(make_user, db, "Betty Banner", "bettyb@acme.test")

    report = photo_bulk.apply_archive(db, org.id, archive({"bbanner.jpg": image()}))

    [outcome] = report.outcomes
    assert outcome.status == "ambiguous"
    assert "email address" in outcome.detail


def test_a_file_naming_nobody_says_so(db, org, peter):
    report = photo_bulk.apply_archive(db, org.id, archive({"nobody.jpg": image()}))

    [outcome] = report.outcomes
    assert outcome.status == "unmatched"
    assert "Nobody here matches" in outcome.detail


def test_something_that_is_not_an_image_is_reported_not_stored(db, org, peter):
    report = photo_bulk.apply_archive(
        db, org.id, archive({"pparker.jpg": b"MZ\x90\x00 not an image"})
    )

    [outcome] = report.outcomes
    assert outcome.status == "rejected"
    assert peter.custom_photo_image_id is None


def test_one_bad_file_does_not_stop_the_rest(db, org, make_user):
    """**The reason every file gets its own line.** An archive of four hundred
    with one corrupt entry must import three hundred and ninety-nine."""
    named(make_user, db, "Peter Parker", "peterp@acme.test")
    named(make_user, db, "Clark Kent", "clarkk@acme.test")

    report = photo_bulk.apply_archive(
        db,
        org.id,
        archive({"pparker.jpg": b"broken", "ckent.jpg": image()}),
    )

    assert report.matched == 1
    assert report.unresolved == 1


def test_a_file_that_is_not_a_zip_says_so(db, org):
    report = photo_bulk.apply_archive(db, org.id, b"this is not a zip")

    assert report.matched == 0
    assert "not a zip" in report.outcomes[0].detail


def test_files_that_are_not_images_by_name_are_skipped(db, org, peter):
    report = photo_bulk.apply_archive(
        db, org.id, archive({"readme.txt": b"hello", "pparker.jpg": image()})
    )

    assert report.matched == 1
    assert any(o.status == "rejected" for o in report.outcomes)


# ── Through the API ──────────────────────────────────────────────────────────


def test_a_manager_may_run_it(client, db, org, make_user, sign_in):
    sign_in(make_user("manager"))
    named(make_user, db, "Peter Parker", "peterp@acme.test")
    db.commit()

    reply = client.post(
        "/api/users/photos/bulk", content=archive({"pparker.jpg": image()})
    )

    assert reply.status_code == 200
    assert reply.json()["matched"] == 1


def test_an_agent_may_not(client, db, org, make_user, sign_in):
    sign_in(make_user("agent"))
    db.commit()

    reply = client.post("/api/users/photos/bulk", content=archive({}))

    assert reply.status_code == 403


def test_the_report_names_every_file(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))
    named(make_user, db, "Peter Parker", "peterp@acme.test")
    db.commit()

    reply = client.post(
        "/api/users/photos/bulk",
        content=archive({"pparker.jpg": image(), "ghost.jpg": image()}),
    )

    body = reply.json()
    assert body["matched"] == 1
    assert body["unresolved"] == 1
    assert {o["filename"] for o in body["outcomes"]} == {"pparker.jpg", "ghost.jpg"}


# ── One photo at a time ──────────────────────────────────────────────────────


def send_one(client, filename: str, data: bytes):
    return client.post(
        "/api/users/photos/one",
        content=data,
        headers={"content-type": "image/jpeg", "x-file-name": filename},
    )


def test_a_single_photo_is_matched_by_its_name_like_one_in_a_zip(
    client, db, org, peter, make_user, sign_in
):
    sign_in(make_user("admin"))
    reply = send_one(client, "pparker.jpg", image())

    assert reply.status_code == 200, reply.json()
    assert reply.json()["status"] == "matched"
    assert reply.json()["user_id"] == peter.id
    db.refresh(peter)
    assert peter.custom_photo_image_id is not None


def test_names_written_the_usual_ways_all_find_the_person(client, db, org, peter, make_user, sign_in):
    """The login with any separator or case, or the whole email address."""
    sign_in(make_user("admin"))
    for filename in ("PParker.JPG", "peter.parker.png", "peter-parker.webp", "peterp@acme.test.jpg"):
        assert send_one(client, filename, image()).json()["status"] == "matched", filename


def test_a_single_photo_nobody_matches_is_said_so_and_sets_nothing(client, db, org, peter, make_user, sign_in):
    sign_in(make_user("admin"))
    found = send_one(client, "mjwatson.jpg", image()).json()

    assert (found["status"], found["user_id"]) == ("unmatched", None)
    assert "mjwatson" in found["detail"]
    db.refresh(peter)
    assert peter.custom_photo_image_id is None


def test_a_single_file_that_is_not_a_picture_is_refused(client, make_user, sign_in):
    sign_in(make_user("admin"))
    assert send_one(client, "notes.txt", b"hello").json()["status"] == "rejected"


def test_a_folder_in_the_name_is_ignored(client, db, org, peter, make_user, sign_in):
    sign_in(make_user("admin"))
    assert send_one(client, "headshots/pparker.jpg", image()).json()["status"] == "matched"


def test_an_agent_cannot_upload_other_peoples_photos(client, make_user, sign_in):
    sign_in(make_user("agent"))
    assert send_one(client, "pparker.jpg", image()).status_code == 403


def test_a_single_photo_needs_its_name(client, make_user, sign_in):
    sign_in(make_user("admin"))
    reply = client.post("/api/users/photos/one", content=image(), headers={"content-type": "image/jpeg"})
    assert reply.status_code == 422
