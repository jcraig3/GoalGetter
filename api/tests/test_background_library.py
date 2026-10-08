"""The background library, and the colours it is made of.

Two things are tested here, because they arrived together. The library itself:
bundled backgrounds, the brand shelf made from the organization's own colours,
and backgrounds kept to be used again. And colour validation, which did not
exist until the library made it urgent — every colour in an appearance ends up
inside CSS on a public screen, and nothing checked one.
"""

import pytest
from pydantic import ValidationError

from app import appearance, backgrounds


# -- Colours -----------------------------------------------------------------


def test_a_colour_is_accepted_and_tidied():
    assert appearance.Background(color="#F5B301").color == "#f5b301"


def test_a_short_colour_is_expanded():
    """It is a colour, and the one fixture that used it was right to."""
    assert appearance.Background(color="#fff").color == "#ffffff"


def test_css_smuggled_into_a_colour_is_refused_on_write():
    """**Every colour here ends up inside CSS on a public screen.** This one
    would make every television fetch a stranger's URL — with the display
    token in the Referer."""
    with pytest.raises(ValidationError):
        appearance.Background(color="red; background: url(//elsewhere)")


def test_the_brand_colours_are_checked_too():
    with pytest.raises(ValidationError):
        appearance.Appearance(primary="blue")


def test_a_bad_stored_colour_falls_back_rather_than_failing_the_wall():
    """**Strict on write, lenient on read.** A layer stored before colours were
    checked must make that colour fall back to "inherit", never take the whole
    wall down."""
    resolved = appearance.resolve(
        {"primary": "not a colour", "background": {"kind": "solid", "color": "nope"}}
    )

    assert resolved.primary == appearance.BASE.primary
    assert resolved.background.color is None


def test_an_organization_cannot_save_a_bad_colour(client, db, make_user, sign_in):
    sign_in(make_user("admin", name="Admin"))

    reply = client.patch(
        "/api/organization", json={"appearance": {"primary": "red;x:y"}}
    )

    assert reply.status_code == 422


# -- Gradients ---------------------------------------------------------------


def test_a_gradient_can_have_three_stops_an_angle_and_motion():
    parsed = appearance.Background(
        kind="gradient", color="#000000", color_mid="#123456", color_to="#ffffff",
        angle=200, style="linear", motion=True,
    )

    assert (parsed.color_mid, parsed.angle, parsed.motion) == ("#123456", 200, True)


def test_an_angle_past_a_full_turn_is_refused():
    with pytest.raises(ValidationError):
        appearance.Background(kind="gradient", angle=400)


# -- What ships --------------------------------------------------------------


def test_every_bundled_background_is_one_a_screen_would_accept():
    """Validated when the module loads, so a typo in the list fails at start-up
    rather than on a television."""
    for preset in backgrounds.BUNDLED:
        appearance.Background.model_validate(preset.background)


def test_every_shelf_has_something_on_it():
    from app.models.background_library import CATEGORIES

    shelves = {p.category for p in backgrounds.bundled_for(appearance.Appearance())}

    assert shelves == set(CATEGORIES)


def test_bundled_ids_are_unique():
    ids = [p.id for p in backgrounds.bundled_for(appearance.Appearance())]

    assert len(ids) == len(set(ids))


def test_the_brand_shelf_is_made_from_the_organizations_colours():
    """A floor that set its colours in Settings finds them already waiting."""
    brand = [
        p for p in backgrounds.bundled_for(
            appearance.Appearance(primary="#112233", secondary="#445566", accent="#778899")
        )
        if p.category == "brand"
    ]

    used = {c for p in brand for c in p.background.values() if isinstance(c, str)}
    assert {"#112233", "#445566", "#778899"} <= used


def test_light_bundled_backgrounds_come_dimmed():
    """The text over them is white. A preset that needed fixing before it could
    be used would not be much of a preset."""
    winter = next(p for p in backgrounds.BUNDLED if p.id == "winter")

    assert winter.background["dim"] >= 0.4


# -- The library over the wire -----------------------------------------------


@pytest.fixture
def admin(make_user):
    return make_user("admin", name="Admin")


def keep(client, **body):
    return client.post(
        "/api/backgrounds",
        json={
            "name": "Office photo",
            "category": "calm",
            "background": {"kind": "image", "asset": "a" * 64, "dim": 0.4},
            **body,
        },
    )


def test_the_library_lists_what_ships(client, db, admin, sign_in):
    sign_in(admin)

    body = client.get("/api/backgrounds").json()

    assert any(e["id"] == "bundled:aurora" for e in body["entries"])
    assert body["categories"] == ["calm", "energy", "celebration", "seasonal", "brand", "scenes", "assets"]


def test_the_brand_shelf_follows_the_colours_set_in_settings(
    client, db, admin, sign_in
):
    sign_in(admin)
    client.patch("/api/organization", json={"appearance": {"primary": "#ab1234"}})

    entries = client.get("/api/backgrounds").json()["entries"]
    blend = next(e for e in entries if e["id"] == "bundled:brand-blend")

    assert blend["background"]["color"] == "#ab1234"


def test_a_background_can_be_kept_and_found_again(client, db, admin, sign_in):
    """**Before this, reusing a background meant uploading it again.**"""
    sign_in(admin)

    reply = keep(client)
    entries = client.get("/api/backgrounds").json()["entries"]

    assert reply.status_code == 201, reply.json()
    assert entries[0]["name"] == "Office photo"
    assert entries[0]["bundled"] is False


def test_nothing_is_not_a_background_to_keep(client, db, admin, sign_in):
    """A library entry that draws nothing is a swatch that looks broken."""
    sign_in(admin)

    reply = keep(client, background={"kind": "none"})

    assert reply.status_code == 422


def test_a_photograph_with_no_file_is_not_kept(client, db, admin, sign_in):
    sign_in(admin)

    reply = keep(client, background={"kind": "image"})

    assert reply.status_code == 422
    assert "Upload" in reply.json()["detail"]


def test_a_kept_background_is_checked_like_a_screens(client, db, admin, sign_in):
    sign_in(admin)

    reply = keep(client, background={"kind": "solid", "color": "red;x"})

    assert reply.status_code == 422


def test_an_unknown_shelf_is_refused(client, db, admin, sign_in):
    sign_in(admin)

    assert keep(client, category="relaxing").status_code == 422


def test_two_with_one_name_are_refused(client, db, admin, sign_in):
    sign_in(admin)
    keep(client)

    assert keep(client).status_code == 409


def test_removing_one_leaves_walls_that_use_it_alone(client, db, admin, sign_in):
    """**A starting point, not a reference.** Choosing an entry copied it onto
    the screen, so taking it off the shelf changes no wall."""
    sign_in(admin)
    kept = keep(client).json()
    client.patch(
        "/api/organization",
        json={"appearance": {"background": kept["background"]}},
    )

    assert client.delete(f"/api/backgrounds/{kept['id'].split(':')[1]}").status_code == 204

    org = client.get("/api/organization").json()
    assert org["appearance"]["background"]["asset"] == "a" * 64


def test_a_manager_browses_it_but_an_agent_cannot(client, db, make_user, sign_in):
    """Phase 25: a manager picks an announcement's background from it."""
    sign_in(make_user("manager", name="Manager"))
    assert client.get("/api/backgrounds").status_code == 200
    sign_in(make_user("agent", name="Agent"))
    assert client.get("/api/backgrounds").status_code == 403


def test_a_manager_uploads_a_background_but_not_the_logo(client, make_user, sign_in):
    from tests.test_brand_images import png

    sign_in(make_user("manager", name="Manager"))
    assert client.post("/api/images/logo", content=png(200, 200)).status_code == 403
    assert client.post("/api/images/background", content=png(1920, 1080)).status_code == 201


def test_another_organizations_entry_is_not_found(client, db, admin, sign_in):
    sign_in(admin)

    assert client.delete("/api/backgrounds/999999").status_code == 404


# ── Drawn scenes and your own photos (6.9) ───────────────────────────────────


def test_a_scene_is_a_background_a_screen_accepts():
    background = appearance.Background(kind="scene", scene="skyline", color="#1e1b4b", motion=True)
    assert background.scene == "skyline"


def test_a_scene_that_does_not_exist_is_refused():
    with pytest.raises(ValidationError):
        appearance.Background(kind="scene", scene="volcano")


def test_every_scene_is_on_the_scenes_shelf():
    from app.appearance import SCENES

    on_shelf = {p.background["scene"] for p in backgrounds.bundled_for(appearance.Appearance()) if p.category == "scenes"}
    assert on_shelf == set(SCENES)


def test_the_brand_shelf_has_scenes_in_the_brand_colours():
    brand = [
        p for p in backgrounds.bundled_for(appearance.Appearance(primary="#ff0000", accent="#00ff00"))
        if p.category == "brand" and p.background["kind"] == "scene"
    ]
    assert brand and all(p.background["color_mid"] == "#ff0000" for p in brand)


def test_your_photos_and_video_are_a_shelf_but_art_and_faces_are_not(
    client, db, org, make_user, sign_in
):
    import io

    from PIL import Image

    from app import images

    sign_in(make_user("admin"))

    def upload(mode, name):
        out = io.BytesIO()
        Image.new(mode, (900, 600), (10, 120, 200, 0) if mode == "RGBA" else (10, 120, 200)).save(out, format="PNG")
        return client.post(
            "/api/assets", content=out.getvalue(),
            headers={"content-type": "image/png", "x-file-name": name},
        ).json()

    photo = upload("RGB", "Office.png")
    upload("RGBA", "Badge art.png")
    alice = make_user("agent", name="Alice")
    out = io.BytesIO()
    Image.new("RGB", (400, 400), (200, 10, 10)).save(out, format="JPEG")
    alice.custom_photo_image_id = images.store(db, org.id, out.getvalue()).id
    db.commit()

    shelf = client.get("/api/backgrounds").json()
    mine = [e for e in shelf["entries"] if e["category"] == "assets"]

    assert "assets" in shelf["categories"]
    assert [(e["name"], e["background"]["kind"], e["background"]["asset"]) for e in mine] == [
        ("Office", "image", photo["digest"])
    ]


def test_a_scene_can_be_kept_on_the_scenes_shelf(client, make_user, sign_in):
    sign_in(make_user("admin"))
    kept = client.post(
        "/api/backgrounds",
        json={"name": "Our skyline", "category": "scenes",
              "background": {"kind": "scene", "scene": "skyline", "color": "#000000"}},
    )
    assert kept.status_code == 201, kept.json()
