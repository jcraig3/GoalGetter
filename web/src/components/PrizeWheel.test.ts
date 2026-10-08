/** The wheel's slice labels (Q2-26): along the radius, never upside down. */
import { describe, expect, test } from 'vitest';

import { labelTurn, wheelLabel } from './PrizeWheel';

describe('a slice label', () => {
  test('reads outward on the right and inward on the left', () => {
    expect(labelTurn(90)).toBe(0); // three o'clock: level, reading outward
    expect(labelTurn(270)).toBe(360); // nine o'clock: level, not upside down
    expect(labelTurn(10)).toBe(-80);
    expect(labelTurn(190)).toBe(280);
  });

  test('is cut to fit between the hub and the rim', () => {
    expect(wheelLabel('Lunch')).toBe('Lunch');
    expect(wheelLabel('Maybe another spin')).toBe('Maybe anothe…');
    expect(wheelLabel('Maybe another spin').length).toBe(13);
  });
});
