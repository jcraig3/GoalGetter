"""The background library: what ships with the product, and what you kept.

**What ships is gradients, and that is a limit rather than a choice.** The
roadmap asks for bundled photographs and loop videos, and those need licensed
footage — the same asset question that deferred the 4f trophies and the badge
art. A photograph cannot be generated here honestly, and a stock image shipped
without a licence is a problem for every deployment that displays it. So the
bundled set is designed gradients, some of them moving, which need no asset at
all and look like somebody chose them. Drop-in photographs and footage can join
the same shelves once there is something licensed to put on them.

**The brand shelf is made from your own colours**, not from ours: two or three
gradients built from the organization's primary, secondary and accent at the
moment the library is opened. A floor that set its colours in Settings finds
them already waiting here, which is the point of having set them.

Every bundled background is written as the same `Background` a screen stores,
and validated through that model when this module loads — so a typo here fails
at start-up rather than on a television.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.appearance import Appearance, Background

__all__ = ["Preset", "BUNDLED", "bundled_for"]


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    category: str
    background: dict


def _preset(id_: str, name: str, category: str, **fields) -> Preset:
    # Validated now, strictly: a bad colour in this file is a bug in this
    # file, and it should stop the process starting rather than blank a wall.
    background = Background(kind="gradient", **fields).model_dump(exclude_none=True)
    return Preset(id=id_, name=name, category=category, background=background)


#: Dimmed where the colours are light, because the text over them is white.
#: A bright gradient straight behind a leaderboard is the thing dim exists to
#: fix, and a preset that needed fixing before it could be used would not be
#: much of a preset.
BUNDLED: tuple[Preset, ...] = (
    # Calm — for a wall that is mostly glanced at.
    _preset("deep-ocean", "Deep ocean", "calm",
            color="#0b1d33", color_mid="#0f2c4d", color_to="#123a5c", angle=160),
    _preset("night-sky", "Night sky", "calm",
            color="#1b2340", color_to="#070a14", style="radial"),
    _preset("slate", "Slate", "calm",
            color="#1c212d", color_to="#0b0e14", angle=180),
    _preset("aurora", "Aurora", "calm",
            color="#0b1020", color_mid="#134e4a", color_to="#1e1b4b",
            angle=135, motion=True),
    # Energy — for a floor in the middle of a push.
    _preset("sunset", "Sunset", "energy",
            color="#ff6a3d", color_mid="#c2185b", color_to="#4a148c",
            angle=135, dim=0.35),
    _preset("electric", "Electric", "energy",
            color="#00c6ff", color_to="#0047b3", angle=120, dim=0.3),
    _preset("ember", "Ember", "energy",
            color="#7a1c0b", color_mid="#c2410c", color_to="#f59e0b",
            angle=200, dim=0.3, motion=True),
    # Celebration — for the week a target falls.
    _preset("gold-rush", "Gold rush", "celebration",
            color="#3b2a00", color_mid="#b8860b", color_to="#f5b301",
            angle=145, dim=0.35),
    _preset("confetti-night", "Confetti night", "celebration",
            color="#1e1b4b", color_mid="#9d174d", color_to="#0e7490",
            angle=120, motion=True),
    # Seasonal — for the months people notice.
    _preset("winter", "Winter", "seasonal",
            color="#cfdef3", color_to="#6b8cae", angle=180, dim=0.45),
    _preset("autumn", "Autumn", "seasonal",
            color="#ff9966", color_to="#8a2d0c", angle=150, dim=0.35),
    _preset("spring", "Spring", "seasonal",
            color="#56ab2f", color_to="#1d4d12", angle=150, dim=0.3),
)


def _scene(id_: str, name: str, scene: str, category: str = "scenes", **fields) -> Preset:
    # The same strict check as a gradient: a scene name this file misspells
    # stops the process, rather than blanking a wall.
    background = Background(kind="scene", scene=scene, **fields).model_dump(exclude_none=True)
    return Preset(id=id_, name=name, category=category, background=background)


#: **Drawn scenes** (6.9): illustrated and abstract backgrounds rendered in
#: code on the wall, so nothing needs a licence and every one can take the
#: organization's colours. Most move — slowly, by shifting layers rather than
#: repainting them — and stand still for anybody who asked for less motion.
SCENES: tuple[Preset, ...] = (
    _scene("scene-waves", "Ocean waves", "waves",
           color="#0b1d33", color_mid="#0e7490", color_to="#38bdf8", motion=True),
    _scene("scene-mesh", "Aurora mesh", "mesh",
           color="#1e1b4b", color_mid="#0f766e", color_to="#7c3aed", motion=True),
    _scene("scene-bokeh", "Bokeh lights", "bokeh",
           color="#0b0e14", color_mid="#f59e0b", color_to="#ec4899", motion=True),
    _scene("scene-grid", "Synthwave grid", "grid",
           color="#12002b", color_mid="#d946ef", color_to="#22d3ee", motion=True),
    _scene("scene-lowpoly", "Low-poly", "lowpoly",
           color="#111827", color_mid="#1e3a8a", color_to="#0e7490"),
    _scene("scene-skyline", "Skyline at dusk", "skyline",
           color="#1e1b4b", color_mid="#9d174d", color_to="#f59e0b", motion=True),
    _scene("scene-confetti", "Confetti", "confetti",
           color="#0f172a", color_mid="#f59e0b", color_to="#22c55e", motion=True),
    _scene("scene-contours", "Contour lines", "contours",
           color="#0b1220", color_mid="#334155", color_to="#64748b"),
)


def bundled_for(org_appearance: Appearance) -> list[Preset]:
    """Everything that ships, plus the brand shelf made from these colours."""
    primary = org_appearance.primary or "#6366f1"
    secondary = org_appearance.secondary or primary
    accent = org_appearance.accent or secondary

    brand = [
        _preset("brand-deep", "Your brand, deep", "brand",
                color="#05070c", color_mid=primary, color_to="#05070c",
                angle=160, dim=0.45),
        _preset("brand-blend", "Your brand, blended", "brand",
                color=primary, color_to=secondary, angle=135, dim=0.4),
        _preset("brand-glow", "Your brand, glowing", "brand",
                color=accent, color_to="#05070c", style="radial",
                dim=0.35, motion=True),
        # Drawn scenes in the organization's own colours (6.9).
        _scene("brand-waves", "Your brand, waves", "waves", category="brand",
               color="#05070c", color_mid=primary, color_to=accent, motion=True),
        _scene("brand-mesh", "Your brand, mesh", "mesh", category="brand",
               color="#05070c", color_mid=primary, color_to=secondary, motion=True),
        _scene("brand-skyline", "Your brand, skyline", "skyline", category="brand",
               color="#05070c", color_mid=primary, color_to=accent, motion=True),
    ]
    return [*BUNDLED, *SCENES, *brand]
