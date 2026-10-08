import { describe, expect, it } from 'vitest';

import {
  chanceLabel,
  landOn,
  shortBy,
  slices,
  wonLabel,
  type Segment,
  type Spin,
} from './spendCopy';

function segment(id: number, chance: number, overrides: Partial<Segment> = {}): Segment {
  return {
    id,
    label: `S${id}`,
    kind: 'nothing',
    points: 0,
    chance,
    stock: null,
    ...overrides,
  };
}

describe('odds, the way people read them', () => {
  it('says the rare ones as "1 in N"', () => {
    // "2.5%" is correct and nobody feels it; "1 in 40" everybody does.
    expect(chanceLabel(0.025)).toBe('1 in 40');
  });

  it('says the common ones as a percentage', () => {
    // "1 in 1.3" reads worse than "75%".
    expect(chanceLabel(0.75)).toBe('75%');
  });

  it('has words for the ends', () => {
    expect(chanceLabel(1)).toBe('every time');
    expect(chanceLabel(0)).toBe('never');
  });
});

describe('the wheel as slices', () => {
  it('sizes each slice by its true chance', () => {
    // **The picture is drawn from the odds, so it cannot disagree with them.**
    const drawn = slices([segment(1, 0.75), segment(2, 0.25)]);

    expect(drawn.map((s) => s.end - s.start)).toEqual([270, 90]);
  });

  it('makes a whole circle', () => {
    const drawn = slices([segment(1, 0.2), segment(2, 0.3), segment(3, 0.5)]);

    expect(drawn.at(-1)?.end).toBeCloseTo(360);
  });

  it('is empty when there is nothing on it', () => {
    expect(slices([])).toEqual([]);
  });
});

describe('where the wheel stops', () => {
  const drawn = slices([segment(1, 0.5), segment(2, 0.25), segment(3, 0.25)]);

  it('lands the middle of the chosen slice under the pointer', () => {
    // Slice 2 runs 180–270, so its middle is 225; turning to 360 − 225 puts
    // it at the top.
    const end = landOn(drawn, 2, 0);

    expect(((end % 360) + 360) % 360).toBe(135);
  });

  it('always spins forward, and a long way', () => {
    // A wheel that nudged backwards to its answer would look rigged.
    const end = landOn(drawn, 3, 1000);

    expect(end).toBeGreaterThan(1000 + 4 * 360);
  });

  it('still spins when the segment has since been deleted', () => {
    expect(landOn(drawn, 99, 0)).toBe(5 * 360);
  });
});

function spin(overrides: Partial<Spin> = {}): Spin {
  return {
    id: 1,
    label: 'So close',
    kind: 'nothing',
    cost: 100,
    points_won: 0,
    given_at: null,
    created_at: '2028-02-01T10:00:00Z',
    prize_id: 1,
    winner_name: null,
    ...overrides,
  };
}

describe('what a spin won', () => {
  it('says a miss plainly', () => {
    // Dressing a loss up as "almost!" on a screen somebody just paid to use
    // is what makes a wheel feel like a machine for taking points.
    expect(wonLabel(spin())).toBe('So close — nothing this time.');
  });

  it('says who hands a real prize over', () => {
    expect(wonLabel(spin({ kind: 'prize', label: 'Long lunch' }))).toContain(
      'manager will hand it over',
    );
  });

  it('says the points', () => {
    expect(wonLabel(spin({ kind: 'points', points_won: 250 }))).toBe(
      'You won 250 points.',
    );
  });
});

it('says how far short, or nothing', () => {
  expect(shortBy(100, 300)).toBe(200);
  expect(shortBy(500, 300)).toBe(0);
});
