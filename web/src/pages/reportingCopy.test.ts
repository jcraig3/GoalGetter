import { describe, expect, it } from 'vitest';

import {
  basisLabel,
  deltaLabel,
  gapSentence,
  hitLabel,
  stepUp,
  streakLabel,
  tone,
  type CompetitionReport,
  type Gap,
  type TrackRecord,
} from './reportingCopy';

/**
 * The sentences, not the layout.
 *
 * A rendering bug is visible the first time somebody opens the page. A
 * sentence that says "needs 0 a day" to somebody who is four hundred short is
 * not — it looks like a finished feature and is wrong in the direction that
 * costs a conversation.
 */

function gap(overrides: Partial<Gap> = {}): Gap {
  return {
    goal_id: 1,
    goal_name: 'Calls this month',
    subject_name: 'Peter Parker',
    metric_name: 'Calls made',
    unit: 'count',
    decimal_places: 0,
    current: '20',
    target: '100',
    behind_by: 30,
    days_left: 8,
    rate_so_far: '4',
    rate_needed: '10',
    ...overrides,
  };
}

describe('the coaching sentence', () => {
  it('names both rates, because the gap between them is the point', () => {
    expect(gapSentence(gap())).toBe(
      'Needs 10 a day for 8 working days (4 a day so far).',
    );
  });

  it('says "working days", which is what the number was computed from', () => {
    // "Twelve a day" over a fortnight containing two weekends is a target
    // somebody would miss by a third while doing exactly what they were told.
    expect(gapSentence(gap())).toContain('working days');
  });

  it('does not say "1 days"', () => {
    expect(gapSentence(gap({ days_left: 1 }))).toContain('for 1 working day (');
  });

  it('drops the comparison when nothing has been recorded yet', () => {
    expect(gapSentence(gap({ rate_so_far: null }))).toBe(
      'Needs 10 a day for 8 working days.',
    );
  });

  it('falls back to the shortfall when a rate would be nonsense', () => {
    // An average response time is not something you do eighteen of a day.
    const said = gapSentence(
      gap({ rate_needed: null, rate_so_far: null, current: '30', target: '100' }),
    );

    expect(said).toBe('70 short, with 8 working days left.');
  });

  it('formats money as money', () => {
    const said = gapSentence(
      gap({ unit: 'currency', decimal_places: 2, rate_needed: '1000', rate_so_far: '250' }),
    );

    expect(said).toContain('$1,000');
  });
});

describe('how much harder it has to get', () => {
  it('is the multiple between the two rates', () => {
    expect(stepUp(gap())).toBe(2.5);
  });

  it('is nothing when the rate so far is zero', () => {
    // "Infinitely faster" is true and useless.
    expect(stepUp(gap({ rate_so_far: '0' }))).toBeNull();
  });

  it('is nothing when there is no rate at all', () => {
    expect(stepUp(gap({ rate_needed: null }))).toBeNull();
  });
});

describe('the headline colour', () => {
  it('is three bands rather than a gradient', () => {
    // A chip that shifts hue by one percentage point is a chip nobody reads.
    expect([tone(95), tone(65), tone(10)]).toEqual(['good', 'warn', 'bad']);
  });

  it('treats everything met as good', () => {
    expect(tone(100)).toBe('good');
  });
});

function record(overrides: Partial<TrackRecord> = {}): TrackRecord {
  return {
    goal_id: 1,
    goal_name: 'Calls this month',
    subject_name: 'Peter Parker',
    metric_name: 'Calls made',
    unit: 'count',
    decimal_places: 0,
    target: '100',
    seasons: [],
    considered: 6,
    hit: 4,
    hit_rate: 66.7,
    current_streak: 0,
    best_streak: 0,
    ...overrides,
  };
}

describe('the streak label', () => {
  it('says nothing rather than "0 in a row"', () => {
    // Which reads as a taunt on a page somebody is already on because things
    // are going badly.
    expect(streakLabel(record())).toBe('');
  });

  it('counts a run', () => {
    expect(streakLabel(record({ current_streak: 3 }))).toBe('3 in a row');
  });

  it('does not call one period a run', () => {
    expect(streakLabel(record({ current_streak: 1 }))).toBe('Hit last period');
  });

  it('remembers a broken run worth remembering', () => {
    expect(streakLabel(record({ current_streak: 0, best_streak: 4 }))).toBe(
      'Best run 4',
    );
  });
});

it('shows the fraction behind the percentage', () => {
  // 67% of what matters.
  expect(hitLabel(record())).toBe('4 of 6');
});

function report(overrides: Partial<CompetitionReport> = {}): CompetitionReport {
  return {
    competition_id: 1,
    name: 'August sprint',
    state: 'active',
    metric_name: 'Revenue',
    unit: 'currency',
    decimal_places: 2,
    entity_type: 'user',
    leader_name: 'Peter Parker',
    leader_value: '5000',
    elapsed_percent: 50,
    predicted: '10000',
    runs: [],
    all_time_high: '12000',
    all_time_high_name: 'Clark Kent',
    first: '6000',
    previous: '9000',
    basis: '10000',
    vs_first: '4000',
    vs_previous: '1000',
    vs_high: '-2000',
    ...overrides,
  };
}

describe('a comparison', () => {
  it('says which way it went, rather than leaving it to a minus sign', () => {
    expect(deltaLabel('-2000', report())).toEqual({
      text: '$2,000 behind',
      tone: 'bad',
    });
  });

  it('reads ahead as good', () => {
    expect(deltaLabel('1000', report())?.tone).toBe('good');
  });

  it('has a word for exactly level', () => {
    expect(deltaLabel('0', report())?.text).toBe('level');
  });

  it('is nothing when there is nothing to compare against', () => {
    // So the row is left out entirely rather than printing a dash somebody
    // has to interpret.
    expect(deltaLabel(null, report())).toBeNull();
  });
});

describe('what the comparison is made from', () => {
  it('is a forecast while it runs', () => {
    // **A prediction and a result are not the same claim.** A page showing
    // one number without saying which lets somebody quote a forecast as a
    // score.
    expect(basisLabel(report())).toBe('On pace to finish at');
  });

  it('is the score once it is settled', () => {
    expect(basisLabel(report({ state: 'closed' }))).toBe('Final score');
  });

  it('is the score the moment it ends, before it settles', () => {
    expect(basisLabel(report({ state: 'ended' }))).toBe('Final score');
  });
});
