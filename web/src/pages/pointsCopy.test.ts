import { describe, expect, it } from 'vitest';

import {
  daysLeft,
  toNextLabel,
  elapsedPercent,
  gapToNext,
  labelFor,
  ordinal,
  seasonWindow,
  signed,
  timeLeftLabel,
  type Season,
  type Standing,
} from './pointsCopy';

/**
 * The wording around the numbers, which is where an economy is won or lost.
 *
 * "165,340 points" with nothing beside it is the exact number that killed the
 * account this feature was designed against: it went up forever and told
 * nobody anything.
 */

function season(overrides: Partial<Season> = {}): Season {
  return {
    id: 1,
    name: 'Q1 2028',
    starts_on: '2028-01-01',
    ends_on: '2028-03-31',
    closed_at: null,
    ...overrides,
  };
}

const MID = new Date(2028, 1, 15); // 15 Feb 2028

describe('ordinals', () => {
  it('handles the ordinary cases', () => {
    expect([1, 2, 3, 4, 21].map(ordinal)).toEqual([
      '1st',
      '2nd',
      '3rd',
      '4th',
      '21st',
    ]);
  });

  it('handles the teens, which are all "th"', () => {
    // 11th, not 11st — the bug every hand-rolled ordinal has.
    expect([11, 12, 13].map(ordinal)).toEqual(['11th', '12th', '13th']);
  });

  it('handles 111 through 113 too', () => {
    expect([111, 112, 113].map(ordinal)).toEqual(['111th', '112th', '113th']);
  });
});

describe('a signed amount', () => {
  it('marks an award', () => {
    expect(signed(120)).toBe('+120');
  });

  it('marks a correction with a real minus sign', () => {
    // Not a hyphen: it lines up with digits in a tabular font, which matters
    // in a column of them.
    expect(signed(-50)).toBe('−50');
  });

  it('groups thousands', () => {
    expect(signed(1200)).toBe('+1,200');
  });
});

describe('how long is left', () => {
  it('counts the last day as a day', () => {
    // A season that reads "0 days left" on the morning of its final day is
    // wrong in the direction that stops somebody bothering.
    expect(daysLeft(season(), new Date(2028, 2, 31))).toBe(1);
    expect(timeLeftLabel(season(), new Date(2028, 2, 31))).toBe('Last day');
  });

  it('is finished the day after', () => {
    expect(daysLeft(season(), new Date(2028, 3, 1))).toBe(0);
    expect(timeLeftLabel(season(), new Date(2028, 3, 1))).toBe('Finished');
  });

  it('counts days when the end is close', () => {
    expect(timeLeftLabel(season(), new Date(2028, 2, 25))).toBe('7 days left');
  });

  it('rounds to weeks when it is far off', () => {
    // Nobody plans around "45 days left".
    expect(timeLeftLabel(season(), MID)).toBe('7 weeks left');
  });

  it('says so once a season has been wrapped up', () => {
    expect(
      timeLeftLabel(season({ closed_at: '2028-04-02T00:00:00Z' }), MID),
    ).toBe('Finished');
  });
});

describe('how much has gone', () => {
  it('is zero on the first morning', () => {
    expect(elapsedPercent(season(), new Date(2028, 0, 1))).toBe(0);
  });

  it('is about half at the midpoint', () => {
    // Not exactly 50: a quarter is 91 days and the 15th of February is 45 of
    // them in. Asserting a range says what the bar is for without pinning it
    // to a calendar that shifts every quarter.
    const half = elapsedPercent(season(), new Date(2028, 1, 15));

    expect(half).toBeGreaterThan(45);
    expect(half).toBeLessThan(55);
  });

  it('never goes past the end of its own bar', () => {
    // A season somebody has since shortened can legitimately be more than
    // finished, and a bar past its own end reads as a rendering bug.
    expect(elapsedPercent(season(), new Date(2029, 0, 1))).toBe(100);
  });
});

it('names a window without repeating the year', () => {
  // The month and day order is the reader's locale, so this asserts the
  // shape rather than one country's spelling of it: both ends present, the
  // year said once at the end.
  const said = seasonWindow(season());

  expect(said).toMatch(/Jan.*–.*Mar/);
  expect(said.match(/2028/g)).toHaveLength(1);
  expect(said.endsWith('2028')).toBe(true);
});

it('gives an achievement rule a readable name', () => {
  // The reason line on the award already names the rule, so this only has to
  // say what kind it is.
  expect(labelFor('achievement.7')).toBe('Achievement');
});

it('names the events people can price', () => {
  expect(labelFor('goal.achieved')).toBe('Hitting a goal');
});

describe('the gap to the next place', () => {
  const table: Standing[] = [
    { user_id: 1, name: 'Clark Kent', points: 900, rank: 1, tier: null },
    { user_id: 2, name: 'Peter Parker', points: 500, rank: 2, tier: null },
    { user_id: 3, name: 'Diana Prince', points: 500, rank: 2, tier: null },
    { user_id: 4, name: 'Bruce Wayne', points: 260, rank: 4, tier: null },
  ];

  it('is to the next place, not to first', () => {
    // "240 behind 2nd" is something somebody can do this week. "640 behind
    // 1st" is a reason to stop trying.
    expect(gapToNext(table, 4)).toEqual({ points: 240, rank: 2 });
  });

  it('is nothing for the leader', () => {
    expect(gapToNext(table, 1)).toBeNull();
  });

  it('looks past anybody they are tied with', () => {
    // The person above is the next one with *more* points, not the next row.
    expect(gapToNext(table, 3)).toEqual({ points: 400, rank: 1 });
  });

  it('is nothing for somebody not on the board', () => {
    expect(gapToNext(table, 99)).toBeNull();
  });
});

describe('the distance to the next rung', () => {
  it('says what it would take', () => {
    // **The only part of a ladder that changes behaviour.**
    expect(toNextLabel(1200, 'Gold')).toBe('1,200 to Gold');
  });

  it('says nothing on the top rung', () => {
    // There is nothing to say, and "0 to nothing" is worse than silence.
    expect(toNextLabel(null, null)).toBeNull();
  });

  it('says nothing when there is no ladder at all', () => {
    expect(toNextLabel(500, null)).toBeNull();
  });
});
