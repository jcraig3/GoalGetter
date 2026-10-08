import { describe, expect, it } from 'vitest';

import { bestOffset, nextPollIn, positionAt, remember, sample } from './wallClock';

/**
 * The arithmetic that keeps every screen on a channel in step.
 *
 * The property everything depends on is the first test: two screens asking at
 * the same instant get the same answer however long each has been running —
 * which is exactly what counting from page load could never give.
 */

describe('where the rotation is', () => {
  const dwells = [10, 20, 30]; // a 60-second cycle

  it('is the same for every screen asking at the same instant', () => {
    const now = 1_700_000_012_345;

    expect(positionAt(dwells, now)).toEqual(positionAt(dwells, now));
  });

  it('walks through the slides at their own pace', () => {
    const start = 1_800_000_000_000 - (1_800_000_000_000 % 60_000); // a cycle boundary

    expect(positionAt(dwells, start)?.index).toBe(0);
    expect(positionAt(dwells, start + 9_999)?.index).toBe(0);
    expect(positionAt(dwells, start + 10_000)?.index).toBe(1);
    expect(positionAt(dwells, start + 30_000)?.index).toBe(2);
    expect(positionAt(dwells, start + 60_000)?.index).toBe(0);
  });

  it('says how long the current slide has left', () => {
    // So a screen opened mid-slide shows it for the time remaining, not for
    // a full dwell — which is what put tabs out of step.
    const start = 1_800_000_000_000 - (1_800_000_000_000 % 60_000);

    expect(positionAt(dwells, start + 14_000)).toEqual({
      index: 1,
      remaining: 16_000,
      length: 20_000,
    });
  });

  it('gives a slide with no dwell a sensible one rather than dividing by zero', () => {
    expect(positionAt([0, 0], 5_000)?.remaining).toBeGreaterThan(0);
  });

  it('is nothing for a channel with no slides', () => {
    expect(positionAt([], 1_000)).toBeNull();
  });
});

describe('setting the clock by the server', () => {
  it('assumes the server read its clock halfway through the round trip', () => {
    // Sent at 1000, answered at 1200: the server's 5100 was most likely read
    // at 1100, so this screen is 4000 behind.
    expect(sample(5_100, 1_000, 1_200)).toEqual({ offset: 4_000, roundTrip: 200 });
  });

  it('believes the quickest reading rather than the average', () => {
    // A slow request can be wrong by half of however slow it was; averaging
    // it in would drag a good answer toward a bad one.
    const slow = sample(10_000, 0, 4_000); // offset 8000, ±2000
    const quick = sample(9_050, 1_000, 1_100); // offset 7_999.99…, ±50

    expect(bestOffset([slow, quick])).toBe(quick.offset);
  });

  it('keeps only the last few readings', () => {
    let kept = [] as ReturnType<typeof sample>[];
    for (let n = 0; n < 20; n += 1) kept = remember(kept, sample(n, 0, 1));

    expect(kept.length).toBeLessThanOrEqual(8);
  });

  it('trusts its own clock until it has heard from the server', () => {
    expect(bestOffset([])).toBe(0);
  });
});

describe('when to ask for the channel again', () => {
  it('waits for the shared boundary, not a private interval', () => {
    // At 12 seconds past the minute, with a 60-second refresh, the next ask is
    // 48 seconds away — for every screen, whenever it loaded.
    expect(nextPollIn(1_800_000_012_000 - (1_800_000_000_000 % 60_000), 60, 0)).toBe(48_000);
  });

  it('adds the spread on top', () => {
    const onBoundary = 1_800_000_000_000 - (1_800_000_000_000 % 60_000);

    expect(nextPollIn(onBoundary + 1, 60, 500)).toBe(60_000 - 1 + 500);
  });

  it('never asks faster than every five seconds', () => {
    expect(nextPollIn(0, 1, 0)).toBe(5_000);
  });
});
