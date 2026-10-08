/**
 * Starter templates (6.4): the dates, in the organization's own timezone;
 * the slides, from what a channel may show; and the metric a rule uses.
 */
import { describe, expect, test } from 'vitest';

import {
  CHANNEL_TEMPLATES,
  RULE_TEMPLATES,
  competitionTemplates,
  describeSlides,
  metricFor,
} from './starterTemplates';

const NY = 'America/New_York';
const byKey = (now: Date) =>
  Object.fromEntries(competitionTemplates(now, NY).map((t) => [t.key, t]));

describe('competition dates', () => {
  // Wednesday 7 October 2026, 11am in New York.
  const wednesday = new Date('2026-10-07T15:00:00Z');

  test('a Friday sprint is next Friday, nine to five there, every week', () => {
    const t = byKey(wednesday)['friday-sprint']!;
    expect(t.starts_at).toBe('2026-10-09T13:00:00.000Z');
    expect(t.ends_at).toBe('2026-10-09T21:00:00.000Z');
    expect(t.repeat).toBe('weekly');
  });

  test('on a Friday, the sprint is the next one, not one already started', () => {
    const t = byKey(new Date('2026-10-09T15:00:00Z'))['friday-sprint']!;
    expect(t.starts_at).toBe('2026-10-16T13:00:00.000Z');
  });

  test('a month-end push runs from tomorrow to the last day of the month', () => {
    const t = byKey(wednesday)['month-end-push']!;
    expect(t.starts_at).toBe('2026-10-08T13:00:00.000Z');
    expect(t.ends_at).toBe('2026-10-31T21:00:00.000Z');
  });

  test('two days from the end, the push is next month’s', () => {
    const t = byKey(new Date('2026-10-29T15:00:00Z'))['month-end-push']!;
    // November: Eastern time again, so five in the afternoon is 22:00 UTC.
    expect(t.ends_at).toBe('2026-11-30T22:00:00.000Z');
  });

  test('team against team is teams, Monday to Friday', () => {
    const t = byKey(wednesday)['team-vs-team']!;
    expect(t.entity_type).toBe('team');
    expect(t.starts_at).toBe('2026-10-12T13:00:00.000Z');
    expect(t.ends_at).toBe('2026-10-16T21:00:00.000Z');
  });
});

describe('channel slides', () => {
  const eligible = {
    leaderboards: [
      { id: 1, name: 'Calls' },
      { id: 2, name: 'Revenue' },
    ],
    competitions: [
      { id: 7, name: 'Sprint — active', state: 'active' },
      { id: 8, name: 'Last month — closed', state: 'closed' },
    ],
  };

  test('a sales floor has every board, the running contests and recent wins', () => {
    const slides = CHANNEL_TEMPLATES.find((t) => t.key === 'sales-floor')!.slides(eligible);
    expect(slides.map((s) => s.kind)).toEqual(['leaderboard', 'leaderboard', 'competition', 'achievements']);
    expect(slides[2]!.competition_id).toBe(7);
    expect(describeSlides(slides)).toBe('2 boards, 1 competition and recent wins');
  });

  test('a lobby is one board as a top-three podium, and recent wins', () => {
    const slides = CHANNEL_TEMPLATES.find((t) => t.key === 'lobby')!.slides(eligible);
    expect(slides[0]!.appearance).toEqual({ ranked_layout: 'podium', row_count: 3 });
    expect(describeSlides(slides)).toBe('1 board and recent wins');
  });
});

test('a rule template uses the first metric of its kind, never a ratio', () => {
  const metrics = [
    { id: 1, unit: 'currency', aggregation: 'ratio' },
    { id: 2, unit: 'count', aggregation: 'sum' },
    { id: 3, unit: 'currency', aggregation: 'sum' },
  ];
  expect(metricFor(RULE_TEMPLATES[0]!, metrics)?.id).toBe(3);
  expect(metricFor(RULE_TEMPLATES[2]!, metrics)?.id).toBe(2);
});
