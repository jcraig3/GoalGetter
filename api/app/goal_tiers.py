"""Stretch targets: the levels past a goal's target.

"Close $50,000 this month" with a stretch at $65,000 and another at $80,000.
The target is still *the* target — progress, pace and "attained" are measured
against it exactly as before. A stretch is a further line past it, celebrated
once per period when it is crossed, the same way hitting the target is.

**Stored on the goal, not as more goals.** The doc's earlier answer was "model
it as several goals on the same metric", which works until the second goal
announces "Calls achieved" at $65k and nobody can tell it from the first.
Levels on one goal are one bar with marks on it, and each mark is announced as
what it is.

**Up to three**, because a ladder longer than that is a leaderboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MAX_LEVELS = 3

#: What a level is called when nobody names it.
DEFAULT_LABELS = ("Stretch", "Stretch 2", "Stretch 3")

MAX_LABEL = 40


@dataclass(frozen=True)
class Level:
    #: 1 for the first stretch past the target.
    level: int
    label: str
    value: Decimal


def levels_of(stored: list | None) -> list[Level]:
    """The goal's stretch levels, as stored. Lenient: a row that no longer
    parses is skipped rather than breaking every page that shows the goal."""
    out: list[Level] = []
    for index, item in enumerate(stored or []):
        if not isinstance(item, dict):
            continue
        try:
            value = Decimal(str(item.get("value")))
        except (InvalidOperation, TypeError):
            continue
        label = str(item.get("label") or "").strip() or DEFAULT_LABELS[min(index, MAX_LEVELS - 1)]
        out.append(Level(level=index + 1, label=label[:MAX_LABEL], value=value))
    return out[:MAX_LEVELS]


def check(target: Decimal, levels: list[dict], direction: str) -> list[dict]:
    """Stretch levels as they will be stored, or a ValueError saying what is
    wrong with them in words.

    Each level has to be *harder* than the one before it: further above the
    target for a count, further below it for something where lower is better
    (average handle time, cost per deal).
    """
    if len(levels) > MAX_LEVELS:
        raise ValueError(f"A goal can have at most {MAX_LEVELS} stretch levels.")
    lower = direction == "lower_is_better"
    stored: list[dict] = []
    previous = target
    for index, item in enumerate(levels):
        try:
            value = Decimal(str(item.get("value")))
        except (InvalidOperation, TypeError):
            raise ValueError("Each stretch level needs a number.") from None
        if value <= 0:
            raise ValueError("A stretch level has to be more than zero.")
        harder = value < previous if lower else value > previous
        if not harder:
            what = "the target" if index == 0 else "the level before it"
            word = "below" if lower else "above"
            raise ValueError(f"Each stretch level has to be {word} {what}.")
        label = str(item.get("label") or "").strip()[:MAX_LABEL]
        stored.append({"value": str(value), "label": label or DEFAULT_LABELS[index]})
        previous = value
    return stored
