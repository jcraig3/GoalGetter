import { describe, expect, it } from 'vitest';

import {
  nextChangeIn,
  playingAt,
  secondsIn,
  type Celebration,
} from './celebrationQueue';

/**
 * Reading the timetable the server hands every screen on a channel.
 *
 * Replaces tests of the old queue, which let each screen decide for itself
 * what to play and when — the design that put two televisions on one channel
 * up to ten seconds apart. The properties now are simpler and stronger: what
 * is on depends only on the time, so every screen agrees, and a screen that
 * joins late joins in step.
 */

function win(n: number, startsAt: number, hold = 10): Celebration {
  return {
    id: `win:${n}`,
    title: `Win ${n}`,
    body: null,
    about_name: 'Alice',
    media_url: null,
    media_kind: null,
    media_id: null,
    media_digest: null,
    media_start_seconds: null,
    media_end_seconds: null,
    hold_seconds: hold,
    created_at: '2026-08-18T12:00:00Z',
    starts_at: startsAt,
    ends_at: startsAt + hold * 1000,
  };
}

const T = 1_800_000_000_000;
const TABLE = [win(1, T), win(2, T + 15_000)];

describe('what is on', () => {
  it('is nothing before the first one starts', () => {
    expect(playingAt(TABLE, T - 1)).toBeNull();
  });

  it('is the first from the instant it starts', () => {
    expect(playingAt(TABLE, T)?.id).toBe('win:1');
  });

  it('is nothing in the gap between two', () => {
    // Without the gap, wins in the same minute strobe.
    expect(playingAt(TABLE, T + 12_000)).toBeNull();
  });

  it('is the second once its time comes', () => {
    expect(playingAt(TABLE, T + 15_000)?.id).toBe('win:2');
  });

  it('lets go on the instant it ends, not a moment after', () => {
    expect(playingAt(TABLE, T + 10_000)).toBeNull();
  });

  it('is the same for every screen asking at the same instant', () => {
    // **The property the whole change exists for.** Nothing a screen
    // remembers goes into the answer, so no two screens can disagree.
    const now = T + 3_210;

    expect(playingAt(TABLE, now)).toBe(playingAt([...TABLE], now));
  });
});

describe('when to look again', () => {
  it('is when the current one ends', () => {
    expect(nextChangeIn(TABLE, T + 4_000)).toBe(6_000);
  });

  it('is when the next one starts, from the gap', () => {
    expect(nextChangeIn(TABLE, T + 11_000)).toBe(4_000);
  });

  it('is never, once everything has finished', () => {
    expect(nextChangeIn(TABLE, T + 60_000)).toBeNull();
  });
});

describe('joining one already playing', () => {
  it('says how far in the rest of the room is', () => {
    // So a clip joins where the other screens' clips are, not at the start.
    expect(secondsIn(TABLE[0]!, T + 4_700)).toBe(4);
  });

  it('is never before the beginning', () => {
    expect(secondsIn(TABLE[0]!, T - 500)).toBe(0);
  });
});
