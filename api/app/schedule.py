"""When a slide plays, how often, and when a wall goes quiet (6.10).

**Worked out on the server, in the organization's own time.** A television
asks for its slides about once a minute; the slides it is given are the ones
that should be playing *now*, already repeated for their weight. The screen's
own rotation does not change at all — it rotates whatever list it is given by
the shared clock, which is what keeps every screen on a channel in step.

**Weight is spread, not stacked.** A slide at 3× appears three times a cycle,
evenly — A B A C A — rather than three times in a row, which would read as
the wall having stuck.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TypeVar

T = TypeVar("T")

#: The most a slide can be repeated in one cycle. Past four the others barely
#: appear, which is a channel with one slide in disguise.
MAX_WEIGHT = 4

#: The quiet modes a channel can choose. `clock` is a large clock drifting
#: slowly round the screen; `dark` is near-black with a small clock that moves
#: — both so nothing sits still long enough to burn in.
QUIET_MODES = ("off", "clock", "dark")


def _in_window(t: time, start: time | None, end: time | None) -> bool:
    """Whether a time of day falls in a window; one that crosses midnight
    (22:00–06:00) wraps."""
    if start is None and end is None:
        return True
    if end is None:
        return t >= start
    start = start or time(0, 0)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def plays_now(
    days: list[int] | None, start: time | None, end: time | None, now: datetime
) -> bool:
    """Whether a slide with these days (0 = Monday) and hours plays at `now`,
    a local time in the organization's zone.

    The days are the days a showing *starts*: a slide on Fridays from 22:00 to
    02:00 still plays at one in the morning on Saturday.
    """
    t = now.time()
    if not _in_window(t, start, end):
        return False
    if not days:
        return True
    starts_on: date = now.date()
    if start is not None and end is not None and start > end and t < end:
        # The after-midnight half of an overnight showing belongs to the day
        # before.
        starts_on = starts_on - timedelta(days=1)
    return starts_on.weekday() in days


def weighted(items: list[tuple[T, int]]) -> list[T]:
    """Each item repeated by its weight, spread evenly through the cycle.

    Smooth weighted round-robin: at each step every item gains its weight,
    the one furthest ahead is chosen and pays back the total. Deterministic,
    so every screen gets the same order.
    """
    if not items:
        return []
    weights = [max(1, min(w, MAX_WEIGHT)) for _, w in items]
    total = sum(weights)
    current = [0] * len(items)
    out: list[T] = []
    for _ in range(total):
        for i, w in enumerate(weights):
            current[i] += w
        best = max(range(len(items)), key=lambda i: (current[i], -i))
        current[best] -= total
        out.append(items[best][0])
    return out


@dataclass
class Quiet:
    mode: str
    #: When the quiet ends, in the organization's zone. None when it never
    #: does on its own (no window, only "weekends").
    until: datetime | None


def quiet_now(
    mode: str,
    start: time | None,
    end: time | None,
    weekends: bool,
    now: datetime,
) -> Quiet | None:
    """The channel's quiet, if it is quiet at `now` (a local time)."""
    if mode not in QUIET_MODES or mode == "off":
        return None
    weekend = now.weekday() >= 5
    in_hours = start is not None and end is not None and _in_window(now.time(), start, end)
    if not (in_hours or (weekends and weekend)):
        return None
    return Quiet(mode=mode, until=_quiet_ends(start, end, weekends, now))


def _quiet_ends(
    start: time | None, end: time | None, weekends: bool, now: datetime
) -> datetime | None:
    """The next minute it is not quiet, within the next three days — found by
    looking, which is simple, and the answer is only for a label."""
    probe = now.replace(second=0, microsecond=0)
    for _ in range(3 * 24 * 60):
        probe += timedelta(minutes=1)
        in_hours = start is not None and end is not None and _in_window(probe.time(), start, end)
        if not (in_hours or (weekends and probe.weekday() >= 5)):
            return probe
    return None
