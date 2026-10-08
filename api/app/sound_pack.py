"""The starter sound pack (6.17): eight celebration sounds, made here.

**Synthesised, not recorded.** A sound somebody else recorded needs a licence
to ship and a file in the repository; these are a few lines of arithmetic each
— tones with harmonics, a bell's uneven partials, filtered noise — so they
belong to this product, cost nothing to ship, and come out identical every
time (the noise is seeded). Made once per process and kept.

**Not in anybody's Assets until chosen.** The pack is offered in the sound
picker; choosing one copies it into the organization's own store, which is
what lets a television fetch it through its own token like any other sound
and lets Assets say where it is used.

Short, on purpose: a celebration sound marks a moment, and the longest here is
under four seconds — well inside the fifteen a wall will play.
"""

from __future__ import annotations

import io
import math
import random
import struct
import wave
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

RATE = 22_050

Buffer = list[float]


@dataclass(frozen=True)
class Sound:
    key: str
    name: str
    description: str
    make: Callable[[], Buffer]


def _buffer(seconds: float) -> Buffer:
    return [0.0] * int(seconds * RATE)


def _tone(
    buf: Buffer,
    freq: float,
    start: float,
    length: float,
    partials: list[tuple[float, float]],
    *,
    attack: float = 0.01,
    decay: float | None = None,
    gain: float = 1.0,
    vibrato: float = 0.0,
) -> None:
    """Add one note: `partials` are (multiple of the frequency, loudness).
    `decay` is the time to fall to a third; None holds, then releases."""
    first = int(start * RATE)
    count = min(int(length * RATE), len(buf) - first)
    release = min(0.08, length / 3)
    for i in range(count):
        t = i / RATE
        envelope = min(1.0, t / attack) if attack else 1.0
        if decay is not None:
            envelope *= math.exp(-t / decay)
        elif t > length - release:
            envelope *= max(0.0, (length - t) / release)
        wobble = 1.0 + vibrato * math.sin(2 * math.pi * 5.5 * t)
        sample = 0.0
        for multiple, loudness in partials:
            sample += loudness * math.sin(2 * math.pi * freq * multiple * wobble * t)
        buf[first + i] += gain * envelope * sample


def _noise(
    buf: Buffer, start: float, length: float, *, decay: float, gain: float, seed: int,
    bright: bool = True,
) -> None:
    """A burst of noise — a clap, a snare, a cymbal. `bright` takes the low end
    off, which is most of the difference between a hiss and a thud."""
    rng = random.Random(seed)
    first = int(start * RATE)
    count = min(int(length * RATE), len(buf) - first)
    previous = 0.0
    for i in range(count):
        value = rng.uniform(-1, 1)
        if bright:
            value, previous = value - previous, value
        buf[first + i] += gain * math.exp(-(i / RATE) / decay) * value


def _finish(buf: Buffer) -> Buffer:
    """Even loudness across the pack, and no click at the end."""
    peak = max((abs(s) for s in buf), default=0.0) or 1.0
    out = [0.8 * s / peak for s in buf]
    fade = int(0.03 * RATE)
    for i in range(min(fade, len(out))):
        out[-1 - i] *= i / fade
    return out


BRASS = [(n, 1.0 / n) for n in range(1, 9)]
BELL = [(1.0, 1.0), (2.0, 0.6), (3.0, 0.4), (4.2, 0.25), (5.4, 0.2), (6.8, 0.1)]
SQUARE = [(n, 1.0 / n) for n in (1, 3, 5, 7)]


def _fanfare() -> Buffer:
    buf = _buffer(2.0)
    for at, freq in ((0.0, 392.0), (0.14, 523.25), (0.28, 659.25)):
        _tone(buf, freq, at, 0.16, BRASS, attack=0.02, gain=0.5)
    _tone(buf, 783.99, 0.42, 1.4, BRASS, attack=0.03, gain=0.55, vibrato=0.004)
    for freq in (523.25, 659.25):
        _tone(buf, freq, 0.42, 1.4, BRASS, attack=0.05, gain=0.3, vibrato=0.003)
    return _finish(buf)


def _chime() -> Buffer:
    buf = _buffer(2.6)
    for at, freq in ((0.0, 1046.5), (0.22, 1318.5), (0.44, 1568.0)):
        _tone(buf, freq, at, 2.1, BELL, attack=0.003, decay=0.55, gain=0.5)
    return _finish(buf)


def _gong() -> Buffer:
    buf = _buffer(3.8)
    partials = [(1.0, 1.0), (1.47, 0.7), (2.09, 0.55), (2.56, 0.4), (3.14, 0.3), (4.0, 0.2)]
    _tone(buf, 98.0, 0.0, 3.8, partials, attack=0.015, decay=1.4, gain=0.7)
    # A second, slightly sharp: the slow beating that makes a gong shimmer.
    _tone(buf, 99.3, 0.0, 3.8, partials[:3], attack=0.02, decay=1.2, gain=0.35)
    _noise(buf, 0.0, 0.15, decay=0.04, gain=0.08, seed=7, bright=False)
    return _finish(buf)


def _level_up() -> Buffer:
    buf = _buffer(1.0)
    notes = (523.25, 659.25, 783.99, 1046.5, 1318.5, 1568.0)
    for i, freq in enumerate(notes):
        _tone(buf, freq, i * 0.065, 0.08, SQUARE, attack=0.002, gain=0.4)
    _tone(buf, 2093.0, len(notes) * 0.065, 0.5, SQUARE, attack=0.002, decay=0.18, gain=0.45)
    return _finish(buf)


def _ka_ching() -> Buffer:
    buf = _buffer(1.5)
    _noise(buf, 0.0, 0.08, decay=0.02, gain=0.6, seed=11)
    _noise(buf, 0.09, 0.06, decay=0.015, gain=0.5, seed=12)
    for freq in (2093.0, 2637.0):
        _tone(buf, freq, 0.12, 1.3, BELL[:3], attack=0.002, decay=0.35, gain=0.35)
    return _finish(buf)


def _drum_roll() -> Buffer:
    buf = _buffer(3.3)
    roll = 1.6
    hits = int(roll / 0.045)
    for i in range(hits):
        swell = 0.25 + 0.75 * (i / hits)
        _noise(buf, i * 0.045, 0.06, decay=0.02, gain=0.9 * swell, seed=100 + i)
    # The crash, and a kick under it.
    _noise(buf, roll, 1.7, decay=0.55, gain=0.75, seed=999)
    _tone(buf, 55.0, roll, 0.5, [(1.0, 1.0), (2.0, 0.3)], attack=0.002, decay=0.15, gain=0.9)
    return _finish(buf)


def _air_horn() -> Buffer:
    buf = _buffer(2.4)
    horn = [(n, 1.0 / n**0.8) for n in range(1, 12)]
    for at, length in ((0.0, 0.32), (0.42, 0.32), (0.84, 1.35)):
        for freq in (466.0, 470.0, 587.0):
            _tone(buf, freq, at, length, horn, attack=0.015, gain=0.3)
    return _finish(buf)


def _applause() -> Buffer:
    buf = _buffer(3.6)
    rng = random.Random(42)
    t = 0.0
    while t < 3.4:
        # Swells in, holds, thins out — the shape of a room clapping.
        density = 0.25 + 0.75 * math.sin(math.pi * min(1.0, t / 3.4))
        _noise(buf, t, 0.03, decay=0.006, gain=rng.uniform(0.3, 0.6) * density, seed=int(t * 1000))
        t += rng.uniform(0.004, 0.022) / max(density, 0.2)
    return _finish(buf)


PACK: tuple[Sound, ...] = (
    Sound("fanfare", "Fanfare", "Brass, rising to a held chord.", _fanfare),
    Sound("chime", "Chime", "Three bells, bright and quick.", _chime),
    Sound("gong", "Gong", "One deep stroke — for the big one.", _gong),
    Sound("level-up", "Level up", "A fast arcade arpeggio.", _level_up),
    Sound("ka-ching", "Ka-ching", "The till, for a sale.", _ka_ching),
    Sound("drum-roll", "Drum roll", "A roll, and the crash.", _drum_roll),
    Sound("air-horn", "Air horn", "Three blasts. Not for the lobby.", _air_horn),
    Sound("applause", "Applause", "A room clapping.", _applause),
)

BY_KEY = {sound.key: sound for sound in PACK}


@lru_cache(maxsize=len(PACK))
def wav(key: str) -> bytes:
    """The sound as a WAV file — 16-bit mono — made once per process."""
    samples = BY_KEY[key].make()
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(
            b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        )
    return out.getvalue()


def seconds(key: str) -> float:
    return round((len(wav(key)) - 44) / 2 / RATE, 1)
