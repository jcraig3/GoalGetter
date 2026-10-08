"""Game boards: one track engine, pluggable boards, and a piece per person.

**One engine rather than twenty-eight designs.** The competition this product
was measured against ships a long catalogue of themed boards, each drawn
separately and each ignoring the organization's theme — which is why its fun
designs hide the background and colour options entirely. Here a game board is a
*layout* like the podium or the list: it reads the same slide, honours the same
background, brand colour, type and panels, and differs only in how position is
drawn.

**Position is percent-to-target.** Every entrant's piece sits at their value as
a share of the finish line — the board's own, if it has one — and reaching it
is finishing. A board with no finish line is measured against whoever is
leading, and says so, rather than inventing a target nobody set.

Four families ship (6.8): the race track, a regatta on water, a mountain
climb and a space race to the Moon. Each is a name, a set of pieces and a
drawing (`wall/GameBoard.tsx`); the engine, the pieces' colours and the
theming are shared. Adding another is the same three things.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["DEFAULT_TOKEN", "FAMILIES", "Standing", "progress"]

#: The piece everybody has without choosing: their own face.
DEFAULT_TOKEN = "face"

#: Which pieces each family offers. The drawing for each lives with the layout
#: on the wall; this is the list the server accepts.
FAMILIES: dict[str, tuple[str, ...]] = {
    "race": ("face", "car", "truck", "bike"),
    "regatta": ("face", "sailboat", "speedboat", "duck"),
    "climb": ("face", "climber", "goat", "balloon"),
    "space": ("face", "rocket", "ufo", "comet"),
}


@dataclass
class Standing:
    """How far along one entrant is, 0–1, and whether they have finished."""

    fraction: float
    finished: bool


def progress(
    value: Decimal | float,
    *,
    finish_line: Decimal | float | None,
    leader: Decimal | float,
    lower_is_better: bool,
) -> Standing:
    """How far along the track this value is.

    **Against the finish line when there is one, against the leader when there
    is not.** A race measured against the leader always has somebody at the far
    end, which is why the wall labels that end "Leader" rather than "Finish" —
    nobody should read the front-runner as having crossed a line that was never
    drawn.

    **Inverted when lower is better.** A response time of 40 seconds against a
    target of 60 has finished; 90 against 60 is two thirds of the way. Nothing
    recorded is not the start line of a lower-is-better race, it is not being in
    it — which is why such an entrant is never on the board to be asked about.
    """
    value = float(value)
    target = float(finish_line) if finish_line is not None else float(leader)
    if target <= 0:
        return Standing(fraction=0.0, finished=False)

    if lower_is_better:
        if value <= 0:
            return Standing(fraction=0.0, finished=False)
        share = target / value
    else:
        share = value / target

    finished = finish_line is not None and share >= 1
    return Standing(fraction=max(0.0, min(share, 1.0)), finished=finished)
