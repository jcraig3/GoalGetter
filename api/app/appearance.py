"""How everything looks, and where each setting comes from.

**One system with inheritance, rather than a settings page per feature.** The
product this is modelled on scattered its customization: the logo in two places,
fonts under Company Settings, colours under Branding, per-competition colours in
a wizard step, per-celebration colours somewhere else again. Each was reasonable
on the day it shipped, and together they are impossible to hold in your head —
"why is this screen green?" has five possible answers and no way to tell which.

So there is one shape, stored at several levels, and a single function that
resolves them:

    organization -> channel -> screen -> moment

Every field is optional at every level, and `None` means **inherit**. A channel
that sets nothing looks exactly like the organization; a screen that sets one
colour differs by one colour. That is what makes "reset to inherited" a real
control rather than a guess about which default to write back.

**Sparse, and stored as JSON.** A column per token would be forty columns on four
tables and a migration every time somebody wants a new knob. The trade is that
the database cannot validate them, so this module does — every read goes through
`Appearance`, and an unknown key is dropped rather than carried around for ever.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

__all__ = [
    "Appearance",
    "BASE",
    "Background",
    "END_TIME_FORMATS",
    "FONTS",
    "GOAL_LAYOUTS",
    "MILESTONE_LEVELS",
    "RANKED_LAYOUTS",
    "NAME_DISPLAYS",
    "display_name",
    "resolve",
]

#: Fonts bundled with the build.
#:
#: **Named here rather than fetched from a font service**, which is the
#: difference between a wall that renders in a warehouse with no internet and one
#: that falls back to Times New Roman at the worst possible moment. Adding one
#: means adding the file, which is the honest cost.
FONTS = (
    "system",
    "inter",
    "montserrat",
    "raleway",
    "ubuntu",
    "oswald",
    "bebas",
    "indie",
)

#: How a person's name is written on screen.
#:
#: `first_initial` exists for the lobby: a wall the public walks past should not
#: publish everybody's surname, and that is a one-setting fix rather than a
#: policy conversation.
NAME_DISPLAYS = ("full", "first", "first_initial", "last", "nickname")

#: How long a competition has left, spelled out.
END_TIME_FORMATS = ("default", "simple", "full", "off")

#: How much a wall interrupts itself for a win. See `app/events.py`, which owns
#: which events count as which.
MILESTONE_LEVELS = ("none", "important", "all")

#: How a ranked screen is drawn — a leaderboard or a competition.
#:
#: **A layout is not a screen kind.** The kind says what the screen is *about*
#: and comes from the thing it points at; the layout says how that is drawn and
#: is a choice. Keeping them apart is what stops "podium" and "list" being two
#: screen types to keep in step for ever.
#: `race` is the first game board: every entrant's piece on a track, placed by
#: their share of the finish line. See `app/game_boards.py`.
RANKED_LAYOUTS = ("list", "podium", "race", "regatta", "climb", "space")

#: How a screen with one number and a target is drawn.
#:
#: **Its own setting rather than sharing one with ranked screens.** A single
#: `layout` field could not say "podiums for boards *and* big numbers for goals"
#: at the organization level, which is exactly where somebody sets a house style
#: — and the screens that would have to disagree are the ones least likely to be
#: configured individually.
GOAL_LAYOUTS = ("gauge", "big_number")

#: What sits behind a screen.
#:
#: **`video` arrived in 4k, once something could check the file.** It was held
#: back in 4e-iii because a kind that saves and then draws nothing was the
#: failure that phase spent a day undoing; `app/video.py` now refuses, at
#: upload, every file a television would silently fail to play. It is also the
#: only ad-free loop: an embedded YouTube video shows ads when its *uploader*
#: says so, and nothing the embedding site does may change that.
BACKGROUND_KINDS = ("inherit", "none", "solid", "gradient", "image", "video", "youtube", "scene")

#: Drawn backgrounds (6.9): illustrated and abstract scenes rendered in code on
#: the wall itself, in the background's own three colours. See
#: `web/src/components/wall/Scenes.tsx`, which must know every name here.
SCENES = ("waves", "mesh", "bokeh", "grid", "lowpoly", "skyline", "confetti", "contours")


#: A colour, and only a colour.
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: The context flag `resolve` passes when reading stored layers.
LENIENT = "lenient"


def _colour(value, info: ValidationInfo):
    """Refuse anything but `#rgb` or `#rrggbb` on the way in; drop it on the way
    out.

    **Every colour here ends up inside CSS on a public screen**, and until 4k
    nothing checked one. A value like `red; background: url(//elsewhere)` would
    make every television fetch a stranger's URL — and a browser sends the page
    address as the Referer, which for a wall is the display token. A typo alone
    blanks the screen instead. Admin-only to write, and still worth closing.

    **Strict on write, lenient on read.** A router validating a payload gets a
    422 naming the field. `resolve`, reading layers stored before this existed,
    passes `LENIENT` and gets `None` for a bad value — which means "inherit",
    so an old row can make a colour fall back but can never take a wall down.

    `#rgb` is expanded rather than refused: it is a colour, and the one test
    fixture that used it was right to.
    """
    if value is None:
        return None
    if isinstance(value, str) and _HEX.match(value.strip()):
        text = value.strip().lower()
        if len(text) == 4:
            text = "#" + "".join(ch * 2 for ch in text[1:])
        return text
    if info.context and info.context.get(LENIENT):
        return None
    raise ValueError("Use a colour written like #f5b301.")


#: How a gradient is drawn.
GRADIENT_STYLES = ("linear", "radial")


class Background(BaseModel):
    """What is behind everything else on a screen."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal[BACKGROUND_KINDS] | None = None  # type: ignore[valid-type]

    #: A hex colour for `solid`, or the first stop of a `gradient`.
    color: str | None = None
    #: The last stop of a `gradient`.
    color_to: str | None = None
    #: An optional middle stop. Two stops is a fade; three is what makes a
    #: gradient look designed rather than defaulted, which is most of what the
    #: bundled library is.
    color_mid: str | None = None

    #: Degrees, for a linear gradient. 135 is the diagonal it always was.
    angle: int | None = Field(default=None, ge=0, le=360)
    style: Literal[GRADIENT_STYLES] | None = None  # type: ignore[valid-type]

    #: A slow drift, for a gradient. **Motion without a video file**: it is the
    #: cheapest way to a background that feels alive, and it is drawn by moving
    #: a layer rather than repainting one, so a television stick that would
    #: stutter through footage does not notice it. Off for anybody who has
    #: asked their device for less motion.
    motion: bool | None = None
    #: A `stored_asset` digest for `image` and `video`, or a YouTube id.
    asset: str | None = None
    #: Seconds into a `youtube` or `video` background to start, and loop back
    #: to (Phase 28).
    start: int | None = Field(default=None, ge=0, le=86_400)
    #: Which drawn scene, for `scene` (6.9). Its colours are `color`,
    #: `color_mid` and `color_to`, and `motion` sets it moving.
    scene: Literal[SCENES] | None = None  # type: ignore[valid-type]

    #: **Dim and blur belong to the background, not to the panels.** A photograph
    #: behind white text is unreadable at ten feet, and the fix is to darken the
    #: photograph rather than to make every panel opaque — which hides the
    #: photograph entirely and raises the question of why it is there at all.
    dim: float | None = Field(default=None, ge=0, le=1)
    blur: int | None = Field(default=None, ge=0, le=40)

    _colours = field_validator("color", "color_to", "color_mid", mode="before")(_colour)

    @field_validator("asset", mode="after")
    @classmethod
    def _youtube_link_to_id(cls, value: str | None) -> str | None:
        """A pasted YouTube link becomes its video id (Phase 28) — the player
        takes an id, and a link in its place played nothing."""
        if value and "/" in value:
            from app.media import youtube_id

            return youtube_id(value) or value
        return value


class Appearance(BaseModel):
    """One layer of look. Every field optional; `None` means inherit.

    Deliberately flat apart from `background`. A nested shape would need a merge
    that understands nesting, and "primary colour" is not a thing that wants a
    namespace.
    """

    model_config = ConfigDict(extra="ignore")

    # ── Identity ─────────────────────────────────────────────────────────────
    #: A `stored_asset` digest. One logo, for the app and the walls alike — a
    #: second "for dark backgrounds" was dropped as more than anybody needed.
    logo: str | None = None
    slogan: str | None = None

    # ── Colour ───────────────────────────────────────────────────────────────
    primary: str | None = None
    secondary: str | None = None
    accent: str | None = None

    _colours = field_validator("primary", "secondary", "accent", mode="before")(_colour)

    # ── Type ─────────────────────────────────────────────────────────────────
    font: Literal[FONTS] | None = None  # type: ignore[valid-type]
    #: Multiplies every size on a wall screen. A room twice as deep needs type
    #: twice as large, and that is one number rather than a second design.
    font_scale: float | None = Field(default=None, ge=0.5, le=2.5)

    # ── Panels: the cards that sit over the background ───────────────────────
    panel_opacity: float | None = Field(default=None, ge=0, le=1)
    panel_blur: int | None = Field(default=None, ge=0, le=40)
    panel_radius: int | None = Field(default=None, ge=0, le=48)

    # ── Content ──────────────────────────────────────────────────────────────
    #: How a leaderboard or a competition is drawn.
    ranked_layout: Literal[RANKED_LAYOUTS] | None = None  # type: ignore[valid-type]
    #: How a goal is drawn.
    goal_layout: Literal[GOAL_LAYOUTS] | None = None  # type: ignore[valid-type]

    #: How many rows a ranked screen draws.
    #:
    #: **A drawing decision, not a filter.** The board still decides who is on
    #: it — this only says how many of those fit on one television, so setting
    #: it higher than the board's own `display_limit` shows what there is
    #: rather than inventing more.
    #:
    #: Three is the fewest that is still a ranking. Twenty is where a 1080-line
    #: screen stops being readable from across a room.
    row_count: int | None = Field(default=None, ge=3, le=20)

    #: Whether the numbers are drawn beside the names.
    #:
    #: Off turns a leaderboard into positions only, which is what makes one
    #: hangable in a room where the figures themselves are commercially
    #: sensitive — the ranking is the motivating part and the revenue is not.
    show_values: bool | None = None

    name_display: Literal[NAME_DISPLAYS] | None = None  # type: ignore[valid-type]
    end_time_format: Literal[END_TIME_FORMATS] | None = None  # type: ignore[valid-type]

    #: Which wins stop the rotation and take over the screen.
    #:
    #: **Per wall, because the right answer is about the room.** A sales floor
    #: wants every shout-out; a reception area wants the contest wins and
    #: nothing else; a screen above a support desk wants to be left alone. One
    #: control with three answers rather than a checkbox per event type.
    milestones: Literal[MILESTONE_LEVELS] | None = None  # type: ignore[valid-type]

    # There is deliberately no `show_target`. A goal with its target hidden is
    # one big number, which `goal_layout` already says — and two settings that
    # can contradict each other about the same pixels is a question with no
    # right answer.

    background: Background | None = None


#: What a deployment looks like before anybody has chosen anything.
#:
#: **Every field is filled, and that is the point.** `resolve` returns something
#: complete, so a renderer never has to ask "and what if this one is null?" — the
#: question is answered once, here, instead of at forty call sites.
BASE = Appearance(
    primary="#6366f1",
    secondary="#818cf8",
    accent="#34d399",
    font="system",
    font_scale=1.0,
    panel_opacity=0.72,
    panel_blur=12,
    panel_radius=16,
    ranked_layout="list",
    goal_layout="gauge",
    row_count=10,
    show_values=True,
    name_display="full",
    end_time_format="default",
    # Everything, which is what a wall did before this was a setting.
    milestones="all",
    background=Background(kind="none", dim=0.35, blur=0),
)


def resolve(*layers: Appearance | dict | None) -> Appearance:
    """Merge layers outermost first; later layers win where they say anything.

    `resolve(org, channel, screen)` is the whole contract. An absent layer and an
    absent field both mean "whatever the layer before me said", so a caller with
    nothing to add passes `None` rather than reconstructing its parent.

    Pure, which is why the merge lives here and not inside a renderer that also
    knows about pixels: it is cheap to test and safe to cache.
    """
    out = BASE.model_copy(deep=True)

    for layer in layers:
        if layer is None:
            continue
        # Lenient: a stored layer written before colours were checked must fall
        # back to "inherit" for a bad value, never fail the whole wall.
        appearance = (
            layer
            if isinstance(layer, Appearance)
            else Appearance.model_validate(layer, context={LENIENT: True})
        )

        for field, value in appearance.model_dump(exclude_none=True).items():
            if field == "background":
                out.background = _merge_background(out.background, value)
                continue
            setattr(out, field, value)

    return out


def _merge_background(current: Background | None, incoming: dict) -> Background:
    """Backgrounds merge field by field, like everything else.

    **Except `kind`, which replaces.** A screen saying "solid blue" over an
    organization's photograph means the photograph is gone; merging the two would
    leave the image asset sitting there unused, and make "why is there still a
    picture?" a reasonable question with no reasonable answer.
    """
    merged = (current or Background()).model_copy(deep=True)

    for field, value in incoming.items():
        if value is not None:
            setattr(merged, field, value)

    if incoming.get("kind") in (None, "inherit"):
        merged.kind = (current or Background()).kind
    return merged


def display_name(full_name: str, nickname: str | None, style: str) -> str:
    """A person's name, written the way the organization asked for.

    **Not cosmetic.** `first_initial` is what makes a wall safe to hang where
    customers walk past, and it has to be applied in one place — or the lobby
    screen will be careful about surnames on the leaderboard and careless about
    them in the celebration banner that interrupts it.
    """
    parts = [part for part in full_name.split() if part]
    first = parts[0] if parts else full_name
    last = parts[-1] if len(parts) > 1 else ""

    if style == "nickname" and nickname:
        return nickname
    if style == "first":
        return first
    if style == "first_initial":
        return f"{first} {last[0]}." if last else first
    if style == "last":
        return last or first
    return full_name
