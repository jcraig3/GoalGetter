"""How everything looks, and where each setting came from.

**The whole point of this module is that "why is this screen green?" has one
answer.** The product it is modelled on scattered customization across five
pages and then could not say which one had won. These tests are mostly about
inheritance being boring and predictable, because that is the feature.
"""

import pytest

from app.appearance import BASE, Appearance, display_name, resolve


# ── Inheriting ───────────────────────────────────────────────────────────────


def test_nothing_set_anywhere_is_still_complete():
    """**A renderer never asks "and what if this is null?"**

    The question is answered once, here, instead of at forty call sites — so
    resolving no layers at all still produces every field.
    """
    out = resolve()

    assert out.primary == BASE.primary
    assert out.font_scale == 1.0
    assert out.background is not None
    assert out.name_display == "full"


def test_an_empty_layer_changes_nothing():
    """A channel that has never been customised looks exactly like its org."""
    org = Appearance(primary="#ff0000")

    assert resolve(org, Appearance()).primary == "#ff0000"


def test_none_layers_are_skipped():
    """A caller with nothing to add passes None rather than rebuilding its
    parent."""
    org = Appearance(primary="#ff0000")

    assert resolve(org, None, None).primary == "#ff0000"


def test_the_innermost_layer_wins():
    org = Appearance(primary="#ff0000")
    channel = Appearance(primary="#00ff00")
    screen = Appearance(primary="#0000ff")

    assert resolve(org, channel, screen).primary == "#0000ff"


def test_a_layer_only_overrides_what_it_mentions():
    """**This is what makes "reset to inherited" a real control.** A screen that
    sets one colour differs by one colour and nothing else."""
    org = Appearance(primary="#ff0000", logo="logo-digest", font="montserrat")
    screen = Appearance(primary="#0000ff")

    out = resolve(org, screen)

    assert out.primary == "#0000ff"
    assert out.logo == "logo-digest"
    assert out.font == "montserrat"


def test_a_plain_dict_resolves_the_same_as_a_model():
    """What comes out of a JSON column is a dict, and it must not need
    unpacking at every call site."""
    assert resolve({"primary": "#123456"}).primary == "#123456"


def test_an_unknown_key_is_dropped_rather_than_carried():
    """The database cannot validate JSON, so this does. A knob somebody removed
    last year must not keep arriving for ever."""
    out = resolve({"primary": "#123456", "chartreuse_mode": True})

    assert out.primary == "#123456"
    assert not hasattr(out, "chartreuse_mode")


# ── Backgrounds ──────────────────────────────────────────────────────────────


def test_a_background_merges_field_by_field():
    org = Appearance(background={"kind": "image", "asset": "photo", "dim": 0.3})
    screen = Appearance(background={"dim": 0.9})

    out = resolve(org, screen)

    assert out.background.kind == "image"
    assert out.background.asset == "photo"
    assert out.background.dim == 0.9


def test_changing_the_kind_replaces_it():
    """**A screen saying "solid blue" over a photograph means the photograph is
    gone.** Merging would leave the asset sitting there unused, and make "why is
    there still a picture?" a reasonable question with no reasonable answer."""
    org = Appearance(background={"kind": "image", "asset": "photo"})
    screen = Appearance(background={"kind": "solid", "color": "#001122"})

    out = resolve(org, screen)

    assert out.background.kind == "solid"
    assert out.background.color == "#001122"


def test_inherit_leaves_the_kind_alone():
    """"Inherit" is a real value a picker can hold, distinct from "none"."""
    org = Appearance(background={"kind": "image", "asset": "photo"})
    screen = Appearance(background={"kind": "inherit", "dim": 0.5})

    out = resolve(org, screen)

    assert out.background.kind == "image"
    assert out.background.dim == 0.5


# ── Bounds ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "field,value",
    [
        ("font_scale", 9.0),
        ("font_scale", 0.1),
        ("panel_opacity", 1.4),
        ("panel_opacity", -0.2),
        ("panel_blur", 500),
        ("panel_radius", -1),
    ],
)
def test_a_value_outside_its_range_is_refused(field, value):
    """A font scale of nine is a wall with one word on it. Caught here rather
    than discovered on a screen somebody has to walk over to."""
    with pytest.raises(Exception):
        Appearance(**{field: value})


def test_an_unknown_font_is_refused():
    """Fonts are bundled files. Accepting a name with no file behind it means a
    wall that silently falls back at the worst moment."""
    with pytest.raises(Exception):
        Appearance(font="comic-sans")


# ── Names ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "style,expected",
    [
        ("full", "Peter Parker"),
        ("first", "Peter"),
        ("first_initial", "Peter P."),
        ("last", "Parker"),
        ("nickname", "Spidey"),
    ],
)
def test_names_are_written_the_way_the_org_asked(style, expected):
    """**`first_initial` is what makes a wall safe to hang in a lobby.** Applied
    in one place, or the leaderboard is careful about surnames and the
    celebration banner that interrupts it is not."""
    assert display_name("Peter Parker", "Spidey", style) == expected


def test_a_nickname_style_falls_back_when_there_is_no_nickname():
    assert display_name("Peter Parker", None, "nickname") == "Peter Parker"


def test_a_single_word_name_survives_every_style():
    """Some directories hold one word — a service account, or somebody with a
    mononym. None of these may produce an empty string."""
    for style in ("full", "first", "first_initial", "last", "nickname"):
        assert display_name("Groot", None, style) == "Groot"


# ── Through the API ──────────────────────────────────────────────────────────


def test_an_untouched_organization_resolves_to_the_defaults(
    client, db, org, make_user, sign_in
):
    sign_in(make_user("agent"))
    db.commit()

    body = client.get("/api/organization").json()

    assert body["appearance"] == {}
    assert body["appearance_resolved"]["primary"] == BASE.primary


def test_saving_keeps_only_what_was_set(client, db, org, make_user, sign_in):
    """**Sparse on disk is what "inherit" looks like.** A field nobody chose
    stays absent, so a later change to the default reaches it."""
    sign_in(make_user("admin"))
    db.commit()

    body = client.patch(
        "/api/organization", json={"appearance": {"primary": "#123456"}}
    ).json()

    assert body["appearance"] == {"primary": "#123456"}
    assert body["appearance_resolved"]["primary"] == "#123456"
    assert body["appearance_resolved"]["font"] == BASE.font


def test_an_unknown_key_is_dropped_on_the_way_in(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))
    db.commit()

    body = client.patch(
        "/api/organization",
        json={"appearance": {"primary": "#123456", "chartreuse_mode": True}},
    ).json()

    assert body["appearance"] == {"primary": "#123456"}


def test_sending_an_empty_object_resets_to_inherited(
    client, db, org, make_user, sign_in
):
    """**Replaces rather than merges, deliberately.** A merging PATCH could not
    express "stop setting this" — absence would mean "leave it alone", which is
    the opposite of what a reset button needs."""
    sign_in(make_user("admin"))
    db.commit()
    client.patch("/api/organization", json={"appearance": {"primary": "#123456"}})

    body = client.patch("/api/organization", json={"appearance": {}}).json()

    assert body["appearance"] == {}
    assert body["appearance_resolved"]["primary"] == BASE.primary


def test_a_value_out_of_range_is_refused(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))
    db.commit()

    reply = client.patch("/api/organization", json={"appearance": {"font_scale": 9}})

    assert reply.status_code == 422


def test_an_agent_cannot_restyle_the_company(client, db, org, make_user, sign_in):
    sign_in(make_user("agent"))
    db.commit()

    reply = client.patch("/api/organization", json={"appearance": {"primary": "#000"}})

    assert reply.status_code == 403


def test_everyone_can_read_it(client, db, org, make_user, sign_in):
    """Every screen that draws a name or a colour needs this, not just admins."""
    sign_in(make_user("agent"))
    db.commit()

    assert client.get("/api/organization").status_code == 200


# ── Layouts ──────────────────────────────────────────────────────────────────


def test_screens_start_as_lists_and_dials():
    out = resolve()

    assert out.ranked_layout == "list"
    assert out.goal_layout == "gauge"


def test_a_layout_inherits_like_everything_else():
    """A channel saying "all my boards are podiums" is one setting, not one per
    screen."""
    channel = Appearance(ranked_layout="podium")

    assert resolve(None, channel, Appearance()).ranked_layout == "podium"


def test_one_screen_can_opt_out_of_a_house_style():
    channel = Appearance(ranked_layout="podium")
    screen = Appearance(ranked_layout="list")

    assert resolve(None, channel, screen).ranked_layout == "list"


def test_boards_and_goals_are_chosen_separately():
    """**The reason these are two fields rather than one.** A single `layout`
    could not say "podiums for boards *and* big numbers for goals" at the
    organization level, which is exactly where a house style gets set."""
    out = resolve(Appearance(ranked_layout="podium", goal_layout="big_number"))

    assert out.ranked_layout == "podium"
    assert out.goal_layout == "big_number"


def test_a_layout_with_no_drawing_is_refused():
    """A value the renderer has no drawing for would fall through to a blank
    screen on a wall nobody is standing next to."""
    with pytest.raises(Exception):
        Appearance(ranked_layout="carnival")


def test_a_goal_cannot_be_given_a_ranked_layout():
    """The families are separate, so the wrong one is a validation error rather
    than something to detect at render time."""
    with pytest.raises(Exception):
        Appearance(goal_layout="podium")
