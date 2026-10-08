import { describe, expect, test } from 'vitest';

import { backAt, driftAt } from './QuietScreen';

describe('the quiet clock drifts (6.10)', () => {
  test('stays on the screen', () => {
    for (let m = 0; m < 24 * 60; m += 7) {
      const { x, y } = driftAt(m * 60_000, 38, 40);
      expect(x).toBeGreaterThanOrEqual(12);
      expect(x).toBeLessThanOrEqual(88);
      expect(y).toBeGreaterThanOrEqual(10);
      expect(y).toBeLessThanOrEqual(90);
    }
  });

  test('and never sits still for long', () => {
    const a = driftAt(0, 22, 24);
    const b = driftAt(60_000, 22, 24);
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(5);
  });
});

describe('when the quiet ends', () => {
  const at = (iso: string) => new Date(iso).getTime();

  test('later today needs no day', () => {
    expect(backAt('America/New_York', at('2026-10-01T22:00:00-04:00'), at('2026-10-01T23:30:00-04:00'))).toMatch(
      /^at 11:30/,
    );
  });

  test('another day names it, in the office time', () => {
    expect(backAt('America/New_York', at('2026-10-02T22:00:00-04:00'), at('2026-10-05T07:00:00-04:00'))).toMatch(
      /^Mon 7:00/,
    );
  });
});
