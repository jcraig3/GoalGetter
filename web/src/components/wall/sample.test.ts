/** The editors' sample follows the form (7.4, Q2-3). */
import { describe, expect, test } from 'vitest';

import { sampleSlide } from './sample';

describe('a board sample', () => {
  test('ranks teams when the form ranks teams', () => {
    const slide = sampleSlide('leaderboard', 'Deals', { entity_type: 'team' });
    expect(slide.entries[0]!.entity_name).toBe('Northern Lights');
    expect(slide.entries.map((e) => e.entity_name)).not.toContain('Peter Parker');
    expect(slide.entries[0]!.team_name).toBeNull();
  });

  test('is in the metric’s unit, not money', () => {
    const slide = sampleSlide('leaderboard', 'Deals', { unit: 'count', unit_label: 'deals' });
    expect(slide.unit).toBe('count');
    expect(slide.unit_label).toBe('deals');
    expect(slide.entries[0]!.value).toBe('48');
  });

  test('says the period chosen, and shows the rows asked for', () => {
    const slide = sampleSlide('leaderboard', 'Deals', { period_label: 'Last 30 days', rows: 3 });
    expect(slide.subtitle).toBe('Last 30 days');
    expect(slide.entries).toHaveLength(3);
  });

  test('puts the smallest first when lower is better', () => {
    const slide = sampleSlide('leaderboard', 'Response time', {
      unit: 'duration',
      direction: 'lower_is_better',
    });
    const values = slide.entries.map((e) => Number(e.value));
    expect(values).toEqual([...values].sort((a, b) => a - b));
  });
});

describe('a goal sample', () => {
  test('is for the person chosen, at their target', () => {
    const slide = sampleSlide('goal', 'Deals', {
      subject_name: 'Test User',
      unit: 'count',
      target: '40',
      period_label: 'This month',
    });
    expect(slide.subtitle).toBe('Test User · This month');
    expect(slide.target_value).toBe('40');
    expect(slide.unit).toBe('count');
  });
});

describe('a contest sample', () => {
  test('has its own prize, end and entrants', () => {
    const ends = new Date(Date.now() + 3_600_000).toISOString();
    const slide = sampleSlide('competition', 'Sprint', {
      prize: 'Lunch on us',
      ends_at: ends,
      entrants: ['Ann', 'Bob'],
    });
    expect(slide.prize).toBe('Lunch on us');
    expect(slide.ends_at).toBe(ends);
    expect(slide.entries.map((e) => e.entity_name)).toEqual(['Ann', 'Bob']);
    expect(slide.total_entrants).toBe(2);
    expect(slide.subtitle).toBe('Ann vs Bob');
  });

  test('with no prize typed has none', () => {
    expect(sampleSlide('competition', 'Sprint', { prize: null }).prize).toBeNull();
  });
});
