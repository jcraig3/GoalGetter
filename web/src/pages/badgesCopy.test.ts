import { describe, expect, it } from 'vitest';

import {
  type Badge,
  type Held,
  type Progress,
  progressPercent,
  remainingLabel,
  termsLabel,
  timesLabel,
} from './badgesCopy';

function progress(overrides: Partial<Progress> = {}): Progress {
  return {
    badge_id: 1,
    name: 'Closer',
    description: 'Three big deals in a month',
    icon: 'medal',
    have: 2,
    need: 3,
    remaining: 1,
    counted_over: 'month',
    ...overrides,
  };
}

function held(overrides: Partial<Held> = {}): Held {
  return {
    badge_id: 1,
    name: 'Closer',
    description: '',
    icon: 'medal',
    reason: 'Closer',
    earned_at: '2028-02-01T10:00:00Z',
    times: 1,
    ...overrides,
  };
}

function badge(overrides: Partial<Badge> = {}): Badge {
  return {
    id: 1,
    name: 'Closer',
    description: '',
    kind: 'count',
    icon: 'medal',
    points: 0,
    achievement_rule_id: 4,
    achievement_rule_name: 'Big deal',
    threshold: 3,
    counted_over: 'month',
    holders: 0,
    ...overrides,
  };
}

describe('what is left', () => {
  it('says the window, so "one more" has a deadline', () => {
    // **The half of a badge that changes behaviour.** Without the window it
    // is a number with no reason to act on it today.
    expect(remainingLabel(progress())).toBe('1 more this month');
  });

  it('says the season for a season badge', () => {
    expect(remainingLabel(progress({ counted_over: 'season', remaining: 4 }))).toBe(
      '4 more this season',
    );
  });
});

describe('how many times over', () => {
  it('says nothing for once', () => {
    // "×1" reads as a count somebody forgot to hide.
    expect(timesLabel(held())).toBe('');
  });

  it('counts a habit', () => {
    // The difference between a good month and a habit is the interesting
    // part of holding a badge more than once.
    expect(timesLabel(held({ times: 4 }))).toBe('×4');
  });
});

describe('a badge’s terms', () => {
  it('says what earns a counted one', () => {
    // "in a month", not "this month": these are the terms of every month.
    expect(termsLabel(badge())).toBe('3× Big deal in a month');
  });

  it('says a manual one is given by hand', () => {
    expect(termsLabel(badge({ kind: 'manual' }))).toBe('Given by hand');
  });
});

describe('the bar', () => {
  it('is how far along', () => {
    expect(progressPercent(progress({ have: 1, need: 4 }))).toBe(25);
  });

  it('never runs past its own end', () => {
    expect(progressPercent(progress({ have: 9, need: 3 }))).toBe(100);
  });

  it('survives a zero it should never be given', () => {
    expect(progressPercent(progress({ need: 0 }))).toBe(100);
  });
});
